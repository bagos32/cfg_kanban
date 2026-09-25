import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


def on_purchase_order_submit(doc, method=None):
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name:
        request_names = {row.material_request for row in doc.items if row.material_request}
        cycles = {frappe.db.get_value("Material Request", name, "cfg_kanban_cycle")
                  for name in request_names}
        cycles.discard(None)
        if len(cycles) == 1:
            cycle_name = cycles.pop()
            doc.db_set({"cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle_name},
                       update_modified=False)
    if not cycle_name:
        return
    from cfg_kanban.services.purchase_replenishment import link_purchase_order
    link_purchase_order(cycle_name, doc.name, "Automatically linked from submitted Material Request")


def on_purchase_receipt_submit(doc, method=None):
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name:
        return
    _refresh_receipt_state(cycle_name, doc.name)


def on_purchase_receipt_cancel(doc, method=None):
    if not doc.get("cfg_kanban_cycle"):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
    active_cycle = (frappe.db.get_value("CFG Kanban Card", cycle.kanban_card, "active_cycle")
                    if cycle.kanban_card else None)
    if cycle.status == "Completed" or active_cycle != cycle.name:
        exception = frappe.get_doc({
            "doctype": "CFG Kanban Exception", "exception_type": "Purchase Receipt Cancelled",
            "severity": "Critical", "status": "Open", "kanban_cycle": cycle.name,
            "kanban_card": cycle.kanban_card,
            "message": (f"Submitted Purchase Receipt {doc.name} was cancelled after the purchase "
                        "Kanban Card had been released. Supervisor stock reconciliation is required."),
            "reference_doctype": "Purchase Receipt", "reference_name": doc.name,
            "raised_on": now_datetime(),
        }).insert(ignore_permissions=True)
        cycle.db_set({"blocked": 1, "exception": exception.name,
                      "purchase_status": "Blocked", "status": "Blocked"})
        return
    _refresh_receipt_state(cycle.name, None)


def _refresh_receipt_state(cycle_name, latest_receipt):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    po = frappe.get_doc("Purchase Order", cycle.purchase_order)
    row = next((item for item in po.items if item.name == cycle.get("purchase_order_item")), None)
    if not row:
        return
    po.reload()
    row = next(item for item in po.items if item.name == cycle.get("purchase_order_item"))
    received = flt(row.received_qty)
    outstanding = max(flt(row.qty) - received, 0)
    complete = outstanding <= 0.000001
    purchase_status = "Received" if complete else ("Partially Received" if received else "Ordered")
    cycle.db_set({"latest_purchase_receipt": latest_receipt,
                  "received_qty": received, "outstanding_qty": outstanding,
                  "purchase_status": purchase_status})
    set_cycle_state(cycle, "Completed" if complete else purchase_status,
                    event_type="Purchase Receipt Posted",
                    reference_doctype="Purchase Receipt", reference_name=latest_receipt)
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        target = "Received" if complete else ("Partially Received" if received else "Purchase Ordered")
        transition_card(card, target, event_type="Purchase Receipt Posted", cycle=cycle.name)
        if complete:
            transition_card(card, "Available", event_type="Purchase Kanban Card Recycled",
                            cycle=cycle.name)
            card.db_set("active_cycle", None, update_modified=False)
            cycle.db_set("completed_on", now_datetime())
    record("Purchase Receipt Reconciled", card=cycle.kanban_card, cycle=cycle.name,
           qty=received, reference_doctype="Purchase Receipt", reference_name=latest_receipt)

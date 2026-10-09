import frappe
from frappe.utils import now_datetime


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
    if doc.get("cfg_movement_manifest"):
        from cfg_kanban.integrations.logistics_feedback import on_purchase_receipt_submit as logistics_submit
        logistics_submit(doc, method)
    from cfg_kanban.services.purchase_disposition import (
        ensure_receipt_dispositions, receipt_cycle,
    )
    cycle_name = receipt_cycle(doc)
    if not cycle_name:
        return
    if not doc.get("cfg_kanban_cycle"):
        doc.db_set("cfg_kanban_cycle", cycle_name, update_modified=False)
    ensure_receipt_dispositions(doc)
    _refresh_receipt_state(cycle_name, doc.name)


def on_purchase_receipt_cancel(doc, method=None):
    from cfg_kanban.api.receiving import void_cancelled_purchase_receipt_tags
    void_cancelled_purchase_receipt_tags(doc)
    if doc.get("cfg_movement_manifest"):
        from cfg_kanban.integrations.logistics_feedback import on_purchase_receipt_cancel as logistics_cancel
        logistics_cancel(doc, method)
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
    from cfg_kanban.services.purchase_disposition import reconcile_purchase_cycle
    return reconcile_purchase_cycle(cycle_name, latest_receipt)

import math

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


PURCHASE_ROLES = ("Purchase User", "Purchase Manager", "Stock User", "Stock Manager",
                  "Manufacturing Manager", "System Manager")


def purchase_request_qty(nominal_qty, minimum_order_qty=0, order_multiple=0, pack_size=0):
    qty = max(flt(nominal_qty), flt(minimum_order_qty))
    multiple = flt(order_multiple) or flt(pack_size)
    return math.ceil(qty / multiple) * multiple if multiple > 0 else qty


def create_material_request_command(signal_name):
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type != "Purchase Replenishment":
        frappe.throw("This Kanban Master is not configured for Purchase Replenishment")
    qty = purchase_request_qty(signal.requested_qty, master.minimum_order_qty,
                               master.purchase_order_multiple, master.supplier_pack_size)
    key = canonical_key("command", signal.name, "Create Material Request")
    command, _ = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Material Request",
        "source_signal": signal.name, "kanban_cycle": signal.kanban_cycle,
        "status": "Pending", "target_doctype": "Material Request",
        "request_payload": frappe.as_json({
            "item_code": master.item_code, "qty": qty, "stock_uom": master.stock_uom,
            "warehouse": master.destination_warehouse, "company": master.company,
            "supplier": master.default_supplier,
            "submit": cint(master.auto_submit_material_request),
        }),
        "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    signal.db_set({"command": command.name, "status": "Executing"})
    if signal.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", signal.kanban_card)
        if card.current_state == "Signal Created":
            transition_card(card, "Replenishment Requested",
                            event_type="Purchase Replenishment Requested",
                            cycle=signal.kanban_cycle)
    return command


def link_purchase_order(cycle_name, purchase_order_name, reason):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    po = frappe.get_doc("Purchase Order", purchase_order_name)
    if po.docstatus != 1 or po.status in ("Closed", "Cancelled"):
        frappe.throw("Select a submitted, open Purchase Order")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if po.company != master.company or po.supplier != master.default_supplier:
        _block(cycle, "Purchase Order Mismatch",
               "Purchase Order company or supplier does not match the Kanban Master", po)
    rows = [row for row in po.items if row.item_code == cycle.item_code]
    if not rows:
        _block(cycle, "Purchase Order Mismatch",
               f"Purchase Order does not contain item {cycle.item_code}", po)
    row = max(rows, key=lambda value: flt(value.qty) - flt(value.received_qty))
    outstanding = max(flt(row.qty) - flt(row.received_qty), 0)
    if outstanding <= 0:
        _block(cycle, "Purchase Order Mismatch", "Selected Purchase Order row is fully received", po)
    po.db_set({"cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle.name,
               "cfg_kanban_signal": cycle.signal}, update_modified=False)
    cycle.db_set({
        "purchase_order": po.name, "purchase_order_item": row.name,
        "supplier": po.supplier, "ordered_qty": row.qty,
        "received_qty": row.received_qty, "outstanding_qty": outstanding,
        "purchase_status": "Ordered",
    })
    set_cycle_state(cycle, "Ordered", event_type="Purchase Order Linked",
                    reference_doctype="Purchase Order", reference_name=po.name)
    if cycle.kanban_card:
        transition_card(cycle.kanban_card, "Purchase Ordered",
                        event_type="Purchase Order Linked", cycle=cycle.name,
                        notes=reason)
    record("Purchase Order Selected", card=cycle.kanban_card, cycle=cycle.name,
           reference_doctype="Purchase Order", reference_name=po.name, notes=reason)
    return receipt_context(cycle.name)


def receipt_context(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if not cycle.purchase_order:
        frappe.throw("Select the effective Purchase Order first")
    po = frappe.get_doc("Purchase Order", cycle.purchase_order)
    row = next((item for item in po.items if item.name == cycle.get("purchase_order_item")), None)
    if not row:
        frappe.throw("The selected Purchase Order item row no longer exists")
    outstanding = max(flt(row.qty) - flt(row.received_qty), 0)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    return {"cycle": cycle.name, "purchase_order": po.name, "supplier": po.supplier,
            "item_code": row.item_code, "ordered_qty": flt(row.qty),
            "received_qty": flt(row.received_qty), "outstanding_qty": outstanding,
            "warehouse": master.destination_warehouse,
            "rejected_warehouse": master.rejected_warehouse,
            "receipt_posting_mode": master.receipt_posting_mode,
            "allow_partial_receipt": bool(master.allow_partial_receipt)}


def create_purchase_receipt_command(cycle_name, delivered_qty, accepted_qty, rejected_qty=0,
                                    warehouse=None, rejected_warehouse=None,
                                    supplier_delivery_note=None, event_token=None):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    context = receipt_context(cycle.name)
    delivered_qty, accepted_qty, rejected_qty = map(flt, (delivered_qty, accepted_qty, rejected_qty))
    if delivered_qty <= 0 or accepted_qty < 0 or rejected_qty < 0:
        frappe.throw("Receipt quantities are invalid")
    if abs(delivered_qty - accepted_qty - rejected_qty) > 0.000001:
        frappe.throw("Delivered Qty must equal Accepted Qty plus Rejected Qty")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    allowed = context["outstanding_qty"] * (1 + flt(master.over_receipt_tolerance_pct) / 100)
    if delivered_qty > allowed + 0.000001:
        _block(cycle, "Purchase Receipt Mismatch",
               f"Delivered quantity {delivered_qty} exceeds permitted outstanding quantity {allowed}")
    if not master.allow_partial_receipt and delivered_qty + 0.000001 < context["outstanding_qty"]:
        frappe.throw("This Kanban Master does not allow partial receipts")
    if rejected_qty and not (rejected_warehouse or master.rejected_warehouse):
        frappe.throw("Rejected Warehouse is required when Rejected Qty is entered")
    key = canonical_key("purchase-receipt", cycle.name,
                        event_token or f"{cycle.purchase_order}:{delivered_qty}:{supplier_delivery_note or ''}")
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Purchase Receipt",
        "source_signal": cycle.signal, "kanban_cycle": cycle.name,
        "status": "Pending", "target_doctype": "Purchase Receipt",
        "request_payload": frappe.as_json({
            "purchase_order": cycle.purchase_order,
            "purchase_order_item": cycle.get("purchase_order_item"),
            "delivered_qty": delivered_qty, "accepted_qty": accepted_qty,
            "rejected_qty": rejected_qty, "warehouse": warehouse or master.destination_warehouse,
            "rejected_warehouse": rejected_warehouse or master.rejected_warehouse,
            "supplier_delivery_note": supplier_delivery_note,
            "submit": master.receipt_posting_mode == "Submit After Receiver Confirmation",
        }), "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    result = execute_command(command.name) if created or command.status != "Completed" else frappe.get_doc(
        command.target_doctype, command.target_document)
    return {"command": command.name, "purchase_receipt": result.name,
            "docstatus": result.docstatus, "duplicate": not created}


def _block(cycle, exception_type, message, reference=None):
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception", "exception_type": exception_type,
        "severity": "Error", "status": "Open", "kanban_cycle": cycle.name,
        "kanban_card": cycle.kanban_card, "message": message,
        "reference_doctype": reference.doctype if reference else None,
        "reference_name": reference.name if reference else None,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    cycle.db_set({"blocked": 1, "exception": exception.name,
                  "purchase_status": "Blocked"})
    # This endpoint performs only this reconciliation action. Preserve the audit exception
    # even though the caller must receive a hard validation failure.
    frappe.db.commit()
    frappe.throw(message)

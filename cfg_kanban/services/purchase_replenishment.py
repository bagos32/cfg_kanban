import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.purchase_uom import calculate_purchase_quantities
from cfg_kanban.services.state_machine import set_cycle_state, transition_card
from cfg_kanban.services.uom_conversion import get_item_purchase_uom


PURCHASE_ROLES = ("Purchase User", "Purchase Manager", "Stock User", "Stock Manager",
                  "Manufacturing Manager", "System Manager")
PURCHASE_EXECUTION_RANK = {
    "Material Request Only": 0,
    "Create Draft Purchase Order": 1,
    "Create and Submit Purchase Order": 2,
}


def purchase_request_qty(nominal_qty, minimum_order_qty=0, order_multiple=0, pack_size=0):
    return calculate_purchase_quantities(
        nominal_qty, 1, minimum_order_qty, order_multiple, pack_size
    )["purchase_qty"]


def create_material_request_command(signal_name):
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type != "Purchase Replenishment":
        frappe.throw("This Kanban Master is not configured for Purchase Replenishment")
    uom = get_item_purchase_uom(master.item_code, master.get("purchase_uom"))
    plan = calculate_purchase_quantities(
        signal.requested_qty,
        uom["conversion_factor"],
        master.minimum_order_qty,
        master.purchase_order_multiple,
        master.supplier_pack_size,
    )
    key = canonical_key("command", signal.name, "Create Material Request")
    command, _ = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Material Request",
        "source_signal": signal.name, "kanban_cycle": signal.kanban_cycle,
        "status": "Pending", "target_doctype": "Material Request",
        "request_payload": frappe.as_json({
            "item_code": master.item_code,
            "purchase_qty": plan["purchase_qty"],
            "stock_qty": plan["stock_qty"],
            "purchase_uom": uom["purchase_uom"],
            "stock_uom": uom["stock_uom"],
            "conversion_factor": uom["conversion_factor"],
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


def effective_purchase_execution_mode(master):
    """Apply the global safety ceiling without weakening a stricter Master."""
    requested = master.get("purchase_execution_mode") or "Material Request Only"
    ceiling = (frappe.db.get_single_value(
        "CFG Kanban Settings", "maximum_purchase_automation"
    ) or "Material Request Only")
    rank = min(PURCHASE_EXECUTION_RANK.get(requested, 0),
               PURCHASE_EXECUTION_RANK.get(ceiling, 0))
    return next(mode for mode, value in PURCHASE_EXECUTION_RANK.items() if value == rank)


def create_purchase_order_command(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    mode = effective_purchase_execution_mode(master)
    if mode == "Material Request Only":
        return None
    if not cycle.material_request:
        frappe.throw("A Kanban Material Request must exist before Purchase Order creation")
    request = frappe.get_doc("Material Request", cycle.material_request)
    if request.docstatus != 1:
        frappe.throw("Submit the Kanban Material Request before Purchase Order creation")
    existing = cycle.get("purchase_order") or frappe.db.get_value(
        "Purchase Order", {"cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]}, "name"
    )
    if existing:
        po = frappe.get_doc("Purchase Order", existing)
        if po.docstatus == 1:
            return None
    key = canonical_key("command", cycle.name, "Create Purchase Order")
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Purchase Order",
        "source_signal": cycle.signal, "kanban_cycle": cycle.name,
        "status": "Pending", "target_doctype": "Purchase Order",
        "request_payload": frappe.as_json({
            "material_request": request.name,
            "supplier": master.default_supplier,
            "mode": mode,
            "master_value_limit": flt(master.get("master_auto_submit_po_value_limit")),
            "global_value_limit": flt(frappe.db.get_single_value(
                "CFG Kanban Settings", "maximum_auto_submit_po_value"
            )),
        }),
        "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    if (existing and mode == "Create and Submit Purchase Order"
            and command.status == "Completed"):
        command.db_set({"status": "Pending", "target_document": None,
                        "completed_on": None, "last_error": None})
        command.reload()
    return command


def continue_purchase_execution(cycle_name):
    """Continue MR → PO without rolling back a valid MR when PO prerequisites fail."""
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    mode = effective_purchase_execution_mode(master)
    if mode == "Material Request Only":
        return {"mode": mode, "status": "Material Requested"}
    try:
        command = create_purchase_order_command(cycle.name)
        if not command:
            return {"mode": mode, "purchase_order": cycle.get("purchase_order"),
                    "status": cycle.get("purchase_status")}
        po = execute_command(command.name)
        return {"mode": mode, "command": command.name, "purchase_order": po.name,
                "docstatus": po.docstatus,
                "status": "Ordered" if po.docstatus == 1 else "Purchase Order Draft"}
    except Exception as exc:
        cycle.reload()
        cycle.db_set({"purchase_status": "Purchase Attention Required"})
        set_cycle_state(cycle, "Purchase Attention Required",
                        event_type="Purchase Automation Attention Required")
        record("Purchase Automation Attention Required", card=cycle.kanban_card,
               cycle=cycle.name, notes=frappe.get_traceback())
        return {"mode": mode, "status": "Purchase Attention Required",
                "error": str(exc)}


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
    item_uom = get_item_purchase_uom(master.item_code, master.get("purchase_uom"))
    # New cycles retain the exact UOM snapshot used when their Material Request
    # was created.  Do not compare them with a Master that may have been revised
    # later.  Older active cycles have no snapshot, so accept the submitted PO's
    # Purchase UOM while still enforcing the Item's canonical Stock UOM.
    has_uom_snapshot = bool(cycle.get("purchase_uom"))
    expected_purchase_uom = cycle.get("purchase_uom") or row.uom
    expected_factor = flt(cycle.get("purchase_uom_conversion_factor")) or flt(
        row.conversion_factor
    )
    if row.uom != expected_purchase_uom or row.stock_uom != item_uom["stock_uom"]:
        _block(cycle, "Purchase Order Mismatch",
               f"Purchase Order UOM must be {expected_purchase_uom} and Stock UOM must be "
               f"{item_uom['stock_uom']}", po)
    if flt(row.conversion_factor) <= 0:
        _block(cycle, "Purchase Order Mismatch",
               "Purchase Order conversion factor must be greater than zero", po)
    if has_uom_snapshot and abs(flt(row.conversion_factor) - expected_factor) > 0.000001:
        _block(cycle, "Purchase Order Mismatch",
               f"Purchase Order conversion factor {row.conversion_factor} does not match "
               f"the released Kanban factor {expected_factor}", po)
    outstanding_purchase = max(flt(row.qty) - flt(row.received_qty), 0)
    ordered_stock = flt(row.stock_qty) or flt(row.qty) * flt(row.conversion_factor)
    received_stock = flt(row.received_qty) * flt(row.conversion_factor)
    outstanding_stock = max(ordered_stock - received_stock, 0)
    if outstanding_purchase <= 0:
        _block(cycle, "Purchase Order Mismatch", "Selected Purchase Order row is fully received", po)
    po.db_set({"cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle.name,
               "cfg_kanban_signal": cycle.signal}, update_modified=False)
    cycle.db_set({
        "purchase_order": po.name, "purchase_order_item": row.name,
        "supplier": po.supplier,
        "purchase_uom": row.uom,
        "purchase_uom_conversion_factor": row.conversion_factor,
        "requested_purchase_qty": cycle.get("requested_purchase_qty") or row.qty,
        "requested_stock_qty": cycle.get("requested_stock_qty") or ordered_stock,
        "ordered_purchase_qty": row.qty,
        "ordered_stock_qty": ordered_stock,
        "received_purchase_qty": row.received_qty,
        "received_stock_qty": received_stock,
        "outstanding_purchase_qty": outstanding_purchase,
        "outstanding_stock_qty": outstanding_stock,
        "ordered_qty": row.qty, "received_qty": row.received_qty,
        "outstanding_qty": outstanding_purchase,
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
    factor = flt(row.conversion_factor or 1)
    ordered_stock = flt(row.stock_qty) or flt(row.qty) * factor
    received_stock = flt(row.received_qty) * factor
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    return {"cycle": cycle.name, "purchase_order": po.name, "supplier": po.supplier,
            "item_code": row.item_code,
            "purchase_uom": row.uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": factor,
            "ordered_qty": flt(row.qty),
            "received_qty": flt(row.received_qty), "outstanding_qty": outstanding,
            "ordered_stock_qty": ordered_stock,
            "received_stock_qty": received_stock,
            "outstanding_stock_qty": max(ordered_stock - received_stock, 0),
            "warehouse": master.destination_warehouse,
            "rejected_warehouse": master.rejected_warehouse,
            "receipt_posting_mode": master.receipt_posting_mode,
            "allow_partial_receipt": bool(master.allow_partial_receipt)}


def create_purchase_receipt_command(cycle_name, delivered_qty, accepted_qty, rejected_qty=0,
                                    warehouse=None, rejected_warehouse=None,
                                    supplier_delivery_note=None, event_token=None):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    existing_draft = frappe.db.get_value(
        "Purchase Receipt", {"cfg_kanban_cycle": cycle.name, "docstatus": 0}, "name"
    )
    if existing_draft:
        frappe.throw(
            f"Draft Purchase Receipt {existing_draft} already exists for this Cycle. "
            "Complete or cancel it before starting another receipt."
        )
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

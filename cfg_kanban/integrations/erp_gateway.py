import json

import frappe
from frappe.model.naming import get_default_naming_series
from frappe.utils import add_to_date, flt, get_datetime, now_datetime
from erpnext.manufacturing.doctype.work_order.work_order import get_item_details

from cfg_kanban.services.state_machine import set_cycle_state, transition_card


HANDLERS = {}


def handler(command_type):
    def register(fn):
        HANDLERS[command_type] = fn
        return fn
    return register


def execute_command(command_name):
    command = frappe.get_doc("CFG ERP Command", command_name)
    if command.status == "Completed" and command.target_document:
        return frappe.get_doc(command.target_doctype, command.target_document)
    if command.status == "Running":
        frappe.throw("ERP command is already running")
    fn = HANDLERS.get(command.command_type)
    if not fn:
        frappe.throw(f"No ERP gateway handler for {command.command_type}")
    command.db_set({"status": "Running", "started_on": now_datetime(),
                    "attempt_count": (command.attempt_count or 0) + 1})
    try:
        result = fn(command, json.loads(command.request_payload or "{}"))
        detail = getattr(result, "_cfg_command_result", None) or {
            "doctype": result.doctype, "name": result.name
        }
        command.db_set({"status": "Completed", "completed_on": now_datetime(),
                        "target_document": result.name,
                        "result_payload": frappe.as_json(detail)})
        return result
    except Exception:
        command.db_set({"status": "Failed", "last_error": frappe.get_traceback()})
        raise


@handler("Create Work Order")
def create_work_order(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value("Work Order", {"cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]}, "name")
    if existing:
        return frappe.get_doc("Work Order", existing)
    work_order = frappe.new_doc("Work Order")
    work_order.production_item = payload["production_item"]
    work_order.company = payload["company"]
    work_order.update(get_item_details(payload["production_item"]))
    work_order.update({
        "bom_no": payload.get("bom_no"), "qty": payload["qty"],
        "source_warehouse": payload.get("source_warehouse"), "wip_warehouse": payload.get("wip_warehouse"),
        "fg_warehouse": payload.get("fg_warehouse"), "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name, "cfg_kanban_signal": command.source_signal,
        "cfg_production_origin": "SALES ORDER" if cycle.get("sales_order") else "KANBAN",
        "cfg_sales_order": cycle.get("sales_order"), "cfg_planned_batch": cycle.batch_no,
    })
    work_order.get_items_and_operations_from_bom()
    if not work_order.required_items:
        frappe.throw(f"BOM {work_order.bom_no} did not provide any required material rows")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.operation_profiles and not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and "
                     "configure the ERPNext BOM route before creating a Kanban Work Order.")
    work_order.insert(ignore_permissions=True)
    settings = frappe.get_single("CFG Kanban Settings")
    if settings.auto_submit_work_order:
        work_order.submit()
    cycle.db_set("work_order", work_order.name)
    signal = frappe.get_doc("CFG Kanban Signal", command.source_signal)
    signal.db_set({"erp_reference_doctype": "Work Order", "erp_reference_name": work_order.name,
                   "status": "Completed"})
    set_cycle_state(cycle, "Released", event_type="Work Order Created",
                    reference_doctype="Work Order", reference_name=work_order.name)
    if cycle.kanban_card:
        transition_card(cycle.kanban_card, "Production Released", event_type="Production Released", cycle=cycle.name)
    return work_order


@handler("Create Material Request")
def create_material_request(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value("Material Request", {
        "cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]
    }, "name")
    if existing:
        return frappe.get_doc("Material Request", existing)
    # Keep recovery compatible with ERP Commands created before dual-UOM
    # support, whose payload contained only qty + stock_uom.
    purchase_qty = payload.get("purchase_qty", payload.get("qty"))
    purchase_uom = payload.get("purchase_uom", payload.get("stock_uom"))
    stock_uom = payload.get("stock_uom", purchase_uom)
    conversion_factor = flt(payload.get("conversion_factor") or 1)
    stock_qty = flt(payload.get("stock_qty") or (flt(purchase_qty) * conversion_factor))
    request = frappe.get_doc({
        "doctype": "Material Request", "material_request_type": "Purchase",
        "company": payload["company"], "schedule_date": add_to_date(now_datetime(), days=1).date(),
        "cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle.name,
        "cfg_kanban_signal": command.source_signal,
        "items": [{"item_code": payload["item_code"],
                   "qty": purchase_qty,
                   "uom": purchase_uom,
                   "stock_uom": stock_uom,
                   "conversion_factor": conversion_factor,
                   "stock_qty": stock_qty,
                   "warehouse": payload.get("warehouse"),
                   "schedule_date": add_to_date(now_datetime(), days=1).date()}],
    }).insert(ignore_permissions=True)
    if payload.get("submit"):
        request.submit()
    cycle.db_set({"material_request": request.name, "supplier": payload.get("supplier"),
                  "purchase_status": "Material Requested",
                  "purchase_uom": purchase_uom,
                  "purchase_uom_conversion_factor": conversion_factor,
                  "requested_purchase_qty": purchase_qty,
                  "requested_stock_qty": stock_qty,
                  "outstanding_purchase_qty": purchase_qty,
                  "outstanding_stock_qty": stock_qty,
                  "outstanding_qty": purchase_qty})
    signal = frappe.get_doc("CFG Kanban Signal", command.source_signal)
    signal.db_set({"erp_reference_doctype": "Material Request",
                   "erp_reference_name": request.name, "status": "Completed"})
    set_cycle_state(cycle, "Material Requested", event_type="Material Request Created",
                    reference_doctype="Material Request", reference_name=request.name)
    return request


@handler("Create Purchase Receipt")
def create_purchase_receipt(command, payload):
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    receipt = make_purchase_receipt(payload["purchase_order"])
    selected = [row for row in receipt.items
                if row.get("purchase_order_item") == payload["purchase_order_item"]]
    if not selected:
        frappe.throw("ERPNext could not map the selected Purchase Order item row")
    receipt.set("items", selected)
    row = receipt.items[0]
    row.received_qty = payload["delivered_qty"]
    row.qty = payload["accepted_qty"]
    row.rejected_qty = payload.get("rejected_qty") or 0
    row.warehouse = payload.get("warehouse")
    row.rejected_warehouse = payload.get("rejected_warehouse")
    receipt.supplier_delivery_note = payload.get("supplier_delivery_note")
    receipt.cfg_kanban_controlled = 1
    receipt.cfg_kanban_cycle = cycle.name
    receipt.cfg_kanban_signal = command.source_signal
    receipt.insert(ignore_permissions=True)

    item = frappe.db.get_value("Item", cycle.item_code,
                               ["has_batch_no", "has_serial_no", "inspection_required_before_purchase"],
                               as_dict=True)
    controlled = item and (item.has_batch_no or item.has_serial_no or
                           item.inspection_required_before_purchase)
    if payload.get("submit") and not controlled:
        receipt.submit()
    receipt._cfg_command_result = {
        "doctype": receipt.doctype, "name": receipt.name, "docstatus": receipt.docstatus,
        "submitted": receipt.docstatus == 1,
        "requires_erp_completion": bool(payload.get("submit") and controlled),
        "message": ("Draft retained because batch, serial, or Quality Inspection control must "
                    "be completed in ERPNext before submission") if payload.get("submit") and controlled else None,
    }
    cycle.db_set("latest_purchase_receipt", receipt.name)
    return receipt


@handler("Create Purchase Order")
def create_purchase_order(command, payload):
    from erpnext.stock.doctype.material_request.material_request import make_purchase_order

    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = cycle.get("purchase_order") or frappe.db.get_value(
        "Purchase Order", {"cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]}, "name"
    )
    if existing:
        purchase_order = frappe.get_doc("Purchase Order", existing)
    else:
        request = frappe.get_doc("Material Request", payload["material_request"])
        if request.docstatus != 1:
            frappe.throw("Material Request must be submitted before creating its Purchase Order")
        purchase_order = make_purchase_order(request.name)
        purchase_order.supplier = payload["supplier"]
        purchase_order.cfg_kanban_controlled = 1
        purchase_order.cfg_kanban_cycle = cycle.name
        purchase_order.cfg_kanban_signal = command.source_signal
        purchase_order.run_method("set_missing_values")
        purchase_order.insert(ignore_permissions=True)
        cycle.db_set({"purchase_order": purchase_order.name,
                      "purchase_status": "Purchase Order Draft"})
        set_cycle_state(cycle, "Purchase Order Draft", event_type="Draft Purchase Order Created",
                        reference_doctype="Purchase Order", reference_name=purchase_order.name)

    requested_submit = payload.get("mode") == "Create and Submit Purchase Order"
    limits = [flt(payload.get("global_value_limit")), flt(payload.get("master_value_limit"))]
    positive_limits = [value for value in limits if value > 0]
    effective_limit = min(positive_limits) if positive_limits else 0
    can_submit = requested_submit and (
        not effective_limit or flt(purchase_order.grand_total) <= effective_limit
    )
    attention = None
    if requested_submit and not can_submit:
        attention = (f"Purchase Order total {purchase_order.grand_total} exceeds the effective "
                     f"auto-submit limit {effective_limit}")
        cycle.db_set("purchase_status", "Purchase Attention Required")
        set_cycle_state(cycle, "Purchase Attention Required",
                        event_type="Purchase Order Review Required",
                        reference_doctype="Purchase Order", reference_name=purchase_order.name)
    if can_submit and purchase_order.docstatus == 0:
        purchase_order.submit()
        purchase_order.reload()
    purchase_order._cfg_command_result = {
        "doctype": purchase_order.doctype, "name": purchase_order.name,
        "docstatus": purchase_order.docstatus, "requested_mode": payload.get("mode"),
        "effective_value_limit": effective_limit, "attention": attention,
    }
    return purchase_order


@handler("Create Intercompany Delivery Note")
def create_intercompany_delivery_note(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Delivery Note",
        {"cfg_movement_manifest": manifest.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Delivery Note", existing)
    delivery_note = build_intercompany_delivery_note(manifest, payload, command=command)
    delivery_note.insert(ignore_permissions=True)
    manifest.db_set("dispatch_delivery_note", delivery_note.name, update_modified=True)
    _link_manifest_erp_rows(manifest.name, delivery_note, "delivery_note_item")
    if payload.get("submit"):
        delivery_note.submit()
        delivery_note.reload()
    delivery_note._cfg_command_result = {
        "doctype": delivery_note.doctype,
        "name": delivery_note.name,
        "docstatus": delivery_note.docstatus,
        "submitted": delivery_note.docstatus == 1,
        "movement_manifest": manifest.name,
    }
    return delivery_note


def build_intercompany_delivery_note(manifest, payload, command=None, validate_required=True):
    """Build the ERP document in memory for preflight or command execution."""
    delivery_note = frappe.get_doc({
        "doctype": "Delivery Note",
        "company": payload["company"],
        "customer": payload["customer"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "selling_price_list": payload["price_list"],
        "cfg_kanban_controlled": 1,
        "cfg_logistics_route": manifest.logistics_route,
        "cfg_movement_manifest": manifest.name,
        "cfg_counterpart_company": payload["counterpart_company"],
        "cfg_requested_operator": command.requested_by_operator if command else None,
        "cfg_scan_event": command.idempotency_key if command else None,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_manifest_line": row["manifest_line"],
        } for row in payload["items"]],
    })
    delivery_note.set_missing_values()
    apply_required_erp_inputs(delivery_note, payload.get("required_erp_inputs"))
    missing = get_required_erp_inputs(delivery_note)
    if validate_required and missing:
        frappe.throw(
            "Required Delivery Note details are missing: "
            + ", ".join(row["label"] for row in missing)
        )
    return delivery_note


@handler("Create Internal Transfer Dispatch")
def create_internal_transfer_dispatch(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Stock Entry",
        {"cfg_movement_manifest": manifest.name,
         "cfg_transfer_stage": ["in", ["Direct", "Outward"]],
         "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        entry = frappe.get_doc("Stock Entry", existing)
        if payload.get("submit") and entry.docstatus == 0:
            entry.submit()
            entry.reload()
        return entry
    entry = build_internal_transfer_stock_entry(manifest, payload, command=command)
    entry.insert(ignore_permissions=True)
    manifest.db_set("dispatch_stock_entry", entry.name, update_modified=False)
    _link_internal_transfer_details(entry)
    if payload.get("submit"):
        entry.submit()
        entry.reload()
    entry._cfg_command_result = {
        "doctype": entry.doctype, "name": entry.name, "docstatus": entry.docstatus,
        "manifest": manifest.name, "stage": payload["stage"],
    }
    return entry


@handler("Create Internal Transfer Receipt")
def create_internal_transfer_receipt(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Stock Entry",
        {"cfg_movement_manifest": manifest.name, "cfg_transfer_stage": "Receipt",
         "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        entry = frappe.get_doc("Stock Entry", existing)
        if payload.get("submit") and entry.docstatus == 0:
            entry.submit()
            entry.reload()
        return entry
    entry = build_internal_transfer_stock_entry(manifest, payload, command=command)
    entry.insert(ignore_permissions=True)
    manifest.db_set("receipt_stock_entry", entry.name, update_modified=False)
    _link_internal_transfer_details(entry)
    if payload.get("submit"):
        entry.submit()
        entry.reload()
    entry._cfg_command_result = {
        "doctype": entry.doctype, "name": entry.name, "docstatus": entry.docstatus,
        "manifest": manifest.name, "stage": "Receipt",
    }
    return entry


def build_internal_transfer_stock_entry(manifest, payload, command=None):
    """Build the native ERPNext Material Transfer behind an internal Manifest."""
    stage = payload["stage"]
    source = (manifest.transit_warehouse if stage == "Receipt"
              else manifest.source_warehouse)
    destination = (manifest.destination_warehouse if stage in ("Direct", "Receipt")
                   else manifest.transit_warehouse)
    items = []
    for row in manifest.lines:
        outgoing_detail = None
        if stage == "Receipt":
            outgoing_detail = frappe.db.get_value(
                "Stock Entry Detail",
                {"parent": manifest.dispatch_stock_entry, "cfg_manifest_line": row.name},
                "name",
            )
            if not outgoing_detail:
                frappe.throw(
                    f"Outward Stock Entry row is missing for Manifest line {row.name}"
                )
        items.append({
            "item_code": row.item_code,
            "qty": row.dispatch_qty,
            "uom": row.stock_uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": 1,
            "transfer_qty": row.dispatch_qty,
            "s_warehouse": source,
            "t_warehouse": destination,
            "batch_no": row.batch_no,
            "against_stock_entry": manifest.dispatch_stock_entry if stage == "Receipt" else None,
            "ste_detail": outgoing_detail,
            "cfg_handling_unit": row.handling_unit,
            "cfg_manifest_line": row.name,
        })
    entry = frappe.get_doc({
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Transfer",
        "purpose": "Material Transfer",
        "company": manifest.source_company,
        "from_warehouse": source,
        "to_warehouse": destination,
        "add_to_transit": 1 if stage == "Outward" else 0,
        "outgoing_stock_entry": (manifest.dispatch_stock_entry if stage == "Receipt" else None),
        "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": manifest.kanban_cycle,
        "cfg_kanban_signal": manifest.source_signal,
        "cfg_logistics_route": manifest.logistics_route,
        "cfg_movement_manifest": manifest.name,
        "cfg_transfer_stage": stage,
        "items": items,
    })
    entry.set_missing_values()
    apply_required_erp_inputs(entry, payload.get("required_erp_inputs"))
    return entry


def _link_internal_transfer_details(entry):
    for row in entry.items:
        if row.get("cfg_manifest_line"):
            frappe.db.set_value(
                "CFG Kanban Manifest Line", row.cfg_manifest_line,
                "stock_entry_detail", row.name, update_modified=False,
            )


@handler("Create Kanban Stock Withdrawal")
def create_kanban_stock_withdrawal(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value(
        "Stock Entry",
        {"cfg_withdrawal_cycle": cycle.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        entry = frappe.get_doc("Stock Entry", existing)
        if payload.get("submit") and entry.docstatus == 0:
            entry.submit()
            entry.reload()
        return entry
    entry = build_withdrawal_stock_entry(cycle, payload, command=command)
    entry.insert(ignore_permissions=True)
    cycle.db_set("withdrawal_stock_entry", entry.name, update_modified=False)
    if payload.get("submit"):
        entry.submit()
        entry.reload()
    entry._cfg_command_result = {
        "doctype": entry.doctype, "name": entry.name, "docstatus": entry.docstatus,
        "cycle": cycle.name, "submitted": entry.docstatus == 1,
    }
    return entry


def build_withdrawal_stock_entry(cycle, payload, command=None):
    """Build the exact ERPNext Material Issue controlled by a Withdrawal Cycle."""
    items = [{
        "item_code": row.item_code,
        "qty": row.qty,
        "transfer_qty": row.qty,
        "uom": row.stock_uom,
        "stock_uom": row.stock_uom,
        "conversion_factor": 1,
        "s_warehouse": cycle.source_warehouse,
        "batch_no": row.batch_no,
        "cfg_handling_unit": row.handling_unit,
        "cfg_withdrawal_allocation": row.name,
    } for row in cycle.withdrawal_allocations]
    if not items:
        frappe.throw("Withdrawal has no selected stock")
    entry = frappe.get_doc({
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Issue",
        "purpose": "Material Issue",
        "company": cycle.company,
        "from_warehouse": cycle.source_warehouse,
        "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name,
        "cfg_kanban_signal": cycle.signal,
        "cfg_withdrawal_cycle": cycle.name,
        "cfg_scan_event": command.idempotency_key if command else None,
        "items": items,
    })
    entry.set_missing_values()
    apply_required_erp_inputs(entry, payload.get("required_erp_inputs"))
    missing = get_required_erp_inputs(entry)
    if missing:
        frappe.throw(
            "Required Material Issue details are missing: "
            + ", ".join(row["label"] for row in missing)
        )
    return entry


@handler("Create Customer Delivery Note")
def create_customer_delivery_note(command, payload):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", command.delivery_session)
    existing = frappe.db.get_value(
        "Delivery Note",
        {"cfg_delivery_session": delivery.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Delivery Note", existing)
    delivery_note = build_customer_delivery_note(delivery, payload, command=command)
    delivery_note.insert(ignore_permissions=True)
    delivery.db_set("delivery_note", delivery_note.name, update_modified=True)
    for row in delivery_note.items:
        allocation = row.get("cfg_delivery_allocation")
        if allocation:
            frappe.db.set_value(
                "CFG Kanban Delivery Allocation", allocation,
                {"delivery_note": delivery_note.name, "delivery_note_item": row.name},
                update_modified=False,
            )
    if payload.get("submit"):
        delivery_note.submit()
        delivery_note.reload()
    delivery_note._cfg_command_result = {
        "doctype": delivery_note.doctype,
        "name": delivery_note.name,
        "docstatus": delivery_note.docstatus,
        "submitted": delivery_note.docstatus == 1,
        "delivery_session": delivery.name,
    }
    return delivery_note


def build_customer_delivery_note(delivery, payload, command=None, validate_required=True):
    """Build one locked-price customer Delivery Note row per physical allocation."""
    values = {
        "doctype": "Delivery Note",
        "company": payload["company"],
        "customer": payload["customer"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "selling_price_list": payload["price_list"],
        "shipping_address_name": payload["customer_address"],
        "cfg_kanban_controlled": 1,
        "cfg_delivery_session": delivery.name,
        "cfg_requested_operator": command.requested_by_operator if command else None,
        "cfg_scan_event": command.idempotency_key if command else None,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_delivery_allocation": row["delivery_allocation"],
        } for row in payload["items"]],
    }
    if payload.get("amended_from"):
        values["amended_from"] = payload["amended_from"]
    delivery_note = frappe.get_doc(values)
    delivery_note.set_missing_values()
    apply_required_erp_inputs(delivery_note, payload.get("required_erp_inputs"))
    missing = get_required_erp_inputs(delivery_note)
    if validate_required and missing:
        frappe.throw(
            "Required Delivery Note details are missing: "
            + ", ".join(row["label"] for row in missing)
        )
    return delivery_note


@handler("Create Correction Return Delivery Note")
def create_correction_return_delivery_note(command, payload):
    """Create a stock return against the exact submitted Delivery Note.

    This path corrects physical delivery only. It never chooses or creates a
    Sales Invoice return, Credit Note, or e-Invoice document.
    """
    from erpnext.controllers.sales_and_purchase_return import make_return_doc

    case = frappe.get_doc("CFG Kanban Return Case", command.return_case)
    if case.correction_return_delivery_note and frappe.db.exists(
        "Delivery Note", case.correction_return_delivery_note
    ):
        return frappe.get_doc("Delivery Note", case.correction_return_delivery_note)
    source_name = payload["original_delivery_note"]
    source = frappe.get_doc("Delivery Note", source_name)
    if source.docstatus != 1 or source.is_return:
        frappe.throw("Delivery Note Correction requires a submitted non-return Delivery Note")
    selected = {
        row["original_delivery_note_item"]: flt(row["claimed_qty"])
        for row in payload.get("lines") or []
    }
    if not selected or None in selected:
        frappe.throw("Correction lines must reference original Delivery Note item rows")
    return_doc = make_return_doc("Delivery Note", source_name)
    kept = []
    for row in return_doc.items:
        source_row = row.get("dn_detail")
        if source_row not in selected:
            continue
        stock_qty = abs(selected[source_row])
        row.qty = -(stock_qty / flt(row.conversion_factor or 1))
        row.stock_qty = -stock_qty
        row.warehouse = payload["return_warehouse"]
        kept.append(row)
    if len(kept) != len(selected):
        frappe.throw("ERPNext could not map every selected original Delivery Note row")
    return_doc.set("items", kept)
    return_doc.set_warehouse = payload["return_warehouse"]
    return_doc.cfg_kanban_controlled = 1
    return_doc.cfg_return_case = case.name
    return_doc.cfg_requested_operator = command.requested_by_operator
    return_doc.cfg_scan_event = command.idempotency_key
    return_doc.remarks = (
        f"Wrong Delivery Note correction {case.name}. "
        "This stock reversal does not create or select an accounting Credit Note."
    )
    return_doc.insert(ignore_permissions=True)
    case.db_set("correction_return_delivery_note", return_doc.name, update_modified=False)
    if payload.get("submit"):
        return_doc.submit()
        return_doc.reload()
    return_doc._cfg_command_result = {
        "doctype": return_doc.doctype, "name": return_doc.name,
        "docstatus": return_doc.docstatus, "submitted": return_doc.docstatus == 1,
        "return_case": case.name, "return_against": source_name,
    }
    return return_doc


@handler("Create Customer Credit Return")
def create_customer_credit_return(command, payload):
    """Prepare a non-stock Draft Sales Invoice Return after controlled QC.

    Submission and e-Invoice validation remain accountant-owned in ERPNext.
    """
    from erpnext.controllers.sales_and_purchase_return import make_return_doc

    case = frappe.get_doc("CFG Kanban Return Case", command.return_case)
    if case.return_flow != "Customer Return for QC" or \
            case.state != "QC Completed - Accounting Pending":
        frappe.throw("Customer Return Case is not ready for a credit return")
    if case.credit_document:
        existing_status = frappe.db.get_value("Sales Invoice", case.credit_document, "docstatus")
        if existing_status in (0, 1):
            return frappe.get_doc("Sales Invoice", case.credit_document)
    source_name = payload["source_sales_invoice"]
    source = frappe.get_doc("Sales Invoice", source_name)
    if source.docstatus != 1 or source.is_return:
        frappe.throw("Credit source must be a submitted non-return Sales Invoice")
    if source.company != case.selling_company or source.customer != case.customer:
        frappe.throw("Credit source Company and Customer do not match the Return Case")
    remaining = {
        item_code: flt(qty)
        for item_code, qty in (payload.get("accepted_items") or {}).items()
        if flt(qty) > 0
    }
    if not remaining:
        frappe.throw("Customer Return Case has no accepted quantity to credit")
    source_remaining = _remaining_sales_invoice_quantities(source)
    source_shortage = {
        item_code: qty - flt(source_remaining.get(item_code))
        for item_code, qty in remaining.items()
        if qty > flt(source_remaining.get(item_code)) + 0.000001
    }
    if source_shortage:
        frappe.throw(
            "Selected Sales Invoice has insufficient uncredited quantity: "
            + ", ".join(f"{item} {qty}" for item, qty in source_shortage.items())
        )
    credit = make_return_doc("Sales Invoice", source_name)
    kept = []
    for row in credit.items:
        required = flt(remaining.get(row.item_code))
        if required <= 0:
            continue
        available = abs(flt(row.stock_qty or row.qty))
        take = min(required, available)
        if take <= 0:
            continue
        row.stock_qty = -take
        row.qty = -(take / flt(row.conversion_factor or 1))
        kept.append(row)
        remaining[row.item_code] = required - take
    shortage = {item: qty for item, qty in remaining.items() if qty > 0.000001}
    if shortage:
        frappe.throw(
            "Selected Sales Invoice has insufficient remaining return quantity: "
            + ", ".join(f"{item} {qty}" for item, qty in shortage.items())
        )
    credit.set("items", kept)
    credit.update_stock = 0
    credit.cfg_return_case = case.name
    credit.cfg_scan_event = command.idempotency_key
    if case.credit_document and frappe.db.get_value(
        "Sales Invoice", case.credit_document, "docstatus"
    ) == 2:
        cancelled_source = frappe.db.get_value(
            "Sales Invoice", case.credit_document, "return_against"
        )
        if cancelled_source == source.name:
            credit.amended_from = case.credit_document
    credit.remarks = (
        f"CFG Kanban Customer Return {case.name}. QC accepted quantity only. "
        f"Accounting source basis: {payload['source_basis']}. "
        f"Decision: {payload['decision_notes']}"
    )
    credit.insert(ignore_permissions=True)
    case.db_set({
        "accounting_status": "Credit Pending",
        "accounting_source_basis": payload["source_basis"],
        "accounting_reference_doctype": "Sales Invoice",
        "accounting_reference": source.name,
        "accounting_decided_by": command.terminal_user or frappe.session.user,
        "accounting_decided_on": now_datetime(),
        "accounting_decision_notes": payload["decision_notes"],
        "credit_document_doctype": "Sales Invoice",
        "credit_document": credit.name,
        "credit_document_status": "Draft",
    }, update_modified=True)
    credit._cfg_command_result = {
        "doctype": credit.doctype, "name": credit.name, "docstatus": credit.docstatus,
        "return_case": case.name, "return_against": source.name,
        "update_stock": 0, "accounting_revision": payload.get("accounting_revision") or 0,
    }
    return credit


def _remaining_sales_invoice_quantities(source):
    totals = {}
    for row in source.items:
        totals[row.item_code] = totals.get(row.item_code, 0) + abs(flt(row.stock_qty))
    returned = frappe.db.sql(
        """
        select item.item_code, sum(abs(item.stock_qty)) as returned_qty
        from `tabSales Invoice` invoice
        inner join `tabSales Invoice Item` item on item.parent=invoice.name
        where invoice.docstatus=1 and invoice.is_return=1 and invoice.return_against=%s
        group by item.item_code
        """,
        (source.name,), as_dict=True,
    )
    for row in returned:
        totals[row.item_code] = max(
            flt(totals.get(row.item_code)) - flt(row.returned_qty), 0
        )
    return totals


@handler("Create Customer Return Material Receipt")
def create_customer_return_material_receipt(command, payload):
    """Prepare a Draft Material Receipt for QC-accepted physical stock."""
    case = frappe.get_doc("CFG Kanban Return Case", command.return_case)
    if case.return_flow != "Customer Return for QC" or not case.qc_completed_on:
        frappe.throw("Customer Return Case is not ready for physical stock disposition")
    if case.stock_disposition_entry:
        existing_status = frappe.db.get_value(
            "Stock Entry", case.stock_disposition_entry, "docstatus"
        )
        if existing_status in (0, 1):
            return frappe.get_doc("Stock Entry", case.stock_disposition_entry)
    lines = payload.get("disposition_lines") or []
    if not lines:
        frappe.throw("Material Receipt requires at least one accepted return disposition row")
    entry = frappe.get_doc({
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Receipt",
        "company": case.selling_company,
        "cfg_kanban_controlled": 1,
        "cfg_return_case": case.name,
        "cfg_scan_event": command.idempotency_key,
        "remarks": (
            f"CFG Kanban accepted customer return {case.name}. "
            f"Physical stock disposition only; accounting credit is controlled separately. "
            f"Decision: {payload.get('decision_notes') or '-'}"
        ),
        "items": [{
            "item_code": row["item_code"],
            "qty": flt(row["qty"]),
            "transfer_qty": flt(row["qty"]),
            "uom": row["stock_uom"],
            "stock_uom": row["stock_uom"],
            "conversion_factor": 1,
            "t_warehouse": row["target_warehouse"],
            "basic_rate": flt(row["valuation_rate"]),
            "allow_zero_valuation_rate": int(not flt(row["valuation_rate"])),
            "batch_no": row.get("batch_no"),
            "cfg_return_disposition_line": row["disposition_line"],
        } for row in lines],
    })
    if case.stock_disposition_entry and frappe.db.get_value(
        "Stock Entry", case.stock_disposition_entry, "docstatus"
    ) == 2:
        entry.amended_from = case.stock_disposition_entry
    entry.insert(ignore_permissions=True)
    for item in entry.items:
        disposition_line = item.get("cfg_return_disposition_line")
        if disposition_line:
            frappe.db.set_value(
                "CFG Kanban Return Disposition Line", disposition_line,
                {"stock_entry_detail": item.name, "status": "Draft"},
                update_modified=False,
            )
    case.db_set({
        "disposition_status": "Stock Receipt Draft",
        "stock_disposition_entry": entry.name,
        "stock_disposition_entry_status": "Draft",
    }, update_modified=True)
    entry._cfg_command_result = {
        "doctype": entry.doctype,
        "name": entry.name,
        "docstatus": entry.docstatus,
        "return_case": case.name,
        "stock_entry_type": entry.stock_entry_type,
        "disposition_revision": payload.get("disposition_revision") or 0,
    }
    return entry


def get_required_erp_inputs(doc):
    """Describe editable mandatory values still missing from an ERP document."""
    # Frappe normally assigns the first configured naming-series option during
    # document insertion. CFG preflights mandatory values before insertion, so
    # resolve that same default here instead of asking a floor operator to choose
    # accounting document numbering for every transaction.
    naming_field = doc.meta.get_field("naming_series")
    if naming_field and not doc.get("naming_series"):
        doc.naming_series = get_default_naming_series(doc.doctype)

    requirements = []
    for field in doc.meta.fields:
        if field.fieldtype == "Table":
            rows = doc.get(field.fieldname) or []
            missing_children = []
            for row_index, row in enumerate(rows):
                missing_children.extend(
                    _missing_child_requirements(field, row=row, row_index=row_index)
                )
            invalid_sales_team = (
                field.fieldname == "sales_team"
                and rows
                and abs(sum(flt(row.get("allocated_percentage")) for row in rows) - 100)
                > 0.000001
            )
            if (field.reqd and not rows) or missing_children or invalid_sales_team:
                requirements.append(_required_table_descriptor(field, rows))
            continue
        if not field.reqd:
            continue
        if _is_missing_required_value(doc.get(field.fieldname)):
            requirements.append(_required_field_descriptor(field, scope="parent"))
    return [row for row in requirements if row]


def apply_required_erp_inputs(doc, values):
    values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    allowed = get_required_erp_inputs(doc)
    parent_values = values.get("parent") or {}
    table_values = values.get("tables") or {}

    for requirement in allowed:
        if requirement["scope"] == "parent":
            value = parent_values.get(requirement["fieldname"])
            if not _is_missing_required_value(value):
                doc.set(requirement["fieldname"], value)

    for requirement in allowed:
        if requirement["scope"] != "table":
            continue
        supplied_rows = table_values.get(requirement["fieldname"])
        if supplied_rows:
            if requirement["fieldname"] == "sales_team":
                allocated = sum(flt(row.get("allocated_percentage")) for row in supplied_rows)
                if abs(allocated - 100) > 0.000001:
                    frappe.throw("Sales Team allocated percentage must total 100%")
            allowed_columns = {column["fieldname"] for column in requirement["fields"]}
            clean_rows = [
                {fieldname: row.get(fieldname) for fieldname in allowed_columns}
                for row in supplied_rows
            ]
            doc.set(requirement["fieldname"], clean_rows)

def _missing_child_requirements(table_field, row, row_index):
    child_meta = frappe.get_meta(table_field.options)
    requirements = []
    for field in child_meta.fields:
        if not field.reqd:
            continue
        value = row.get(field.fieldname) if row else None
        if _is_missing_required_value(value):
            requirements.append(_required_field_descriptor(
                field,
                scope="child",
                table_field=table_field.fieldname,
                table_label=table_field.label,
                row_index=row_index,
            ))
    return [requirement for requirement in requirements if requirement]


def _required_table_descriptor(table_field, rows):
    child_meta = frappe.get_meta(table_field.options)
    fields = []
    for field in child_meta.fields:
        include = bool(field.reqd or field.in_list_view)
        if table_field.fieldname == "sales_team" and field.fieldname in (
            "sales_person", "allocated_percentage"
        ):
            include = True
        if not include or field.read_only:
            continue
        descriptor = _required_field_descriptor(field, scope="table_column")
        if not descriptor:
            continue
        descriptor["reqd"] = bool(
            field.reqd
            or (
                table_field.fieldname == "sales_team"
                and field.fieldname in ("sales_person", "allocated_percentage")
            )
        )
        if table_field.fieldname == "sales_team" and field.fieldname == "allocated_percentage":
            descriptor["default"] = 100
        fields.append(descriptor)
    if not fields:
        frappe.throw(
            f"Mandatory ERP table {table_field.label} has no editable columns. "
            "Configure a default in ERPNext."
        )
    return {
        "scope": "table",
        "fieldname": table_field.fieldname,
        "label": table_field.label,
        "fieldtype": "Table",
        "options": table_field.options,
        "fields": fields,
        "default": [
            {column["fieldname"]: row.get(column["fieldname"]) for column in fields}
            for row in rows
        ],
    }


def _required_field_descriptor(field, scope, table_field=None, table_label=None, row_index=None):
    # Read-only mandatory values such as child-row Status are maintained by
    # ERPNext during validation and are not operator-supplied dispatch data.
    if field.read_only:
        return None
    supported = {
        "Data", "Link", "Select", "Date", "Datetime", "Int", "Float",
        "Currency", "Percent", "Check", "Time", "Duration", "Small Text", "Text",
    }
    if field.fieldtype not in supported:
        frappe.throw(
            f"Mandatory ERP field {table_label + ' / ' if table_label else ''}{field.label} "
            "cannot be collected from the logistics panel. Configure a default in ERPNext."
        )
    default = field.default
    if table_field == "sales_team" and field.fieldname == "allocated_percentage":
        default = 100
    return {
        "scope": scope,
        "fieldname": field.fieldname,
        "label": f"{table_label} / {field.label}" if table_label else field.label,
        "fieldtype": field.fieldtype,
        "options": field.options,
        "default": default,
        "table_field": table_field,
        "row_index": row_index,
    }


def _is_missing_required_value(value):
    return value is None or value == "" or value == []


@handler("Create Intercompany Purchase Receipt")
def create_intercompany_purchase_receipt(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Purchase Receipt",
        {"cfg_movement_manifest": manifest.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Purchase Receipt", existing)
    receipt = frappe.get_doc({
        "doctype": "Purchase Receipt",
        "company": payload["company"],
        "supplier": payload["supplier"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "buying_price_list": payload["price_list"],
        "cfg_kanban_controlled": 1,
        "cfg_logistics_route": manifest.logistics_route,
        "cfg_movement_manifest": manifest.name,
        "cfg_counterpart_company": payload["counterpart_company"],
        "cfg_counterpart_document": payload.get("counterpart_document"),
        "cfg_requested_operator": command.requested_by_operator,
        "cfg_scan_event": command.idempotency_key,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "received_qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_manifest_line": row["manifest_line"],
        } for row in payload["items"]],
    })
    receipt.set_missing_values()
    receipt.insert(ignore_permissions=True)
    manifest.db_set("receipt_purchase_receipt", receipt.name, update_modified=True)
    _link_manifest_erp_rows(manifest.name, receipt, "purchase_receipt_item")
    if payload.get("submit"):
        receipt.submit()
        receipt.reload()
    receipt._cfg_command_result = {
        "doctype": receipt.doctype,
        "name": receipt.name,
        "docstatus": receipt.docstatus,
        "submitted": receipt.docstatus == 1,
        "movement_manifest": manifest.name,
    }
    return receipt


def _link_manifest_erp_rows(manifest_name, erp_document, target_field):
    for row in erp_document.items:
        manifest_line = row.get("cfg_manifest_line")
        if manifest_line:
            frappe.db.set_value(
                "CFG Kanban Manifest Line", manifest_line, target_field, row.name,
                update_modified=False,
            )


@frappe.whitelist()
def reload_draft_work_order_bom(work_order_name):
    """Repair a draft Kanban Work Order created before BOM population was added."""
    work_order = frappe.get_doc("Work Order", work_order_name)
    work_order.check_permission("write")
    if not work_order.cfg_kanban_cycle:
        frappe.throw("This Work Order is not linked to a CFG Kanban Cycle")
    if work_order.docstatus != 0:
        frappe.throw("BOM details can only be reloaded into a Draft Work Order")
    work_order.get_items_and_operations_from_bom()
    if not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and add the route first.")
    work_order.save()
    return {"work_order": work_order.name, "operations": len(work_order.operations),
            "required_items": len(work_order.required_items)}


@handler("Start Job Card")
def start_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if command.get("operator_session") and not payload.get("employee"):
        frappe.throw("An Employee is required for a Kanban operator Job Card action")
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if not any(not row.to_time for row in job_card.time_logs):
        started = now_datetime()
        job_card.append("time_logs", {
            "from_time": started, "employee": payload.get("employee")
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not start Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="started")
    return job_card


@handler("Pause Job Card")
def pause_job_card(command, payload):
    """Close only the active time log; ERPNext retains cumulative Job Card output."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status != "Work In Progress":
        frappe.throw(f"Job Card {job_card.name} must be Work In Progress before it can be paused")
    open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
    closed_time_log = None
    if open_row:
        open_row.to_time = get_datetime(payload.get("paused_on") or now_datetime())
        closed_time_log = open_row.name
        job_card.save(ignore_permissions=True)
    job_card.reload()
    job_card._cfg_command_result = _job_card_result(
        job_card, action="paused", closed_time_log=closed_time_log,
        kanban_pause=True,
    )
    return job_card


@handler("Resume Job Card")
def resume_job_card(command, payload):
    """Open a fresh time log on the same Job Card after a Kanban-controlled pause."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status not in ("Open", "Work In Progress"):
        frappe.throw(f"Job Card {job_card.name} cannot resume while its status is {job_card.status}")
    if not any(not row.to_time for row in job_card.time_logs):
        job_card.append("time_logs", {
            "from_time": get_datetime(payload.get("resumed_on") or now_datetime()),
            "employee": payload.get("employee"),
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not resume Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="resumed", kanban_pause=True)
    return job_card


@handler("Update Job Card")
def update_job_card(command, payload):
    required = ("job_card", "operation_progress", "incremental_good_qty")
    missing = [field for field in required if payload.get(field) in (None, "")]
    if missing:
        frappe.throw("Job Card progress payload is missing: " + ", ".join(missing))
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")

    progress_ref = payload["operation_progress"]
    # The app-owned child-row link makes a retry independently detectable even when
    # the original CFG command is manually re-created by a supervisor.
    existing = next((row for row in job_card.time_logs
                     if row.get("cfg_kanban_progress") == progress_ref), None)
    before_qty = flt(job_card.total_completed_qty)
    delta = flt(payload["incremental_good_qty"])
    if not existing:
        end_time = get_datetime(payload.get("to_time") or now_datetime())
        start_time = get_datetime(payload.get("from_time") or add_to_date(end_time, minutes=-1))
        closed_rows = [row for row in job_card.time_logs if row.to_time]
        if closed_rows:
            start_time = max(start_time, max(get_datetime(row.to_time) for row in closed_rows))
        if start_time >= end_time:
            start_time = add_to_date(end_time, minutes=-1)
        open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
        if open_row:
            open_row.to_time = end_time
            open_row.completed_qty = delta
            open_row.employee = open_row.employee or payload.get("employee")
            open_row.cfg_kanban_progress = progress_ref
        else:
            job_card.append("time_logs", {
                "from_time": start_time, "to_time": end_time,
                "completed_qty": delta, "employee": payload.get("employee"),
                "cfg_kanban_progress": progress_ref,
            })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    after_qty = flt(job_card.total_completed_qty)
    expected_qty = before_qty if existing else before_qty + delta
    if after_qty + 0.000001 < expected_qty:
        frappe.throw(f"ERPNext Job Card {job_card.name} quantity verification failed: "
                     f"expected at least {expected_qty}, found {after_qty}")
    auto_submitted = False
    settings = frappe.get_single("CFG Kanban Settings")
    if (settings.get("auto_submit_job_card") and job_card.docstatus == 0 and
            after_qty + 0.000001 >= flt(job_card.for_quantity)):
        job_card.submit()
        job_card.reload()
        auto_submitted = True
        if job_card.status != "Completed":
            frappe.throw(f"ERPNext submitted Job Card {job_card.name}, but its status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(
        job_card, action="progress_updated", before_qty=before_qty,
        applied_qty=0 if existing else delta, operation_progress=progress_ref,
        duplicate=bool(existing), reject_qty=flt(payload.get("reject_qty")),
        auto_submitted=auto_submitted,
    )
    return job_card


@handler("Complete Job Card")
def complete_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus == 0:
        if flt(job_card.total_completed_qty) + 0.000001 < flt(job_card.for_quantity):
            frappe.throw(f"Job Card {job_card.name} cannot be completed: ERP completed quantity "
                         f"is {job_card.total_completed_qty} of {job_card.for_quantity}")
        job_card.submit()
    job_card.reload()
    if job_card.status != "Completed":
        frappe.throw(f"ERPNext did not complete Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="completed")
    return job_card


def _job_card_result(job_card, action, **details):
    return {
        "doctype": job_card.doctype, "name": job_card.name, "action": action,
        "status": job_card.status, "docstatus": job_card.docstatus,
        "for_quantity": flt(job_card.for_quantity),
        "total_completed_qty": flt(job_card.total_completed_qty),
        "time_log_rows": len(job_card.time_logs), **details,
    }


@handler("Cancel Signal and Rollback")
def cancel_signal_and_rollback(command, payload):
    from cfg_kanban.services.signal_cancellation import cancel_and_rollback

    return cancel_and_rollback(payload["signal"], payload.get("reason"))


@handler("Create Stock Entry")
def create_stock_entry(command, payload):
    doc = frappe.get_doc({"doctype": "Stock Entry", **payload, "cfg_kanban_controlled": 1,
                          "cfg_kanban_cycle": command.kanban_cycle,
                          "cfg_kanban_signal": command.source_signal}).insert(ignore_permissions=True)
    return doc

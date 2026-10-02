import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


SUPPORTED_PURPOSES = {
    "Manufacture",
    "Material Transfer for Manufacture",
    "Material Consumption for Manufacture",
    "Repack",
}
ACTIVE_INPUT_STATUSES = ("Reserved", "Confirmed")
ACTIVE_OUTPUT_STATUSES = ("Pending", "Confirmed")
ALLOWED_ROLES = (
    "Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager",
    "System Manager",
)
TOLERANCE = 0.000001


@frappe.whitelist()
def get_stock_entry_trace_plan(stock_entry):
    frappe.only_for(ALLOWED_ROLES)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    doc.check_permission("read")
    _assert_supported(doc)
    trace = _get_trace(doc.name)
    return _trace_plan(doc, trace)


@frappe.whitelist()
def allocate_input_tag(stock_entry, item_row, scan_value, qty):
    frappe.only_for(ALLOWED_ROLES)
    qty = flt(qty)
    if qty <= 0:
        frappe.throw("Input tag quantity must be positive")
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    doc.check_permission("write")
    _assert_editable(doc)
    row = _find_row(doc, item_row)
    if not row.s_warehouse:
        frappe.throw("The selected Stock Entry row is not a material input")
    policy = effective_trace_policy(row.item_code, doc.company)
    if policy.production_input_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} uses ERP stock without physical production-input tags"
        )

    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Handling Unit tag for the production input")
    batch_no = _tag_batch_no(row)
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    _validate_input_unit(unit, doc, row, policy, batch_no)

    trace = _ensure_trace(doc)
    remaining = _remaining_row_qty(doc, trace, row, "Input")
    if qty > remaining + TOLERANCE:
        frappe.throw(
            f"Allocated quantity {qty} exceeds remaining Stock Entry input quantity {remaining}"
        )
    if qty > flt(unit.available_qty) + TOLERANCE:
        frappe.throw(
            f"Handling Unit {unit.handling_unit_id} has only {unit.available_qty} available"
        )
    if _is_transfer_purpose(doc) and abs(qty - flt(unit.current_qty)) > TOLERANCE:
        frappe.throw(
            "A physical tag cannot be split across two Warehouses. Transfer the complete "
            f"Handling Unit quantity {unit.current_qty}, or activate a detachable child tag "
            "for the partial physical quantity first."
        )

    line = trace.append("lines", {
        "direction": "Input",
        "status": "Reserved",
        "stock_entry_detail": row.name,
        "item_code": row.item_code,
        "batch_no": batch_no,
        "warehouse": row.s_warehouse,
        "qty": qty,
        "stock_uom": row.stock_uom,
        "trace_policy": policy.production_input_tag_policy,
        "handling_unit": unit.name,
    })
    trace.save(ignore_permissions=True)
    ledger = post_quantity_event(
        event_type="Reserve",
        qty=qty,
        stock_uom=row.stock_uom,
        idempotency_key=f"production-trace-reserve:{trace.name}:{line.name}",
        source_handling_unit=unit.name,
        item_code=row.item_code,
        batch_no=batch_no,
        source_company=doc.company,
        source_warehouse=row.s_warehouse,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        reason=f"Reserved for {_purpose(doc)} / {doc.work_order or 'no Work Order'}",
    )
    line.reservation_ledger = ledger.name
    trace.save(ignore_permissions=True)
    record(
        "Production Input Tag Reserved",
        cycle=doc.get("cfg_kanban_cycle"),
        handling_unit=unit.name,
        qty=qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{row.item_code} / {row.s_warehouse}",
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def stage_output_tag(stock_entry, item_row, scan_value, qty,
                     handling_unit_type="Container"):
    frappe.only_for(ALLOWED_ROLES)
    qty = flt(qty)
    if qty <= 0:
        frappe.throw("Output tag quantity must be positive")
    try:
        visible_code = normalize_physical_code(scan_value)
    except ValueError as exc:
        frappe.throw(str(exc))
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    doc.check_permission("write")
    _assert_editable(doc)
    row = _find_row(doc, item_row)
    if not _is_output_row(doc, row):
        frappe.throw("The selected Stock Entry row is not a manufactured/repacked output")
    policy = effective_trace_policy(row.item_code, doc.company)
    if policy.production_output_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} uses ERP stock without physical production-output tags"
        )
    batch_no = _tag_batch_no(row)
    if policy.require_batch and not batch_no:
        frappe.throw(f"Item {row.item_code} requires a Batch before an output tag can be staged")
    _validate_unused_main_tag(visible_code)
    existing_pending = frappe.db.get_value(
        "CFG Kanban Material Trace Line",
        {"pending_tag_code": visible_code, "status": ["in", ["Pending", "Confirmed"]]},
        ["parent", "name"],
        as_dict=True,
    )
    if existing_pending:
        frappe.throw(
            f"Output tag {visible_code} is already staged on Material Trace "
            f"{existing_pending.parent}"
        )

    trace = _ensure_trace(doc)
    remaining = _remaining_row_qty(doc, trace, row, "Output")
    if qty > remaining + TOLERANCE:
        frappe.throw(
            f"Staged quantity {qty} exceeds remaining Stock Entry output quantity {remaining}"
        )
    if not policy.allow_partial_tag_quantity and abs(qty - remaining) > TOLERANCE:
        frappe.throw(
            f"Item {row.item_code} requires the remaining output quantity {remaining} "
            "to be staged on one tag"
        )

    trace.append("lines", {
        "direction": "Output",
        "status": "Pending",
        "stock_entry_detail": row.name,
        "item_code": row.item_code,
        "batch_no": batch_no,
        "warehouse": row.t_warehouse,
        "qty": qty,
        "stock_uom": row.stock_uom,
        "trace_policy": policy.production_output_tag_policy,
        "pending_tag_code": visible_code,
        "handling_unit_type": handling_unit_type or "Container",
    })
    trace.save(ignore_permissions=True)
    record(
        "Production Output Tag Staged",
        cycle=doc.get("cfg_kanban_cycle"),
        qty=qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{visible_code} / {row.item_code} / {row.t_warehouse}",
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def cancel_trace_line(stock_entry, trace_line):
    frappe.only_for(ALLOWED_ROLES)
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    doc.check_permission("write")
    _assert_editable(doc)
    trace = _get_trace(doc.name)
    if not trace or trace.status != "Draft":
        frappe.throw("No editable Material Trace exists for this Stock Entry")
    line = next((candidate for candidate in trace.lines if candidate.name == trace_line), None)
    if not line or line.status not in ("Reserved", "Pending"):
        frappe.throw("The selected trace line is no longer cancellable")
    if line.direction == "Input":
        ledger = post_quantity_event(
            event_type="Unreserve",
            qty=line.qty,
            stock_uom=line.stock_uom,
            idempotency_key=f"production-trace-unreserve:{trace.name}:{line.name}",
            source_handling_unit=line.handling_unit,
            item_code=line.item_code,
            batch_no=line.batch_no,
            source_company=doc.company,
            source_warehouse=line.warehouse,
            reference_doctype="CFG Kanban Material Trace",
            reference_name=trace.name,
            reason="Production trace line cancelled before ERP submission",
        )
        line.reversal_ledger = ledger.name
    line.status = "Cancelled"
    trace.save(ignore_permissions=True)
    record(
        "Production Material Trace Line Cancelled",
        cycle=doc.get("cfg_kanban_cycle"),
        handling_unit=line.handling_unit,
        qty=line.qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{line.direction} / {line.item_code} / {line.pending_tag_code or ''}",
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def abandon_draft_trace(stock_entry, reason):
    frappe.only_for(ALLOWED_ROLES)
    if not (reason or "").strip():
        frappe.throw("Reason is required to discard a Draft Material Trace")
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    doc.check_permission("write")
    _assert_editable(doc)
    trace = _get_trace(doc.name)
    if not trace or trace.status != "Draft":
        frappe.throw("No Draft Material Trace exists for this Stock Entry")
    for line in trace.lines:
        if line.status == "Reserved":
            ledger = post_quantity_event(
                event_type="Unreserve",
                qty=line.qty,
                stock_uom=line.stock_uom,
                idempotency_key=f"production-trace-abandon-unreserve:{trace.name}:{line.name}",
                source_handling_unit=line.handling_unit,
                item_code=line.item_code,
                batch_no=line.batch_no,
                source_company=doc.company,
                source_warehouse=line.warehouse,
                reference_doctype="CFG Kanban Material Trace",
                reference_name=trace.name,
                reason=f"Draft Material Trace abandoned: {reason.strip()}",
            )
            line.reversal_ledger = ledger.name
            line.status = "Cancelled"
        elif line.status == "Pending":
            line.status = "Cancelled"
    trace.status = "Abandoned"
    trace.abandoned_on = now_datetime()
    trace.abandoned_by = frappe.session.user
    trace.abandon_reason = reason.strip()
    trace.stock_entry = None
    trace.save(ignore_permissions=True)
    record(
        "Draft Production Material Trace Abandoned",
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"Material Trace {trace.name}: {reason.strip()}",
    )
    return {"trace": trace.name, "status": trace.status, "stock_entry": doc.name}


def validate_stock_entry_trace(doc):
    """Enforce only explicit Required policies; ERP-only rows remain untouched."""
    if _purpose(doc) not in SUPPORTED_PURPOSES:
        return
    trace = _get_trace(doc.name)
    for row in doc.items:
        if row.s_warehouse:
            policy = effective_trace_policy(row.item_code, doc.company)
            allocated = _line_qty(trace, row.name, "Input", ACTIVE_INPUT_STATUSES)
            required = policy.production_input_tag_policy == "Required Physical Tag"
            if allocated > _row_stock_qty(row) + TOLERANCE:
                frappe.throw(f"Tagged input exceeds Stock Entry quantity for Item {row.item_code}")
            if required and allocated + TOLERANCE < _row_stock_qty(row):
                frappe.throw(
                    f"Item {row.item_code} requires production-input tags for "
                    f"{_row_stock_qty(row)} {row.stock_uom}; allocated {allocated}"
                )
        if _is_output_row(doc, row):
            policy = effective_trace_policy(row.item_code, doc.company)
            staged = _line_qty(trace, row.name, "Output", ACTIVE_OUTPUT_STATUSES)
            required = policy.production_output_tag_policy == "Required Physical Tag"
            if staged > _row_stock_qty(row) + TOLERANCE:
                frappe.throw(f"Tagged output exceeds Stock Entry quantity for Item {row.item_code}")
            if required and staged + TOLERANCE < _row_stock_qty(row):
                frappe.throw(
                    f"Item {row.item_code} requires production-output tags for "
                    f"{_row_stock_qty(row)} {row.stock_uom}; staged {staged}"
                )
    if not trace:
        return
    rows = {row.name: row for row in doc.items}
    for line in trace.lines:
        if line.status not in ("Reserved", "Pending"):
            continue
        row = rows.get(line.stock_entry_detail)
        if not row or row.item_code != line.item_code or row.stock_uom != line.stock_uom:
            frappe.throw(
                f"Material Trace line {line.idx} no longer matches its Stock Entry row"
            )
        expected_warehouse = row.s_warehouse if line.direction == "Input" else row.t_warehouse
        if (line.warehouse != expected_warehouse
                or (line.batch_no or "") != (_tag_batch_no(row) or "")):
            frappe.throw(
                f"Material Trace line {line.idx} Warehouse or Batch changed after scanning"
            )


def confirm_stock_entry_trace(doc):
    if _purpose(doc) not in SUPPORTED_PURPOSES:
        return
    trace = _get_trace(doc.name)
    if not trace or trace.status != "Draft":
        return
    validate_stock_entry_trace(doc)
    rows = {row.name: row for row in doc.items}
    for line in trace.lines:
        if line.status == "Reserved":
            row = rows[line.stock_entry_detail]
            if _is_transfer_purpose(doc):
                post_quantity_event(
                    event_type="Unreserve",
                    qty=line.qty,
                    stock_uom=line.stock_uom,
                    idempotency_key=f"production-transfer-unreserve:{trace.name}:{line.name}",
                    source_handling_unit=line.handling_unit,
                    item_code=line.item_code,
                    batch_no=line.batch_no,
                    source_company=doc.company,
                    source_warehouse=row.s_warehouse,
                    reference_doctype="Stock Entry",
                    reference_name=doc.name,
                    reason="ERP material transfer submitted",
                )
                ledger = post_quantity_event(
                    event_type="Location Transfer",
                    qty=line.qty,
                    stock_uom=line.stock_uom,
                    idempotency_key=f"production-transfer:{trace.name}:{line.name}",
                    source_handling_unit=line.handling_unit,
                    item_code=line.item_code,
                    batch_no=line.batch_no,
                    source_company=doc.company,
                    destination_company=doc.company,
                    source_warehouse=row.s_warehouse,
                    destination_warehouse=row.t_warehouse,
                    reference_doctype="Stock Entry",
                    reference_name=doc.name,
                    reason="ERP material transfer for manufacture submitted",
                )
                frappe.db.set_value(
                    "CFG Kanban Handling Unit", line.handling_unit,
                    {"current_warehouse": row.t_warehouse, "movement_state": "Received"},
                    update_modified=False,
                )
            else:
                ledger = post_quantity_event(
                    event_type="Production Consume",
                    qty=line.qty,
                    stock_uom=line.stock_uom,
                    idempotency_key=f"production-consume:{trace.name}:{line.name}",
                    source_handling_unit=line.handling_unit,
                    item_code=line.item_code,
                    batch_no=line.batch_no,
                    source_company=doc.company,
                    source_warehouse=row.s_warehouse,
                    reference_doctype="Stock Entry",
                    reference_name=doc.name,
                    reason=f"ERP {_purpose(doc)} submitted",
                    release_reserved=True,
                )
                _mark_empty_if_needed(line.handling_unit)
            line.confirmation_ledger = ledger.name
            line.status = "Confirmed"
        elif line.status == "Pending":
            row = rows[line.stock_entry_detail]
            unit = _activate_output_unit(doc, row, line)
            line.handling_unit = unit.name
            line.confirmation_ledger = frappe.db.get_value(
                "CFG Kanban Handling Unit Quantity Ledger",
                {"idempotency_key": f"handling-unit-activation:{unit.name}"},
                "name",
            )
            line.status = "Confirmed"
    trace.status = "Confirmed"
    trace.confirmed_on = now_datetime()
    trace.confirmed_by = frappe.session.user
    trace.save(ignore_permissions=True)
    record(
        "Production Material Trace Confirmed",
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="Stock Entry",
        reference_name=doc.name,
        notes=f"Material Trace {trace.name} confirmed by ERP submission",
    )


def reverse_stock_entry_trace(doc):
    if _purpose(doc) not in SUPPORTED_PURPOSES:
        return
    trace = _get_trace(doc.name)
    if not trace or trace.status != "Confirmed":
        return
    rows = {row.name: row for row in doc.items}
    _validate_trace_reversal(doc, trace, rows)
    for line in trace.lines:
        if line.status != "Confirmed":
            continue
        row = rows[line.stock_entry_detail]
        if line.direction == "Output":
            ledger = post_quantity_event(
                event_type="Production Output Reversal",
                qty=line.qty,
                stock_uom=line.stock_uom,
                idempotency_key=f"production-output-reversal:{trace.name}:{line.name}",
                source_handling_unit=line.handling_unit,
                item_code=line.item_code,
                batch_no=line.batch_no,
                source_company=doc.company,
                source_warehouse=row.t_warehouse,
                reference_doctype="Stock Entry",
                reference_name=doc.name,
                reason="ERP Stock Entry cancelled; produced tag voided",
            )
            frappe.db.set_value(
                "CFG Kanban Handling Unit", line.handling_unit,
                {"state": "Void", "identity_state": "Void", "movement_state": "Empty",
                 "void_reason": f"Origin Stock Entry {doc.name} cancelled"},
                update_modified=False,
            )
        elif _is_transfer_purpose(doc):
            unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
            if unit.current_warehouse != row.t_warehouse:
                frappe.throw(
                    f"Cannot cancel: Handling Unit {unit.handling_unit_id} has moved from "
                    f"{row.t_warehouse}"
                )
            ledger = post_quantity_event(
                event_type="Location Transfer",
                qty=line.qty,
                stock_uom=line.stock_uom,
                idempotency_key=f"production-transfer-reversal:{trace.name}:{line.name}",
                source_handling_unit=line.handling_unit,
                item_code=line.item_code,
                batch_no=line.batch_no,
                source_company=doc.company,
                destination_company=doc.company,
                source_warehouse=row.t_warehouse,
                destination_warehouse=row.s_warehouse,
                reference_doctype="Stock Entry",
                reference_name=doc.name,
                reason="ERP material transfer cancelled",
            )
            frappe.db.set_value(
                "CFG Kanban Handling Unit", line.handling_unit,
                {"current_warehouse": row.s_warehouse, "movement_state": "Received"},
                update_modified=False,
            )
        else:
            ledger = post_quantity_event(
                event_type="Production Consume Reversal",
                qty=line.qty,
                stock_uom=line.stock_uom,
                idempotency_key=f"production-consume-reversal:{trace.name}:{line.name}",
                destination_handling_unit=line.handling_unit,
                item_code=line.item_code,
                batch_no=line.batch_no,
                destination_company=doc.company,
                destination_warehouse=row.s_warehouse,
                reference_doctype="Stock Entry",
                reference_name=doc.name,
                reason="ERP production consumption cancelled",
            )
            frappe.db.set_value(
                "CFG Kanban Handling Unit", line.handling_unit,
                {"identity_state": "Active", "movement_state": "Received"},
                update_modified=False,
            )
        line.reversal_ledger = ledger.name
        line.status = "Reversed"
    trace.status = "Reversed"
    trace.reversed_on = now_datetime()
    trace.reversed_by = frappe.session.user
    trace.save(ignore_permissions=True)
    record(
        "Production Material Trace Reversed",
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="Stock Entry",
        reference_name=doc.name,
        notes=f"Material Trace {trace.name} reversed by ERP cancellation",
    )


def _trace_plan(doc, trace):
    rows = []
    for row in doc.items:
        if row.s_warehouse:
            policy = effective_trace_policy(row.item_code, doc.company)
            allocated = _line_qty(trace, row.name, "Input", ACTIVE_INPUT_STATUSES)
            rows.append(_plan_row(
                row, "Input", row.s_warehouse, policy.production_input_tag_policy,
                policy.policy_source, allocated,
            ))
        if _is_output_row(doc, row):
            policy = effective_trace_policy(row.item_code, doc.company)
            staged = _line_qty(trace, row.name, "Output", ACTIVE_OUTPUT_STATUSES)
            rows.append(_plan_row(
                row, "Output", row.t_warehouse, policy.production_output_tag_policy,
                policy.policy_source, staged,
            ))
    lines = [] if not trace else [{
        "name": line.name,
        "direction": line.direction,
        "status": line.status,
        "item_code": line.item_code,
        "batch_no": line.batch_no,
        "warehouse": line.warehouse,
        "qty": line.qty,
        "stock_uom": line.stock_uom,
        "handling_unit": line.handling_unit,
        "pending_tag_code": line.pending_tag_code,
        "can_cancel": doc.docstatus == 0 and line.status in ("Reserved", "Pending"),
    } for line in trace.lines]
    return {
        "stock_entry": doc.name,
        "docstatus": doc.docstatus,
        "purpose": _purpose(doc),
        "company": doc.company,
        "work_order": doc.work_order,
        "kanban_cycle": doc.get("cfg_kanban_cycle"),
        "trace": trace.name if trace else None,
        "trace_status": trace.status if trace else "Not Started",
        "can_edit": doc.docstatus == 0,
        "can_abandon": bool(trace and trace.status == "Draft" and doc.docstatus == 0),
        "rows": rows,
        "lines": lines,
    }


def _plan_row(row, direction, warehouse, tag_policy, policy_source, allocated):
    total = _row_stock_qty(row)
    return {
        "row_name": row.name,
        "direction": direction,
        "item_code": row.item_code,
        "item_name": row.item_name,
        "batch_no": _display_batch(row),
        "warehouse": warehouse,
        "stock_uom": row.stock_uom,
        "stock_qty": total,
        "traced_qty": allocated,
        "remaining_qty": max(total - allocated, 0),
        "tag_policy": tag_policy,
        "policy_source": policy_source,
        "tagging_available": tag_policy != NO_TAG,
        "tag_required": tag_policy == "Required Physical Tag",
    }


def _ensure_trace(doc):
    trace = _get_trace(doc.name)
    if trace:
        if trace.status != "Draft":
            frappe.throw(f"Material Trace {trace.name} is {trace.status}")
        return trace
    return frappe.get_doc({
        "doctype": "CFG Kanban Material Trace",
        "status": "Draft",
        "company": doc.company,
        "purpose": _purpose(doc),
        "stock_entry": doc.name,
        "stock_entry_reference": doc.name,
        "work_order": doc.work_order,
        "kanban_cycle": doc.get("cfg_kanban_cycle"),
    }).insert(ignore_permissions=True)


def _get_trace(stock_entry):
    if not stock_entry:
        return None
    name = frappe.db.get_value("CFG Kanban Material Trace", {"stock_entry": stock_entry}, "name")
    return frappe.get_doc("CFG Kanban Material Trace", name) if name else None


def _find_row(doc, row_name):
    row = next((candidate for candidate in doc.items if candidate.name == row_name), None)
    if not row:
        frappe.throw("The selected item row does not belong to this Stock Entry")
    return row


def _remaining_row_qty(doc, trace, row, direction):
    statuses = ACTIVE_INPUT_STATUSES if direction == "Input" else ACTIVE_OUTPUT_STATUSES
    return max(_row_stock_qty(row) - _line_qty(trace, row.name, direction, statuses), 0)


def _line_qty(trace, row_name, direction, statuses):
    if not trace:
        return 0
    return sum(flt(line.qty) for line in trace.lines
               if line.stock_entry_detail == row_name and line.direction == direction
               and line.status in statuses)


def _row_stock_qty(row):
    return flt(row.get("transfer_qty") or (flt(row.qty) * flt(row.conversion_factor or 1)))


def _purpose(doc):
    return doc.get("purpose") or doc.get("stock_entry_type")


def _is_transfer_purpose(doc):
    return _purpose(doc) == "Material Transfer for Manufacture"


def _is_output_row(doc, row):
    return _purpose(doc) in ("Manufacture", "Repack") and bool(row.t_warehouse) and not row.s_warehouse


def _assert_supported(doc):
    if _purpose(doc) not in SUPPORTED_PURPOSES:
        frappe.throw(
            "Material Trace supports Manufacture, Repack, Material Transfer for Manufacture, "
            "and Material Consumption for Manufacture Stock Entries"
        )


def _assert_editable(doc):
    _assert_supported(doc)
    if doc.docstatus != 0:
        frappe.throw("Production tags can be staged only while the Stock Entry is Draft")
    if doc.is_new():
        frappe.throw("Save the Stock Entry before scanning production tags")


def _lock_stock_entry(name):
    frappe.db.sql("select name from `tabStock Entry` where name=%s for update", name)


def _validate_input_unit(unit, doc, row, policy, batch_no):
    if unit.tag_kind == "Reusable Container":
        frappe.throw("Scan a Stock Tag, not an empty reusable-container identity")
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw(
            f"Handling Unit {unit.handling_unit_id} is {unit.identity_state} / {unit.quality_state}"
        )
    if unit.item_code != row.item_code:
        frappe.throw(f"Handling Unit Item {unit.item_code} does not match {row.item_code}")
    if unit.inventory_company != doc.company:
        frappe.throw(
            f"Handling Unit belongs to {unit.inventory_company}, not Stock Entry Company {doc.company}"
        )
    if unit.current_warehouse != row.s_warehouse:
        frappe.throw(
            f"Handling Unit is in {unit.current_warehouse}, not source Warehouse {row.s_warehouse}"
        )
    if unit.stock_uom != row.stock_uom:
        frappe.throw(f"Handling Unit UOM {unit.stock_uom} does not match {row.stock_uom}")
    if (unit.batch_no or "") != (batch_no or ""):
        frappe.throw(
            f"Handling Unit Batch {unit.batch_no or '(blank)'} does not match Stock Entry "
            f"Batch {batch_no or '(blank)'}"
        )
    if policy.require_batch and not unit.batch_no:
        frappe.throw(f"Item {row.item_code} requires a Batch on the production input tag")


def _validate_unused_main_tag(visible_code):
    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        frappe.throw(f"Preprinted tag {visible_code} is already active as {identity['name']}")
    if not identity or identity.get("identity_type") not in (
        "Registered Tag Identity", "Tag Range Candidate"
    ):
        frappe.throw(
            f"Preprinted tag {visible_code} is not covered by an active Tag Family or Tag Range"
        )
    if identity.get("tag_role") != "Main":
        frappe.throw("A detachable child cannot be staged as a new production-output tag")
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(f"Preprinted tag {visible_code} is {identity.get('state')}")
    tag_family = identity.get("tag_family")
    if tag_family and not frappe.db.get_value("CFG Kanban Tag Family", tag_family, "active"):
        frappe.throw(f"Tag Family {tag_family} is inactive")
    return identity


def _activate_output_unit(doc, row, line):
    activation_key = canonical_key(
        "production-output-tag", doc.name, row.name, line.pending_tag_code
    )
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": activation_key}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Kanban Handling Unit", existing)
    _validate_unused_main_tag(line.pending_tag_code)
    batch_no = line.batch_no
    expiry_date = (frappe.db.get_value("Batch", batch_no, "expiry_date")
                   if batch_no else None)
    cycle_name = doc.get("cfg_kanban_cycle")
    card_name = (frappe.db.get_value("CFG Kanban Cycle", cycle_name, "kanban_card")
                 if cycle_name else None)
    unit = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": line.pending_tag_code,
        "handling_unit_type": line.handling_unit_type or "Container",
        "tag_kind": "Main Stock Tag",
        "kanban_cycle": cycle_name,
        "kanban_card": card_name,
        "item_code": row.item_code,
        "short_description": row.item_name,
        "qty": line.qty,
        "stock_uom": row.stock_uom,
        "batch_no": batch_no,
        "expiry_date": expiry_date,
        "work_order": doc.work_order,
        "inventory_company": doc.company,
        "current_warehouse": row.t_warehouse,
        "source_location": doc.work_order or doc.name,
        "destination_location": row.t_warehouse,
        "state": "Received",
        "movement_state": "Received",
        "origin_reference_doctype": "Stock Entry",
        "origin_reference_name": doc.name,
        "origin_reference_row": row.name,
        "activation_key": activation_key,
    })
    unit.flags.activation_reason = "Production output confirmed by submitted Stock Entry"
    unit.insert(ignore_permissions=True)
    record(
        "Production Output Tag Activated",
        cycle=cycle_name,
        handling_unit=unit.name,
        qty=line.qty,
        reference_doctype="Stock Entry",
        reference_name=doc.name,
        notes=f"{row.item_code} / {batch_no or 'no Batch'} / {row.t_warehouse}",
    )
    return unit


def _mark_empty_if_needed(handling_unit):
    current_qty = flt(frappe.db.get_value(
        "CFG Kanban Handling Unit", handling_unit, "current_qty"
    ))
    if current_qty <= TOLERANCE:
        frappe.db.set_value(
            "CFG Kanban Handling Unit", handling_unit,
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )


def _validate_trace_reversal(doc, trace, rows):
    for line in trace.lines:
        if line.status != "Confirmed":
            continue
        row = rows.get(line.stock_entry_detail)
        if not row:
            frappe.throw(f"Cannot reverse trace line {line.idx}: Stock Entry row is missing")
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if line.direction == "Input":
            expected_warehouse = row.t_warehouse if _is_transfer_purpose(doc) else row.s_warehouse
            if unit.identity_state in ("Void", "Replaced"):
                frappe.throw(
                    f"Cannot cancel: input Handling Unit {unit.handling_unit_id} is "
                    f"{unit.identity_state}"
                )
            if unit.current_warehouse != expected_warehouse or flt(unit.reserved_qty) > TOLERANCE:
                frappe.throw(
                    f"Cannot cancel: input Handling Unit {unit.handling_unit_id} has moved or "
                    "is reserved by later activity"
                )
            continue
        if (unit.origin_reference_doctype != "Stock Entry"
                or unit.origin_reference_name != trace.stock_entry
                or unit.origin_reference_row != row.name):
            frappe.throw(f"Cannot reverse: Handling Unit {unit.handling_unit_id} origin changed")
        if (unit.identity_state != "Active"
                or unit.current_warehouse != row.t_warehouse
                or abs(flt(unit.current_qty) - flt(line.qty)) > TOLERANCE
                or flt(unit.reserved_qty) > TOLERANCE):
            frappe.throw(
                f"Cannot cancel Stock Entry while produced Handling Unit {unit.handling_unit_id} "
                "has moved, split, reduced, or been reserved"
            )


def _row_batch_numbers(row):
    if row.get("batch_no"):
        return [row.batch_no]
    bundle = row.get("serial_and_batch_bundle")
    if not bundle:
        return []
    values = frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": bundle, "parenttype": "Serial and Batch Bundle",
                 "batch_no": ["is", "set"]},
        pluck="batch_no",
        order_by="idx asc",
    )
    return list(dict.fromkeys(value for value in values if value))


def _tag_batch_no(row):
    batches = _row_batch_numbers(row)
    if len(batches) > 1:
        frappe.throw(
            f"Stock Entry row {row.idx} contains multiple Batches. Split it into one row or "
            "Serial and Batch Bundle per Batch before assigning physical Handling Unit tags."
        )
    return batches[0] if batches else None


def _display_batch(row):
    batches = _row_batch_numbers(row)
    return batches[0] if len(batches) == 1 else "Multiple batches" if batches else None

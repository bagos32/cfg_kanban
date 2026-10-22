import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


SUPPORTED_PURPOSES = {
    "Manufacture",
    "Material Transfer",
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
def get_stock_entry_trace_plan(stock_entry, operator_session_token=None, kanban_card=None):
    doc = frappe.get_doc("Stock Entry", stock_entry)
    operator_actor = _authorize_trace_access(
        doc, "read", operator_session_token=operator_session_token, kanban_card=kanban_card
    )
    _assert_supported(doc)
    trace = _get_trace(doc.name)
    return _trace_plan(doc, trace, operator_actor=operator_actor)


@frappe.whitelist()
def classify_trace_scan(stock_entry, scan_value, operator_session_token=None,
                        kanban_card=None):
    """Classify one scanner value without mutating the Draft Stock Entry trace.

    Manufacture and Repack entries can expose optional physical inputs and a new output
    tag at the same time. The visible code itself is authoritative: an active Handling
    Unit is an input, while an unused preprinted main identity is an output.
    """
    doc = frappe.get_doc("Stock Entry", stock_entry)
    _authorize_trace_access(
        doc, "write", operator_session_token=operator_session_token,
        kanban_card=kanban_card,
    )
    _assert_editable(doc)
    identity = resolve_logistics_scan(scan_value)
    if identity and identity.get("identity_type") == "Handling Unit":
        return {
            "direction": "Input",
            "identity_type": identity.get("identity_type"),
            "name": identity.get("name"),
        }
    identity = _validate_unused_main_tag(normalize_physical_code(scan_value))
    return {
        "direction": "Output",
        "identity_type": identity.get("identity_type"),
        "name": identity.get("name"),
    }


@frappe.whitelist()
def allocate_input_tag(stock_entry, item_row=None, scan_value=None, qty=0,
                       operator_session_token=None, kanban_card=None):
    qty = flt(qty)
    if qty < 0:
        frappe.throw("Input tag quantity cannot be negative")
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    operator_actor = _authorize_trace_access(
        doc, "write", operator_session_token=operator_session_token, kanban_card=kanban_card
    )
    _assert_editable(doc)
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Handling Unit tag for the production input")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    trace = _ensure_trace(doc)
    row = _resolve_input_row(doc, trace, unit, item_row)
    policy = effective_trace_policy(row.item_code, doc.company)
    if policy.production_input_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} uses ERP stock without physical production-input tags"
        )

    batch_no = _tag_batch_no(row)
    _validate_input_unit(unit, doc, row, policy, batch_no)

    remaining = _remaining_row_qty(doc, trace, row, "Input")
    if qty == 0:
        qty = (flt(unit.current_qty) if _is_transfer_purpose(doc)
               else min(flt(unit.available_qty), remaining))
    if qty <= 0:
        frappe.throw("The scanned Handling Unit has no quantity available for this input row")
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

    from cfg_kanban.services.serial_evidence import (
        active_serials_for_unit,
        serials_to_json,
        validate_unit_serials_for_row,
    )
    validate_unit_serials_for_row(unit, row, qty)
    input_serials = active_serials_for_unit(unit.name)

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
        "serial_count": len(input_serials),
        "serial_numbers_json": serials_to_json(input_serials),
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
        ("Warehouse Transfer Tag Reserved" if _purpose(doc) == "Material Transfer"
         else "Production Input Tag Reserved"),
        cycle=doc.get("cfg_kanban_cycle"),
        handling_unit=unit.name,
        qty=qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{row.item_code} / {row.s_warehouse}",
        **_operator_audit(operator_actor),
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def stage_output_tag(stock_entry, item_row, scan_value, qty,
                     handling_unit_type="Container", operator_session_token=None,
                     kanban_card=None, serial_numbers=None):
    qty = flt(qty)
    try:
        visible_code = normalize_physical_code(scan_value)
    except ValueError as exc:
        frappe.throw(str(exc))
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    operator_actor = _authorize_trace_access(
        doc, "write", operator_session_token=operator_session_token, kanban_card=kanban_card
    )
    _assert_editable(doc)
    trace = _get_trace(doc.name)
    row = _resolve_output_row(doc, trace, item_row)
    policy = effective_trace_policy(row.item_code, doc.company)
    if policy.production_output_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} uses ERP stock without physical production-output tags"
        )
    batch_no = _tag_batch_no(row)
    # A Manufacture output Batch may be generated by ERPNext only while the Stock
    # Entry is submitted. Keep the staged line unbound until that authoritative
    # submission, then copy the resulting Batch to every staged output tag.
    _validate_unused_main_tag(visible_code)
    if qty <= 0:
        frappe.throw("Output tag quantity must be positive")
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

    from cfg_kanban.services.serial_evidence import (
        select_serials_for_tag,
        serials_to_json,
    )
    selected_serials = select_serials_for_tag(
        row, qty, serial_numbers, exclude=_trace_row_serials(trace, row.name)
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
        "serial_count": len(selected_serials),
        "serial_numbers_json": serials_to_json(selected_serials),
    })
    trace.save(ignore_permissions=True)
    record(
        "Production Output Tag Staged",
        cycle=doc.get("cfg_kanban_cycle"),
        qty=qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{visible_code} / {row.item_code} / {row.t_warehouse}",
        **_operator_audit(operator_actor),
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def cancel_trace_line(stock_entry, trace_line, operator_session_token=None,
                      kanban_card=None):
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    operator_actor = _authorize_trace_access(
        doc, "write", operator_session_token=operator_session_token, kanban_card=kanban_card
    )
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
        "Material Trace Line Cancelled",
        cycle=doc.get("cfg_kanban_cycle"),
        handling_unit=line.handling_unit,
        qty=line.qty,
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"{line.direction} / {line.item_code} / {line.pending_tag_code or ''}",
        **_operator_audit(operator_actor),
    )
    return _trace_plan(doc, trace)


@frappe.whitelist()
def abandon_draft_trace(stock_entry, reason, operator_session_token=None,
                        kanban_card=None):
    if not (reason or "").strip():
        frappe.throw("Reason is required to discard a Draft Material Trace")
    _lock_stock_entry(stock_entry)
    doc = frappe.get_doc("Stock Entry", stock_entry)
    operator_actor = _authorize_trace_access(
        doc, "write", operator_session_token=operator_session_token, kanban_card=kanban_card
    )
    if operator_actor and not cint(operator_actor[0].get("can_override")):
        frappe.throw("Operator override permission is required to abandon an entire Draft trace")
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
        "Draft Material Trace Abandoned",
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="CFG Kanban Material Trace",
        reference_name=trace.name,
        notes=f"Material Trace {trace.name}: {reason.strip()}",
        **_operator_audit(operator_actor),
    )
    return {"trace": trace.name, "status": trace.status, "stock_entry": doc.name}


def validate_stock_entry_trace(doc):
    """Enforce only explicit Required policies; ERP-only rows remain untouched."""
    if doc.get("cfg_wip_bin_return_load"):
        return
    purpose = _purpose(doc)
    if purpose not in SUPPORTED_PURPOSES:
        return
    trace = _get_trace(doc.name)
    for row in doc.items:
        if row.s_warehouse:
            if purpose in (
                "Material Transfer for Manufacture",
                "Material Consumption for Manufacture",
            ):
                from cfg_kanban.services.wip_bin_loads import (
                    consumption_loads_for_row,
                    entry_wip_bin_rule,
                    transfer_loads_for_row,
                )
                loads = (
                    transfer_loads_for_row(doc.name, row.name)
                    if purpose == "Material Transfer for Manufacture"
                    else consumption_loads_for_row(doc.name, row.name)
                )
                if loads or entry_wip_bin_rule(doc, row):
                    # Standard-quantity WIP Bin allocation is the physical evidence for
                    # this row. Its service enforces the source-tag policy on transfer,
                    # the Ready-bin scan on consumption, and complete ERP-row coverage.
                    # Requiring a second ordinary production-input trace would double
                    # allocate the same material.
                    continue
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
        row_batch = _tag_batch_no(row)
        batch_changed = bool(line.batch_no) and line.batch_no != row_batch
        if line.warehouse != expected_warehouse or batch_changed:
            frappe.throw(
                f"Material Trace line {line.idx} Warehouse or Batch changed after scanning"
            )


def confirm_stock_entry_trace(doc):
    if doc.get("cfg_wip_bin_return_load"):
        return
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
                    reason=f"ERP {_purpose(doc)} submitted",
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
                if line.serial_count:
                    from cfg_kanban.services.serial_evidence import release_unit_serials
                    release_unit_serials(
                        line.handling_unit, "Consumed by submitted ERP Stock Entry",
                        "Stock Entry", doc.name,
                    )
            line.confirmation_ledger = ledger.name
            line.status = "Confirmed"
        elif line.status == "Pending":
            row = rows[line.stock_entry_detail]
            _bind_submitted_output_batch(doc, row, line)
            unit = _activate_output_unit(doc, row, line)
            if line.serial_count:
                from cfg_kanban.services.serial_evidence import assign_serials, serials_from_json
                assign_serials(
                    unit, serials_from_json(line.serial_numbers_json),
                    "Stock Entry", doc.name, row.name,
                )
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
        ("Warehouse Transfer Trace Confirmed" if _purpose(doc) == "Material Transfer"
         else "Production Material Trace Confirmed"),
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="Stock Entry",
        reference_name=doc.name,
        notes=f"Material Trace {trace.name} confirmed by ERP submission",
    )


def _bind_submitted_output_batch(doc, row, line):
    """Bind ERPNext's authoritative submitted Batch to one staged output tag."""
    row_batch = _tag_batch_no(row)
    if line.batch_no and line.batch_no != row_batch:
        frappe.throw(
            f"Staged output tag {line.pending_tag_code} Batch {line.batch_no} no longer "
            f"matches ERPNext Batch {row_batch or '(blank)'}"
        )
    policy = effective_trace_policy(row.item_code, doc.company)
    if policy.require_batch and not row_batch:
        frappe.throw(
            f"ERPNext did not assign the required Batch for output Item {row.item_code}"
        )
    line.batch_no = row_batch


def reverse_stock_entry_trace(doc):
    if doc.get("cfg_wip_bin_return_load"):
        return
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
            if line.serial_count:
                from cfg_kanban.services.serial_evidence import release_unit_serials
                release_unit_serials(
                    line.handling_unit, "Origin Stock Entry cancelled",
                    "Stock Entry", doc.name,
                )
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
            if line.serial_count:
                from cfg_kanban.services.serial_evidence import reactivate_unit_serials
                reactivate_unit_serials(line.handling_unit, doc.name)
        line.reversal_ledger = ledger.name
        line.status = "Reversed"
    trace.status = "Reversed"
    trace.reversed_on = now_datetime()
    trace.reversed_by = frappe.session.user
    trace.save(ignore_permissions=True)
    record(
        ("Warehouse Transfer Trace Reversed" if _purpose(doc) == "Material Transfer"
         else "Production Material Trace Reversed"),
        cycle=doc.get("cfg_kanban_cycle"),
        reference_doctype="Stock Entry",
        reference_name=doc.name,
        notes=f"Material Trace {trace.name} reversed by ERP cancellation",
    )


def _trace_plan(doc, trace, operator_actor=None):
    rows = []
    for row in doc.items:
        if row.s_warehouse:
            policy = effective_trace_policy(row.item_code, doc.company)
            allocated = _line_qty(trace, row.name, "Input", ACTIVE_INPUT_STATUSES)
            wip_context = None
            wip_loads = []
            wip_action = None
            if _purpose(doc) == "Material Transfer for Manufacture":
                from cfg_kanban.services.wip_bin_loads import (
                    entry_wip_bin_rule,
                    transfer_loads_for_row,
                )
                wip_context = entry_wip_bin_rule(doc, row)
                if wip_context:
                    wip_loads = transfer_loads_for_row(doc.name, row.name)
                    wip_action = "Load"
            elif _purpose(doc) == "Material Consumption for Manufacture":
                from cfg_kanban.services.wip_bin_loads import (
                    consumption_loads_for_row,
                    entry_wip_bin_rule,
                )
                wip_context = entry_wip_bin_rule(doc, row)
                if wip_context:
                    wip_loads = consumption_loads_for_row(doc.name, row.name)
                    wip_action = "Consume"
            rows.append(_plan_row(
                row, "Input", row.s_warehouse, policy.production_input_tag_policy,
                policy.policy_source, allocated,
                wip_context=wip_context, wip_loads=wip_loads,
                wip_action=wip_action,
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
        "serial_count": line.serial_count,
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
        "can_approve_partial_wip_bin": _can_approve_partial_wip_bin(operator_actor),
        "can_abandon": bool(trace and trace.status == "Draft" and doc.docstatus == 0),
        "rows": rows,
        "lines": lines,
    }


def _plan_row(row, direction, warehouse, tag_policy, policy_source, allocated,
              wip_context=None, wip_loads=None, wip_action=None):
    from cfg_kanban.services.serial_evidence import erp_row_serials, item_uses_serials
    total = _row_stock_qty(row)
    serial_controlled = item_uses_serials(row.item_code)
    row_serials = erp_row_serials(row) if serial_controlled else []
    wip_loads = wip_loads or []
    wip_prepared_bound = sum(flt(load.actual_qty) for load in wip_loads)
    wip_allocated = sum(
        flt(load.consumed_qty or load.actual_qty)
        if wip_action == "Consume" else flt(load.actual_qty)
        for load in wip_loads
    )
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
        "tagging_available": tag_policy != NO_TAG and not wip_context,
        "tag_required": tag_policy == "Required Physical Tag",
        "wip_bin_required": bool(wip_context),
        "wip_bin_action": wip_action,
        "wip_bin_pool": wip_context.get("wip_bin_pool") if wip_context else None,
        "allow_supervisor_partial_exception": (
            bool(wip_context.get("allow_supervisor_partial_exception"))
            if wip_context else False
        ),
        "require_full_bin_consumption": (
            bool(wip_context.get("require_full_bin_consumption"))
            if wip_context else False
        ),
        "standard_bin_qty": (wip_context.get("standard_bin_qty")
                             if wip_context else 0),
        "wip_bin_allocated_qty": wip_allocated,
        "wip_bin_remaining_qty": max(
            total - (wip_prepared_bound if wip_action == "Consume" else wip_allocated), 0
        ),
        "wip_bin_loads": wip_loads,
        "serial_controlled": serial_controlled,
        "available_serial_numbers": [value for value in row_serials
                                     if value not in _trace_row_serials_by_document(
                                         row.parent, row.name
                                     )],
    }


def _can_approve_partial_wip_bin(operator_actor):
    if not operator_actor:
        return bool({"Manufacturing Manager", "System Manager"}.intersection(
            frappe.get_roles(frappe.session.user)
        ))
    profile, _session = operator_actor
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and cint(profile.get("can_override"))
    )


def _trace_row_serials(trace, item_row):
    if not trace:
        return []
    from cfg_kanban.services.serial_evidence import serials_from_json
    values = []
    for line in trace.lines:
        if line.stock_entry_detail == item_row and line.status in (
            "Reserved", "Pending", "Confirmed"
        ):
            values.extend(serials_from_json(line.serial_numbers_json))
    return list(dict.fromkeys(values))


def _trace_row_serials_by_document(stock_entry, item_row):
    trace = _get_trace(stock_entry)
    return _trace_row_serials(trace, item_row)


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


def _resolve_output_row(doc, trace, row_reference=None):
    """Resolve an output selection, accepting a row name, UI option, or one-row default."""
    reference = str(row_reference or "").split(" :: ", 1)[0].strip()
    selected = next((row for row in doc.items if row.name == reference), None)
    if selected:
        if not _is_output_row(doc, selected):
            frappe.throw("The selected Stock Entry row is not a manufactured/repacked output")
        if _remaining_row_qty(doc, trace, selected, "Output") <= TOLERANCE:
            frappe.throw(f"Output Item {selected.item_code} is already fully staged")
        return selected

    candidates = [
        row for row in doc.items
        if _is_output_row(doc, row)
        and _remaining_row_qty(doc, trace, row, "Output") > TOLERANCE
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        frappe.throw("This Stock Entry has no remaining manufactured/repacked output to tag")
    items = ", ".join(dict.fromkeys(row.item_code for row in candidates))
    frappe.throw(f"Select the exact ERP output row before staging a tag: {items}")


def _resolve_input_row(doc, trace, unit, row_name=None):
    """Resolve a Stock Entry input row from the physical Handling Unit scan.

    A supplied row remains supported for Desk/API compatibility, but the scanner-only
    operator flow deliberately omits it. In that flow the tag's item, company,
    Warehouse, UOM, Batch, and the ERP row's unallocated balance are authoritative.
    """
    if row_name and row_name != "AUTO":
        row = _find_row(doc, row_name)
        if not row.s_warehouse:
            frappe.throw("The selected Stock Entry row is not a material input")
        return row

    remaining_rows = [
        row for row in doc.items
        if row.s_warehouse and _remaining_row_qty(doc, trace, row, "Input") > TOLERANCE
    ]
    item_rows = [row for row in remaining_rows if row.item_code == unit.item_code]
    if not item_rows:
        expected_items = ", ".join(dict.fromkeys(row.item_code for row in remaining_rows))
        frappe.throw(
            f"Item {unit.item_code} from tag {unit.handling_unit_id} is not in the "
            f"remaining Stock Entry input list: {expected_items or 'none'}"
        )

    candidates = []
    for row in item_rows:
        if row.s_warehouse != unit.current_warehouse:
            continue
        if row.stock_uom != unit.stock_uom:
            continue
        if (_tag_batch_no(row) or "") != (unit.batch_no or ""):
            continue
        candidates.append(row)

    if not candidates:
        frappe.throw(
            f"Item {unit.item_code} exists in the input list, but tag "
            f"{unit.handling_unit_id} does not match its source Warehouse, UOM, Batch, "
            "or remaining ERP quantity."
        )
    return candidates[0]


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
    return _purpose(doc) in ("Material Transfer", "Material Transfer for Manufacture")


def _is_output_row(doc, row):
    return _purpose(doc) in ("Manufacture", "Repack") and bool(row.t_warehouse) and not row.s_warehouse


def _assert_supported(doc):
    if _purpose(doc) not in SUPPORTED_PURPOSES:
        frappe.throw(
            "Material Trace supports Manufacture, Repack, Material Transfer, Material Transfer "
            "for Manufacture, and Material Consumption for Manufacture Stock Entries"
        )


def _assert_editable(doc):
    _assert_supported(doc)
    if doc.docstatus != 0:
        frappe.throw("Production tags can be staged only while the Stock Entry is Draft")
    if doc.is_new():
        frappe.throw("Save the Stock Entry before scanning production tags")


def _authorize_trace_access(doc, permission_type, operator_session_token=None,
                            kanban_card=None):
    """Authorize either a normal ERP user or a tightly scoped floor operator.

    A floor session never grants general Stock Entry access. It is accepted only when the
    supplied card owns the active Cycle and the Stock Entry belongs to that Cycle's Work Order.
    ERPNext submission remains outside this path.
    """
    if not operator_session_token:
        frappe.only_for(ALLOWED_ROLES)
        doc.check_permission(permission_type)
        return None

    if not kanban_card:
        if _purpose(doc) != "Material Transfer":
            frappe.throw("Scan a Kanban card before opening Production Material Trace")
        from cfg_kanban.services.operator_auth import require_operator

        profile, session = require_operator(
            operator_session_token,
            action="report_progress" if permission_type == "write" else None,
        )
        responsibilities = {
            row.responsibility for row in profile.responsibilities if row.responsibility
        }
        can_view_all = (
            profile.kanban_role == "Supervisor" and
            cint(profile.get("view_all_responsibilities"))
        )
        if not can_view_all and "Internal Warehouse Transfer" not in responsibilities:
            frappe.throw(
                "Operator is not assigned to the Internal Warehouse Transfer responsibility"
            )
        return profile, session
    card = frappe.get_doc("CFG Kanban Card", kanban_card)
    if not card.active_cycle:
        frappe.throw("The scanned Kanban card has no active Cycle")
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle)
    if cycle.kanban_card != card.name:
        frappe.throw("The active Cycle no longer belongs to the scanned Kanban card")
    if not cycle.work_order:
        frappe.throw("The active Kanban Cycle has no effective Work Order")
    if permission_type == "write" and cycle.status in ("Completed", "Cancelled"):
        frappe.throw(f"Production Material Trace is closed because Cycle {cycle.name} is {cycle.status}")
    if doc.work_order != cycle.work_order:
        frappe.throw(
            f"Stock Entry {doc.name} belongs to Work Order {doc.work_order or '(blank)'}, "
            f"not the scanned Cycle Work Order {cycle.work_order}"
        )
    if doc.company != cycle.company:
        frappe.throw(
            f"Stock Entry Company {doc.company} does not match Kanban Cycle Company {cycle.company}"
        )
    linked_cycle = doc.get("cfg_kanban_cycle")
    operation_scope = _operation_card_controls_entry(cycle, doc, linked_cycle)
    if linked_cycle and linked_cycle != cycle.name and not operation_scope:
        frappe.throw(
            f"Stock Entry {doc.name} is explicitly linked to a different Kanban Cycle "
            f"{linked_cycle}"
        )

    from cfg_kanban.services.operator_auth import require_operator

    return require_operator(
        operator_session_token,
        action="report_progress" if permission_type == "write" else None,
        operation=card.operation,
        workstation=card.workstation,
    )


def _operation_card_controls_entry(cycle, doc, linked_cycle):
    """Allow a runtime operation Card to trace only its selected Job Card material entry."""
    if (not linked_cycle or not cycle.runtime_allocation or not cycle.selected_job_card
            or _purpose(doc) not in (
                "Material Transfer for Manufacture",
                "Material Consumption for Manufacture",
            )):
        return False
    owner_cycle = frappe.db.get_value("Work Order", cycle.work_order, "cfg_kanban_cycle")
    return bool(
        linked_cycle == owner_cycle
        and (doc.get("cfg_kanban_job_card") or doc.get("job_card"))
        == cycle.selected_job_card
        and frappe.db.get_value("Job Card", cycle.selected_job_card, "work_order")
        == cycle.work_order
    )


def _operator_audit(operator_actor):
    if not operator_actor:
        return {}
    profile, session = operator_actor
    return {
        "operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }


def _lock_stock_entry(name):
    frappe.db.sql("select name from `tabStock Entry` where name=%s for update", name)


def _validate_input_unit(unit, doc, row, policy, batch_no):
    from cfg_kanban.services.container_contents import assert_not_loaded_in_container

    if unit.tag_kind == "Reusable Container":
        frappe.throw("Scan a Stock Tag, not an empty reusable-container identity")
    assert_not_loaded_in_container(unit.name, "allocating it to a Stock Entry")
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
    # Range-backed tags are materialized only when the new Handling Unit is inserted.
    # Only a family which already exists as a registered identity can be inactive here.
    if (identity.get("identity_type") == "Registered Tag Identity"
            and tag_family
            and not frappe.db.get_value("CFG Kanban Tag Family", tag_family, "active")):
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

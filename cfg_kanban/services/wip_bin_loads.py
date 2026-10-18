"""Controlled load episodes for fixed-quantity reusable WIP bins.

This service deliberately follows native ERPNext Stock Entry state. A Draft entry may reserve a
physical bin, but it never makes material Ready or Consumed. Those states are confirmed only from
the Stock Entry submit hook.
"""

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


TOLERANCE = 0.000001
TRANSFER_PURPOSE = "Material Transfer for Manufacture"
CONSUMPTION_PURPOSES = ("Material Consumption for Manufacture", "Manufacture")


def validate_job_card_bins_consumed(doc, method=None):
    """Prevent Job Card submission while its physical WIP bins remain unconsumed."""
    if doc.docstatus == 2:
        return
    active = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"job_card": doc.name,
         "status": ["in", ["Transfer Draft", "Ready", "In Use", "Consumption Draft"]]},
        ["name", "reusable_bin", "status"], limit_page_length=6,
    )
    if not active:
        return
    detail = ", ".join(f"{row.reusable_bin} ({row.status})" for row in active[:5])
    frappe.throw(
        "Submit the Job Card WIP-bin Material Consumption before completing this Job Card. "
        f"Active bin load(s): {detail}"
    )


def abandon_draft_stock_entry(doc, method=None):
    """Release physical-bin intent when an ERP Draft is deleted before submission."""
    if doc.docstatus != 0:
        return
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    if direction == "transfer":
        reverse_wip_bin_stock_entry(doc)
        return
    for summary in loads:
        _lock_load(summary.name)
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        if load.status != "Consumption Draft":
            frappe.throw(
                f"Draft Stock Entry cannot be deleted while WIP Bin Load {load.name} "
                f"is {load.status}"
            )
        load.db_set({
            "status": "Ready", "consumption_stock_entry": None,
            "consumption_stock_entry_detail": None, "in_use_on": None,
            "notes": f"ERP Draft {doc.name} deleted; physical WIP Bin restored to Ready",
        }, update_modified=True)
        frappe.db.set_value(
            "CFG Kanban Handling Unit", load.reusable_bin, "wip_bin_state", "Ready",
            update_modified=False,
        )
        record(
            "WIP Bin Consumption Draft Abandoned", cycle=load.kanban_cycle,
            execution=load.process_execution, handling_unit=load.reusable_bin,
            qty=load.actual_qty, reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name} restored to Ready",
        )
@frappe.whitelist()
def allocate_transfer_bin(stock_entry, item_row, reusable_bin_scan,
                          operator_session_token, kanban_card,
                          source_scan=None, event_token=None, actual_qty=None,
                          exception_reason=None):
    """Reserve one fixed-quantity bin against a Draft native material-transfer row.

    A source Stock Tag is optional or mandatory according to the Item trace policy. Its
    fixed-bin quantity is reserved now and removed only when ERPNext submits the transfer.
    """
    from cfg_kanban.services.production_trace import _authorize_trace_access, _tag_batch_no

    _lock_stock_entry(stock_entry)
    entry = frappe.get_doc("Stock Entry", stock_entry)
    actor = _authorize_trace_access(
        entry, "write", operator_session_token=operator_session_token,
        kanban_card=kanban_card,
    )
    if entry.docstatus != 0 or _purpose(entry) != TRANSFER_PURPOSE:
        frappe.throw("WIP Bin allocation requires a Draft Material Transfer for Manufacture")
    row = _entry_row(entry, item_row)
    context = entry_wip_bin_rule(entry, row)
    if not context:
        frappe.throw(f"Item {row.item_code} is not configured for a Standard Quantity WIP Bin")
    profile, session = actor
    if event_token:
        existing = frappe.db.get_value(
            "CFG Kanban WIP Bin Load", {"idempotency_key": event_token}, "name"
        )
        if existing:
            existing_load = frappe.get_doc("CFG Kanban WIP Bin Load", existing)
            if (existing_load.transfer_stock_entry != entry.name
                    or existing_load.transfer_stock_entry_detail != row.name):
                frappe.throw("This WIP Bin allocation token already belongs to another ERP row")
            return _allocation_result(entry, row, existing_load)
    from cfg_kanban.services.serial_evidence import item_uses_serials
    if item_uses_serials(row.item_code):
        frappe.throw(
            f"Serial-controlled Item {row.item_code} cannot use the fixed-quantity WIP Bin "
            "scanner in this release; use Standard ERP / Tag Flow"
        )
    remaining = _remaining_transfer_qty(entry.name, row.name, _row_stock_qty(row))
    standard_qty = flt(context["standard_bin_qty"])
    explicit_qty = actual_qty not in (None, "")
    requested_qty = flt(actual_qty)
    if explicit_qty and requested_qty <= TOLERANCE:
        frappe.throw("Partial WIP Bin quantity must be greater than zero")
    qty = requested_qty if explicit_qty else standard_qty
    partial_exception = abs(qty - standard_qty) > TOLERANCE
    exception_reason = (exception_reason or "").strip()
    if qty > standard_qty + TOLERANCE:
        frappe.throw(
            f"A WIP Bin cannot exceed its Standard Full-bin Qty of {standard_qty} "
            f"{row.stock_uom}"
        )
    if partial_exception:
        _assert_partial_exception_authorized(
            actor, context, qty, standard_qty, remaining, exception_reason
        )
    if remaining + TOLERANCE < qty:
        frappe.throw(
            f"Remaining ERP transfer quantity is {remaining} {row.stock_uom}; a full "
            f"{qty} {row.stock_uom} WIP Bin cannot be allocated"
        )

    bin_unit = _resolve_reusable_bin(reusable_bin_scan, context, entry, row)
    policy = effective_trace_policy(row.item_code, entry.company)
    batch_no = _tag_batch_no(row)
    source_unit = _resolve_source_unit(source_scan, entry, row, policy, qty, batch_no)
    key = event_token or (
        f"wip-bin-load:{entry.name}:{row.name}:{bin_unit.name}:{qty}"
    )
    existing = frappe.db.get_value(
        "CFG Kanban WIP Bin Load", {"idempotency_key": key}, "name"
    )
    if existing:
        return _allocation_result(entry, row, frappe.get_doc(
            "CFG Kanban WIP Bin Load", existing
        ))

    reservation = None
    if source_unit:
        reservation = post_quantity_event(
            event_type="Reserve", qty=qty, stock_uom=row.stock_uom,
            idempotency_key=f"wip-bin-source-reserve:{key}",
            source_handling_unit=source_unit.name,
            item_code=row.item_code, batch_no=batch_no,
            source_company=entry.company, source_warehouse=row.s_warehouse,
            reference_doctype="Stock Entry", reference_name=entry.name,
            operator=profile.employee, operator_session=session.name,
            reason=f"Reserved for fixed WIP Bin {bin_unit.handling_unit_id}",
        )
    load, _created = create_transfer_load(
        stock_entry=entry.name, stock_entry_detail=row.name,
        reusable_bin=bin_unit.name, kanban_cycle=entry.get("cfg_kanban_cycle"),
        job_card=context["job_card"], item_code=row.item_code, actual_qty=qty,
        source_handling_unit=source_unit.name if source_unit else None,
        batch_no=batch_no, process_execution=context.get("process_execution"),
        operator=profile.employee, operator_session=session.name, idempotency_key=key,
        partial_exception=partial_exception,
        exception_reason=exception_reason if partial_exception else None,
        approved_by=frappe.session.user if partial_exception else None,
        approved_by_operator=profile.employee if partial_exception else None,
        exception_approved_on=now_datetime() if partial_exception else None,
    )
    if reservation:
        load.db_set("source_reservation_ledger", reservation.name, update_modified=False)
    if partial_exception:
        record(
            "WIP Bin Partial Exception Approved", card=frappe.db.get_value(
                "CFG Kanban Cycle", load.kanban_cycle, "kanban_card"
            ), cycle=load.kanban_cycle, execution=load.process_execution,
            handling_unit=load.reusable_bin, qty=load.actual_qty,
            reference_doctype="CFG Kanban WIP Bin Load", reference_name=load.name,
            operator=profile.employee, operator_session=session.name,
            terminal_user=session.terminal_user,
            notes=(f"Standard {standard_qty} {row.stock_uom}; actual {qty} "
                   f"{row.stock_uom}; reason: {exception_reason}"),
        )
    return _allocation_result(entry, row, load)


@frappe.whitelist()
def cancel_transfer_bin(load_name, operator_session_token, kanban_card):
    """Release a Draft allocation before ERPNext submits the transfer."""
    from cfg_kanban.services.production_trace import _authorize_trace_access

    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    entry = frappe.get_doc("Stock Entry", load.transfer_stock_entry)
    actor = _authorize_trace_access(
        entry, "write", operator_session_token=operator_session_token,
        kanban_card=kanban_card,
    )
    if entry.docstatus != 0 or load.status != "Transfer Draft":
        frappe.throw("Only a Draft WIP Bin allocation can be cancelled")
    reversal_ledger = None
    if load.source_handling_unit and load.source_reservation_ledger:
        profile, session = actor
        reversal_ledger = post_quantity_event(
            event_type="Unreserve", qty=load.actual_qty, stock_uom=load.stock_uom,
            idempotency_key=f"wip-bin-source-unreserve:{load.name}",
            source_handling_unit=load.source_handling_unit,
            item_code=load.item_code, batch_no=load.batch_no,
            source_company=load.company, source_warehouse=load.source_warehouse,
            reference_doctype="CFG Kanban WIP Bin Load", reference_name=load.name,
            operator=profile.employee, operator_session=session.name,
            reason="Draft WIP Bin allocation cancelled before ERP submission",
        )
    load.db_set({
        "status": "Cancelled", "reversed_on": now_datetime(),
        "source_reversal_ledger": reversal_ledger.name if reversal_ledger else None,
        "notes": "Draft WIP Bin allocation cancelled; ERPNext stock was not moved",
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin, "wip_bin_state", "Empty",
        update_modified=False,
    )
    return {"load": load.name, "status": "Cancelled", "stock_entry": entry.name}


@frappe.whitelist()
def allocate_consumption_bin(stock_entry, item_row, reusable_bin_scan,
                             operator_session_token, kanban_card,
                             event_token=None):
    """Bind one Ready fixed-quantity WIP bin to a Draft consumption row.

    Scanning records intent only. ERPNext Stock Entry submission remains the event that
    consumes the material and returns the reusable bin to Empty.
    """
    from cfg_kanban.services.production_trace import _authorize_trace_access

    _lock_stock_entry(stock_entry)
    entry = frappe.get_doc("Stock Entry", stock_entry)
    actor = _authorize_trace_access(
        entry, "write", operator_session_token=operator_session_token,
        kanban_card=kanban_card,
    )
    if entry.docstatus != 0 or _purpose(entry) != "Material Consumption for Manufacture":
        frappe.throw("Ready WIP Bin scanning requires a Draft Material Consumption entry")
    row = _entry_row(entry, item_row)
    context = entry_wip_bin_rule(entry, row)
    if not context:
        frappe.throw(f"Item {row.item_code} is not configured for a Standard Quantity WIP Bin")
    remaining = _remaining_consumption_qty(entry.name, row.name, _row_stock_qty(row))
    load = _resolve_ready_load(reusable_bin_scan, context, entry, row)
    if load.status == "Consumption Draft":
        return _consumption_allocation_result(entry, row, load)
    if flt(load.actual_qty) > remaining + TOLERANCE:
        frappe.throw(
            f"Ready WIP Bin {load.reusable_bin} contains {load.actual_qty} {load.stock_uom}, "
            f"but the selected ERP row has only {remaining} remaining"
        )
    bound = bind_consumption_draft(load.name, entry.name, row.name)
    profile, session = actor
    bound.db_set("in_use_on", now_datetime(), update_modified=False)
    record(
        "WIP Bin Consumption Draft Bound", card=frappe.db.get_value(
            "CFG Kanban Cycle", bound.kanban_cycle, "kanban_card"
        ), cycle=bound.kanban_cycle, execution=bound.process_execution,
        handling_unit=bound.reusable_bin, qty=bound.actual_qty,
        reference_doctype="Stock Entry", reference_name=entry.name,
        operator=profile.employee, operator_session=session.name,
        notes=f"WIP Bin Load {bound.name}; ERP Draft only; token {event_token or '-'}",
    )
    return _consumption_allocation_result(entry, row, bound)


@frappe.whitelist()
def cancel_consumption_bin(load_name, operator_session_token, kanban_card):
    """Remove an incorrectly scanned bin from a Draft consumption and restore Ready."""
    from cfg_kanban.services.production_trace import _authorize_trace_access

    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    if load.status != "Consumption Draft" or not load.consumption_stock_entry:
        frappe.throw("Only a WIP Bin linked to a Draft consumption can be removed")
    entry = frappe.get_doc("Stock Entry", load.consumption_stock_entry)
    profile, session = _authorize_trace_access(
        entry, "write", operator_session_token=operator_session_token,
        kanban_card=kanban_card,
    )
    if entry.docstatus != 0:
        frappe.throw("Submitted ERP consumption cannot be undone from the operator panel")
    entry_name = entry.name
    load.db_set({
        "status": "Ready",
        "consumption_stock_entry": None,
        "consumption_stock_entry_detail": None,
        "in_use_on": None,
        "notes": "Removed from Draft consumption; physical WIP Bin restored to Ready",
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin, "wip_bin_state", "Ready",
        update_modified=False,
    )
    record(
        "WIP Bin Consumption Draft Released", cycle=load.kanban_cycle,
        execution=load.process_execution, handling_unit=load.reusable_bin,
        qty=load.actual_qty, reference_doctype="Stock Entry", reference_name=entry_name,
        operator=profile.employee, operator_session=session.name,
        notes=f"WIP Bin Load {load.name} restored to Ready",
    )
    return {"load": load.name, "status": "Ready", "stock_entry": entry_name}


def entry_wip_bin_rule(entry, row):
    """Return the exact Master/Job Card context when an ERP row uses a fixed WIP bin."""
    cycle_name = entry.get("cfg_kanban_cycle")
    if not cycle_name:
        return None
    cycle = frappe.db.get_value(
        "CFG Kanban Cycle", cycle_name,
        ["name", "kanban_master", "selected_job_card", "runtime_allocation"],
        as_dict=True,
    )
    if not cycle:
        return None
    job_card = entry.get("job_card") or cycle.selected_job_card
    if not job_card:
        return None
    job = frappe.db.get_value(
        "Job Card", {"name": job_card, "work_order": entry.work_order},
        ["name", "operation", "workstation"], as_dict=True,
    )
    if not job:
        return None
    rule = frappe.db.get_value("CFG Kanban Material Flow Rule", {
        "parent": cycle.kanban_master,
        "parenttype": "CFG Kanban Master",
        "item_code": row.item_code,
        "operation": job.operation,
        "wip_presentation_method": "Standard Quantity Reusable WIP Bin",
    }, ["wip_bin_pool", "standard_bin_qty", "stock_uom"], as_dict=True)
    if not rule:
        return None
    pool = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool", rule.wip_bin_pool,
        ["require_full_bin_consumption", "allow_supervisor_partial_exception"],
        as_dict=True,
    ) or {}
    return {
        "kanban_cycle": cycle.name, "kanban_master": cycle.kanban_master,
        "job_card": job.name, "operation": job.operation,
        "workstation": job.workstation, "wip_bin_pool": rule.wip_bin_pool,
        "standard_bin_qty": flt(rule.standard_bin_qty), "stock_uom": rule.stock_uom,
        "require_full_bin_consumption": bool(cint(pool.get("require_full_bin_consumption"))),
        "allow_supervisor_partial_exception": bool(cint(
            pool.get("allow_supervisor_partial_exception")
        )),
        "process_execution": frappe.db.get_value(
            "CFG Kanban Process Execution",
            {"kanban_cycle": cycle.name, "operation": job.operation}, "name",
        ),
    }


def transfer_loads_for_row(stock_entry, row_name):
    return frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"transfer_stock_entry": stock_entry, "transfer_stock_entry_detail": row_name,
         "status": ["in", ["Transfer Draft", "Ready"]]},
        ["name", "status", "reusable_bin", "source_handling_unit", "actual_qty",
         "stock_uom", "partial_exception", "exception_reason", "approved_by",
         "approved_by_operator", "exception_approved_on"], order_by="creation asc",
    )


def consumption_loads_for_row(stock_entry, row_name):
    return frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"consumption_stock_entry": stock_entry,
         "consumption_stock_entry_detail": row_name,
         "status": ["in", ["Consumption Draft", "Consumed"]]},
        ["name", "status", "reusable_bin", "actual_qty", "stock_uom",
         "partial_exception", "exception_reason", "approved_by",
         "approved_by_operator", "exception_approved_on"],
        order_by="creation asc",
    )


def create_transfer_load(*, stock_entry, stock_entry_detail, reusable_bin,
                         kanban_cycle, job_card, item_code, actual_qty,
                         source_handling_unit=None, batch_no=None,
                         process_execution=None, operator=None,
                         operator_session=None, idempotency_key=None,
                         partial_exception=False, exception_reason=None,
                         approved_by=None, approved_by_operator=None,
                         exception_approved_on=None):
    """Create one auditable Draft transfer/load episode for a scanned fixed bin.

    The scanner runtime calls this only after ERPNext has created and saved the Draft native
    Material Transfer for Manufacture. No stock or WIP quantity is confirmed here.
    """
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) != TRANSFER_PURPOSE:
        frappe.throw("A WIP Bin load requires a Draft Material Transfer for Manufacture")
    if entry.get("cfg_kanban_cycle") != kanban_cycle:
        frappe.throw("Material Transfer does not belong to the selected Kanban Cycle")
    row = _entry_row(entry, stock_entry_detail)
    if row.item_code != item_code or not row.s_warehouse or not row.t_warehouse:
        frappe.throw("Selected Stock Entry row is not the requested WIP material transfer")

    cycle = frappe.get_doc("CFG Kanban Cycle", kanban_cycle)
    job = frappe.db.get_value(
        "Job Card", {"name": job_card, "work_order": entry.work_order, "docstatus": ["<", 2]},
        ["name", "operation", "workstation"], as_dict=True,
    )
    if not job:
        frappe.throw("Select an active Job Card from the transfer Work Order")
    rule = _wip_rule(cycle.kanban_master, item_code, job.operation)
    pool = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool", rule.wip_bin_pool,
        ["company", "wip_warehouse"], as_dict=True,
    )
    if not pool or pool.company != entry.company or pool.wip_warehouse != row.t_warehouse:
        frappe.throw("WIP Bin Pool does not match the ERPNext transfer Company/WIP Warehouse")
    qty = flt(actual_qty)
    if qty <= 0 or qty > _row_stock_qty(row) + TOLERANCE:
        frappe.throw("WIP Bin load quantity must be positive and within the Stock Entry row")

    key = idempotency_key or (
        f"wip-bin-load:{entry.name}:{row.name}:{reusable_bin}:{qty}"
    )
    existing = frappe.db.get_value("CFG Kanban WIP Bin Load", {"idempotency_key": key}, "name")
    if existing:
        return frappe.get_doc("CFG Kanban WIP Bin Load", existing), False

    _lock_reusable_bin(reusable_bin)
    bin_unit = frappe.get_doc("CFG Kanban Handling Unit", reusable_bin)
    _assert_reusable_bin(bin_unit, rule.wip_bin_pool, entry.company, row.t_warehouse)
    load = frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Load",
        "status": "Transfer Draft",
        "reusable_bin": reusable_bin,
        "wip_bin_pool": rule.wip_bin_pool,
        "company": entry.company,
        "item_code": item_code,
        "batch_no": batch_no or row.get("batch_no"),
        "standard_qty": rule.standard_bin_qty,
        "actual_qty": qty,
        "stock_uom": row.stock_uom,
        "partial_exception": 1 if partial_exception else 0,
        "exception_reason": exception_reason if partial_exception else None,
        "approved_by": approved_by if partial_exception else None,
        "approved_by_operator": approved_by_operator if partial_exception else None,
        "exception_approved_on": exception_approved_on if partial_exception else None,
        "kanban_master": cycle.kanban_master,
        "kanban_cycle": cycle.name,
        "work_order": entry.work_order,
        "job_card": job.name,
        "process_execution": process_execution,
        "operation": job.operation,
        "workstation": job.workstation,
        "source_handling_unit": source_handling_unit,
        "source_warehouse": row.s_warehouse,
        "wip_warehouse": row.t_warehouse,
        "transfer_stock_entry": entry.name,
        "transfer_stock_entry_detail": row.name,
        "idempotency_key": key,
        "reserved_on": now_datetime(),
        "reserved_by_operator": operator,
        "operator_session": operator_session,
        "notes": "Awaiting ERPNext Material Transfer submission",
    }).insert(ignore_permissions=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", reusable_bin, "wip_bin_state", "Reserved",
        update_modified=False,
    )
    record(
        "WIP Bin Load Reserved", card=cycle.kanban_card, cycle=cycle.name,
        execution=process_execution, handling_unit=reusable_bin, qty=qty,
        reference_doctype="CFG Kanban WIP Bin Load", reference_name=load.name,
        operator=operator, operator_session=operator_session,
        notes=f"{item_code} / {row.s_warehouse} -> {row.t_warehouse}; ERP Draft {entry.name}",
    )
    return load, True


def bind_consumption_draft(load_name, stock_entry, stock_entry_detail):
    """Bind a Ready/In-Use load to a Draft ERP consumption row without consuming it."""
    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    if load.status not in ("Ready", "In Use"):
        frappe.throw(f"WIP Bin Load {load.name} is {load.status}, not Ready for consumption")
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) not in CONSUMPTION_PURPOSES:
        frappe.throw("WIP Bin consumption requires a Draft production consumption Stock Entry")
    if entry.get("cfg_kanban_cycle") != load.kanban_cycle or entry.work_order != load.work_order:
        frappe.throw("Consumption Stock Entry does not belong to the WIP Bin Load production context")
    if entry.get("job_card") and entry.job_card != load.job_card:
        frappe.throw("Consumption Stock Entry Job Card does not match the WIP Bin Load")
    row = _entry_row(entry, stock_entry_detail)
    _assert_consumption_row(load, row)
    load.db_set({
        "status": "Consumption Draft",
        "consumption_stock_entry": entry.name,
        "consumption_stock_entry_detail": row.name,
        "notes": "Awaiting ERPNext consumption submission",
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin, "wip_bin_state", "In Use",
        update_modified=False,
    )
    return frappe.get_doc("CFG Kanban WIP Bin Load", load.name)


def validate_wip_bin_stock_entry(doc):
    """Validate every linked load and require complete coverage of WIP-bin material rows."""
    purpose = _purpose(doc)
    if purpose not in (TRANSFER_PURPOSE, *CONSUMPTION_PURPOSES):
        return
    if purpose == "Manufacture":
        _assert_no_unconsumed_loads(doc.work_order, doc.get("cfg_kanban_cycle"))
    loads, direction = _loads_for_entry(doc.name)
    required_transfer_rows = (
        {row.name: row for row in doc.items if entry_wip_bin_rule(doc, row)}
        if purpose == TRANSFER_PURPOSE else {}
    )
    required_consumption_rows = (
        {row.name: row for row in doc.items if entry_wip_bin_rule(doc, row)}
        if purpose == "Material Consumption for Manufacture" else {}
    )
    required_rows = required_transfer_rows or required_consumption_rows
    if required_rows and not loads:
        items = ", ".join(dict.fromkeys(row.item_code for row in required_transfer_rows.values()))
        if required_consumption_rows:
            items = ", ".join(dict.fromkeys(
                row.item_code for row in required_consumption_rows.values()
            ))
        frappe.throw(
            "Standard Quantity WIP Bin allocation is required before submitting this "
            f"production entry. Open Production Material Trace and scan: {items}"
        )
    if not loads:
        return
    expected_statuses = (
        ("Transfer Draft", "Ready") if direction == "transfer"
        else ("Consumption Draft", "Consumed")
    )
    rows = {row.name: row for row in doc.items}
    allocated = {}
    for load in loads:
        if load.status not in expected_statuses:
            frappe.throw(f"WIP Bin Load {load.name} is {load.status}; expected {expected_statuses[0]}")
        row_name = (load.transfer_stock_entry_detail if direction == "transfer"
                    else load.consumption_stock_entry_detail)
        row = rows.get(row_name)
        if not row:
            frappe.throw(f"WIP Bin Load {load.name} no longer matches a Stock Entry row")
        if direction == "transfer":
            _assert_transfer_row(load, row, doc)
        else:
            _assert_consumption_row(load, row)
        allocated[row.name] = allocated.get(row.name, 0) + flt(load.actual_qty)
    for row_name, qty in allocated.items():
        row_qty = _row_stock_qty(rows[row_name])
        if abs(qty - row_qty) > TOLERANCE:
            frappe.throw(
                f"WIP Bin loads cover {qty} of {row_qty} {rows[row_name].stock_uom} "
                f"for Item {rows[row_name].item_code}; allocate the complete Stock Entry row"
            )
    missing_required = set(required_transfer_rows) - set(allocated)
    if direction == "consumption":
        missing_required = set(required_consumption_rows) - set(allocated)
    if missing_required:
        source = required_transfer_rows if direction == "transfer" else required_consumption_rows
        items = ", ".join(dict.fromkeys(source[name].item_code for name in missing_required))
        frappe.throw(f"Allocate Standard Quantity WIP Bins for: {items}")


def confirm_wip_bin_stock_entry(doc):
    """Advance bin/load state only after ERPNext has submitted the native transaction."""
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    validate_wip_bin_stock_entry(doc)
    timestamp = now_datetime()
    for summary in loads:
        _lock_load(summary.name)
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        if direction == "transfer":
            if load.status == "Ready":
                continue
            if load.source_handling_unit:
                ledger = post_quantity_event(
                    event_type="WIP Bin Load", qty=load.actual_qty,
                    stock_uom=load.stock_uom,
                    idempotency_key=f"wip-bin-source-confirm:{load.name}:{doc.name}",
                    source_handling_unit=load.source_handling_unit,
                    item_code=load.item_code, batch_no=load.batch_no,
                    source_company=load.company,
                    source_warehouse=load.source_warehouse,
                    destination_company=load.company,
                    destination_warehouse=load.wip_warehouse,
                    reference_doctype="Stock Entry", reference_name=doc.name,
                    reason=f"ERPNext confirmed WIP Bin Load {load.name}",
                    release_reserved=True,
                )
            load.db_set({
                "status": "Ready", "ready_on": timestamp,
                "source_confirmation_ledger": ledger.name if load.source_handling_unit else None,
                "notes": f"Ready after submitted ERPNext transfer {doc.name}",
            }, update_modified=True)
            bin_state = "Ready"
            event_type = "WIP Bin Load Ready"
        else:
            if load.status == "Consumed":
                continue
            load.db_set({
                "status": "Consumed", "consumed_on": timestamp,
                "notes": f"Consumed by submitted ERPNext entry {doc.name}",
            }, update_modified=True)
            bin_state = "Empty"
            event_type = "WIP Bin Load Consumed"
        frappe.db.set_value(
            "CFG Kanban Handling Unit", load.reusable_bin,
            "wip_bin_state", bin_state, update_modified=False,
        )
        record(
            event_type, cycle=load.kanban_cycle, execution=load.process_execution,
            handling_unit=load.reusable_bin, qty=load.actual_qty,
            reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name}; ERPNext confirmed",
        )


def reverse_wip_bin_stock_entry(doc):
    """Make ERP cancellation visible and stop automatic reuse pending reconciliation."""
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    for summary in loads:
        _lock_load(summary.name)
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        if load.status == "Reversed":
            continue
        if direction == "transfer" and load.status not in ("Transfer Draft", "Ready"):
            frappe.throw(
                f"Cannot cancel transfer: WIP Bin Load {load.name} is already {load.status}"
            )
        if direction == "consumption" and load.status != "Consumed":
            frappe.throw(
                f"Cannot cancel consumption: WIP Bin Load {load.name} is {load.status}"
            )
        bin_state = "Empty" if direction == "transfer" else "Exception"
        reversal_ledger = None
        if (direction == "transfer" and load.status == "Ready"
                and load.source_handling_unit and load.source_confirmation_ledger):
            reversal_ledger = post_quantity_event(
                event_type="WIP Bin Load Reversal", qty=load.actual_qty,
                stock_uom=load.stock_uom,
                idempotency_key=f"wip-bin-source-reverse:{load.name}:{doc.name}",
                destination_handling_unit=load.source_handling_unit,
                item_code=load.item_code, batch_no=load.batch_no,
                source_company=load.company, source_warehouse=load.wip_warehouse,
                destination_company=load.company,
                destination_warehouse=load.source_warehouse,
                reference_doctype="Stock Entry", reference_name=doc.name,
                reason=f"ERPNext cancelled WIP Bin Load {load.name}",
            )
        elif (direction == "transfer" and load.status == "Transfer Draft"
              and load.source_handling_unit and load.source_reservation_ledger):
            reversal_ledger = post_quantity_event(
                event_type="Unreserve", qty=load.actual_qty,
                stock_uom=load.stock_uom,
                idempotency_key=f"wip-bin-source-cancel:{load.name}:{doc.name}",
                source_handling_unit=load.source_handling_unit,
                item_code=load.item_code, batch_no=load.batch_no,
                source_company=load.company, source_warehouse=load.source_warehouse,
                reference_doctype="Stock Entry", reference_name=doc.name,
                reason=f"ERPNext cancelled Draft WIP Bin Load {load.name}",
            )
        load.db_set({
            "status": "Reversed", "reversed_on": now_datetime(),
            "source_reversal_ledger": reversal_ledger.name if reversal_ledger else None,
            "notes": (f"ERPNext {direction} Stock Entry {doc.name} cancelled; "
                      "supervisor reconciliation required"),
        }, update_modified=True)
        frappe.db.set_value(
            "CFG Kanban Handling Unit", load.reusable_bin,
            "wip_bin_state", bin_state, update_modified=False,
        )
        record(
            "WIP Bin Load Reversed", cycle=load.kanban_cycle,
            execution=load.process_execution, handling_unit=load.reusable_bin,
            qty=load.actual_qty, reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name}; physical state {bin_state}",
        )


def _loads_for_entry(stock_entry):
    fields = [
        "name", "status", "reusable_bin", "item_code", "batch_no", "actual_qty",
        "stock_uom", "company", "source_warehouse", "wip_warehouse", "kanban_cycle",
        "process_execution", "transfer_stock_entry_detail",
        "consumption_stock_entry_detail",
    ]
    transfer = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"transfer_stock_entry": stock_entry,
         "status": ["in", ["Transfer Draft", "Ready"]]}, fields,
    )
    consumption = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"consumption_stock_entry": stock_entry,
         "status": ["in", ["Consumption Draft", "Consumed"]]}, fields,
    )
    if transfer and consumption:
        frappe.throw("One Stock Entry cannot be both WIP Bin transfer and consumption")
    if transfer:
        return transfer, "transfer"
    if consumption:
        return consumption, "consumption"
    purpose = frappe.db.get_value("Stock Entry", stock_entry, "stock_entry_type")
    return [], "transfer" if purpose == TRANSFER_PURPOSE else "consumption"


def _wip_rule(master, item_code, operation):
    rule = frappe.db.get_value("CFG Kanban Material Flow Rule", {
        "parent": master,
        "parenttype": "CFG Kanban Master",
        "item_code": item_code,
        "operation": operation,
        "wip_presentation_method": "Standard Quantity Reusable WIP Bin",
    }, ["wip_bin_pool", "standard_bin_qty", "stock_uom"], as_dict=True)
    if not rule:
        frappe.throw(f"Item {item_code} is not configured as a reusable WIP Bin material")
    return rule


def _entry_row(doc, row_name):
    row = next((candidate for candidate in doc.items if candidate.name == row_name), None)
    if not row:
        frappe.throw("Selected Stock Entry material row was not found")
    return row


def _assert_transfer_row(load, row, doc):
    if (_purpose(doc) != TRANSFER_PURPOSE or row.item_code != load.item_code
            or row.s_warehouse != load.source_warehouse
            or row.t_warehouse != load.wip_warehouse
            or row.stock_uom != load.stock_uom
            or (row.get("batch_no") or "") != (load.batch_no or "")):
        frappe.throw(f"WIP Bin Load {load.name} no longer matches its ERP transfer row")


def _assert_consumption_row(load, row):
    if (row.item_code != load.item_code or row.s_warehouse != load.wip_warehouse
            or row.stock_uom != load.stock_uom
            or (row.get("batch_no") or "") != (load.batch_no or "")):
        frappe.throw(f"WIP Bin Load {load.name} no longer matches its ERP consumption row")


def _row_stock_qty(row):
    return flt(row.get("transfer_qty") or row.get("qty"))


def _purpose(doc):
    return doc.get("stock_entry_type") or doc.get("purpose")


def _lock_reusable_bin(reusable_bin):
    if not frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        reusable_bin,
    ):
        frappe.throw("Reusable WIP Bin was not found")


def _lock_load(load_name):
    if not frappe.db.sql(
        "select name from `tabCFG Kanban WIP Bin Load` where name=%s for update",
        load_name,
    ):
        frappe.throw("WIP Bin Load was not found")


def _lock_stock_entry(name):
    if not frappe.db.sql("select name from `tabStock Entry` where name=%s for update", name):
        frappe.throw("Stock Entry was not found")


def _remaining_transfer_qty(stock_entry, row_name, row_qty):
    allocated = frappe.db.sql(
        """
        select coalesce(sum(actual_qty), 0)
        from `tabCFG Kanban WIP Bin Load`
        where transfer_stock_entry=%s and transfer_stock_entry_detail=%s
          and status in ('Transfer Draft', 'Ready')
        """,
        (stock_entry, row_name),
    )[0][0]
    return max(flt(row_qty) - flt(allocated), 0)


def _remaining_consumption_qty(stock_entry, row_name, row_qty):
    allocated = frappe.db.sql(
        """
        select coalesce(sum(actual_qty), 0)
        from `tabCFG Kanban WIP Bin Load`
        where consumption_stock_entry=%s and consumption_stock_entry_detail=%s
          and status in ('Consumption Draft', 'Consumed')
        """,
        (stock_entry, row_name),
    )[0][0]
    return max(flt(row_qty) - flt(allocated), 0)


def _resolve_ready_load(scan_value, context, entry, row):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan a Ready Standard Quantity WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != "Standard Quantity WIP Bin"):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a Standard Quantity WIP Bin")
    existing = frappe.db.get_value("CFG Kanban WIP Bin Load", {
        "reusable_bin": unit.name, "status": "Consumption Draft",
        "consumption_stock_entry": entry.name,
        "consumption_stock_entry_detail": row.name,
    }, "name")
    if existing:
        return frappe.get_doc("CFG Kanban WIP Bin Load", existing)
    if unit.wip_bin_state != "Ready":
        frappe.throw(f"WIP Bin {unit.handling_unit_id} is {unit.wip_bin_state}, not Ready")
    # MariaDB/Frappe null filters vary across supported versions; perform the final
    # batch-safe match in Python for both blank and explicit batches.
    candidates = frappe.get_all("CFG Kanban WIP Bin Load", {
        "reusable_bin": unit.name, "status": "Ready",
        "kanban_cycle": context["kanban_cycle"], "work_order": entry.work_order,
        "job_card": context["job_card"], "item_code": row.item_code,
        "wip_warehouse": row.s_warehouse, "stock_uom": row.stock_uom,
    }, ["name", "batch_no"])
    load_name = next((value.name for value in candidates
                      if (value.batch_no or "") == (row.get("batch_no") or "")), None)
    if not load_name:
        frappe.throw(
            f"Ready WIP Bin {unit.handling_unit_id} does not match this Cycle, Job Card, "
            "Item, WIP Warehouse, UOM, or Batch"
        )
    return frappe.get_doc("CFG Kanban WIP Bin Load", load_name)


def _assert_no_unconsumed_loads(work_order, cycle_name=None):
    filters = {
        "work_order": work_order,
        "status": ["in", ["Transfer Draft", "Ready", "In Use", "Consumption Draft"]],
    }
    if cycle_name:
        filters["kanban_cycle"] = cycle_name
    active = frappe.get_all(
        "CFG Kanban WIP Bin Load", filters,
        ["name", "reusable_bin", "status"], limit_page_length=6,
    )
    if active:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.status})" for row in active[:5]
        )
        frappe.throw(
            "Submit the WIP-bin Material Consumption entry before Manufacture receipt. "
            f"Active bin load(s): {detail}"
        )


def _resolve_reusable_bin(scan_value, context, entry, row):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Standard Quantity WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    _assert_reusable_bin(unit, context["wip_bin_pool"], entry.company, row.t_warehouse)
    return unit


def _assert_reusable_bin(unit, pool_name, company, wip_warehouse):
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != "Standard Quantity WIP Bin"):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a Standard Quantity WIP Bin")
    if unit.identity_state not in ("Active", "Empty") or unit.wip_bin_state != "Empty":
        frappe.throw(
            f"WIP Bin {unit.handling_unit_id} is {unit.identity_state} / "
            f"{unit.wip_bin_state or 'Unspecified'}, not Empty"
        )
    if unit.inventory_company != company or unit.current_warehouse != wip_warehouse:
        frappe.throw(
            f"WIP Bin {unit.handling_unit_id} does not belong to {company} / {wip_warehouse}"
        )
    if not frappe.db.exists("CFG Kanban WIP Bin Pool Entry", {
        "parent": pool_name, "parenttype": "CFG Kanban WIP Bin Pool",
        "reusable_bin": unit.name,
    }):
        frappe.throw(f"WIP Bin {unit.handling_unit_id} is not approved in Pool {pool_name}")
    active = frappe.db.get_value(
        "CFG Kanban WIP Bin Load",
        {"reusable_bin": unit.name,
         "status": ["in", ["Reserved", "Transfer Draft", "Ready", "In Use",
                            "Consumption Draft"]]},
        "name",
    )
    if active:
        frappe.throw(f"WIP Bin {unit.handling_unit_id} already has active Load {active}")


def _resolve_source_unit(scan_value, entry, row, policy, qty, batch_no):
    value = str(scan_value or "").strip()
    if not value:
        if policy.production_input_tag_policy == "Required Physical Tag":
            frappe.throw(f"Item {row.item_code} requires a source Stock Tag before the WIP Bin")
        return None
    if policy.production_input_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} is configured for ERP-only input; scan the WIP Bin "
            "without a source Stock Tag"
        )
    identity = resolve_logistics_scan(value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active source Stock Tag, not a reusable bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if unit.tag_kind == "Reusable Container":
        frappe.throw("The source scan must be a Stock Tag, not a reusable container")
    from cfg_kanban.services.container_contents import assert_not_loaded_in_container
    assert_not_loaded_in_container(unit.name, "allocating it to a Standard Quantity WIP Bin")
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw(
            f"Source Tag {unit.handling_unit_id} is {unit.identity_state} / {unit.quality_state}"
        )
    if (unit.item_code != row.item_code or unit.inventory_company != entry.company
            or unit.current_warehouse != row.s_warehouse or unit.stock_uom != row.stock_uom
            or (unit.batch_no or "") != (batch_no or "")):
        frappe.throw(
            f"Source Tag {unit.handling_unit_id} does not match Item, Company, Warehouse, "
            "UOM, or Batch of the selected ERP material row"
        )
    if flt(unit.available_qty) + TOLERANCE < qty:
        frappe.throw(
            f"Source Tag {unit.handling_unit_id} has only {unit.available_qty} "
            f"{unit.stock_uom} available; the full WIP Bin requires {qty}"
        )
    return unit


def _allocation_result(entry, row, load):
    return {
        "stock_entry": entry.name, "row_name": row.name, "load": load.name,
        "status": load.status, "reusable_bin": load.reusable_bin,
        "source_handling_unit": load.source_handling_unit,
        "actual_qty": flt(load.actual_qty), "stock_uom": load.stock_uom,
        "partial_exception": bool(load.partial_exception),
        "exception_reason": load.exception_reason,
        "remaining_qty": _remaining_transfer_qty(entry.name, row.name, _row_stock_qty(row)),
    }


def _consumption_allocation_result(entry, row, load):
    return {
        "stock_entry": entry.name, "row_name": row.name, "load": load.name,
        "status": load.status, "reusable_bin": load.reusable_bin,
        "actual_qty": flt(load.actual_qty), "stock_uom": load.stock_uom,
        "partial_exception": bool(load.partial_exception),
        "exception_reason": load.exception_reason,
        "remaining_qty": _remaining_consumption_qty(
            entry.name, row.name, _row_stock_qty(row)
        ),
    }


def _assert_partial_exception_authorized(actor, context, qty, standard_qty, remaining,
                                         reason):
    if qty <= TOLERANCE or qty >= standard_qty - TOLERANCE:
        frappe.throw(
            f"Partial WIP Bin quantity must be greater than zero and below the Standard "
            f"Full-bin Qty of {standard_qty}"
        )
    if qty > remaining + TOLERANCE:
        frappe.throw(
            f"Partial WIP Bin quantity {qty} exceeds the remaining ERP row quantity "
            f"{remaining}"
        )
    if not context.get("allow_supervisor_partial_exception"):
        frappe.throw("This WIP Bin Pool does not allow supervisor partial-bin exceptions")
    profile, _session = actor
    if (profile.kanban_role not in ("Supervisor", "Development Proxy")
            or not cint(profile.get("can_override"))):
        frappe.throw(
            "A Kanban Supervisor with Override permission must approve a partial WIP Bin"
        )
    if not reason:
        frappe.throw("Supervisor exception reason is required for a partial WIP Bin")

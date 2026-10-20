"""Controlled load episodes for fixed-quantity reusable WIP bins.

This service deliberately follows native ERPNext Stock Entry state. A Draft entry may reserve a
physical bin, but it never makes material Ready or Consumed. Those states are confirmed only from
the Stock Entry submit hook.
"""

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


TOLERANCE = 0.000001
TRANSFER_PURPOSE = "Material Transfer for Manufacture"
CONSUMPTION_PURPOSES = ("Material Consumption for Manufacture", "Manufacture")
ACTIVE_LOAD_STATUSES = ("Transfer Draft", "Ready", "In Use", "Consumption Draft")
JOB_CARD_SUBMIT_BLOCK_STATUSES = ("Transfer Draft",)


def validate_job_card_wip_bin_submission(doc, method=None):
    """Allow ERP operation completion once transfer is authoritative.

    ERPNext requires the Job Card operation to be completed before it will submit the matching
    production consumption. Ready/In Use/Consumption Draft bins therefore cannot block Job Card
    submission; Cycle closure and Manufacture receipt retain the stricter consumed-bin gate.
    """
    if doc.docstatus == 2:
        return
    readiness = job_card_wip_bin_submit_readiness(doc.name)
    if not readiness["ready"]:
        frappe.throw(readiness["reason"])


def validate_job_card_bins_consumed(doc, method=None):
    """Backward-compatible alias for sites whose cached hooks still reference the old name."""
    return validate_job_card_wip_bin_submission(doc, method)


def job_card_wip_bin_submit_readiness(job_card):
    """Return whether ERPNext may submit the operation Job Card without a WIP deadlock."""
    if not job_card:
        return {"ready": True, "reason": None, "blocking_loads": [], "reconciliations": []}
    reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        {"job_card": job_card, "status": "Open"},
        ["name", "reusable_bin", "reversal_context"],
        order_by="raised_on asc", limit_page_length=6,
    )
    blocking = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"job_card": job_card, "status": ["in", list(JOB_CARD_SUBMIT_BLOCK_STATUSES)]},
        ["name", "reusable_bin", "status"],
        order_by="creation asc", limit_page_length=6,
    )
    if reconciliations:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.reversal_context or 'Cancellation'})"
            for row in reconciliations[:5]
        )
        return {
            "ready": False,
            "reason": (
                f"Cannot complete Job Card {job_card} while a WIP Bin supervisor "
                f"reconciliation is open: {detail}"
            ),
            "blocking_loads": blocking,
            "reconciliations": reconciliations,
        }
    if blocking:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.status})" for row in blocking[:5]
        )
        return {
            "ready": False,
            "reason": (
                "Submit or cancel the Draft WIP-bin transfer before completing this Job Card. "
                f"Blocking bin load(s): {detail}"
            ),
            "blocking_loads": blocking,
            "reconciliations": reconciliations,
        }
    return {"ready": True, "reason": None, "blocking_loads": [],
            "reconciliations": reconciliations}


def job_card_wip_bin_close_readiness(job_card):
    """Return whether a Job Card has no unresolved physical WIP-bin responsibility.

    Runtime operation Cards may complete in smaller allocations than the ERP Job Card. This gate
    deliberately uses Job Card scope because a WIP Bin Load is not divisible between runtime
    cards: the physical bin must be consumed or reconciled before any controlling operation Card
    is released for reuse.
    """
    if not job_card:
        return {"ready": True, "reason": None, "active_loads": [], "reconciliations": []}
    reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        {"job_card": job_card, "status": "Open"},
        ["name", "reusable_bin", "reversal_context"],
        order_by="raised_on asc", limit_page_length=6,
    )
    active = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"job_card": job_card, "status": ["in", list(ACTIVE_LOAD_STATUSES)]},
        ["name", "reusable_bin", "status"],
        order_by="creation asc", limit_page_length=6,
    )
    if reconciliations:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.reversal_context or 'Cancellation'})"
            for row in reconciliations[:5]
        )
        return {
            "ready": False,
            "reason": (
                f"Cannot close the Kanban Cycle while Job Card {job_card} has an open WIP Bin "
                f"supervisor reconciliation: {detail}"
            ),
            "active_loads": active,
            "reconciliations": reconciliations,
        }
    if active:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.status})" for row in active[:5]
        )
        return {
            "ready": False,
            "reason": (
                "Submit or cancel the Job Card WIP-bin material movement before closing this "
                f"Kanban Cycle. Active bin load(s): {detail}"
            ),
            "active_loads": active,
            "reconciliations": reconciliations,
        }
    return {"ready": True, "reason": None, "active_loads": [], "reconciliations": []}


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
def allocate_consumption_bin(stock_entry, item_row=None, reusable_bin_scan=None,
                             operator_session_token=None, kanban_card=None,
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
    # A Ready-bin scan is sufficient for consumption. Resolve its immutable Ready-load
    # snapshot first and use that to select the exact ERP Item/Warehouse/UOM/Batch row.
    # ``item_row`` remains accepted for compatibility with already-open browser clients.
    row = (_entry_row(entry, item_row) if item_row
           else _consumption_row_for_ready_bin(entry, reusable_bin_scan))
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
    job_card = (
        entry.get("cfg_kanban_job_card")
        or entry.get("job_card")
        or cycle.selected_job_card
    )
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
    entry_job_card = entry.get("cfg_kanban_job_card") or entry.get("job_card")
    if entry_job_card and entry_job_card != load.job_card:
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
    deferred_job_cards = set()
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
        if load.job_card:
            deferred_job_cards.add(load.job_card)
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
    if deferred_job_cards:
        _submit_deferred_job_cards(deferred_job_cards, doc)


def _submit_deferred_job_cards(job_cards, production_entry):
    """Queue target-reached Job Cards after their WIP transfer becomes authoritative.

    Progress reporting deliberately leaves these Job Cards in Draft while any physical bin
    transfer remains Draft. A submitted ERPNext transfer is the first safe point at which the
    operation may complete. Run the retry after commit so Job Card validation cannot roll back an
    already-valid ERPNext stock movement.
    """
    settings = frappe.get_single("CFG Kanban Settings")
    if not settings.get("auto_submit_job_card"):
        return
    for job_card_name in sorted(job_cards):
        frappe.enqueue(
            "cfg_kanban.services.wip_bin_loads.submit_deferred_job_card",
            queue="short", enqueue_after_commit=True,
            job_card_name=job_card_name,
            production_entry_name=production_entry.name,
        )


def submit_deferred_job_card(job_card_name, production_entry_name):
    """Background retry for target progress recorded before the WIP transfer submitted."""
    settings = frappe.get_single("CFG Kanban Settings")
    if not settings.get("auto_submit_job_card"):
        return
    if frappe.db.get_value("Stock Entry", production_entry_name, "docstatus") != 1:
        return
    job_card = frappe.get_doc("Job Card", job_card_name)
    if (job_card.docstatus != 0 or
            flt(job_card.total_completed_qty) + TOLERANCE < flt(job_card.for_quantity)):
        return
    readiness = job_card_wip_bin_submit_readiness(job_card.name)
    if not readiness["ready"]:
        return
    job_card.submit()
    job_card.reload()
    if job_card.status != "Completed":
        frappe.throw(
            f"ERPNext submitted Job Card {job_card.name} after WIP-bin consumption, "
            f"but its status is {job_card.status}"
        )
    cycle = frappe.db.get_value(
        "CFG Kanban WIP Bin Load",
        {"job_card": job_card.name, "transfer_stock_entry": production_entry_name},
        "kanban_cycle",
    ) or frappe.db.get_value(
        "CFG Kanban WIP Bin Load",
        {"job_card": job_card.name, "consumption_stock_entry": production_entry_name},
        "kanban_cycle",
    )
    record(
        "Deferred Job Card Auto-submit Completed",
        cycle=cycle,
        reference_doctype="Job Card", reference_name=job_card.name,
        notes=f"Released after submitted WIP-bin stock movement {production_entry_name}",
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
        submitted_transfer = direction == "transfer" and load.status == "Ready"
        bin_state = "Exception" if (direction == "consumption" or submitted_transfer) else "Empty"
        reversal_ledger = None
        if (submitted_transfer and load.source_handling_unit
                and not load.source_confirmation_ledger):
            frappe.throw(
                f"Cannot cancel transfer for WIP Bin Load {load.name}: its source-tag "
                "confirmation ledger is missing. Reconcile the audit record first."
            )
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
            "notes": (
                f"ERPNext {direction} Stock Entry {doc.name} cancelled; "
                + ("supervisor reconciliation required"
                   if direction == "consumption" or submitted_transfer
                   else "Draft allocation released before ERP movement")
            ),
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
        if direction == "consumption":
            _create_consumption_reconciliation(load, doc)
        elif submitted_transfer:
            _create_transfer_reconciliation(load, doc)


@frappe.whitelist()
def resolve_wip_bin_reconciliation(reconciliation_name, decision, reusable_bin_scan,
                                   reason, operator_session_token, kanban_card,
                                   correction_stock_entry=None,
                                   source_handling_unit_scan=None,
                                   event_token=None):
    """Resolve a submitted transfer/consumption cancellation against physical truth.

    Every path requires the exact affected bin scan. Transfer cancellation also keeps any
    restored source-tag quantity reserved until the Supervisor verifies where material is.
    """
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("Supervisor reconciliation reason is required")
    _lock_reconciliation(reconciliation_name)
    reconciliation = frappe.get_doc(
        "CFG Kanban WIP Bin Reconciliation", reconciliation_name
    )
    _lock_load(reconciliation.wip_bin_load)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", reconciliation.wip_bin_load)
    _lock_reusable_bin(load.reusable_bin)
    profile, session = _authorize_reconciliation(
        load, operator_session_token, kanban_card
    )
    identity = resolve_logistics_scan(reusable_bin_scan)
    if (not identity or identity.get("identity_type") != "Handling Unit"
            or identity.get("name") != load.reusable_bin):
        frappe.throw(f"Scan the affected WIP Bin {load.reusable_bin} to resolve this hold")
    if reconciliation.status == "Resolved":
        return _reconciliation_result(reconciliation)
    if reconciliation.status != "Open":
        frappe.throw(f"WIP Bin reconciliation is {reconciliation.status}, not Open")
    allowed = _reconciliation_decisions(reconciliation.reversal_context)
    if decision not in allowed:
        frappe.throw(
            f"Select an outcome for {reconciliation.reversal_context or 'this cancellation'}"
        )
    unit = frappe.get_doc("CFG Kanban Handling Unit", load.reusable_bin)
    if load.status != "Reversed" or unit.wip_bin_state != "Exception":
        frappe.throw(
            f"Expected Reversed load / Exception bin, found {load.status} / "
            f"{unit.wip_bin_state or 'Unspecified'}"
        )

    restored_load = None
    correction = None
    source_resolution_ledger = None
    if decision == "Material Restored to Bin":
        if correction_stock_entry:
            frappe.throw("Do not select an ERP correction when material is restored to the bin")
        restored_load = _create_recovered_ready_load(
            load, reconciliation, profile, session, event_token
        )
        physical_state = "Ready"
        evidence = (
            f"Exact {load.actual_qty} {load.stock_uom} {load.item_code}"
            f"{f' / Batch {load.batch_no}' if load.batch_no else ''} physically restored "
            f"to {load.reusable_bin}; recovered as Load {restored_load.name}"
        )
    elif decision == "Bin Empty after ERP Correction":
        correction = _validate_empty_bin_correction(
            load, reconciliation, correction_stock_entry
        )
        physical_state = "Empty"
        evidence = (
            f"Bin verified empty after submitted ERPNext correction {correction.name} "
            f"removed exact {load.actual_qty} {load.stock_uom} from {load.wip_warehouse}"
        )
    elif decision == "Material Returned to Source":
        if correction_stock_entry:
            frappe.throw("Do not select an ERP correction when material returned to source")
        _verify_source_handling_unit_scan(load, source_handling_unit_scan)
        if reconciliation.source_hold_ledger:
            source_resolution_ledger = post_quantity_event(
                event_type="Unreserve", qty=load.actual_qty,
                stock_uom=load.stock_uom,
                idempotency_key=f"wip-bin-source-returned:{reconciliation.name}",
                source_handling_unit=load.source_handling_unit,
                item_code=load.item_code, batch_no=load.batch_no,
                source_company=load.company, source_warehouse=load.source_warehouse,
                reference_doctype="CFG Kanban WIP Bin Reconciliation",
                reference_name=reconciliation.name,
                operator=profile.employee, operator_session=session.name,
                reason=f"Supervisor verified material returned from {load.reusable_bin}",
            )
        physical_state = "Empty"
        evidence = (
            f"Exact {load.actual_qty} {load.stock_uom} {load.item_code} physically returned "
            f"from {load.reusable_bin} to {load.source_warehouse}"
            f"{f' / Source Tag {load.source_handling_unit}' if load.source_handling_unit else ''}"
        )
    else:
        correction, correction_row = _validate_transfer_recovery_correction(
            load, reconciliation, correction_stock_entry
        )
        if reconciliation.source_hold_ledger:
            source_resolution_ledger = post_quantity_event(
                event_type="WIP Bin Load", qty=load.actual_qty,
                stock_uom=load.stock_uom,
                idempotency_key=f"wip-bin-source-remains:{reconciliation.name}",
                source_handling_unit=load.source_handling_unit,
                item_code=load.item_code, batch_no=load.batch_no,
                source_company=load.company, source_warehouse=load.source_warehouse,
                destination_company=load.company,
                destination_warehouse=load.wip_warehouse,
                reference_doctype="Stock Entry", reference_name=correction.name,
                operator=profile.employee, operator_session=session.name,
                reason=f"ERP correction confirmed material remains in {load.reusable_bin}",
                release_reserved=True,
            )
        restored_load = _create_recovered_ready_load(
            load, reconciliation, profile, session, event_token,
            transfer_stock_entry=correction.name,
            transfer_stock_entry_detail=correction_row.name,
            source_confirmation_ledger=(
                source_resolution_ledger.name if source_resolution_ledger else None
            ),
        )
        physical_state = "Ready"
        evidence = (
            f"Bin still holds exact {load.actual_qty} {load.stock_uom} {load.item_code}; "
            f"submitted correction {correction.name} restored ERP stock to "
            f"{load.wip_warehouse}; recovered as Load {restored_load.name}"
        )

    timestamp = now_datetime()
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin,
        {"wip_bin_state": physical_state, "last_reconciled_on": timestamp},
        update_modified=False,
    )
    reconciliation.db_set({
        "status": "Resolved", "decision": decision,
        "correction_stock_entry": correction.name if correction else None,
        "restored_load": restored_load.name if restored_load else None,
        "source_resolution_ledger": (
            source_resolution_ledger.name if source_resolution_ledger else None
        ),
        "resolved_on": timestamp, "resolved_by_operator": profile.employee,
        "operator_session": session.name, "terminal_user": session.terminal_user,
        "reason": reason, "resolution_notes": evidence,
    }, update_modified=True)
    _release_reconciled_cycle_hold(reconciliation)
    load.db_set(
        "notes", f"{load.notes or ''}\nResolved by {reconciliation.name}: {evidence}".strip(),
        update_modified=True,
    )
    if reconciliation.exception:
        frappe.db.set_value("CFG Kanban Exception", reconciliation.exception, {
            "status": "Resolved", "resolved_on": timestamp,
            "resolved_by": session.terminal_user,
            "resolution": f"{decision}. {reason}. {evidence}",
        }, update_modified=True)
    record(
        "WIP Bin Reconciliation Resolved", card=frappe.db.get_value(
            "CFG Kanban Cycle", load.kanban_cycle, "kanban_card"
        ), cycle=load.kanban_cycle, execution=load.process_execution,
        handling_unit=load.reusable_bin, qty=load.actual_qty,
        reference_doctype="CFG Kanban WIP Bin Reconciliation",
        reference_name=reconciliation.name, operator=profile.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        previous_state="Exception", new_state=physical_state,
        notes=f"{decision}; {reason}; {evidence}",
    )
    return _reconciliation_result(frappe.get_doc(
        "CFG Kanban WIP Bin Reconciliation", reconciliation.name
    ))


def _create_consumption_reconciliation(load, cancelled_entry):
    return _create_stock_entry_reconciliation(load, cancelled_entry, "consumption")


def _create_transfer_reconciliation(load, cancelled_entry):
    return _create_stock_entry_reconciliation(load, cancelled_entry, "transfer")


def _create_stock_entry_reconciliation(load, cancelled_entry, direction):
    existing = frappe.db.get_value(
        "CFG Kanban WIP Bin Reconciliation", {"wip_bin_load": load.name}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Kanban WIP Bin Reconciliation", existing)
    timestamp = now_datetime()
    cycle = frappe.get_doc("CFG Kanban Cycle", load.kanban_cycle)
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card) if cycle.kanban_card else None
    source_hold = None
    if direction == "transfer" and load.source_handling_unit:
        source_hold = post_quantity_event(
            event_type="Reserve", qty=load.actual_qty, stock_uom=load.stock_uom,
            idempotency_key=f"wip-bin-source-cancel-hold:{load.name}:{cancelled_entry.name}",
            source_handling_unit=load.source_handling_unit,
            item_code=load.item_code, batch_no=load.batch_no,
            source_company=load.company, source_warehouse=load.source_warehouse,
            reference_doctype="Stock Entry", reference_name=cancelled_entry.name,
            reason=(
                f"Safety hold while cancelled transfer for WIP Bin {load.reusable_bin} "
                "awaits physical reconciliation"
            ),
        )
    context = "Transfer Cancellation" if direction == "transfer" else "Consumption Cancellation"
    reconciliation = frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Reconciliation",
        "status": "Open", "reversal_context": context,
        "wip_bin_load": load.name,
        "reusable_bin": load.reusable_bin, "company": load.company,
        "source_handling_unit": load.source_handling_unit,
        "item_code": load.item_code, "batch_no": load.batch_no,
        "qty": load.actual_qty, "stock_uom": load.stock_uom,
        "kanban_cycle": load.kanban_cycle, "work_order": load.work_order,
        "job_card": load.job_card, "process_execution": load.process_execution,
        "operation": load.operation, "workstation": load.workstation,
        "previous_cycle_status": cycle.status,
        "previous_cycle_blocked": cint(cycle.get("blocked")),
        "previous_card_blocked": cint(card.get("blocked")) if card else 0,
        "previous_card_blocked_reason": card.get("blocked_reason") if card else None,
        "cancelled_stock_entry": cancelled_entry.name,
        "source_hold_ledger": source_hold.name if source_hold else None,
        "raised_on": timestamp, "raised_by_system": 1,
    }).insert(ignore_permissions=True)
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": (
            "WIP Bin Transfer Reversal" if direction == "transfer"
            else "WIP Bin Consumption Reversal"
        ),
        "severity": "Critical", "status": "Open",
        "kanban_cycle": load.kanban_cycle,
        "kanban_card": frappe.db.get_value(
            "CFG Kanban Cycle", load.kanban_cycle, "kanban_card"
        ),
        "process_execution": load.process_execution,
        "handling_unit": load.reusable_bin,
        "message": (
            f"Submitted {direction} {cancelled_entry.name} was cancelled. WIP Bin "
            f"{load.reusable_bin} is blocked until a Supervisor verifies the exact physical "
            "material state."
        ),
        "reference_doctype": "CFG Kanban WIP Bin Reconciliation",
        "reference_name": reconciliation.name, "raised_on": timestamp,
    }).insert(ignore_permissions=True)
    reconciliation.db_set("exception", exception.name, update_modified=False)
    record(
        "WIP Bin Reconciliation Required", cycle=load.kanban_cycle,
        execution=load.process_execution, handling_unit=load.reusable_bin,
        qty=load.actual_qty,
        reference_doctype="CFG Kanban WIP Bin Reconciliation",
        reference_name=reconciliation.name,
        previous_state="Ready" if direction == "transfer" else "Consumed",
        new_state="Exception",
        notes=f"Cancelled {direction} {cancelled_entry.name}; Exception {exception.name}",
    )
    return reconciliation


def _authorize_reconciliation(load, operator_session_token, kanban_card):
    from cfg_kanban.services.operator_auth import require_operator

    profile, session = require_operator(
        operator_session_token, action="override",
        operation=load.operation, workstation=load.workstation,
    )
    if profile.kanban_role not in ("Supervisor", "Development Proxy"):
        frappe.throw("A Kanban Supervisor with Override permission must resolve this WIP Bin")
    card = frappe.get_doc("CFG Kanban Card", kanban_card)
    if not card.active_cycle:
        frappe.throw("Scan the active production or operation Card for this WIP Bin")
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle)
    if cycle.work_order != load.work_order:
        frappe.throw("The scanned Card does not control this WIP Bin Work Order")
    if cycle.name != load.kanban_cycle and cycle.selected_job_card != load.job_card:
        frappe.throw("The scanned operation Card does not control this WIP Bin Job Card")
    return profile, session


def _create_recovered_ready_load(load, reconciliation, profile, session, event_token,
                                 transfer_stock_entry=None,
                                 transfer_stock_entry_detail=None,
                                 source_confirmation_ledger=None):
    key = event_token or f"wip-bin-recovery:{reconciliation.name}"
    existing = frappe.db.get_value(
        "CFG Kanban WIP Bin Load", {"idempotency_key": key}, "name"
    )
    if existing:
        recovered = frappe.get_doc("CFG Kanban WIP Bin Load", existing)
        if recovered.recovery_reconciliation != reconciliation.name:
            frappe.throw("This reconciliation token belongs to another WIP Bin recovery")
        return recovered
    return frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Load", "status": "Ready",
        "reusable_bin": load.reusable_bin, "wip_bin_pool": load.wip_bin_pool,
        "company": load.company, "item_code": load.item_code,
        "batch_no": load.batch_no, "standard_qty": load.standard_qty,
        "actual_qty": load.actual_qty, "stock_uom": load.stock_uom,
        "partial_exception": load.partial_exception,
        "exception_reason": load.exception_reason,
        "approved_by": load.approved_by,
        "approved_by_operator": load.approved_by_operator,
        "exception_approved_on": load.exception_approved_on,
        "kanban_master": load.kanban_master, "kanban_cycle": load.kanban_cycle,
        "work_order": load.work_order, "job_card": load.job_card,
        "process_execution": load.process_execution, "operation": load.operation,
        "workstation": load.workstation,
        "source_handling_unit": load.source_handling_unit,
        "source_warehouse": load.source_warehouse,
        "wip_warehouse": load.wip_warehouse,
        "source_confirmation_ledger": (
            source_confirmation_ledger or load.source_confirmation_ledger
        ),
        "transfer_stock_entry": transfer_stock_entry,
        "transfer_stock_entry_detail": transfer_stock_entry_detail,
        "recovery_of_load": load.name,
        "recovery_reconciliation": reconciliation.name,
        "idempotency_key": key, "reserved_on": now_datetime(),
        "reserved_by_operator": profile.employee,
        "operator_session": session.name, "ready_on": now_datetime(),
        "notes": (
            f"Exact physical material recovered after "
            f"{reconciliation.reversal_context or 'ERP cancellation'} "
            f"{reconciliation.cancelled_stock_entry}; recovered from {load.name}"
        ),
    }).insert(ignore_permissions=True)


def _reconciliation_decisions(context):
    if not context or context == "Consumption Cancellation":
        return ("Material Restored to Bin", "Bin Empty after ERP Correction")
    if context == "Transfer Cancellation":
        return ("Material Returned to Source", "Material Remains in WIP after ERP Correction")
    return ()


def _verify_source_handling_unit_scan(load, scan_value):
    if not load.source_handling_unit:
        if scan_value:
            frappe.throw("This transfer used ERP-only source stock; do not scan a source tag")
        return
    identity = resolve_logistics_scan(scan_value)
    if (not identity or identity.get("identity_type") != "Handling Unit"
            or identity.get("name") != load.source_handling_unit):
        frappe.throw(
            f"Scan original Source Stock Tag {load.source_handling_unit} after returning "
            "the material"
        )


def _validate_transfer_recovery_correction(load, reconciliation, correction_stock_entry):
    if not correction_stock_entry:
        frappe.throw(
            "Select the submitted ERPNext correction before keeping material in the WIP Bin"
        )
    if correction_stock_entry == reconciliation.cancelled_stock_entry:
        frappe.throw("The cancelled transfer cannot be used as its own ERP correction")
    entry = frappe.get_doc("Stock Entry", correction_stock_entry)
    if entry.docstatus != 1 or _purpose(entry) != TRANSFER_PURPOSE:
        frappe.throw("WIP recovery requires a submitted Material Transfer for Manufacture")
    if entry.company != load.company:
        frappe.throw("ERP correction Company does not match the WIP Bin Load")
    if entry.work_order != load.work_order or (
            entry.get("job_card") and entry.job_card != load.job_card):
        frappe.throw("ERP correction must belong to the same Work Order and Job Card")
    if get_datetime(entry.creation) < get_datetime(reconciliation.creation):
        frappe.throw("ERP correction must be created after the WIP Bin reconciliation was raised")
    from cfg_kanban.services.production_trace import _tag_batch_no
    used_rows = set(frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"transfer_stock_entry": entry.name, "recovery_reconciliation": ["is", "set"]},
        pluck="transfer_stock_entry_detail",
    ))
    candidates = [
        row for row in entry.items
        if row.name not in used_rows
        and row.item_code == load.item_code
        and row.s_warehouse == load.source_warehouse
        and row.t_warehouse == load.wip_warehouse
        and row.stock_uom == load.stock_uom
        and (_tag_batch_no(row) or "") == (load.batch_no or "")
        and abs(_row_stock_qty(row) - flt(load.actual_qty)) <= TOLERANCE
    ]
    if len(candidates) != 1:
        frappe.throw(
            f"Submitted correction must contain one unused row moving exactly "
            f"{load.actual_qty} {load.stock_uom} of {load.item_code} from "
            f"{load.source_warehouse} to {load.wip_warehouse}; matching rows: "
            f"{len(candidates)}"
        )
    return entry, candidates[0]


def _validate_empty_bin_correction(load, reconciliation, correction_stock_entry):
    if not correction_stock_entry:
        frappe.throw("Select the submitted ERPNext correction before declaring the bin Empty")
    if correction_stock_entry == reconciliation.cancelled_stock_entry:
        frappe.throw("The cancelled consumption cannot be used as its own ERP correction")
    entry = frappe.get_doc("Stock Entry", correction_stock_entry)
    if entry.docstatus != 1:
        frappe.throw("WIP Bin correction Stock Entry must be submitted")
    if entry.company != load.company:
        frappe.throw("ERP correction Company does not match the WIP Bin Load")
    if get_datetime(entry.creation) < get_datetime(reconciliation.creation):
        frappe.throw("ERP correction must be created after the WIP Bin reconciliation was raised")
    from cfg_kanban.services.production_trace import _tag_batch_no
    matching_qty = sum(
        _row_stock_qty(row) for row in entry.items
        if row.item_code == load.item_code
        and row.s_warehouse == load.wip_warehouse
        and row.stock_uom == load.stock_uom
        and (_tag_batch_no(row) or "") == (load.batch_no or "")
    )
    if abs(flt(matching_qty) - flt(load.actual_qty)) > TOLERANCE:
        frappe.throw(
            f"Submitted correction must remove exactly {load.actual_qty} {load.stock_uom} "
            f"of {load.item_code} from {load.wip_warehouse}; matching quantity is "
            f"{matching_qty}"
        )
    return entry


def _release_reconciled_cycle_hold(reconciliation):
    """Restore only the generic cancellation hold after every physical bin is reconciled."""
    if frappe.db.exists("CFG Kanban WIP Bin Reconciliation", {
        "kanban_cycle": reconciliation.kanban_cycle,
        "status": "Open",
        "name": ["!=", reconciliation.name],
    }):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", reconciliation.kanban_cycle)
    card = (frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
            if cycle.kanban_card else None)
    if cycle.status == "Blocked" and cint(cycle.get("blocked")):
        cycle.db_set({
            "status": reconciliation.previous_cycle_status or "In Production",
            "blocked": cint(reconciliation.previous_cycle_blocked),
        }, update_modified=True)
    if (card and cint(card.get("blocked"))
            and (card.get("blocked_reason") or "") == "Stock Entry Cancelled"):
        card.db_set({
            "blocked": cint(reconciliation.previous_card_blocked),
            "blocked_reason": reconciliation.previous_card_blocked_reason,
        }, update_modified=True)


def _reconciliation_result(reconciliation):
    return {
        "reconciliation": reconciliation.name, "status": reconciliation.status,
        "reversal_context": reconciliation.reversal_context,
        "decision": reconciliation.decision,
        "wip_bin_load": reconciliation.wip_bin_load,
        "reusable_bin": reconciliation.reusable_bin,
        "restored_load": reconciliation.restored_load,
        "correction_stock_entry": reconciliation.correction_stock_entry,
        "source_resolution_ledger": reconciliation.source_resolution_ledger,
    }


def _lock_reconciliation(name):
    frappe.db.sql(
        "select name from `tabCFG Kanban WIP Bin Reconciliation` where name=%s for update",
        name,
    )
    if not frappe.db.exists("CFG Kanban WIP Bin Reconciliation", name):
        frappe.throw("WIP Bin reconciliation was not found")


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
    purpose_values = frappe.db.get_value(
        "Stock Entry", stock_entry, ["purpose", "stock_entry_type"], as_dict=True
    ) or {}
    purpose = purpose_values.get("purpose") or purpose_values.get("stock_entry_type")
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
    # ``purpose`` is ERPNext's canonical transaction behaviour. ``stock_entry_type``
    # may be a customized label and must not turn a consumption into a transfer flow.
    return doc.get("purpose") or doc.get("stock_entry_type")


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


def _consumption_row_for_ready_bin(entry, scan_value):
    """Resolve a scanned Ready WIP Bin to one unambiguous ERP consumption row."""
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan a Ready Standard Quantity WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != "Standard Quantity WIP Bin"):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a Standard Quantity WIP Bin")

    entry_job_card = entry.get("cfg_kanban_job_card") or entry.get("job_card")
    summaries = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"reusable_bin": unit.name,
         "status": ["in", ["Ready", "Consumption Draft"]]},
        ["name", "status", "wip_bin_pool", "kanban_cycle", "work_order",
         "job_card", "item_code", "batch_no", "wip_warehouse", "stock_uom",
         "consumption_stock_entry", "consumption_stock_entry_detail"],
        order_by="creation desc",
    )
    matches = []
    for load in summaries:
        if (load.kanban_cycle != entry.get("cfg_kanban_cycle")
                or load.work_order != entry.work_order
                or (entry_job_card and load.job_card != entry_job_card)):
            continue
        if (load.status == "Consumption Draft"
                and load.consumption_stock_entry != entry.name):
            continue
        for row in entry.items:
            context = entry_wip_bin_rule(entry, row)
            if not context or context.get("wip_bin_pool") != load.wip_bin_pool:
                continue
            if (row.item_code != load.item_code
                    or row.s_warehouse != load.wip_warehouse
                    or row.stock_uom != load.stock_uom
                    or (row.get("batch_no") or "") != (load.batch_no or "")):
                continue
            if (load.status == "Consumption Draft"
                    and load.consumption_stock_entry_detail != row.name):
                continue
            matches.append((load.name, row.name))

    unique_rows = {row_name for _load_name, row_name in matches}
    if not matches:
        frappe.throw(
            f"Ready WIP Bin {unit.handling_unit_id} does not match any pending Item, "
            "WIP Warehouse, UOM, Batch, Cycle, or Job Card row in this consumption"
        )
    if len(unique_rows) != 1:
        frappe.throw(
            f"Ready WIP Bin {unit.handling_unit_id} matches multiple ERP rows. "
            "Separate the rows by Batch or correct the Draft consumption before scanning."
        )
    return _entry_row(entry, next(iter(unique_rows)))


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
    readiness = manufacture_receipt_wip_bin_readiness(work_order, cycle_name)
    if not readiness["ready"]:
        frappe.throw(readiness["reason"])


def manufacture_receipt_wip_bin_readiness(work_order, cycle_name=None):
    """Return the physical-bin gate that must be clear before final manufacture.

    A submitted transfer proves that material reached WIP; it does not prove consumption.
    Keeping this as a separate, reusable readiness result lets the operator panel prevent a
    premature Manufacture draft instead of allowing ERPNext to show the same inputs again.
    """
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
        return {
            "ready": False,
            "reason": (
                "Consume and submit the Ready WIP Bin material before preparing the "
                f"Manufacture receipt. Active bin load(s): {detail}"
            ),
            "active_loads": active,
        }
    return {"ready": True, "reason": None, "active_loads": []}


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
        "item_code": row.item_code,
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

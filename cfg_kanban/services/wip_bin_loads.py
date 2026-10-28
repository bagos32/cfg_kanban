"""Controlled load episodes for fixed-quantity reusable WIP bins.

This service deliberately follows native ERPNext Stock Entry state. A Draft entry may reserve a
physical bin, but it never makes material Ready or Consumed. Those states are confirmed only from
the Stock Entry submit hook.
"""

from types import MethodType

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


TOLERANCE = 0.000001
TRANSFER_PURPOSE = "Material Transfer for Manufacture"
CONSUMPTION_PURPOSES = ("Material Consumption for Manufacture", "Manufacture")
ACTIVE_LOAD_STATUSES = (
    "Transfer Draft", "Ready", "In Use", "Consumption Pending ERP",
    "Consumption Draft", "Return Draft",
)
JOB_CARD_SUBMIT_BLOCK_STATUSES = ("Transfer Draft",)
OPERATION_CLOSE_BLOCK_STATUSES = (
    "Transfer Draft", "Ready", "In Use", "Return Draft",
)


def enable_operation_scoped_consumption_validation(entry):
    """Replace ERPNext's route-wide operation check for one controlled WIP-bin entry.

    ERPNext v15 treats ``fg_completed_qty`` on Material Consumption for Manufacture as if every
    Work Order operation must already have completed that quantity. That rule is correct for a
    Work Order-wide consumption entry, but it deadlocks an operation-owned WIP-bin entry: Cooking
    cannot post its own consumption until downstream Moulding is complete.

    CFG Kanban narrows only this one validation for entries carrying its audited Job Card link.
    The owning Job Card must already be submitted and completed for the required quantity. No
    downstream Job Card is consulted. All other native Stock Entry validation and submission
    behaviour remains in force.
    """
    if (entry.doctype != "Stock Entry"
            or _purpose(entry) != "Material Consumption for Manufacture"
            or not entry.get("cfg_kanban_controlled")
            or not entry.get("cfg_kanban_job_card")
            or not entry.get("work_order")):
        return entry

    def _validate_owning_operation(doc):
        job = frappe.get_doc("Job Card", doc.cfg_kanban_job_card)
        if job.work_order != doc.work_order or job.docstatus == 2:
            frappe.throw(
                f"Job Card {job.name} does not belong to Work Order {doc.work_order}"
            )
        if job.docstatus != 1 or job.status != "Completed":
            frappe.throw(
                f"Complete Job Card {job.name} before posting its WIP-bin consumption"
            )
        work_order = frappe.get_doc("Work Order", doc.work_order)
        required_qty = flt(doc.fg_completed_qty) + flt(work_order.produced_qty)
        completed_qty = flt(job.total_completed_qty)
        if completed_qty + TOLERANCE < required_qty:
            frappe.throw(
                f"Job Card {job.name} has completed {completed_qty} of {required_qty}; "
                "post the owning operation progress before consuming its WIP Bin"
            )

    object.__setattr__(
        entry,
        "check_if_operations_completed",
        MethodType(_validate_owning_operation, entry),
    )
    return entry


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
    """Return whether an operation Card may close its WIP-bin responsibility.

    Runtime operation Cards may complete in smaller allocations than the ERP Job Card. This gate
    deliberately uses Job Card scope because a WIP Bin Load is not divisible between runtime
    cards. Once physical use is recorded or an operation-owned consumption Draft exists, it does
    not block operation closure or release of the next operation. ERP posting remains the owning
    operation's separate audited responsibility, and the final Manufacture receipt retains the
    stricter all-bins-consumed gate.
    """
    if not job_card:
        return {
            "ready": True, "reason": None, "active_loads": [],
            "pending_erp_entries": [], "reconciliations": [],
        }
    reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        {"job_card": job_card, "status": "Open"},
        ["name", "reusable_bin", "reversal_context"],
        order_by="raised_on asc", limit_page_length=6,
    )
    active = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"job_card": job_card, "status": ["in", list(ACTIVE_LOAD_STATUSES)]},
        ["name", "reusable_bin", "status", "bin_mode", "consumption_stock_entry"],
        order_by="creation asc", limit_page_length=0,
    )
    blocking = [
        row for row in active
        if row.status in OPERATION_CLOSE_BLOCK_STATUSES
        and (row.bin_mode or "Standard Quantity") != "Loose Multi-Item"
    ]
    pending_use = [row for row in active if row.status == "Consumption Pending ERP"]
    pending = [row for row in active if row.status == "Consumption Draft"]
    pending_entry_names = list(dict.fromkeys(
        row.consumption_stock_entry for row in pending if row.consumption_stock_entry
    ))
    pending_entries = frappe.get_all(
        "Stock Entry",
        {"name": ["in", pending_entry_names or ["__none__"]], "docstatus": 0,
         "purpose": "Material Consumption for Manufacture"},
        ["name", "purpose", "docstatus"], limit_page_length=0,
    )
    valid_pending_names = {row.name for row in pending_entries}
    broken_pending = [
        row for row in pending
        if not row.consumption_stock_entry
        or row.consumption_stock_entry not in valid_pending_names
    ]
    if broken_pending:
        blocking.extend(broken_pending)
    if reconciliations:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.reversal_context or 'Cancellation'})"
            for row in reconciliations[:5]
        )
        return {
            "ready": False,
            "reason": (
                f"Cannot close the Operation Cycle while Job Card {job_card} has an open WIP Bin "
                f"supervisor reconciliation: {detail}"
            ),
            "active_loads": active,
            "pending_erp_entries": pending_entries,
            "reconciliations": reconciliations,
        }
    if blocking:
        detail = ", ".join(
            f"{row.reusable_bin} ({row.status})" for row in blocking[:5]
        )
        return {
            "ready": False,
            "reason": (
                "Record physical use for every Ready WIP Bin, or resolve "
                f"the remaining material movement before closing this Operation Cycle. "
                f"Blocking bin load(s): {detail}"
            ),
            "active_loads": active,
            "pending_erp_entries": pending_entries,
            "reconciliations": reconciliations,
        }
    pending_reason = None
    if pending_use:
        pending_reason = (
            "Operation use is fully scanned. ERP posting remains pending for WIP Bin Load(s) "
            + ", ".join(row.name for row in pending_use)
            + "; the WIP bin stays locked until ERPNext accepts the later consumption entry."
        )
    elif pending_entries:
        pending_reason = (
            "Operation use is fully scanned. ERP posting remains pending in "
            + ", ".join(row.name for row in pending_entries)
            + "; the WIP bin stays locked until ERPNext accepts the entry."
        )
    return {
        "ready": True, "reason": pending_reason, "active_loads": active,
        "pending_erp_entries": pending_entries, "pending_wip_loads": pending_use,
        "reconciliations": reconciliations,
    }


def abandon_draft_stock_entry(doc, method=None):
    """Release physical-bin intent when an ERP Draft is deleted before submission."""
    if doc.docstatus != 0:
        return
    from cfg_kanban.services.loose_wip import abandon_consumption_draft
    abandon_consumption_draft(doc.name)
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
            "consumption_stock_entry_detail": None, "consumed_qty": 0,
            "return_qty": 0, "consumption_reason": None,
            "consumption_reported_by": None, "consumption_reported_on": None,
            "in_use_on": None,
            "notes": f"ERP Draft {doc.name} deleted; physical WIP Bin restored to Ready",
        }, update_modified=True)
        _refresh_wip_bin_state(load.reusable_bin)
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
        frappe.throw(f"Item {row.item_code} is not configured for a controlled WIP Bin")
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
    bin_unit = _resolve_reusable_bin(reusable_bin_scan, context, entry, row)
    _lock_reusable_bin(bin_unit.name)
    loose_mode = context.get("bin_mode") == "Loose Multi-Item"
    standard_qty = (
        remaining if loose_mode else wip_bin_full_qty(
            bin_unit.name, row.item_code, row.stock_uom, context["standard_bin_qty"]
        )
    )
    explicit_qty = actual_qty not in (None, "")
    requested_qty = flt(actual_qty)
    if explicit_qty and requested_qty <= TOLERANCE:
        frappe.throw("Partial WIP Bin quantity must be greater than zero")
    qty = requested_qty if explicit_qty else standard_qty
    partial_exception = (not loose_mode and abs(qty - standard_qty) > TOLERANCE)
    exception_reason = (exception_reason or "").strip()
    if not loose_mode and qty > standard_qty + TOLERANCE:
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
            reason=(f"Reserved for {'loose' if loose_mode else 'fixed'} WIP Bin "
                    f"{bin_unit.handling_unit_id}"),
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
            notes=(f"Physical-bin capacity {standard_qty} {row.stock_uom}; actual {qty} "
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
    _refresh_wip_bin_state(load.reusable_bin)
    return {"load": load.name, "status": "Cancelled", "stock_entry": entry.name}


@frappe.whitelist()
def allocate_consumption_bin(stock_entry, item_row=None, reusable_bin_scan=None,
                             operator_session_token=None, kanban_card=None,
                             event_token=None, actual_qty=None,
                             exception_reason=None):
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
    consumed_qty = flt(actual_qty) if actual_qty not in (None, "") else flt(load.actual_qty)
    if consumed_qty <= 0:
        frappe.throw("Actual WIP Bin consumption must be positive")
    if consumed_qty > flt(load.actual_qty) + TOLERANCE:
        frappe.throw(
            f"Actual consumption {consumed_qty} exceeds the prepared WIP Bin quantity "
            f"{load.actual_qty} {load.stock_uom}"
        )
    if consumed_qty > remaining + TOLERANCE:
        frappe.throw(
            f"Ready WIP Bin consumption {consumed_qty} {load.stock_uom} "
            f"but the selected ERP row has only {remaining} remaining"
        )
    profile, session = actor
    reason = (exception_reason or "").strip()
    partial = consumed_qty < flt(load.actual_qty) - TOLERANCE
    if partial and not reason:
        frappe.throw("Enter why actual consumption is lower than the prepared WIP Bin quantity")
    if partial and context["require_full_bin_consumption"]:
        if not context["allow_supervisor_partial_exception"]:
            frappe.throw(
                "This WIP Bin Pool requires full-bin consumption and does not allow a "
                "supervisor partial-consumption exception"
            )
        if not _actor_can_approve_partial_consumption(profile):
            frappe.throw(
                "Switch to a Supervisor QR with Override permission before reporting "
                "partial consumption for this WIP Bin Pool"
            )
    bound = bind_consumption_draft(
        load.name, entry.name, row.name, consumed_qty=consumed_qty,
        consumption_reason=reason, reported_by=profile.employee,
    )
    bound.db_set("in_use_on", now_datetime(), update_modified=False)
    record(
        "WIP Bin Consumption Draft Bound", card=frappe.db.get_value(
            "CFG Kanban Cycle", bound.kanban_cycle, "kanban_card"
        ), cycle=bound.kanban_cycle, execution=bound.process_execution,
        handling_unit=bound.reusable_bin, qty=bound.consumed_qty,
        reference_doctype="Stock Entry", reference_name=entry.name,
        operator=profile.employee, operator_session=session.name,
        notes=(f"WIP Bin Load {bound.name}; prepared {bound.actual_qty}; "
               f"actual consumed {bound.consumed_qty}; return {bound.return_qty}; "
               f"ERP Draft only; token {event_token or '-'}"),
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
        "consumed_qty": 0,
        "return_qty": 0,
        "consumption_reason": None,
        "consumption_reported_by": None,
        "consumption_reported_on": None,
        "in_use_on": None,
        "notes": "Removed from Draft consumption; physical WIP Bin restored to Ready",
    }, update_modified=True)
    _refresh_wip_bin_state(load.reusable_bin)
    record(
        "WIP Bin Consumption Draft Released", cycle=load.kanban_cycle,
        execution=load.process_execution, handling_unit=load.reusable_bin,
        qty=load.actual_qty, reference_doctype="Stock Entry", reference_name=entry_name,
        operator=profile.employee, operator_session=session.name,
        notes=f"WIP Bin Load {load.name} restored to Ready",
    )
    return {"load": load.name, "status": "Ready", "stock_entry": entry_name}


def record_pending_consumption(*, kanban_cycle, work_order, job_card,
                               reusable_bin_scan, actual_qty=None,
                               consumption_reason=None, operator=None,
                               operator_session=None, event_token=None,
                               profile=None):
    """Record physical WIP-bin use before the owning Job Card is complete.

    The operator may scan actual use while the operation is running. Once that same Job Card is
    submitted and complete, CFG Kanban creates its operation-owned native consumption entry. A
    downstream operation is never part of this readiness decision.
    """
    identity = resolve_logistics_scan(reusable_bin_scan)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan a Ready Standard Quantity WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != "Standard Quantity WIP Bin"):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a Standard Quantity WIP Bin")
    candidates = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"reusable_bin": unit.name, "kanban_cycle": kanban_cycle,
         "work_order": work_order, "job_card": job_card,
         "status": ["in", ["Ready", "Consumption Pending ERP"]]},
        ["name", "status"], order_by="creation desc", limit_page_length=2,
    )
    if not candidates:
        frappe.throw(
            f"WIP Bin {unit.handling_unit_id} is not Ready for this Cycle and Job Card"
        )
    _lock_load(candidates[0].name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", candidates[0].name)
    if load.status == "Consumption Pending ERP":
        return _pending_consumption_result(load, duplicate=True)
    if unit.wip_bin_state != "Ready":
        frappe.throw(f"WIP Bin {unit.handling_unit_id} is {unit.wip_bin_state}, not Ready")
    consumed = flt(actual_qty) if actual_qty not in (None, "", 0, "0") else flt(load.actual_qty)
    if consumed <= 0 or consumed > flt(load.actual_qty) + TOLERANCE:
        frappe.throw(
            f"Actual consumption must be above zero and no more than the prepared "
            f"{load.actual_qty} {load.stock_uom}"
        )
    reason = (consumption_reason or "").strip()
    partial = consumed < flt(load.actual_qty) - TOLERANCE
    pool = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool", load.wip_bin_pool,
        ["require_full_bin_consumption", "allow_supervisor_partial_exception"],
        as_dict=True,
    ) or {}
    if partial and not reason:
        frappe.throw("Enter why actual consumption is lower than the prepared WIP Bin quantity")
    if partial and cint(pool.get("require_full_bin_consumption")):
        if not cint(pool.get("allow_supervisor_partial_exception")):
            frappe.throw(
                "This WIP Bin Pool requires full-bin consumption and does not allow a "
                "supervisor partial-consumption exception"
            )
        if not profile or not _actor_can_approve_partial_consumption(profile):
            frappe.throw(
                "Switch to a Supervisor QR with Override permission before reporting "
                "partial consumption for this WIP Bin Pool"
            )
    returned = max(flt(load.actual_qty) - consumed, 0)
    load.db_set({
        "status": "Consumption Pending ERP",
        "consumed_qty": consumed,
        "return_qty": returned,
        "consumption_reason": reason or None,
        "consumption_reported_by": operator,
        "consumption_reported_on": now_datetime(),
        "in_use_on": now_datetime(),
        "notes": (
            f"Physical operation use recorded before ERP posting; prepared {load.actual_qty}; "
            f"consume {consumed}; return {returned}; token {event_token or '-'}"
        ),
    }, update_modified=True)
    _refresh_wip_bin_state(load.reusable_bin)
    card = frappe.db.get_value("CFG Kanban Cycle", load.kanban_cycle, "kanban_card")
    record(
        "WIP Bin Physical Use Recorded", card=card, cycle=load.kanban_cycle,
        execution=load.process_execution, handling_unit=load.reusable_bin,
        qty=consumed, reference_doctype="CFG Kanban WIP Bin Load",
        reference_name=load.name, operator=operator, operator_session=operator_session,
        notes=(f"Job Card {load.job_card}; prepared {load.actual_qty}; consume {consumed}; "
               f"return {returned}; ERP posting deferred until Work Order route completion"),
    )
    return _pending_consumption_result(
        frappe.get_doc("CFG Kanban WIP Bin Load", load.name), duplicate=False
    )


def cancel_pending_consumption(load_name, *, operator=None, operator_session=None):
    """Restore an unposted physical-use record to Ready under operator control."""
    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    if load.status != "Consumption Pending ERP" or load.consumption_stock_entry:
        frappe.throw("Only WIP Bin use awaiting ERP posting can be cancelled here")
    load.db_set({
        "status": "Ready", "consumed_qty": 0, "return_qty": 0,
        "consumption_reason": None, "consumption_reported_by": None,
        "consumption_reported_on": None, "in_use_on": None,
        "notes": "Unposted physical-use record cancelled; WIP Bin restored to Ready",
    }, update_modified=True)
    _refresh_wip_bin_state(load.reusable_bin)
    record(
        "WIP Bin Physical Use Cancelled", cycle=load.kanban_cycle,
        execution=load.process_execution, handling_unit=load.reusable_bin,
        qty=load.actual_qty, reference_doctype="CFG Kanban WIP Bin Load",
        reference_name=load.name, operator=operator, operator_session=operator_session,
        notes=f"Job Card {load.job_card}; restored to Ready before ERP posting",
    )
    return _pending_consumption_result(
        frappe.get_doc("CFG Kanban WIP Bin Load", load.name), duplicate=False
    )


def entry_wip_bin_rule(entry, row):
    """Return the exact Master/Job Card context for either controlled WIP-bin mode."""
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
        "wip_presentation_method": ["in", [
            "Standard Quantity Reusable WIP Bin", "Loose Multi-Item WIP Bin",
        ]],
    }, ["wip_bin_pool", "standard_bin_qty", "stock_uom",
        "wip_presentation_method"], as_dict=True)
    if not rule:
        return None
    pool = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool", rule.wip_bin_pool,
        ["pool_mode", "loose_consumption_policy", "require_full_bin_consumption",
         "allow_supervisor_partial_exception"],
        as_dict=True,
    ) or {}
    return {
        "kanban_cycle": cycle.name, "kanban_master": cycle.kanban_master,
        "work_order": entry.work_order, "item_code": row.item_code,
        "job_card": job.name, "operation": job.operation,
        "workstation": job.workstation, "wip_bin_pool": rule.wip_bin_pool,
        "presentation_method": rule.wip_presentation_method,
        "bin_mode": pool.get("pool_mode") or "Standard Quantity",
        "loose_consumption_policy": pool.get("loose_consumption_policy"),
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
         "status": ["in", ["Consumption Draft", "Return Draft", "Consumed"]]},
        ["name", "status", "reusable_bin", "actual_qty", "consumed_qty",
         "return_qty", "consumption_reason", "stock_uom",
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
        ["company", "pool_mode", "wip_warehouse"], as_dict=True,
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
    bin_mode = pool.pool_mode or "Standard Quantity"
    context = {
        "wip_bin_pool": rule.wip_bin_pool, "bin_mode": bin_mode,
        "work_order": entry.work_order, "job_card": job.name,
        "operation": job.operation, "workstation": job.workstation,
        "item_code": item_code,
    }
    _assert_reusable_bin(
        bin_unit, context, entry.company, row.t_warehouse,
    )
    standard_qty = (
        qty if bin_mode == "Loose Multi-Item" else
        wip_bin_full_qty(bin_unit.name, item_code, row.stock_uom, rule.standard_bin_qty)
    )
    if bin_mode == "Standard Quantity" and qty > standard_qty + TOLERANCE:
        frappe.throw(
            f"WIP Bin {bin_unit.handling_unit_id} cannot exceed its Item-specific Full-bin "
            f"Capacity of {standard_qty} {row.stock_uom}"
        )

    load = frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Load",
        "status": "Transfer Draft",
        "bin_mode": bin_mode,
        "reusable_bin": reusable_bin,
        "wip_bin_pool": rule.wip_bin_pool,
        "company": entry.company,
        "item_code": item_code,
        "batch_no": batch_no or row.get("batch_no"),
        "standard_qty": standard_qty,
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
    _refresh_wip_bin_state(reusable_bin)
    record(
        "WIP Bin Load Reserved", card=cycle.kanban_card, cycle=cycle.name,
        execution=process_execution, handling_unit=reusable_bin, qty=qty,
        reference_doctype="CFG Kanban WIP Bin Load", reference_name=load.name,
        operator=operator, operator_session=operator_session,
        notes=f"{item_code} / {row.s_warehouse} -> {row.t_warehouse}; ERP Draft {entry.name}",
    )
    return load, True


def bind_consumption_draft(load_name, stock_entry, stock_entry_detail,
                           consumed_qty=None, consumption_reason=None,
                           reported_by=None):
    """Bind a Ready/In-Use load to a Draft ERP consumption row without consuming it."""
    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    if load.status not in ("Ready", "In Use", "Consumption Pending ERP"):
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
    was_pending = load.status == "Consumption Pending ERP"
    consumed = (flt(load.consumed_qty) if was_pending else
                flt(consumed_qty) if consumed_qty not in (None, "") else flt(load.actual_qty))
    returned = max(flt(load.actual_qty) - consumed, 0)
    load.db_set({
        "status": "Consumption Draft",
        "consumption_stock_entry": entry.name,
        "consumption_stock_entry_detail": row.name,
        "consumed_qty": consumed,
        "return_qty": returned,
        "consumption_reason": (load.consumption_reason if was_pending
                               else consumption_reason or None),
        "consumption_reported_by": (load.consumption_reported_by if was_pending
                                    else reported_by),
        "consumption_reported_on": (load.consumption_reported_on if was_pending
                                    else now_datetime()),
        "notes": (
            f"Awaiting ERPNext consumption submission; prepared {load.actual_qty}; "
            f"consume {consumed}; return {returned}"
        ),
    }, update_modified=True)
    _refresh_wip_bin_state(load.reusable_bin)
    return frappe.get_doc("CFG Kanban WIP Bin Load", load.name)


def bind_pending_consumption_loads(stock_entry, load_names):
    """Attach previously scanned operation use to the now-valid native ERP draft."""
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) != "Material Consumption for Manufacture":
        frappe.throw("Pending WIP Bin use can bind only to a Draft material consumption entry")
    bound = []
    for load_name in load_names:
        load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
        if load.status != "Consumption Pending ERP":
            frappe.throw(f"WIP Bin Load {load.name} is no longer awaiting ERP posting")
        matching = [row for row in entry.items if (
            row.item_code == load.item_code
            and row.s_warehouse == load.wip_warehouse
            and row.stock_uom == load.stock_uom
            and (row.get("batch_no") or "") == (load.batch_no or "")
        )]
        if len(matching) != 1:
            frappe.throw(
                f"WIP Bin Load {load.name} does not map to one unambiguous ERP consumption row"
            )
        bound.append(bind_consumption_draft(
            load.name, entry.name, matching[0].name,
            consumed_qty=load.consumed_qty,
            consumption_reason=load.consumption_reason,
            reported_by=load.consumption_reported_by,
        ))
    return bound


def finalize_wip_bin_consumption_entry(stock_entry):
    """Apply scanned actual-use quantities to the Draft native consumption rows.

    The draft is initially mapped from the complete prepared loads so every Ready bin can be
    matched safely. Immediately before Kanban submits it, this function reduces each ERP row to
    the sum explicitly reported by the operator. The unused balance never enters consumption.
    """
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) != "Material Consumption for Manufacture":
        return entry
    loads, direction = _loads_for_entry(entry.name)
    if not loads or direction != "consumption":
        return entry
    totals = {}
    for load in loads:
        if load.status != "Consumption Draft":
            frappe.throw(
                f"WIP Bin Load {load.name} is {load.status}; expected Consumption Draft"
            )
        qty = flt(load.consumed_qty or load.actual_qty)
        if qty <= 0:
            frappe.throw(f"WIP Bin Load {load.name} has no positive actual consumption")
        totals[load.consumption_stock_entry_detail] = (
            totals.get(load.consumption_stock_entry_detail, 0) + qty
        )
    rows = {row.name: row for row in entry.items}
    if set(totals) != set(rows):
        frappe.throw(
            "Every WIP-bin consumption row must have at least one scanned Ready bin before "
            "submitting the ERP entry"
        )
    for row_name, stock_qty in totals.items():
        row = rows[row_name]
        conversion = flt(row.conversion_factor) or 1
        row.transfer_qty = stock_qty
        row.qty = stock_qty / conversion
    enable_operation_scoped_consumption_validation(entry)
    entry.save(ignore_permissions=True)
    entry = frappe.get_doc("Stock Entry", entry.name)
    enable_operation_scoped_consumption_validation(entry)
    return entry


def validate_wip_bin_stock_entry(doc):
    """Validate every linked load and require complete coverage of WIP-bin material rows."""
    purpose = _purpose(doc)
    is_unused_return = bool(doc.get("cfg_wip_bin_return_load"))
    if purpose not in (TRANSFER_PURPOSE, *CONSUMPTION_PURPOSES) and not is_unused_return:
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
    expected_statuses = {
        "transfer": ("Transfer Draft", "Ready"),
        "consumption": ("Consumption Draft", "Return Draft", "Consumed"),
        "return": ("Return Draft", "Consumed"),
    }[direction]
    rows = {row.name: row for row in doc.items}
    allocated = {}
    for load in loads:
        if load.status not in expected_statuses:
            frappe.throw(f"WIP Bin Load {load.name} is {load.status}; expected {expected_statuses[0]}")
        row_name = (
            load.transfer_stock_entry_detail if direction == "transfer"
            else load.return_stock_entry_detail if direction == "return"
            else load.consumption_stock_entry_detail
        )
        row = rows.get(row_name)
        if not row:
            frappe.throw(f"WIP Bin Load {load.name} no longer matches a Stock Entry row")
        if direction == "transfer":
            _assert_transfer_row(load, row, doc)
        elif direction == "return":
            _assert_return_row(load, row, doc)
        else:
            _assert_consumption_row(load, row)
        load_qty = (
            flt(load.actual_qty) if direction == "transfer"
            else flt(load.return_qty) if direction == "return"
            else flt(load.consumed_qty or load.actual_qty)
        )
        allocated[row.name] = allocated.get(row.name, 0) + load_qty
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
        elif direction == "consumption":
            if load.status in ("Return Draft", "Consumed"):
                continue
            if flt(load.return_qty) > TOLERANCE:
                return_entry = _create_wip_bin_return_draft(load)
                load.db_set({
                    "status": "Return Draft", "consumed_on": timestamp,
                    "return_stock_entry": return_entry.name,
                    "return_stock_entry_detail": return_entry.items[0].name,
                    "notes": (
                        f"Consumed {load.consumed_qty} by submitted ERPNext entry {doc.name}; "
                        f"unused {load.return_qty} awaits WIP return {return_entry.name}"
                    ),
                }, update_modified=True)
                bin_state = "In Use"
                event_type = "WIP Bin Partial Consumption Confirmed"
            else:
                load.db_set({
                    "status": "Consumed", "consumed_on": timestamp,
                    "notes": f"Consumed by submitted ERPNext entry {doc.name}",
                }, update_modified=True)
                bin_state = "Empty"
                event_type = "WIP Bin Load Consumed"
        else:
            if load.status == "Consumed":
                continue
            ledger = None
            if load.source_handling_unit:
                ledger = post_quantity_event(
                    event_type="WIP Bin Unused Material Return",
                    qty=load.return_qty, stock_uom=load.stock_uom,
                    idempotency_key=f"wip-bin-unused-return:{load.name}:{doc.name}",
                    destination_handling_unit=load.source_handling_unit,
                    item_code=load.item_code, batch_no=load.batch_no,
                    source_company=load.company, source_warehouse=load.wip_warehouse,
                    destination_company=load.company,
                    destination_warehouse=load.source_warehouse,
                    reference_doctype="Stock Entry", reference_name=doc.name,
                    reason=f"ERPNext confirmed unused WIP Bin return {load.name}",
                )
            load.db_set({
                "status": "Consumed", "returned_on": timestamp,
                "return_confirmation_ledger": ledger.name if ledger else None,
                "notes": (
                    f"Consumed {load.consumed_qty}; unused {load.return_qty} returned by "
                    f"submitted ERPNext entry {doc.name}"
                ),
            }, update_modified=True)
            bin_state = "Empty"
            event_type = "WIP Bin Unused Material Returned"
        if load.job_card:
            deferred_job_cards.add(load.job_card)
        _refresh_wip_bin_state(load.reusable_bin)
        record(
            event_type, cycle=load.kanban_cycle, execution=load.process_execution,
            handling_unit=load.reusable_bin,
            qty=(load.return_qty if direction == "return"
                 else load.consumed_qty if direction == "consumption"
                 else load.actual_qty),
            reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name}; ERPNext confirmed",
        )
    if deferred_job_cards:
        _submit_deferred_job_cards(deferred_job_cards, doc)
    if direction == "consumption":
        from cfg_kanban.services.loose_wip import confirm_consumption
        confirm_consumption(doc.name)


def _create_wip_bin_return_draft(load):
    """Create the native WIP-to-source transfer for an operator-reported unused balance."""
    existing = load.get("return_stock_entry")
    if existing and frappe.db.exists("Stock Entry", existing):
        return frappe.get_doc("Stock Entry", existing)
    entry = frappe.get_doc({
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Transfer",
        "purpose": "Material Transfer",
        "company": load.company,
        "from_warehouse": load.wip_warehouse,
        "to_warehouse": load.source_warehouse,
        "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": load.kanban_cycle,
        "cfg_kanban_job_card": load.job_card,
        "cfg_wip_bin_return_load": load.name,
    })
    entry.append("items", {
        "item_code": load.item_code,
        "s_warehouse": load.wip_warehouse,
        "t_warehouse": load.source_warehouse,
        "qty": load.return_qty,
        "transfer_qty": load.return_qty,
        "uom": load.stock_uom,
        "stock_uom": load.stock_uom,
        "conversion_factor": 1,
        "batch_no": load.batch_no,
    })
    entry.set_missing_values()
    entry.insert(ignore_permissions=True)
    return entry


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
                f"Cannot cancel consumption: WIP Bin Load {load.name} is {load.status}. "
                "Submit the unused-material return or reconcile it first."
            )
        if direction == "return" and load.status != "Consumed":
            frappe.throw(
                f"Cannot cancel unused-material return: WIP Bin Load {load.name} is "
                f"{load.status}"
            )
        submitted_transfer = direction == "transfer" and load.status == "Ready"
        bin_state = (
            "Exception" if direction in ("consumption", "return") or submitted_transfer
            else "Empty"
        )
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
        if direction == "consumption" and load.bin_mode == "Loose Multi-Item":
            for usage_name in frappe.get_all(
                "CFG Kanban Loose WIP Usage",
                {"wip_bin_load": load.name, "consumption_stock_entry": doc.name,
                 "status": "Posted"},
                pluck="name", limit_page_length=0,
            ):
                frappe.db.set_value(
                    "CFG Kanban Loose WIP Usage", usage_name,
                    {"status": "Posting Reversed",
                     "reversal_reason": (
                         f"ERPNext consumption {doc.name} was cancelled; supervisor "
                         "reconciliation is required"
                     )},
                    update_modified=True,
                )
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
        elif direction == "return":
            _create_stock_entry_reconciliation(load, doc, "return")
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

    affected_qty = flt(reconciliation.qty)
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
            f"Exact {affected_qty} {load.stock_uom} {load.item_code}"
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
            f"removed exact {affected_qty} {load.stock_uom} from {load.wip_warehouse}"
        )
    elif decision == "Material Returned to Source":
        if correction_stock_entry:
            frappe.throw("Do not select an ERP correction when material returned to source")
        _verify_source_handling_unit_scan(load, source_handling_unit_scan)
        if reconciliation.source_hold_ledger:
            source_resolution_ledger = post_quantity_event(
                event_type="Unreserve", qty=affected_qty,
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
            f"Exact {affected_qty} {load.stock_uom} {load.item_code} physically returned "
            f"from {load.reusable_bin} to {load.source_warehouse}"
            f"{f' / Source Tag {load.source_handling_unit}' if load.source_handling_unit else ''}"
        )
    else:
        correction, correction_row = _validate_transfer_recovery_correction(
            load, reconciliation, correction_stock_entry
        )
        if reconciliation.source_hold_ledger:
            source_resolution_ledger = post_quantity_event(
                event_type="WIP Bin Load", qty=affected_qty,
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
            f"Bin still holds exact {affected_qty} {load.stock_uom} {load.item_code}; "
            f"submitted correction {correction.name} restored ERP stock to "
            f"{load.wip_warehouse}; recovered as Load {restored_load.name}"
        )

    timestamp = now_datetime()
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin,
        "last_reconciled_on", timestamp, update_modified=False,
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
    _refresh_wip_bin_state(load.reusable_bin)
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
        handling_unit=load.reusable_bin, qty=affected_qty,
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
    context = {
        "transfer": "Transfer Cancellation",
        "consumption": "Consumption Cancellation",
        "return": "Unused Return Cancellation",
    }[direction]
    affected_qty = (
        flt(load.actual_qty) if direction == "transfer"
        else flt(load.return_qty) if direction == "return"
        else flt(load.consumed_qty or load.actual_qty)
    )
    reconciliation = frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Reconciliation",
        "status": "Open", "reversal_context": context,
        "wip_bin_load": load.name,
        "reusable_bin": load.reusable_bin, "company": load.company,
        "source_handling_unit": load.source_handling_unit,
        "item_code": load.item_code, "batch_no": load.batch_no,
        "qty": affected_qty, "stock_uom": load.stock_uom,
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
        qty=affected_qty,
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
        "bin_mode": load.bin_mode or "Standard Quantity",
        "reusable_bin": load.reusable_bin, "wip_bin_pool": load.wip_bin_pool,
        "company": load.company, "item_code": load.item_code,
        "batch_no": load.batch_no, "standard_qty": load.standard_qty,
        "actual_qty": flt(reconciliation.qty), "stock_uom": load.stock_uom,
        "partial_exception": cint(
            flt(reconciliation.qty) < flt(load.standard_qty) - TOLERANCE
        ),
        "exception_reason": (
            f"Controlled recovery of {reconciliation.qty} after "
            f"{reconciliation.reversal_context or 'ERP cancellation'}"
        ),
        "approved_by": frappe.session.user,
        "approved_by_operator": profile.employee,
        "exception_approved_on": now_datetime(),
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
    if not context or context in ("Consumption Cancellation", "Unused Return Cancellation"):
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
        and abs(_row_stock_qty(row) - flt(reconciliation.qty)) <= TOLERANCE
    ]
    if len(candidates) != 1:
        frappe.throw(
            f"Submitted correction must contain one unused row moving exactly "
            f"{reconciliation.qty} {load.stock_uom} of {load.item_code} from "
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
    if abs(flt(matching_qty) - flt(reconciliation.qty)) > TOLERANCE:
        frappe.throw(
            f"Submitted correction must remove exactly {reconciliation.qty} {load.stock_uom} "
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
        "consumed_qty", "return_qty", "source_handling_unit",
        "stock_uom", "company", "source_warehouse", "wip_warehouse", "kanban_cycle",
        "process_execution", "transfer_stock_entry_detail",
        "consumption_stock_entry_detail", "return_stock_entry_detail",
    ]
    transfer = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"transfer_stock_entry": stock_entry,
         "status": ["in", ["Transfer Draft", "Ready"]]}, fields,
    )
    consumption = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"consumption_stock_entry": stock_entry,
         "status": ["in", ["Consumption Draft", "Return Draft", "Consumed"]]}, fields,
    )
    returned = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"return_stock_entry": stock_entry,
         "status": ["in", ["Return Draft", "Consumed"]]}, fields,
    )
    if sum(bool(value) for value in (transfer, consumption, returned)) > 1:
        frappe.throw("One Stock Entry cannot represent multiple WIP Bin movement directions")
    if transfer:
        return transfer, "transfer"
    if consumption:
        return consumption, "consumption"
    if returned:
        return returned, "return"
    purpose_values = frappe.db.get_value(
        "Stock Entry", stock_entry, ["purpose", "stock_entry_type"], as_dict=True
    ) or {}
    purpose = purpose_values.get("purpose") or purpose_values.get("stock_entry_type")
    return [], "transfer" if purpose == TRANSFER_PURPOSE else "consumption"


def _pending_consumption_result(load, duplicate=False):
    return {
        "load": load.name, "status": load.status,
        "reusable_bin": load.reusable_bin, "item_code": load.item_code,
        "prepared_qty": flt(load.actual_qty), "consumed_qty": flt(load.consumed_qty),
        "return_qty": flt(load.return_qty), "stock_uom": load.stock_uom,
        "job_card": load.job_card, "duplicate": duplicate,
    }


def _wip_rule(master, item_code, operation):
    rule = frappe.db.get_value("CFG Kanban Material Flow Rule", {
        "parent": master,
        "parenttype": "CFG Kanban Master",
        "item_code": item_code,
        "operation": operation,
        "wip_presentation_method": ["in", [
            "Standard Quantity Reusable WIP Bin", "Loose Multi-Item WIP Bin",
        ]],
    }, ["wip_bin_pool", "standard_bin_qty", "stock_uom",
        "wip_presentation_method"], as_dict=True)
    if not rule:
        frappe.throw(f"Item {item_code} is not configured as a reusable WIP Bin material")
    return rule


def wip_bin_full_qty(reusable_bin, item_code, stock_uom, default_qty):
    """Return the scanned physical bin's Item capacity, with Kanban Master fallback."""
    capacity = frappe.db.get_value(
        "CFG Kanban WIP Bin Capacity",
        {
            "parent": reusable_bin,
            "parenttype": "CFG Kanban Handling Unit",
            "parentfield": "wip_bin_capacities",
            "item_code": item_code,
            "active": 1,
        },
        ["full_bin_qty", "stock_uom"],
        as_dict=True,
    )
    if capacity:
        if capacity.stock_uom != stock_uom:
            frappe.throw(
                f"WIP Bin {reusable_bin} capacity UOM {capacity.stock_uom} does not match "
                f"ERP row UOM {stock_uom} for Item {item_code}"
            )
        qty = flt(capacity.full_bin_qty)
        if qty <= TOLERANCE:
            frappe.throw(
                f"WIP Bin {reusable_bin} has an invalid Full-bin Capacity for Item {item_code}"
            )
        return qty
    qty = flt(default_qty)
    if qty <= TOLERANCE:
        frappe.throw(
            f"WIP Bin {reusable_bin} has no active Item-specific capacity and the Kanban "
            "Master Fallback Qty per Full Bin is not positive"
        )
    return qty


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


def _assert_return_row(load, row, entry):
    if (row.item_code != load.item_code
            or row.s_warehouse != load.wip_warehouse
            or row.t_warehouse != load.source_warehouse
            or row.stock_uom != load.stock_uom
            or (row.get("batch_no") or "") != (load.batch_no or "")
            or entry.company != load.company):
        frappe.throw(f"WIP Bin Load {load.name} no longer matches its unused-material return row")


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


def _refresh_wip_bin_state(reusable_bin):
    """Derive physical state from all active load episodes for one permanent bin."""
    unit = frappe.db.get_value(
        "CFG Kanban Handling Unit", reusable_bin,
        ["reusable_container_role", "wip_bin_state"], as_dict=True,
    )
    if not unit or unit.reusable_container_role not in (
        "Standard Quantity WIP Bin", "Loose Multi-Item WIP Bin",
    ):
        return
    if frappe.db.exists(
        "CFG Kanban WIP Bin Reconciliation",
        {"reusable_bin": reusable_bin, "status": "Open"},
    ):
        next_state = "Exception"
    else:
        active = frappe.get_all(
            "CFG Kanban WIP Bin Load",
            {"reusable_bin": reusable_bin, "status": ["in", list(ACTIVE_LOAD_STATUSES)]},
            ["status", "bin_mode"], limit_page_length=0,
        )
        if not active:
            next_state = "Empty"
        elif unit.reusable_container_role == "Loose Multi-Item WIP Bin":
            statuses = {row.status for row in active}
            if statuses.intersection({"Consumption Draft", "Return Draft"}):
                next_state = "Awaiting Consumption"
            elif statuses.intersection({"Transfer Draft"}):
                next_state = "Filling"
            else:
                next_state = "Accumulating"
        else:
            status = active[0].status
            if status == "Transfer Draft":
                next_state = "Reserved"
            elif status == "Ready":
                next_state = "Ready"
            else:
                next_state = "In Use"
    frappe.db.set_value(
        "CFG Kanban Handling Unit", reusable_bin, "wip_bin_state", next_state,
        update_modified=False,
    )


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
        select coalesce(sum(case when consumed_qty > 0 then consumed_qty else actual_qty end), 0)
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
        "status": ["in", list(ACTIVE_LOAD_STATUSES)],
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
        frappe.throw("Scan an active reusable WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    _assert_reusable_bin(unit, context, entry.company, row.t_warehouse)
    return unit


def _assert_reusable_bin(unit, context, company, wip_warehouse):
    pool_name = context["wip_bin_pool"]
    bin_mode = context.get("bin_mode") or "Standard Quantity"
    item_code = context.get("item_code")
    if not item_code:
        frappe.throw(
            "The selected ERP material row has no Item Code. Refresh Production Material "
            "Trace and scan the material again."
        )
    expected_role = (
        "Loose Multi-Item WIP Bin" if bin_mode == "Loose Multi-Item"
        else "Standard Quantity WIP Bin"
    )
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != expected_role):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a {expected_role}")
    if unit.identity_state not in ("Active", "Empty"):
        frappe.throw(f"WIP Bin {unit.handling_unit_id} is not active")
    if bin_mode != "Loose Multi-Item" and unit.wip_bin_state != "Empty":
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
        "reusable_bin": unit.name, "workstation": context.get("workstation"), "active": 1,
    }):
        frappe.throw(f"WIP Bin {unit.handling_unit_id} is not approved in Pool {pool_name}")
    if bin_mode == "Loose Multi-Item" and not frappe.db.exists(
        "CFG Kanban Loose WIP Allowed Item", {
            "parent": unit.name, "parenttype": "CFG Kanban Handling Unit",
            "parentfield": "loose_wip_allowed_items",
            "item_code": item_code, "active": 1,
        },
    ):
        frappe.throw(
            f"Item {item_code} is not authorized for Loose WIP Bin "
            f"{unit.handling_unit_id}"
        )
    active = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"reusable_bin": unit.name,
         "status": ["in", ["Reserved", "Transfer Draft", "Ready", "In Use",
                            "Consumption Pending ERP", "Consumption Draft", "Return Draft"]]},
        ["name", "bin_mode", "wip_bin_pool", "work_order", "job_card", "operation",
         "workstation"],
    )
    if active and bin_mode != "Loose Multi-Item":
        frappe.throw(f"WIP Bin {unit.handling_unit_id} already has active Load {active[0].name}")
    for load in active:
        if ((load.bin_mode or "Standard Quantity") != "Loose Multi-Item"
                or load.wip_bin_pool != pool_name
                or load.work_order != context.get("work_order")
                or load.job_card != context.get("job_card")
                or load.operation != context.get("operation")
                or load.workstation != context.get("workstation")):
            frappe.throw(
                f"Loose WIP Bin {unit.handling_unit_id} is already owned by Load "
                f"{load.name} for another production context"
            )


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
        "standard_qty": flt(load.standard_qty),
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
        "prepared_qty": flt(load.actual_qty),
        "actual_qty": flt(load.consumed_qty or load.actual_qty),
        "consumed_qty": flt(load.consumed_qty or load.actual_qty),
        "return_qty": flt(load.return_qty), "stock_uom": load.stock_uom,
        "partial_exception": bool(load.partial_exception),
        "exception_reason": load.exception_reason,
        "remaining_qty": _remaining_consumption_qty(
            entry.name, row.name, _row_stock_qty(row)
        ),
    }


def _actor_can_approve_partial_consumption(profile):
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and cint(profile.get("can_override"))
    )


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

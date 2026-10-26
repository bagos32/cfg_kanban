"""P07-0D2B1 preview-only foundation for controlled Kanban adjustments."""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once


TERMINAL_CYCLE_STATUSES = {"Completed", "Cancelled"}
TERMINAL_EXECUTION_STATUSES = {"Completed", "Cancelled"}
EPSILON = 0.000001


@frappe.whitelist()
def preview_operation_quantity_adjustment(
    request_name, good_qty_delta=0, reject_qty_delta=0
):
    """Return current and proposed quantities without creating or changing any record."""
    _require_workforce_manager()
    request = frappe.get_doc("CFG Kanban Correction Request", request_name)
    request.check_permission("read")
    return _operation_quantity_preview(request, good_qty_delta, reject_qty_delta)


@frappe.whitelist()
def prepare_operation_quantity_adjustment(
    request_name,
    good_qty_delta=0,
    reject_qty_delta=0,
    preparation_notes=None,
    event_token=None,
):
    """Freeze one eligible preview; deliberately do not apply it to production."""
    _require_workforce_manager()
    preparation_notes = (preparation_notes or "").strip()
    if not preparation_notes:
        frappe.throw("Preparation notes are required")
    if not event_token:
        frappe.throw("A proposal event token is required")

    frappe.db.sql(
        "select name from `tabCFG Kanban Correction Request` where name=%s for update",
        (request_name,),
    )
    request = frappe.get_doc("CFG Kanban Correction Request", request_name)
    request.check_permission("read")
    _assert_consumed_request_approval(request)
    key = canonical_key(
        "kanban-adjustment-proposal", request.name, event_token
    )
    duplicate = frappe.db.get_value(
        "CFG Kanban Adjustment Proposal", {"idempotency_key": key}, "name"
    )
    if duplicate:
        return _proposal_result(frappe.get_doc("CFG Kanban Adjustment Proposal", duplicate), True)

    active = frappe.db.get_value(
        "CFG Kanban Adjustment Proposal",
        {"correction_request": request.name, "status": "Prepared"},
        "name",
    )
    if active:
        frappe.throw(
            f"Correction Request {request.name} already has Prepared proposal {active}; "
            "cancel that proposal before preparing another revision"
        )

    preview = _operation_quantity_preview(request, good_qty_delta, reject_qty_delta)
    if not preview["eligible"]:
        frappe.throw("This adjustment cannot be prepared: " + "; ".join(preview["blocks"]))

    prior = frappe.get_all(
        "CFG Kanban Adjustment Proposal",
        filters={"correction_request": request.name},
        fields=["name", "revision"],
        order_by="revision desc",
        limit_page_length=1,
    )
    revision = (int(prior[0].revision or 0) + 1) if prior else 1
    proposal, created = insert_once(
        frappe.get_doc({
            "doctype": "CFG Kanban Adjustment Proposal",
            "status": "Prepared",
            "correction_request": request.name,
            "revision": revision,
            "supersedes": prior[0].name if prior else None,
            "company": request.company,
            "kanban_card": request.kanban_card,
            "kanban_cycle": request.kanban_cycle,
            "process_execution": request.process_execution,
            "adjustment_kind": "Operation Quantity Delta",
            "target_doctype": preview["target_doctype"],
            "target_document": preview["target_document"],
            "stock_uom": preview["stock_uom"],
            "target_qty": preview["target_qty"],
            "released_qty": preview["released_qty"],
            "current_good_qty": preview["current_good_qty"],
            "good_qty_delta": preview["good_qty_delta"],
            "proposed_good_qty": preview["proposed_good_qty"],
            "current_reject_qty": preview["current_reject_qty"],
            "reject_qty_delta": preview["reject_qty_delta"],
            "proposed_reject_qty": preview["proposed_reject_qty"],
            "current_processed_qty": preview["current_processed_qty"],
            "processed_qty_delta": preview["processed_qty_delta"],
            "proposed_processed_qty": preview["proposed_processed_qty"],
            "eligibility_state": "Eligible",
            "eligibility_reason": preview["eligibility_reason"],
            "readiness_warnings": "\n".join(preview["warnings"]) or None,
            "correction_snapshot": request.current_value_snapshot,
            "current_snapshot": json.dumps(
                preview["current_snapshot"], sort_keys=True, default=str
            ),
            "target_modified_on": preview["current_snapshot"].get("modified"),
            "preparation_notes": preparation_notes,
            "prepared_by_employee": request.reviewed_by_employee,
            "prepared_by_name": request.reviewed_by_name,
            "prepared_by_user": frappe.session.user,
            "prepared_on": now_datetime(),
            "supervisor_action_approval": request.supervisor_action_approval,
        }),
        key,
        ignore_permissions=True,
    )
    if created:
        record(
            "Kanban Adjustment Proposal Prepared",
            card=request.kanban_card,
            cycle=request.kanban_cycle,
            execution=request.process_execution,
            reference_doctype=proposal.doctype,
            reference_name=proposal.name,
            operator=request.reviewed_by_employee,
            terminal_user=frappe.session.user,
            qty=preview["processed_qty_delta"],
            notes=(
                f"Revision {revision}; good {preview['good_qty_delta']:+g}; "
                f"reject {preview['reject_qty_delta']:+g}. Preview only; not applied."
            ),
            system_generated=False,
            ignore_permissions=True,
        )
    return _proposal_result(proposal, not created)


@frappe.whitelist()
def cancel_adjustment_proposal(proposal_name, cancellation_reason):
    """Cancel only a preview proposal; no production quantity is changed."""
    _require_workforce_manager()
    reason = (cancellation_reason or "").strip()
    if not reason:
        frappe.throw("A proposal cancellation reason is required")
    frappe.db.sql(
        "select name from `tabCFG Kanban Adjustment Proposal` where name=%s for update",
        (proposal_name,),
    )
    proposal = frappe.get_doc("CFG Kanban Adjustment Proposal", proposal_name)
    proposal.check_permission("read")
    if proposal.status != "Prepared":
        frappe.throw(f"Proposal {proposal.name} cannot be cancelled from {proposal.status}")
    proposal.db_set({
        "status": "Cancelled",
        "cancelled_by_user": frappe.session.user,
        "cancelled_on": now_datetime(),
        "cancellation_reason": reason,
    }, update_modified=True)
    record(
        "Kanban Adjustment Proposal Cancelled",
        card=proposal.kanban_card,
        cycle=proposal.kanban_cycle,
        execution=proposal.process_execution,
        reference_doctype=proposal.doctype,
        reference_name=proposal.name,
        terminal_user=frappe.session.user,
        notes=reason,
        system_generated=False,
        ignore_permissions=True,
    )
    return {"name": proposal.name, "status": "Cancelled"}


def _operation_quantity_preview(request, good_qty_delta, reject_qty_delta):
    blocks = []
    warnings = []
    if request.status != "Approved" or request.review_decision != "Approve Kanban Adjustment":
        blocks.append("The Correction Request does not have an approved Kanban-adjustment decision")
    if request.correction_category != "Operation Progress":
        blocks.append("P07-0D2B1 supports only Operation Progress quantity proposals")
    if request.affected_doctype != "CFG Kanban Process Execution":
        blocks.append("The affected record is not a Kanban Process Execution")
    if request.affected_document != request.process_execution:
        blocks.append("The affected execution does not match the Correction Request context")

    cycle = frappe.get_doc("CFG Kanban Cycle", request.kanban_cycle)
    execution = frappe.get_doc("CFG Kanban Process Execution", request.process_execution)
    cycle.check_permission("read")
    execution.check_permission("read")
    if execution.kanban_cycle != cycle.name:
        blocks.append("The Process Execution no longer belongs to the approved Cycle")
    if cycle.status in TERMINAL_CYCLE_STATUSES:
        blocks.append(f"Cycle {cycle.name} is already {cycle.status}")
    if execution.status in TERMINAL_EXECUTION_STATUSES:
        blocks.append(f"Process Execution {execution.name} is already {execution.status}")

    good_delta = flt(good_qty_delta)
    reject_delta = flt(reject_qty_delta)
    processed_delta = good_delta + reject_delta
    current_good = flt(execution.good_qty)
    current_reject = flt(execution.reject_qty)
    current_processed = flt(execution.processed_qty)
    proposed_good = current_good + good_delta
    proposed_reject = current_reject + reject_delta
    proposed_processed = current_processed + processed_delta
    target_qty = flt(execution.target_qty)
    released_qty = flt(execution.released_qty)

    if abs(good_delta) <= EPSILON and abs(reject_delta) <= EPSILON:
        blocks.append("Enter a non-zero Good or Reject quantity delta")
    if proposed_good < -EPSILON:
        blocks.append("Proposed Good Qty cannot be negative")
    if proposed_reject < -EPSILON:
        blocks.append("Proposed Reject Qty cannot be negative")
    if proposed_processed < -EPSILON:
        blocks.append("Proposed Processed Qty cannot be negative")
    if proposed_processed > target_qty + EPSILON:
        blocks.append(
            f"Proposed Processed Qty {proposed_processed:g} exceeds target {target_qty:g}"
        )
    if proposed_good + EPSILON < released_qty:
        blocks.append(
            f"Proposed Good Qty cannot be below already released quantity {released_qty:g}"
        )
    if abs(good_delta) > EPSILON and execution.job_card:
        blocks.append(
            f"Good quantity is owned by ERPNext Job Card {execution.job_card}; "
            "use an authoritative ERP correction"
        )

    original = _json_value(request.current_value_snapshot, {})
    current_snapshot = {
        "name": execution.name,
        "status": execution.status,
        "kanban_cycle": execution.kanban_cycle,
        "job_card": execution.job_card,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "target_qty": target_qty,
        "processed_qty": current_processed,
        "good_qty": current_good,
        "reject_qty": current_reject,
        "released_qty": released_qty,
        "modified": execution.modified,
    }
    if original.get("modified") and str(original.get("modified")) != str(execution.modified):
        warnings.append(
            "The execution changed after the operator requested correction; proposed values use "
            "the latest current quantities and must be rechecked before future application."
        )
    if execution.job_card and abs(reject_delta) > EPSILON:
        warnings.append(
            "Reject Qty is Kanban operational evidence; this proposal does not change ERPNext "
            f"Job Card {execution.job_card}."
        )
    return {
        "eligible": not blocks,
        "blocks": blocks,
        "warnings": warnings,
        "eligibility_reason": (
            "Eligible for an audited preview proposal only; no production value will change."
            if not blocks else "; ".join(blocks)
        ),
        "target_doctype": "CFG Kanban Process Execution",
        "target_document": execution.name,
        "stock_uom": cycle.stock_uom,
        "target_qty": target_qty,
        "released_qty": released_qty,
        "current_good_qty": current_good,
        "good_qty_delta": good_delta,
        "proposed_good_qty": proposed_good,
        "current_reject_qty": current_reject,
        "reject_qty_delta": reject_delta,
        "proposed_reject_qty": proposed_reject,
        "current_processed_qty": current_processed,
        "processed_qty_delta": processed_delta,
        "proposed_processed_qty": proposed_processed,
        "current_snapshot": current_snapshot,
    }


def _proposal_result(proposal, duplicate=False):
    return {
        "name": proposal.name,
        "status": proposal.status,
        "correction_request": proposal.correction_request,
        "revision": proposal.revision,
        "eligible": proposal.eligibility_state == "Eligible",
        "duplicate": duplicate,
        "applied": False,
    }


def _assert_consumed_request_approval(request):
    if not request.reviewed_by_employee or not request.supervisor_action_approval:
        frappe.throw("The approved Correction Request has no complete reviewer approval audit")
    approval = frappe.db.get_value(
        "CFG Kanban Supervisor Action Approval",
        request.supervisor_action_approval,
        ["status", "correction_request", "correction_decision", "approved_by_employee"],
        as_dict=True,
    )
    if not approval:
        frappe.throw("The Correction Request approval record was not found")
    if (
        approval.status != "Consumed"
        or approval.correction_request != request.name
        or approval.correction_decision != "Approve Kanban Adjustment"
        or approval.approved_by_employee != request.reviewed_by_employee
    ):
        frappe.throw(
            "The Correction Request does not have a matching consumed Kanban-adjustment approval"
        )


def _json_value(value, default):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _require_workforce_manager():
    roles = set(frappe.get_roles())
    if not roles.intersection({"Manufacturing Manager", "HR Manager", "System Manager"}):
        frappe.throw(
            _("A workforce supervisor or manager role is required"),
            frappe.PermissionError,
        )

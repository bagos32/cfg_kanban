import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.operator_auth import require_operator


OPEN_STATUSES = ("Open", "Under Review", "Approved", "ERP Correction Required")
CATEGORY_SCOPES = {
    "Cycle Status": {"Current Cycle"},
    "Operation Progress": {"Current Operation / Execution"},
    "Ownership": {"Current Ownership"},
    "Participation": {"My Participation"},
    "Material / ERP Record": {"Work Order", "Job Card"},
    "Other": {
        "Current Cycle", "Current Operation / Execution", "Work Order", "Job Card",
        "Current Ownership", "My Participation",
    },
}
DECISION_TRANSITIONS = {
    "Start Review": {
        "from": {"Open"},
        "status": "Under Review",
        "resolution_type": None,
    },
    "Approve Kanban Adjustment": {
        "from": {"Open", "Under Review"},
        "status": "Approved",
        "resolution_type": "Kanban Adjustment Required",
    },
    "Reject": {
        "from": {"Open", "Under Review"},
        "status": "Rejected",
        "resolution_type": "No Change Approved",
    },
    "Require ERP Correction": {
        "from": {"Open", "Under Review", "Approved"},
        "status": "ERP Correction Required",
        "resolution_type": "ERP Correction Required",
    },
    "Resolve": {
        "from": {"ERP Correction Required"},
        "status": "Resolved",
        "resolution_type": "ERP Correction Confirmed",
    },
}
SNAPSHOT_FIELDS = {
    "CFG Kanban Cycle": (
        "name", "status", "kanban_card", "work_order", "priority", "blocked",
        "job_owner", "job_owner_name", "active_owner_assignment", "modified",
    ),
    "CFG Kanban Process Execution": (
        "name", "status", "kanban_cycle", "job_card", "operation", "workstation",
        "target_qty", "processed_qty", "good_qty", "reject_qty", "modified",
    ),
    "CFG Kanban Job Owner Assignment": (
        "name", "status", "kanban_cycle", "process_execution", "employee",
        "employee_name", "job_code", "assigned_on", "ended_on", "modified",
    ),
    "CFG Kanban Job Participation": (
        "name", "status", "kanban_cycle", "process_execution", "employee",
        "employee_name", "crew_role", "work_category", "participation_kind",
        "started_on", "ended_on", "duration_hours", "modified",
    ),
    "Work Order": (
        "name", "status", "docstatus", "production_item", "qty", "produced_qty",
        "material_transferred_for_manufacturing", "modified",
    ),
    "Job Card": (
        "name", "status", "docstatus", "work_order", "operation", "workstation",
        "for_quantity", "total_completed_qty", "modified",
    ),
}


def create_correction_request(
    execution_name,
    correction_category,
    affected_scope,
    reason,
    requested_change,
    evidence_notes=None,
    event_token=None,
    operator_session_token=None,
):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(operator_session_token, execution=execution)
    if session.get("development_proxy"):
        frappe.throw(
            "Use a real Employee operator credential for an auditable correction request"
        )
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    category = (correction_category or "").strip()
    scope = (affected_scope or "").strip()
    reason = (reason or "").strip()
    requested_change = (requested_change or "").strip()
    if category not in CATEGORY_SCOPES:
        frappe.throw("Select a valid correction category")
    if scope not in CATEGORY_SCOPES[category]:
        frappe.throw(f"{scope or 'The selected scope'} is not valid for {category}")
    if not reason:
        frappe.throw("A correction reason is required")
    if not requested_change:
        frappe.throw("Describe the correction that should be reviewed")
    if not event_token:
        frappe.throw("A request event token is required")

    affected_doctype, affected_document = _resolve_affected_record(
        scope, cycle, execution, profile
    )
    snapshot = _record_snapshot(affected_doctype, affected_document)
    key = canonical_key(
        "correction-request",
        event_token,
        cycle.name,
        execution.name,
        profile.employee,
    )
    request, created = insert_once(
        frappe.get_doc({
            "doctype": "CFG Kanban Correction Request",
            "status": "Open",
            "correction_category": category,
            "affected_scope": scope,
            "company": cycle.company,
            "kanban_card": cycle.kanban_card,
            "kanban_cycle": cycle.name,
            "process_execution": execution.name,
            "operation": execution.operation,
            "workstation": execution.workstation,
            "affected_doctype": affected_doctype,
            "affected_document": affected_document,
            "current_value_snapshot": json.dumps(snapshot, sort_keys=True, default=str),
            "reason": reason,
            "requested_change": requested_change,
            "evidence_notes": (evidence_notes or "").strip() or None,
            "requested_by_employee": profile.employee,
            "requested_by_name": (
                profile.employee_name
                or frappe.db.get_value("Employee", profile.employee, "employee_name")
                or profile.employee
            ),
            "requested_by_operator_profile": profile.name,
            "operator_session": session.name,
            "terminal_user": session.terminal_user,
            "requested_on": now_datetime(),
        }),
        key,
        ignore_permissions=True,
    )
    if created:
        record(
            "Correction Requested",
            card=cycle.kanban_card,
            cycle=cycle.name,
            execution=execution.name,
            reference_doctype=request.doctype,
            reference_name=request.name,
            operator=profile.employee,
            operator_session=session.name,
            terminal_user=session.terminal_user,
            notes=f"{category}: {reason}",
            system_generated=False,
            ignore_permissions=True,
        )
    return {
        "name": request.name,
        "status": request.status,
        "affected_doctype": request.affected_doctype,
        "affected_document": request.affected_document,
        "duplicate": not created,
    }


@frappe.whitelist()
def review_correction_request(
    request_name,
    decision,
    review_notes,
    reviewer_qr_token,
    reviewer_pin=None,
    erp_correction_doctype=None,
    erp_correction_document=None,
):
    _require_workforce_manager()
    frappe.db.sql(
        "select name from `tabCFG Kanban Correction Request` where name=%s for update",
        (request_name,),
    )
    request = frappe.get_doc("CFG Kanban Correction Request", request_name)
    request.check_permission("read")
    transition = DECISION_TRANSITIONS.get(decision)
    if not transition:
        frappe.throw("Select a valid correction review decision")
    if request.status not in transition["from"]:
        frappe.throw(
            f"Correction Request {request.name} cannot move from {request.status} "
            f"using {decision}"
        )
    if decision == "Require ERP Correction":
        active_proposal = frappe.db.get_value(
            "CFG Kanban Adjustment Proposal",
            {"correction_request": request.name, "status": "Prepared"},
            "name",
        )
        if active_proposal:
            frappe.throw(
                f"Cancel Prepared adjustment proposal {active_proposal} before routing this "
                "Correction Request to ERP correction"
            )
    review_notes = (review_notes or "").strip()
    if not review_notes:
        frappe.throw("Review notes are required")

    erp_doctype = (erp_correction_doctype or "").strip() or None
    erp_document = (erp_correction_document or "").strip() or None
    if bool(erp_doctype) != bool(erp_document):
        frappe.throw("Provide both the ERP correction DocType and document")
    if erp_doctype:
        if erp_doctype not in ("Stock Entry", "Work Order", "Job Card"):
            frappe.throw("ERP correction references are limited to Stock Entry, Work Order, or Job Card")
        if not frappe.db.exists(erp_doctype, erp_document):
            frappe.throw(f"{erp_doctype} {erp_document} does not exist")
    if decision == "Resolve" and not erp_document:
        frappe.throw("Link the authoritative ERPNext correction document before resolving")

    from cfg_kanban.services.action_approval import (
        approve_and_consume_correction_review,
    )
    approval, reviewer = approve_and_consume_correction_review(
        request,
        decision,
        reviewer_qr_token,
        review_notes,
        reviewer_pin,
    )
    current = now_datetime()
    resolution_type = transition["resolution_type"]
    values = {
        "status": transition["status"],
        "reviewed_by_employee": reviewer.employee,
        "reviewed_by_name": (
            reviewer.employee_name
            or frappe.db.get_value("Employee", reviewer.employee, "employee_name")
            or reviewer.employee
        ),
        "reviewed_by_operator_profile": reviewer.name,
        "reviewed_on": current,
        "review_decision": decision,
        "review_notes": review_notes,
        "supervisor_action_approval": approval.name,
        "resolution_type": resolution_type,
    }
    if erp_document:
        values.update({
            "erp_correction_doctype": erp_doctype,
            "erp_correction_document": erp_document,
        })
    if transition["status"] in ("Rejected", "Resolved"):
        values.update({
            "resolved_by_employee": reviewer.employee,
            "resolved_by_name": values["reviewed_by_name"],
            "resolved_on": current,
            "resolution_notes": review_notes,
        })
    request.db_set(values, update_modified=True)
    record(
        f"Correction Request {transition['status']}",
        card=request.kanban_card,
        cycle=request.kanban_cycle,
        execution=request.process_execution,
        reference_doctype=request.doctype,
        reference_name=request.name,
        operator=reviewer.employee,
        operator_session=request.operator_session,
        terminal_user=frappe.session.user,
        notes=f"{decision}: {review_notes}",
        system_generated=False,
        ignore_permissions=True,
    )
    return {
        "name": request.name,
        "status": transition["status"],
        "decision": decision,
        "approval": approval.name,
        "reviewed_by_employee": reviewer.employee,
        "reviewed_by_name": values["reviewed_by_name"],
        "erp_correction_doctype": erp_doctype,
        "erp_correction_document": erp_document,
    }


def _resolve_affected_record(scope, cycle, execution, profile):
    if scope == "Current Cycle":
        return "CFG Kanban Cycle", cycle.name
    if scope == "Current Operation / Execution":
        return "CFG Kanban Process Execution", execution.name
    if scope == "Work Order":
        if not cycle.work_order:
            frappe.throw("This Cycle has no Work Order to report")
        return "Work Order", cycle.work_order
    if scope == "Job Card":
        if not execution.job_card:
            frappe.throw("This execution has no Job Card to report")
        return "Job Card", execution.job_card
    if scope == "Current Ownership":
        if not cycle.get("active_owner_assignment"):
            frappe.throw("This Cycle has no active ownership assignment to report")
        return "CFG Kanban Job Owner Assignment", cycle.active_owner_assignment
    if scope == "My Participation":
        rows = frappe.get_all(
            "CFG Kanban Job Participation",
            filters={
                "kanban_cycle": cycle.name,
                "process_execution": execution.name,
                "employee": profile.employee,
            },
            fields=["name"],
            order_by="started_on desc",
            limit_page_length=1,
        )
        name = rows[0].name if rows else None
        if not name:
            frappe.throw("No participation record exists for this operator and execution")
        return "CFG Kanban Job Participation", name
    frappe.throw("Select a supported affected scope")


def _record_snapshot(doctype, name):
    fields = SNAPSHOT_FIELDS.get(doctype)
    if not fields:
        frappe.throw(f"Correction snapshots are not configured for {doctype}")
    values = frappe.db.get_value(doctype, name, list(fields), as_dict=True)
    if not values:
        frappe.throw(f"{doctype} {name} was not found")
    return {fieldname: values.get(fieldname) for fieldname in fields}


def _require_workforce_manager():
    roles = set(frappe.get_roles())
    if not roles.intersection({"Manufacturing Manager", "HR Manager", "System Manager"}):
        frappe.throw(
            _("A workforce supervisor or manager role is required"),
            frappe.PermissionError,
        )


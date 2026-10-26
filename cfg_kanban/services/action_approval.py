import hmac
import json
import secrets

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from cfg_kanban.services.authority import has_authority_role
from cfg_kanban.services.competency import employee_has_competency
from cfg_kanban.services.events import record
from cfg_kanban.services.operator_auth import credential_hash, require_operator


ACTION_CAPABILITIES = {
    "CLOSE_CYCLE_ON_BEHALF": "can_close_on_behalf",
    "TRANSFER_CYCLE_OWNERSHIP": "can_transfer_ownership",
    "START_CORRECTION_REVIEW": "can_correct_records",
    "APPROVE_CORRECTION_REQUEST": "can_correct_records",
    "REJECT_CORRECTION_REQUEST": "can_correct_records",
    "REQUIRE_ERP_CORRECTION": "can_correct_records",
    "RESOLVE_CORRECTION_REQUEST": "can_correct_records",
}

CORRECTION_DECISION_ACTIONS = {
    "Start Review": "START_CORRECTION_REVIEW",
    "Approve Kanban Adjustment": "APPROVE_CORRECTION_REQUEST",
    "Reject": "REJECT_CORRECTION_REQUEST",
    "Require ERP Correction": "REQUIRE_ERP_CORRECTION",
    "Resolve": "RESOLVE_CORRECTION_REQUEST",
}


def close_on_behalf_requirement(execution, requester_profile):
    """Return the opt-in supervisor-pass requirement for a non-owner close."""
    execution = _execution_doc(execution)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    if not cycle.get("enforce_job_owner") or not cycle.get("job_owner"):
        return _not_required()
    if cycle.job_owner == requester_profile.employee:
        return _not_required()

    requirements = _capability_requirements(cycle, "can_close_on_behalf")
    if not requirements:
        return _not_required()

    actor_match = _matching_requirement(
        cycle, execution, requester_profile, requirements,
        requester_employee=requester_profile.employee,
        require_separate=False,
    )
    strict_separation = any(cint(row.separate_approver_required) for row in requirements)
    required = bool(strict_separation or not actor_match)
    return {
        "required": required,
        "action_code": "CLOSE_CYCLE_ON_BEHALF",
        "required_capability": "can_close_on_behalf",
        "cycle_owner": cycle.job_owner,
        "cycle_owner_name": cycle.job_owner_name,
        "separate_approver_required": strict_separation,
        "authorized_by_current_operator": bool(actor_match and not strict_separation),
    }


def ownership_transfer_requirement(execution, requester_profile):
    """Return availability and policy evidence for a controlled owner transfer."""
    execution = _execution_doc(execution)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    if not cycle.get("enforce_job_owner"):
        return _transfer_not_available("Job Owner enforcement is not enabled for this Cycle")
    if not cycle.get("job_owner") or not cycle.get("active_owner_assignment"):
        return _transfer_not_available("This Cycle does not have an active owner to transfer")
    if cycle.status in ("Completed", "Cancelled"):
        return _transfer_not_available(f"Ownership cannot be transferred for a {cycle.status} Cycle")

    requirements = _capability_requirements(cycle, "can_transfer_ownership")
    if not requirements:
        return _transfer_not_available(
            "The Cycle snapshot has no Supervisor / Mentor or Verifier role with Transfer Ownership authority"
        )
    return {
        "available": True,
        "required": True,
        "action_code": "TRANSFER_CYCLE_OWNERSHIP",
        "required_capability": "can_transfer_ownership",
        "cycle_owner": cycle.job_owner,
        "cycle_owner_name": cycle.job_owner_name,
        "requester_employee": requester_profile.employee,
        "reason": None,
    }


def approve_action(
    action_code,
    execution_name,
    approver_qr_token,
    reason,
    operator_session_token,
    approver_pin=None,
    subject_qr_token=None,
    subject_pin=None,
):
    if action_code not in (
        "CLOSE_CYCLE_ON_BEHALF", "TRANSFER_CYCLE_OWNERSHIP"
    ):
        frappe.throw(f"Unsupported supervisor approval action: {action_code}")
    if not (reason or "").strip():
        frappe.throw("A reason is required for supervisor action approval")

    execution = _execution_doc(execution_name)
    requester, session = require_operator(operator_session_token, execution=execution)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
    evaluate_cycle_roles(cycle.name, persist=True)
    subject = None
    if action_code == "CLOSE_CYCLE_ON_BEHALF":
        requirement = close_on_behalf_requirement(execution, requester)
        if not requirement["required"]:
            frappe.throw("This Cycle closure does not require a separate supervisor pass")
    else:
        requirement = ownership_transfer_requirement(execution, requester)
        if not requirement["available"]:
            frappe.throw(requirement["reason"])
        if not subject_qr_token:
            frappe.throw("Scan the replacement operator credential before supervisor approval")
        subject = profile_from_credential(subject_qr_token, subject_pin)
        from cfg_kanban.services.job_ownership import validate_transfer_target
        validate_transfer_target(cycle, execution, subject)

    approver = profile_from_credential(approver_qr_token, approver_pin)
    if approver.employee == requester.employee:
        frappe.throw("The requesting operator cannot approve their own exact-action pass")
    if subject and approver.employee == subject.employee:
        frappe.throw("The replacement owner cannot approve their own ownership transfer")
    capability = ACTION_CAPABILITIES[action_code]
    requirements = _capability_requirements(cycle, capability)
    matched = _matching_requirement(
        cycle, execution, approver, requirements,
        requester_employee=requester.employee,
        require_separate=True,
        excluded_employees={subject.employee} if subject else None,
    )
    if not matched:
        frappe.throw(
            "The scanned employee does not satisfy the Cycle's scoped supervisor role, "
            "competency, presence, and separation requirements for this action"
        )

    raw_token = secrets.token_urlsafe(32)
    current = now_datetime()
    _retire_prior_approvals(
        action_code,
        cycle.name,
        execution.name,
        requester.employee,
        session.name,
        current,
    )
    approval = frappe.get_doc({
        "doctype": "CFG Kanban Supervisor Action Approval",
        "action_code": action_code,
        "required_capability": capability,
        "status": "Approved",
        "company": cycle.company,
        "kanban_card": cycle.kanban_card,
        "kanban_cycle": cycle.name,
        "process_execution": execution.name,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "requested_by_employee": requester.employee,
        "requested_by_operator_profile": requester.name,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
        "requested_on": current,
        "approved_by_employee": approver.employee,
        "approved_by_name": (
            approver.employee_name
            or frappe.db.get_value("Employee", approver.employee, "employee_name")
            or approver.employee
        ),
        "approved_by_operator_profile": approver.name,
        "matched_requirement_row": matched.name,
        "matched_authority_role": matched.authority_role,
        "approved_on": current,
        "expires_on": add_to_date(current, minutes=2),
        "reason": reason.strip(),
        "subject_employee": subject.employee if subject else None,
        "subject_name": (
            subject.employee_name
            or frappe.db.get_value("Employee", subject.employee, "employee_name")
            or subject.employee
        ) if subject else None,
        "subject_operator_profile": subject.name if subject else None,
        "approval_token_hash": credential_hash(raw_token),
        "action_context": json.dumps({
            "action_code": action_code,
            "capability": capability,
            "kanban_cycle": cycle.name,
            "process_execution": execution.name,
            "requester_employee": requester.employee,
            "approver_employee": approver.employee,
            "subject_employee": subject.employee if subject else None,
            "subject_operator_profile": subject.name if subject else None,
            "reason": reason.strip(),
            "terminal_user": session.terminal_user,
        }, sort_keys=True),
    }).insert(ignore_permissions=True)
    record(
        "Supervisor Exact-action Pass Approved",
        card=cycle.kanban_card,
        cycle=cycle.name,
        execution=execution.name,
        reference_doctype=approval.doctype,
        reference_name=approval.name,
        operator=approver.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=f"{action_code}: {reason.strip()}",
        system_generated=False,
        ignore_permissions=True,
    )
    return {
        "approval": approval.name,
        "approval_token": raw_token,
        "action_code": action_code,
        "approved_by_employee": approval.approved_by_employee,
        "approved_by_name": approval.approved_by_name,
        "expires_on": approval.expires_on,
        "subject_employee": approval.subject_employee,
        "subject_name": approval.subject_name,
        "subject_operator_profile": approval.subject_operator_profile,
    }


def approve_and_consume_correction_review(
    correction_request,
    decision,
    approver_qr_token,
    reason,
    approver_pin=None,
):
    """Create and consume a request-bound exact-action pass in one transaction."""
    request = (
        correction_request
        if getattr(correction_request, "doctype", None) == "CFG Kanban Correction Request"
        else frappe.get_doc("CFG Kanban Correction Request", correction_request)
    )
    action_code = CORRECTION_DECISION_ACTIONS.get(decision)
    if not action_code:
        frappe.throw(f"Unsupported correction review decision: {decision}")
    if not (reason or "").strip():
        frappe.throw("Review notes are required for a correction decision")

    execution = _execution_doc(request.process_execution)
    cycle = frappe.get_doc("CFG Kanban Cycle", request.kanban_cycle)
    requester = frappe.get_doc(
        "CFG Kanban Operator Profile", request.requested_by_operator_profile
    )
    operator_session = frappe.get_doc(
        "CFG Kanban Operator Session", request.operator_session
    )
    from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
    evaluate_cycle_roles(cycle.name, persist=True)

    approver = profile_from_credential(approver_qr_token, approver_pin)
    if approver.employee == requester.employee:
        frappe.throw("The correction requester cannot approve their own correction decision")
    capability = ACTION_CAPABILITIES[action_code]
    requirements = _capability_requirements(cycle, capability)
    if not requirements:
        frappe.throw(
            "The Cycle snapshot has no Supervisor / Mentor or Verifier role with "
            "Correct Records authority"
        )
    matched = _matching_requirement(
        cycle,
        execution,
        approver,
        requirements,
        requester_employee=requester.employee,
        require_separate=True,
    )
    if not matched:
        frappe.throw(
            "The scanned employee does not satisfy the Cycle's scoped correction authority, "
            "competency, presence, and separation requirements"
        )

    raw_token = secrets.token_urlsafe(32)
    current = now_datetime()
    _retire_prior_approvals(
        action_code,
        cycle.name,
        execution.name,
        requester.employee,
        operator_session.name,
        current,
    )
    approval = frappe.get_doc({
        "doctype": "CFG Kanban Supervisor Action Approval",
        "action_code": action_code,
        "required_capability": capability,
        "status": "Approved",
        "company": cycle.company,
        "kanban_card": cycle.kanban_card,
        "kanban_cycle": cycle.name,
        "process_execution": execution.name,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "correction_request": request.name,
        "correction_decision": decision,
        "requested_by_employee": requester.employee,
        "requested_by_operator_profile": requester.name,
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
        "action_terminal_user": frappe.session.user,
        "requested_on": current,
        "approved_by_employee": approver.employee,
        "approved_by_name": (
            approver.employee_name
            or frappe.db.get_value("Employee", approver.employee, "employee_name")
            or approver.employee
        ),
        "approved_by_operator_profile": approver.name,
        "matched_requirement_row": matched.name,
        "matched_authority_role": matched.authority_role,
        "approved_on": current,
        "expires_on": add_to_date(current, minutes=2),
        "reason": reason.strip(),
        "approval_token_hash": credential_hash(raw_token),
        "action_context": json.dumps({
            "action_code": action_code,
            "capability": capability,
            "correction_request": request.name,
            "correction_decision": decision,
            "kanban_cycle": cycle.name,
            "process_execution": execution.name,
            "requester_employee": requester.employee,
            "approver_employee": approver.employee,
            "reason": reason.strip(),
            "origin_terminal_user": operator_session.terminal_user,
            "action_terminal_user": frappe.session.user,
        }, sort_keys=True),
    }).insert(ignore_permissions=True)
    record(
        "Correction Exact-action Pass Approved",
        card=cycle.kanban_card,
        cycle=cycle.name,
        execution=execution.name,
        reference_doctype=approval.doctype,
        reference_name=approval.name,
        operator=approver.employee,
        operator_session=operator_session.name,
        terminal_user=frappe.session.user,
        notes=f"{action_code}: {reason.strip()}",
        system_generated=False,
        ignore_permissions=True,
    )
    consumed = consume_action_approval(
        raw_token,
        action_code,
        execution,
        requester,
        operator_session,
        reason=reason,
    )
    return consumed, approver


def consume_action_approval(
    approval_token,
    action_code,
    execution,
    requester_profile,
    operator_session,
    subject_profile=None,
    reason=None,
):
    if not approval_token:
        frappe.throw("Scan an eligible supervisor credential before performing this action")
    execution = _execution_doc(execution)
    token_hash = credential_hash(approval_token)
    frappe.db.sql(
        "select name from `tabCFG Kanban Supervisor Action Approval` "
        "where approval_token_hash=%s for update",
        (token_hash,),
    )
    name = frappe.db.get_value(
        "CFG Kanban Supervisor Action Approval",
        {"approval_token_hash": token_hash},
        "name",
    )
    if not name:
        frappe.throw("Supervisor action approval is invalid")
    approval = frappe.get_doc("CFG Kanban Supervisor Action Approval", name)
    if not hmac.compare_digest(approval.approval_token_hash or "", token_hash):
        frappe.throw("Supervisor action approval is invalid")
    if approval.status != "Approved":
        frappe.throw(f"Supervisor action approval {approval.name} is already {approval.status}")
    if approval.expires_on and get_datetime(approval.expires_on) <= now_datetime():
        approval.db_set("status", "Expired", update_modified=True)
        frappe.throw("Supervisor action approval expired; scan the supervisor credential again")
    expected = {
        "action_code": action_code,
        "process_execution": execution.name,
        "kanban_cycle": execution.kanban_cycle,
        "requested_by_employee": requester_profile.employee,
        "requested_by_operator_profile": requester_profile.name,
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
    }
    if subject_profile:
        expected.update({
            "subject_employee": subject_profile.employee,
            "subject_operator_profile": subject_profile.name,
        })
    mismatches = [
        fieldname for fieldname, value in expected.items()
        if approval.get(fieldname) != value
    ]
    if mismatches:
        frappe.throw(
            "Supervisor action approval belongs to a different action context: "
            + ", ".join(mismatches)
        )
    if reason is not None and (approval.reason or "").strip() != (reason or "").strip():
        if approval.get("correction_request"):
            frappe.throw("Supervisor action approval belongs to different correction review notes")
        frappe.throw("Supervisor action approval belongs to a different transfer reason")
    approval.db_set({"status": "Consumed", "consumed_on": now_datetime()}, update_modified=True)
    record(
        "Supervisor Exact-action Pass Consumed",
        card=approval.kanban_card,
        cycle=approval.kanban_cycle,
        execution=approval.process_execution,
        reference_doctype=approval.doctype,
        reference_name=approval.name,
        operator=(
            approval.approved_by_employee
            if approval.get("correction_request")
            else requester_profile.employee
        ),
        operator_session=operator_session.name,
        terminal_user=approval.get("action_terminal_user") or operator_session.terminal_user,
        notes=action_code,
        system_generated=False,
        ignore_permissions=True,
    )
    return approval


def _retire_prior_approvals(
    action_code,
    cycle_name,
    execution_name,
    requester_employee,
    operator_session,
    current,
):
    """Keep only the newest usable pass for one exact action context."""
    prior = frappe.get_all(
        "CFG Kanban Supervisor Action Approval",
        filters={
            "action_code": action_code,
            "kanban_cycle": cycle_name,
            "process_execution": execution_name,
            "requested_by_employee": requester_employee,
            "operator_session": operator_session,
            "status": "Approved",
        },
        fields=["name", "expires_on"],
        limit_page_length=0,
    )
    for row in prior:
        status = (
            "Expired"
            if row.expires_on and get_datetime(row.expires_on) <= current
            else "Cancelled"
        )
        frappe.db.set_value(
            "CFG Kanban Supervisor Action Approval",
            row.name,
            "status",
            status,
            update_modified=True,
        )


def profile_from_credential(qr_token, pin=None):
    qr_token = _credential_value(qr_token)
    profile_name = frappe.db.get_value(
        "CFG Kanban Operator Profile",
        {"qr_token_hash": credential_hash(qr_token), "active": 1},
        "name",
    )
    if not profile_name:
        frappe.throw("Unknown or inactive operator credential")
    profile = frappe.get_doc("CFG Kanban Operator Profile", profile_name)
    employee_status = frappe.db.get_value("Employee", profile.employee, "status")
    if employee_status and employee_status != "Active":
        frappe.throw("The scanned employee is not active")
    if cint(profile.pin_required):
        saved_pin = profile.get_password("pin", raise_exception=False)
        if not saved_pin or not hmac.compare_digest(str(pin or ""), str(saved_pin)):
            frappe.throw("Invalid operator PIN")
    return profile


def _credential_value(value):
    value = str(value or "").strip()
    if "#operator=" in value:
        value = value.split("#operator=", 1)[1].split("&", 1)[0]
    elif "operator=" in value:
        value = value.split("operator=", 1)[1].split("&", 1)[0]
    return value


def _capability_requirements(cycle, capability):
    result = []
    for row in cycle.get("job_role_requirements_snapshot") or []:
        if row.assignment_type not in ("Supervisor / Mentor", "Verifier"):
            continue
        if not row.authority_role:
            continue
        role = frappe.get_cached_doc("CFG Kanban Authority Role", row.authority_role)
        if cint(role.active) and cint(role.get(capability)):
            result.append(row)
    return result


def _matching_requirement(
    cycle,
    execution,
    profile,
    requirements,
    requester_employee,
    require_separate,
    excluded_employees=None,
):
    excluded_employees = set(excluded_employees or [])
    for row in requirements:
        if require_separate and profile.employee == requester_employee:
            continue
        if profile.employee in excluded_employees:
            continue
        if cint(row.separate_approver_required) and profile.employee in (
            requester_employee, cycle.get("job_owner")
        ):
            continue
        if row.job_code and row.job_code not in [
            item.job_code for item in (profile.get("job_codes") or [])
        ]:
            continue
        if row.job_code:
            job_code = frappe.get_cached_doc("CFG Kanban Job Code", row.job_code)
            if not cint(job_code.active):
                continue
            if job_code.company and job_code.company != cycle.company:
                continue
        context = {
            "company": cycle.company,
            "operation": execution.operation,
            "workstation": execution.workstation,
            "responsibility": None,
        }
        if not has_authority_role(profile, row.authority_role, context=context):
            continue
        if row.skill and not employee_has_competency(
            profile.employee,
            row.skill,
            row.minimum_competency_level or "L0",
            require_independent=bool(
                cint(row.require_independent_authorization)
                and not cint(row.allow_supervised_trainee)
            ),
            require_supervisor=row.assignment_type == "Supervisor / Mentor",
        ):
            continue
        if cint(row.require_active_presence) and not frappe.db.exists(
            "CFG Kanban Cycle Role Assignment",
            {
                "kanban_cycle": cycle.name,
                "requirement_row": row.name,
                "employee": profile.employee,
                "status": "Active",
            },
        ):
            continue
        return row
    return None


def _execution_doc(execution):
    if getattr(execution, "doctype", None) == "CFG Kanban Process Execution":
        return execution
    return frappe.get_doc("CFG Kanban Process Execution", execution)


def _not_required():
    return {
        "required": False,
        "action_code": "CLOSE_CYCLE_ON_BEHALF",
        "required_capability": "can_close_on_behalf",
        "cycle_owner": None,
        "cycle_owner_name": None,
        "separate_approver_required": False,
        "authorized_by_current_operator": False,
    }


def _transfer_not_available(reason):
    return {
        "available": False,
        "required": False,
        "action_code": "TRANSFER_CYCLE_OWNERSHIP",
        "required_capability": "can_transfer_ownership",
        "cycle_owner": None,
        "cycle_owner_name": None,
        "reason": reason,
    }

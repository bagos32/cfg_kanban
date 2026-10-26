import json

import frappe
from frappe.utils import cint, now_datetime

from cfg_kanban.services.authority import has_authority_role
from cfg_kanban.services.competency import employee_has_competency
from cfg_kanban.services.crew_registry import get_active_workstation_crew


TERMINAL_CYCLE_STATUSES = ("Completed", "Cancelled")


def evaluate_cycle_roles(cycle_name, persist=True):
    """Match Cycle snapshot requirements to the owner and actively present crew.

    P07-0B1 is intentionally advisory. It records evidence and exposes missing
    coverage, but it does not authorize, block, approve, or close an action.
    """
    if persist:
        frappe.db.sql(
            "select name from `tabCFG Kanban Cycle` where name=%s for update",
            (cycle_name,),
        )
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    requirements = list(cycle.get("job_role_requirements_snapshot") or [])

    if cycle.status in TERMINAL_CYCLE_STATUSES:
        close_cycle_role_assignments(cycle, f"Cycle status is {cycle.status}")
        return _empty_result(cycle, requirements, "Closed")

    if not requirements:
        if persist:
            _end_undesired(cycle.name, set(), "Cycle has no configured role requirements")
            _persist_summary(cycle, "Not Configured", "No job-role requirements configured.")
        return _empty_result(cycle, requirements, "Not Configured")

    candidates = _runtime_candidates(cycle)
    desired = {}
    result_rows = []
    total_required = 0
    total_assigned = 0

    for requirement in requirements:
        required_count = max(cint(requirement.required_count), 1)
        total_required += required_count
        eligible = []
        seen_employees = set()
        for candidate in candidates:
            employee = candidate.get("employee")
            if not employee or employee in seen_employees:
                continue
            evidence = _matching_evidence(cycle, requirement, candidate)
            if evidence.get("eligible"):
                eligible.append((candidate, evidence))
                seen_employees.add(employee)
        selected = eligible[:required_count]
        total_assigned += len(selected)
        assignments = []
        for candidate, evidence in selected:
            key = (requirement.name, candidate.employee)
            desired[key] = (requirement, candidate, evidence)
            assignments.append({
                "employee": candidate.employee,
                "employee_name": candidate.employee_name,
                "operator_profile": candidate.operator_profile,
                "source": candidate.source,
                "crew_session": candidate.get("crew_session"),
                "crew_membership": candidate.get("crew_membership"),
            })
        result_rows.append({
            "requirement_row": requirement.name,
            "assignment_type": requirement.assignment_type,
            "job_code": requirement.job_code,
            "authority_role": requirement.authority_role,
            "skill": requirement.skill,
            "minimum_competency_level": requirement.minimum_competency_level,
            "required_count": required_count,
            "assigned_count": len(selected),
            "missing_count": max(required_count - len(selected), 0),
            "assignments": assignments,
        })

    if persist:
        _sync_assignments(cycle, desired)
    missing = max(total_required - total_assigned, 0)
    status = "Compliant" if not missing else "Pending"
    summary = (
        f"{total_assigned}/{total_required} required runtime role positions matched"
        + ("." if not missing else f"; {missing} awaiting eligible active assignment.")
    )
    if persist:
        _persist_summary(cycle, status, summary)
    return {
        "configured": True,
        "status": status,
        "compliant": not missing,
        "required_count": total_required,
        "assigned_count": total_assigned,
        "missing_count": missing,
        "summary": summary,
        "requirements": result_rows,
        "enforcement_active": False,
        "advisory_only": True,
    }


def close_cycle_role_assignments(cycle, reason):
    if isinstance(cycle, str):
        cycle = frappe.get_doc("CFG Kanban Cycle", cycle)
    active = frappe.get_all(
        "CFG Kanban Cycle Role Assignment",
        filters={"kanban_cycle": cycle.name, "status": "Active"},
        pluck="name",
    )
    current = now_datetime()
    for name in active:
        frappe.db.set_value(
            "CFG Kanban Cycle Role Assignment",
            name,
            {"status": "Ended", "ended_on": current, "end_reason": reason},
            update_modified=True,
        )
    return active


def _runtime_candidates(cycle):
    candidates = []
    if cycle.get("job_owner") and cycle.get("job_owner_operator_profile"):
        candidates.append(frappe._dict({
            "employee": cycle.job_owner,
            "employee_name": cycle.job_owner_name or cycle.job_owner,
            "operator_profile": cycle.job_owner_operator_profile,
            "source": "Cycle Ownership",
            "owner": True,
            "present": True,
            "owner_assignment": cycle.get("active_owner_assignment"),
            "company": cycle.company,
            "operation": None,
            "workstation": None,
            "crew_role": None,
            "work_category": "Direct Participation",
        }))

    executions = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={"kanban_cycle": cycle.name},
        fields=["operation", "workstation"],
        limit_page_length=0,
    )
    visited = set()
    for execution in executions:
        context_key = (execution.operation, execution.workstation)
        if not execution.workstation or context_key in visited:
            continue
        visited.add(context_key)
        crew = get_active_workstation_crew(cycle.company, execution.workstation)
        if not crew:
            continue
        for member in crew.get("members") or []:
            if member.status != "Active" or not member.operator_profile:
                continue
            candidates.append(frappe._dict({
                "employee": member.employee,
                "employee_name": member.employee_name or member.employee,
                "operator_profile": member.operator_profile,
                "source": "Active Crew",
                "owner": member.employee == cycle.get("job_owner"),
                "present": True,
                "crew_session": crew["session"].name,
                "crew_membership": member.name,
                "company": cycle.company,
                "operation": execution.operation,
                "workstation": execution.workstation,
                "crew_role": member.crew_role,
                "work_category": member.work_category,
            }))
    return candidates


def _matching_evidence(cycle, requirement, candidate):
    profile = frappe.get_cached_doc(
        "CFG Kanban Operator Profile", candidate.operator_profile
    )
    assignment_type = requirement.assignment_type
    reasons = []

    if not cint(profile.active):
        reasons.append("operator_profile_inactive")

    if assignment_type == "Operator-in-Charge" and not candidate.owner:
        reasons.append("not_cycle_owner")
    elif assignment_type == "Direct Worker" and (
        candidate.source != "Active Crew"
        or candidate.work_category != "Direct Participation"
    ):
        reasons.append("not_active_direct_worker")
    elif assignment_type == "Assistant" and (
        candidate.source != "Active Crew"
        or candidate.work_category != "Direct Participation"
        or candidate.crew_role not in ("Supporting Operator", "Temporary Support")
    ):
        reasons.append("not_active_assistant")
    elif assignment_type == "Supervisor / Mentor" and (
        candidate.source != "Active Crew"
        or not (
            candidate.crew_role == "Senior / Overseer"
            or candidate.work_category == "Oversight Only"
        )
    ):
        reasons.append("not_active_supervisor_or_mentor")
    elif assignment_type == "Verifier" and candidate.source != "Active Crew":
        reasons.append("not_active_crew_verifier")

    if cint(requirement.require_active_presence) and not candidate.present:
        reasons.append("not_actively_present")
    if cint(requirement.separate_approver_required) and candidate.employee == cycle.get("job_owner"):
        reasons.append("owner_cannot_be_separate_approver")

    assigned_job_codes = [row.job_code for row in (profile.get("job_codes") or [])]
    if requirement.job_code and requirement.job_code not in assigned_job_codes:
        reasons.append("job_code_not_assigned")
    elif requirement.job_code:
        job_code = frappe.get_cached_doc("CFG Kanban Job Code", requirement.job_code)
        if not cint(job_code.active):
            reasons.append("job_code_inactive")
        elif job_code.company and job_code.company != cycle.company:
            reasons.append("job_code_company_mismatch")

    context = {
        "company": candidate.company,
        "operation": candidate.operation,
        "workstation": candidate.workstation,
        "responsibility": None,
    }
    if requirement.authority_role and not has_authority_role(
        profile, requirement.authority_role, context=context
    ):
        reasons.append("scoped_authority_role_not_assigned")

    if requirement.skill:
        require_independent = bool(
            cint(requirement.require_independent_authorization)
            and not cint(requirement.allow_supervised_trainee)
        )
        require_supervisor = assignment_type == "Supervisor / Mentor"
        if not employee_has_competency(
            candidate.employee,
            requirement.skill,
            requirement.minimum_competency_level or "L0",
            require_independent=require_independent,
            require_supervisor=require_supervisor,
        ):
            reasons.append("competency_not_satisfied")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "assignment_type": assignment_type,
        "job_code": requirement.job_code,
        "authority_role": requirement.authority_role,
        "skill": requirement.skill,
        "minimum_competency_level": requirement.minimum_competency_level,
        "context": context,
        "source": candidate.source,
        "crew_role": candidate.crew_role,
        "work_category": candidate.work_category,
    }


def _sync_assignments(cycle, desired):
    existing = frappe.get_all(
        "CFG Kanban Cycle Role Assignment",
        filters={"kanban_cycle": cycle.name, "status": "Active"},
        fields=["name", "requirement_row", "employee"],
        limit_page_length=0,
    )
    existing_keys = {(row.requirement_row, row.employee): row for row in existing}
    _end_undesired(cycle.name, set(desired), "Runtime role coverage changed")
    current = now_datetime()
    for key, (requirement, candidate, evidence) in desired.items():
        if key in existing_keys:
            continue
        frappe.get_doc({
            "doctype": "CFG Kanban Cycle Role Assignment",
            "kanban_cycle": cycle.name,
            "kanban_card": cycle.kanban_card,
            "company": cycle.company,
            "requirement_row": requirement.name,
            "assignment_type": requirement.assignment_type,
            "job_code": requirement.job_code,
            "authority_role": requirement.authority_role,
            "skill": requirement.skill,
            "minimum_competency_level": requirement.minimum_competency_level,
            "employee": candidate.employee,
            "employee_name": candidate.employee_name,
            "operator_profile": candidate.operator_profile,
            "assignment_source": candidate.source,
            "crew_session": candidate.get("crew_session"),
            "crew_membership": candidate.get("crew_membership"),
            "owner_assignment": candidate.get("owner_assignment"),
            "status": "Active",
            "assigned_on": current,
            "matching_evidence": json.dumps(evidence, sort_keys=True, default=str),
        }).insert(ignore_permissions=True)


def _end_undesired(cycle_name, desired_keys, reason):
    rows = frappe.get_all(
        "CFG Kanban Cycle Role Assignment",
        filters={"kanban_cycle": cycle_name, "status": "Active"},
        fields=["name", "requirement_row", "employee"],
        limit_page_length=0,
    )
    current = now_datetime()
    for row in rows:
        if (row.requirement_row, row.employee) in desired_keys:
            continue
        frappe.db.set_value(
            "CFG Kanban Cycle Role Assignment",
            row.name,
            {"status": "Ended", "ended_on": current, "end_reason": reason},
            update_modified=True,
        )


def _persist_summary(cycle, status, summary):
    cycle.db_set({
        "job_role_compliance_status": status,
        "job_role_compliance_summary": summary,
        "job_role_last_evaluated_on": now_datetime(),
    }, update_modified=False)


def _empty_result(cycle, requirements, status):
    configured = bool(requirements)
    return {
        "configured": configured,
        "status": status,
        "compliant": not configured,
        "required_count": sum(max(cint(row.required_count), 1) for row in requirements),
        "assigned_count": 0,
        "missing_count": 0,
        "summary": (
            "Cycle role assignments are closed."
            if status == "Closed"
            else "No job-role requirements configured."
        ),
        "requirements": [],
        "enforcement_active": False,
        "advisory_only": True,
    }

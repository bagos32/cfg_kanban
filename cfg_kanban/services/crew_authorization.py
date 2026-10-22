import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from cfg_kanban.services.competency import employee_has_competency
from cfg_kanban.services.crew_authorization_rules import (
    DIRECT_WORK,
    LEAD_ROLES,
    SUPERVISOR_ROLE,
    evaluate_crew_authorization,
    requirement_key,
)
from cfg_kanban.services.crew_policy import get_effective_crew_policy
from cfg_kanban.services.crew_registry import get_active_workstation_crew


ACTIVE_EXECUTION_STATUSES = ("Ready", "In Progress", "Paused", "Waiting Input", "Blocked")


def evaluate_execution_crew(execution_name, checkpoint, actor=None, persist=True):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    result = evaluate_operation_crew(
        execution.kanban_master,
        execution.operation,
        execution.workstation,
        card_name=cycle.kanban_card,
    )
    result.update({
        "checkpoint": checkpoint,
        "kanban_cycle": cycle.name,
        "kanban_card": cycle.kanban_card,
        "process_execution": execution.name,
        "job_card": execution.job_card,
    })
    if persist and result.get("configured"):
        _persist_execution_decision(execution, result, actor)
    return result


def evaluate_operation_crew(kanban_master, operation, workstation, card_name=None):
    policy = get_effective_crew_policy(
        kanban_master, operation, workstation=workstation, card_name=card_name
    )
    if not policy.get("configured"):
        return {
            "allowed": True,
            "configured": False,
            "policy": policy,
            "crew_session": None,
            "members": [],
            "findings": [],
        }

    master = frappe.get_cached_doc("CFG Kanban Master", kanban_master)
    crew = get_active_workstation_crew(master.company, workstation)
    members = list((crew or {}).get("members") or [])
    active_members = [row for row in members if row.get("status") == "Active"]
    qualified = _qualified_by_requirement(policy, active_members)
    trainees = _trainee_employees(policy, active_members)
    concurrent = _concurrent_direct_employees(active_members, (crew or {}).get("session"))
    decision = evaluate_crew_authorization(
        policy,
        members,
        qualified_by_requirement=qualified,
        trainee_employees=trainees,
        concurrent_employees=concurrent,
    )
    decision.update({
        "policy": policy,
        "company": master.company,
        "workstation": workstation,
        "operation": operation,
        "crew_session": crew["session"].name if crew else None,
        "members": [_member_snapshot(row) for row in members],
        "qualified_by_requirement": qualified,
    })
    if not crew:
        decision["allowed"] = False
        decision["findings"].insert(0, {
            "code": "NO_ACTIVE_CREW_SESSION",
            "message": f"No active Crew Session exists for Workstation {workstation}",
        })
    return decision


def enforce_execution_crew(execution_name, checkpoint, actor=None):
    result = evaluate_execution_crew(execution_name, checkpoint, actor=actor, persist=True)
    if not result.get("allowed"):
        _commit_hold_and_throw(result)
    return result


def enforce_operation_crew(
    kanban_master,
    operation,
    workstation,
    checkpoint,
    card_name=None,
    actor=None,
):
    result = evaluate_operation_crew(
        kanban_master, operation, workstation, card_name=card_name
    )
    result.update({
        "checkpoint": checkpoint,
        "kanban_card": card_name,
        "process_execution": None,
        "kanban_cycle": None,
        "job_card": None,
    })
    if result.get("configured"):
        check = _insert_check(result, actor)
        result["check"] = check.name
        if not result.get("allowed"):
            exception = _create_or_update_hold(result, check)
            check.db_set("exception", exception.name, update_modified=False)
            result["exception"] = exception.name
            _commit_hold_and_throw(result)
    return result


def reconcile_workstation_crew_compliance(company, workstation, actor=None):
    """Crew changes never fail silently; they create or clear holds on live executions."""
    rows = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={
            "workstation": workstation,
            "status": ["in", ACTIVE_EXECUTION_STATUSES],
        },
        fields=["name", "kanban_cycle"],
        limit_page_length=0,
    )
    results = []
    for row in rows:
        cycle_company = frappe.db.get_value("CFG Kanban Cycle", row.kanban_cycle, "company")
        if cycle_company and cycle_company != company:
            continue
        result = evaluate_execution_crew(
            row.name, "Crew Change", actor=actor, persist=True
        )
        if not result.get("configured"):
            # An unconfigured operation remains backward compatible, but an
            # already-running execution must still mirror actual crew joins,
            # breaks, resumes, and departures into participation intervals.
            _sync_participation_projection(
                row.name, actor, "Crew Change", result.get("check")
            )
        results.append(result)
    return results


def release_execution_wip_if_authorized(execution_name, checkpoint="Before WIP Release"):
    """ERP feedback must stay authoritative; failed crew coverage holds only the WIP release."""
    result = evaluate_execution_crew(execution_name, checkpoint, persist=True)
    return bool(result.get("allowed"))


def _qualified_by_requirement(policy, active_members):
    result = {}
    for requirement in policy.get("skill_requirements") or []:
        role = requirement.get("participation_role")
        candidates = [row for row in active_members if _eligible_for_role(row, role)]
        result[requirement_key(requirement)] = [
            row.get("employee") for row in candidates
            if employee_has_competency(
                row.get("employee"),
                requirement.get("skill"),
                requirement.get("minimum_level") or "L0",
                require_independent=bool(
                    requirement.get("require_independent_authorization")
                ),
                require_supervisor=bool(
                    requirement.get("require_supervisor_authorization")
                ),
            )
        ]
    return result


def _eligible_for_role(member, participation_role):
    if participation_role == "Direct Worker":
        return member.get("work_category") == DIRECT_WORK
    if participation_role == "Qualified Lead":
        return (
            member.get("work_category") == DIRECT_WORK
            and member.get("crew_role") in LEAD_ROLES
        )
    if participation_role == "Active Supervisor":
        return member.get("crew_role") == SUPERVISOR_ROLE
    return False


def _trainee_employees(policy, active_members):
    direct = [row for row in active_members if row.get("work_category") == DIRECT_WORK]
    requirements = [
        row for row in policy.get("skill_requirements") or []
        if row.get("participation_role") in ("Direct Worker", "Qualified Lead")
    ]
    trainees = []
    for member in direct:
        if not requirements:
            if member.get("crew_role") == "Temporary Support":
                trainees.append(member.get("employee"))
            continue
        independently_qualified = any(
            employee_has_competency(
                member.get("employee"),
                row.get("skill"),
                row.get("minimum_level") or "L0",
                require_independent=True,
            )
            for row in requirements
        )
        if not independently_qualified:
            trainees.append(member.get("employee"))
    return trainees


def _concurrent_direct_employees(active_members, current_session):
    if not current_session:
        return []
    result = []
    for member in active_members:
        if member.get("work_category") != DIRECT_WORK:
            continue
        rows = frappe.db.sql(
            """
            select distinct m.crew_session
            from `tabCFG Kanban Crew Membership` m
            inner join `tabCFG Kanban Crew Session` s on s.name=m.crew_session
            where m.employee=%s and m.status='Active'
              and m.work_category='Direct Participation' and s.status='Active'
            """,
            (member.get("employee"),),
            as_dict=True,
        )
        if len(rows) > 1:
            result.append(member.get("employee"))
    return result


def _persist_execution_decision(execution, result, actor):
    check = _insert_check(result, actor)
    result["check"] = check.name
    current = now_datetime()
    if result.get("allowed"):
        _resolve_execution_hold(execution, check, current, actor)
        return
    exception = _create_or_update_hold(result, check, execution=execution)
    check.db_set("exception", exception.name, update_modified=False)
    previous = execution.get("crew_hold_previous_status")
    if execution.status != "Blocked":
        previous = execution.status
    updates = {
        "crew_compliance_status": "Hold",
        "last_crew_compliance_check": check.name,
        "crew_compliance_hold": exception.name,
        "crew_hold_previous_status": previous,
        "crew_compliance_checked_on": current,
        "status": "Blocked",
        "blocked": 1,
    }
    if not execution.exception:
        updates["exception"] = exception.name
    execution.db_set(updates, update_modified=True)
    _sync_dispatch_projection(execution.name)
    _sync_participation_projection(
        execution.name, actor, "Crew Compliance Hold", check.name
    )
    result["exception"] = exception.name


def _resolve_execution_hold(execution, check, current, actor=None):
    hold = execution.get("crew_compliance_hold")
    updates = {
        "crew_compliance_status": "Compliant",
        "last_crew_compliance_check": check.name,
        "crew_compliance_checked_on": current,
    }
    if hold:
        crew_owns_general_block = not execution.exception or execution.exception == hold
        frappe.db.set_value("CFG Kanban Exception", hold, {
            "status": "Resolved",
            "resolved_on": current,
            "resolved_by": frappe.session.user,
            "resolution": "Active crew again satisfies the effective approved policy",
        })
        if execution.status == "Blocked" and crew_owns_general_block:
            updates["status"] = execution.get("crew_hold_previous_status") or "Ready"
        if execution.exception == hold:
            updates["exception"] = None
            updates["blocked"] = 0
        updates["crew_compliance_hold"] = None
        updates["crew_hold_previous_status"] = None
    execution.db_set(updates, update_modified=True)
    _sync_dispatch_projection(execution.name)
    _sync_participation_projection(
        execution.name, actor, "Crew Compliance Restored", check.name
    )


def _insert_check(result, actor):
    actor = actor or {}
    return frappe.get_doc({
        "doctype": "CFG Kanban Crew Compliance Check",
        "company": result.get("company"),
        "workstation": result.get("workstation"),
        "operation": result.get("operation"),
        "checkpoint": result.get("checkpoint"),
        "result": "Pass" if result.get("allowed") else "Hold",
        "kanban_cycle": result.get("kanban_cycle"),
        "kanban_card": result.get("kanban_card"),
        "process_execution": result.get("process_execution"),
        "job_card": result.get("job_card"),
        "crew_session": result.get("crew_session"),
        "active_direct_workers": result.get("active_direct_workers") or 0,
        "active_assistants": result.get("active_assistants") or 0,
        "active_supervisors": result.get("active_supervisors") or 0,
        "policy_snapshot": json.dumps(result.get("policy") or {}, default=str),
        "crew_snapshot": json.dumps(result.get("members") or [], default=str),
        "findings": json.dumps(result.get("findings") or [], default=str),
        "checked_on": now_datetime(),
        "actor_employee": actor.get("employee"),
        "operator_session": actor.get("operator_session"),
        "terminal_user": actor.get("terminal_user") or frappe.session.user,
    }).insert(ignore_permissions=True)


def _create_or_update_hold(result, check, execution=None):
    existing = execution.get("crew_compliance_hold") if execution else None
    message = "; ".join(row.get("message") for row in result.get("findings") or [])
    if existing and frappe.db.exists("CFG Kanban Exception", existing):
        frappe.db.set_value("CFG Kanban Exception", existing, {
            "status": "Open",
            "message": message,
            "resolved_on": None,
            "resolved_by": None,
            "resolution": None,
            "reference_doctype": check.doctype,
            "reference_name": check.name,
        })
        return frappe.get_doc("CFG Kanban Exception", existing)
    return frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": "Crew Compliance Hold",
        "severity": "Critical",
        "status": "Open",
        "kanban_cycle": result.get("kanban_cycle"),
        "kanban_card": result.get("kanban_card"),
        "process_execution": result.get("process_execution"),
        "message": message,
        "reference_doctype": check.doctype,
        "reference_name": check.name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)


def _member_snapshot(member):
    return {
        key: member.get(key)
        for key in (
            "name", "employee", "employee_name", "operator_profile", "crew_role",
            "work_category", "status", "joined_on", "break_started_on",
        )
    }


def _sync_dispatch_projection(execution_name):
    from cfg_kanban.services.dispatch import dispatch_schema_available, ensure_queue_entry

    if dispatch_schema_available():
        ensure_queue_entry(frappe.get_doc("CFG Kanban Process Execution", execution_name))


def _sync_participation_projection(execution_name, actor, source_event, compliance_check=None):
    from cfg_kanban.services.job_participation import sync_execution_participation

    return sync_execution_participation(
        execution_name,
        actor=actor,
        source_event=source_event,
        compliance_check=compliance_check,
    )


def _commit_hold_and_throw(result):
    # This checkpoint runs before the requested production mutation. Commit only the
    # immutable decision/hold so Frappe's exception rollback cannot erase the safety event.
    frappe.db.commit()
    detail = "; ".join(row.get("message") for row in result.get("findings") or [])
    frappe.throw(
        _("Crew Compliance Hold: {0}").format(detail),
        title=_("Crew authorization required"),
    )

import frappe
from frappe.utils import get_datetime, now_datetime, time_diff_in_seconds

from cfg_kanban.services.crew_policy import get_effective_crew_policy
from cfg_kanban.services.crew_registry import get_active_workstation_crew
from cfg_kanban.services.job_participation_rules import (
    desired_participants,
    segment_identity,
)


RUNNING_EXECUTION_STATUS = "In Progress"


def sync_execution_participation(
    execution_name,
    actor=None,
    source_event="Execution Synchronization",
    compliance_check=None,
):
    """Reconcile active workforce intervals for one Process Execution.

    This ledger never owns or posts production quantity. ERPNext Job Card output is
    counted once; these rows preserve only who participated, in which capacity, and
    for what interval.
    """
    frappe.db.sql(
        "select name from `tabCFG Kanban Process Execution` where name=%s for update",
        execution_name,
    )
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    actor = _actor_context(actor)
    current = now_datetime()
    desired = _desired_for_execution(execution, actor)
    active = frappe.get_all(
        "CFG Kanban Job Participation",
        filters={"process_execution": execution.name, "status": "Active"},
        fields=[
            "name", "employee", "crew_membership", "crew_role", "work_category",
            "participation_source", "started_on",
        ],
        order_by="started_on asc, creation asc",
    )
    desired_by_key = {segment_identity(row): row for row in desired}
    active_by_key = {segment_identity(row): row for row in active}

    closed = []
    for key, row in active_by_key.items():
        if key in desired_by_key:
            continue
        _close_segment(
            row.name,
            current,
            source_event,
            actor,
            _close_reason(execution, source_event),
        )
        closed.append(row.name)

    opened = []
    for key, participant in desired_by_key.items():
        if key in active_by_key:
            continue
        opened.append(
            _open_segment(
                execution,
                participant,
                current,
                source_event,
                actor,
                compliance_check or execution.get("last_crew_compliance_check"),
            ).name
        )
    return {
        "process_execution": execution.name,
        "opened": opened,
        "closed": closed,
        "active_count": len(desired),
        "production_labour_count": len([
            row for row in desired if row["participation_kind"] == "Production Labour"
        ]),
        "oversight_count": len([
            row for row in desired if row["participation_kind"] == "Oversight"
        ]),
    }


def close_execution_participation(
    execution_name,
    actor=None,
    source_event="Execution Closed",
    reason=None,
):
    actor = _actor_context(actor)
    current = now_datetime()
    rows = frappe.get_all(
        "CFG Kanban Job Participation",
        filters={"process_execution": execution_name, "status": "Active"},
        fields=["name"],
        order_by="started_on asc, creation asc",
    )
    for row in rows:
        _close_segment(
            row.name,
            current,
            source_event,
            actor,
            reason or source_event,
        )
    return {"process_execution": execution_name, "closed": [row.name for row in rows]}


@frappe.whitelist()
def get_execution_participation(process_execution):
    if not frappe.has_permission("CFG Kanban Job Participation", "read"):
        frappe.throw("Not permitted to read Employee Job Participation", frappe.PermissionError)
    rows = frappe.get_all(
        "CFG Kanban Job Participation",
        filters={"process_execution": process_execution},
        fields=[
            "name", "employee", "employee_name", "crew_role", "work_category",
            "participation_kind", "participation_source", "status", "started_on",
            "ended_on", "duration_seconds", "duration_hours", "source_event",
        ],
        order_by="started_on asc, creation asc",
    )
    direct_seconds = sum(
        row.duration_seconds or 0 for row in rows
        if row.participation_kind == "Production Labour"
    )
    oversight_seconds = sum(
        row.duration_seconds or 0 for row in rows
        if row.participation_kind == "Oversight"
    )
    return {
        "process_execution": process_execution,
        "rows": rows,
        "direct_labour_seconds": direct_seconds,
        "oversight_seconds": oversight_seconds,
    }


def _desired_for_execution(execution, actor):
    if execution.status != RUNNING_EXECUTION_STATUS:
        return []
    if execution.get("crew_compliance_status") == "Hold" or execution.get("blocked"):
        return []
    cycle = frappe.get_cached_doc("CFG Kanban Cycle", execution.kanban_cycle)
    master = frappe.get_cached_doc("CFG Kanban Master", execution.kanban_master)
    policy = get_effective_crew_policy(
        execution.kanban_master,
        execution.operation,
        workstation=execution.workstation,
        card_name=cycle.kanban_card,
    )
    if policy.get("configured") and execution.get("crew_compliance_status") != "Compliant":
        return []
    crew = get_active_workstation_crew(master.company, execution.workstation)
    members = []
    if crew:
        members = [dict(row, crew_session=crew["session"].name) for row in crew["members"]]
    fallback = actor if not policy.get("configured") else None
    return desired_participants(members, fallback_actor=fallback)


def _open_segment(execution, participant, current, source_event, actor, compliance_check):
    cycle = frappe.get_cached_doc("CFG Kanban Cycle", execution.kanban_cycle)
    master = frappe.get_cached_doc("CFG Kanban Master", execution.kanban_master)
    job_card = execution.job_card
    work_order = (
        frappe.db.get_value("Job Card", job_card, "work_order") if job_card else cycle.work_order
    )
    return frappe.get_doc({
        "doctype": "CFG Kanban Job Participation",
        "process_execution": execution.name,
        "kanban_cycle": execution.kanban_cycle,
        "kanban_master": execution.kanban_master,
        "company": master.company,
        "work_order": work_order,
        "job_card": job_card,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "employee": participant["employee"],
        "employee_name": participant.get("employee_name") or participant["employee"],
        "operator_profile": participant.get("operator_profile"),
        "crew_session": participant.get("crew_session"),
        "crew_membership": participant.get("crew_membership"),
        "crew_role": participant["crew_role"],
        "work_category": participant["work_category"],
        "participation_kind": participant["participation_kind"],
        "participation_source": participant["participation_source"],
        "status": "Active",
        "started_on": current,
        "source_event": source_event,
        "crew_compliance_check": compliance_check,
        "started_by_employee": actor.get("employee"),
        "operator_session": actor.get("operator_session"),
        "terminal_user": actor.get("terminal_user") or frappe.session.user,
    }).insert(ignore_permissions=True)


def _close_segment(name, current, source_event, actor, reason):
    segment = frappe.get_doc("CFG Kanban Job Participation", name)
    seconds = max(
        0,
        time_diff_in_seconds(get_datetime(current), get_datetime(segment.started_on)),
    )
    segment.db_set({
        "status": "Closed",
        "ended_on": current,
        "duration_seconds": seconds,
        "duration_hours": seconds / 3600,
        "close_event": source_event,
        "close_reason": reason,
        "ended_by_employee": actor.get("employee"),
        "ended_operator_session": actor.get("operator_session"),
        "ended_terminal_user": actor.get("terminal_user") or frappe.session.user,
    }, update_modified=True)


def _actor_context(actor):
    actor = actor or {}
    employee = actor.get("employee")
    if employee and not actor.get("employee_name"):
        actor = dict(actor)
        actor["employee_name"] = frappe.db.get_value(
            "Employee", employee, "employee_name"
        ) or employee
    if employee and not actor.get("operator_profile"):
        actor = dict(actor)
        actor["operator_profile"] = frappe.db.get_value(
            "CFG Kanban Operator Profile", {"employee": employee, "active": 1}, "name"
        )
    return actor


def _close_reason(execution, source_event):
    if execution.status != RUNNING_EXECUTION_STATUS:
        return f"Execution state changed to {execution.status}"
    if execution.get("crew_compliance_status") == "Hold" or execution.get("blocked"):
        return "Crew authorization is on hold"
    return source_event

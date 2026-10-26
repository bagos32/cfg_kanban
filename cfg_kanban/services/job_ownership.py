import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.events import record


def ownership_context(cycle, operator_profile=None):
    if isinstance(cycle, str):
        cycle = frappe.get_doc("CFG Kanban Cycle", cycle)
    enabled = bool(cycle.get("enforce_job_owner"))
    employee = operator_profile.employee if operator_profile else None
    eligible = bool(
        enabled
        and operator_profile
        and cycle.owner_job_code in [
            row.job_code for row in (operator_profile.get("job_codes") or [])
        ]
    )
    return {
        "enabled": enabled,
        "required_job_code": cycle.get("owner_job_code"),
        "owner": cycle.get("job_owner"),
        "owner_name": cycle.get("job_owner_name"),
        "owner_operator_profile": cycle.get("job_owner_operator_profile"),
        "assigned_on": cycle.get("job_owner_assigned_on"),
        "assignment": cycle.get("active_owner_assignment"),
        "eligible_to_accept": bool(eligible and not cycle.get("job_owner")),
        "owned_by_current_operator": bool(employee and cycle.get("job_owner") == employee),
        "status": (
            "Not Required" if not enabled
            else "Owned" if cycle.get("job_owner")
            else "Awaiting Eligible Owner"
        ),
    }


def accept_cycle_ownership(cycle_name, operator_profile, operator_session, crew_result=None):
    """Atomically assign the first eligible operator-in-charge for this Cycle."""
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update",
        (cycle_name,),
    )
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if not cycle.get("enforce_job_owner"):
        return ownership_context(cycle, operator_profile)
    if cycle.job_owner:
        # Ownership does not prohibit assistants or other authorized participants
        # from executing later operations. It identifies who remains in charge.
        return ownership_context(cycle, operator_profile)
    if cycle.status in ("Completed", "Cancelled"):
        frappe.throw(f"Ownership cannot be accepted for a {cycle.status} Cycle")

    assigned_codes = [
        row.job_code for row in (operator_profile.get("job_codes") or [])
    ]
    if cycle.owner_job_code not in assigned_codes:
        frappe.throw(
            f"This Card requires Job Code {cycle.owner_job_code}. "
            f"Operator {operator_profile.employee_name or operator_profile.employee} "
            "cannot accept Cycle ownership."
        )
    job_code = frappe.db.get_value(
        "CFG Kanban Job Code", cycle.owner_job_code,
        ["active", "company"], as_dict=True,
    )
    if not job_code or not job_code.active:
        frappe.throw(f"Required Job Code {cycle.owner_job_code} is not active")
    if job_code.company and cycle.company and job_code.company != cycle.company:
        frappe.throw(
            f"Required Job Code {cycle.owner_job_code} does not belong to {cycle.company}"
        )
    _assert_direct_crew_participant(operator_profile.employee, crew_result)

    assigned_on = now_datetime()
    employee_name = (
        operator_profile.employee_name
        or frappe.db.get_value("Employee", operator_profile.employee, "employee_name")
        or operator_profile.employee
    )
    assignment = frappe.get_doc({
        "doctype": "CFG Kanban Job Owner Assignment",
        "kanban_cycle": cycle.name,
        "kanban_card": cycle.kanban_card,
        "company": cycle.company,
        "job_code": cycle.owner_job_code,
        "employee": operator_profile.employee,
        "employee_name": employee_name,
        "operator_profile": operator_profile.name,
        "status": "Active",
        "assigned_on": assigned_on,
        "assignment_source": "First Operation Start",
        "assignment_reason": "Eligible operator accepted ownership while starting Cycle work.",
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
    }).insert(ignore_permissions=True)
    cycle.db_set({
        "job_owner": operator_profile.employee,
        "job_owner_name": employee_name,
        "job_owner_operator_profile": operator_profile.name,
        "job_owner_assigned_on": assigned_on,
        "active_owner_assignment": assignment.name,
    }, update_modified=True)
    record(
        "Cycle Ownership Accepted",
        card=cycle.kanban_card,
        cycle=cycle.name,
        reference_doctype=assignment.doctype,
        reference_name=assignment.name,
        notes=f"{employee_name} accepted {cycle.owner_job_code} ownership.",
        operator=operator_profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    cycle.reload()
    from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
    evaluate_cycle_roles(cycle.name, persist=True)
    return ownership_context(cycle, operator_profile)


def close_cycle_ownership(cycle, reason):
    """End the active ownership interval while retaining the historical owner snapshot."""
    if isinstance(cycle, str):
        cycle = frappe.get_doc("CFG Kanban Cycle", cycle)
    assignment_name = cycle.get("active_owner_assignment")
    if not assignment_name:
        return None
    assignment = frappe.get_doc("CFG Kanban Job Owner Assignment", assignment_name)
    if assignment.status == "Active":
        assignment.db_set({
            "status": "Ended",
            "ended_on": now_datetime(),
            "assignment_reason": (
                (assignment.assignment_reason or "") + f"\nEnded: {reason}"
            ).strip(),
        }, update_modified=True)
    cycle.db_set("active_owner_assignment", None, update_modified=False)
    record(
        "Cycle Ownership Ended",
        card=cycle.kanban_card,
        cycle=cycle.name,
        reference_doctype=assignment.doctype,
        reference_name=assignment.name,
        notes=reason,
    )
    return assignment.name


def _assert_direct_crew_participant(employee, crew_result):
    if not crew_result or not crew_result.get("configured"):
        return
    member = next(
        (
            row for row in crew_result.get("members") or []
            if row.get("employee") == employee and row.get("status") == "Active"
        ),
        None,
    )
    if not member or member.get("work_category") != "Direct Participation":
        frappe.throw(
            "The Cycle owner must be an active Direct Participation member of the "
            "authorized workstation crew. Oversight-only members remain participants, "
            "not the operator-in-charge."
        )

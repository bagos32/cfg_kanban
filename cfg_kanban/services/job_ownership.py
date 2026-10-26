import frappe
from frappe.utils import cint, now_datetime

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


def validate_transfer_target(cycle, execution, target_profile):
    """Validate a replacement owner against the immutable Cycle policy and live crew."""
    if isinstance(cycle, str):
        cycle = frappe.get_doc("CFG Kanban Cycle", cycle)
    if getattr(execution, "doctype", None) != "CFG Kanban Process Execution":
        execution = frappe.get_doc("CFG Kanban Process Execution", execution)
    if not cycle.get("enforce_job_owner"):
        frappe.throw("Job Owner enforcement is not enabled for this Cycle")
    if cycle.status in ("Completed", "Cancelled"):
        frappe.throw(f"Ownership cannot be transferred for a {cycle.status} Cycle")
    if not cycle.get("job_owner") or not cycle.get("active_owner_assignment"):
        frappe.throw("This Cycle does not have an active owner to transfer")
    if target_profile.employee == cycle.job_owner:
        frappe.throw("The scanned replacement operator is already the Cycle owner")

    assigned_codes = [row.job_code for row in (target_profile.get("job_codes") or [])]
    if cycle.owner_job_code not in assigned_codes:
        frappe.throw(
            f"Replacement operator requires Job Code {cycle.owner_job_code}"
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

    from cfg_kanban.services.crew_authorization import evaluate_execution_crew
    crew_result = evaluate_execution_crew(
        execution.name, "Ownership Transfer Target", persist=False
    )
    _assert_direct_crew_participant(target_profile.employee, crew_result)
    _assert_owner_role_requirements(cycle, target_profile)
    return target_profile


def transfer_cycle_ownership(
    cycle_name,
    execution,
    target_profile,
    requester_profile,
    operator_session,
    reason,
    supervisor_approval,
):
    """End the old interval and create a linked owner interval without rewriting history."""
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("An ownership transfer reason is required")
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update",
        (cycle_name,),
    )
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    validate_transfer_target(cycle, execution, target_profile)
    previous_assignment = frappe.get_doc(
        "CFG Kanban Job Owner Assignment", cycle.active_owner_assignment
    )
    if previous_assignment.status != "Active":
        frappe.throw("The current owner assignment is no longer active; refresh the Card")

    assigned_on = now_datetime()
    target_name = (
        target_profile.employee_name
        or frappe.db.get_value("Employee", target_profile.employee, "employee_name")
        or target_profile.employee
    )
    previous_owner = cycle.job_owner
    previous_owner_name = cycle.job_owner_name or previous_owner
    previous_assignment.db_set({
        "status": "Ended",
        "ended_on": assigned_on,
        "assignment_reason": (
            (previous_assignment.assignment_reason or "")
            + f"\nTransferred to {target_name}: {reason}"
        ).strip(),
    }, update_modified=True)
    assignment = frappe.get_doc({
        "doctype": "CFG Kanban Job Owner Assignment",
        "kanban_cycle": cycle.name,
        "kanban_card": cycle.kanban_card,
        "company": cycle.company,
        "job_code": cycle.owner_job_code,
        "employee": target_profile.employee,
        "employee_name": target_name,
        "operator_profile": target_profile.name,
        "status": "Active",
        "assigned_on": assigned_on,
        "assignment_source": "Supervisor Ownership Transfer",
        "assignment_reason": reason,
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
        "previous_assignment": previous_assignment.name,
        "supervisor_action_approval": supervisor_approval.name,
    }).insert(ignore_permissions=True)
    cycle.db_set({
        "job_owner": target_profile.employee,
        "job_owner_name": target_name,
        "job_owner_operator_profile": target_profile.name,
        "job_owner_assigned_on": assigned_on,
        "active_owner_assignment": assignment.name,
    }, update_modified=True)
    record(
        "Cycle Ownership Transferred",
        card=cycle.kanban_card,
        cycle=cycle.name,
        execution=execution.name,
        reference_doctype=assignment.doctype,
        reference_name=assignment.name,
        notes=(
            f"{previous_owner_name} → {target_name}; {reason}; "
            f"approval {supervisor_approval.name}"
        ),
        operator=requester_profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
        system_generated=False,
        ignore_permissions=True,
    )
    from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
    evaluate_cycle_roles(cycle.name, persist=True)
    cycle.reload()
    result = ownership_context(cycle, requester_profile)
    result.update({
        "previous_owner": previous_owner,
        "previous_owner_name": previous_owner_name,
        "new_owner": target_profile.employee,
        "new_owner_name": target_name,
        "new_assignment": assignment.name,
        "previous_assignment": previous_assignment.name,
        "supervisor_action_approval": supervisor_approval.name,
    })
    return result


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


def _assert_owner_role_requirements(cycle, target_profile):
    """Do not let a transfer weaken immutable Operator-in-Charge requirements."""
    requirements = [
        row for row in (cycle.get("job_role_requirements_snapshot") or [])
        if row.assignment_type == "Operator-in-Charge"
    ]
    if not requirements:
        return
    from cfg_kanban.services.authority import has_authority_role
    from cfg_kanban.services.competency import employee_has_competency

    assigned_codes = [row.job_code for row in (target_profile.get("job_codes") or [])]
    context = {
        "company": cycle.company,
        # Cycle ownership spans every operation. Match the same company-wide
        # context used by the runtime Operator-in-Charge candidate.
        "operation": None,
        "workstation": None,
        "responsibility": None,
    }
    for requirement in requirements:
        if requirement.job_code and requirement.job_code not in assigned_codes:
            frappe.throw(
                f"Replacement operator does not satisfy Operator-in-Charge Job Code "
                f"{requirement.job_code}"
            )
        if requirement.job_code:
            job_code = frappe.get_cached_doc(
                "CFG Kanban Job Code", requirement.job_code
            )
            if not cint(job_code.active) or (
                job_code.company and job_code.company != cycle.company
            ):
                frappe.throw(
                    f"Operator-in-Charge Job Code {requirement.job_code} is not active "
                    f"for {cycle.company}"
                )
        if requirement.authority_role and not has_authority_role(
            target_profile, requirement.authority_role, context=context
        ):
            frappe.throw(
                f"Replacement operator does not hold scoped Operator-in-Charge authority "
                f"{requirement.authority_role}"
            )
        if requirement.skill and not employee_has_competency(
            target_profile.employee,
            requirement.skill,
            requirement.minimum_competency_level or "L0",
            require_independent=bool(
                cint(requirement.require_independent_authorization)
                and not cint(requirement.allow_supervised_trainee)
            ),
            require_supervisor=False,
        ):
            frappe.throw(
                f"Replacement operator does not satisfy Operator-in-Charge competency "
                f"{requirement.skill} at {requirement.minimum_competency_level or 'L0'}"
            )

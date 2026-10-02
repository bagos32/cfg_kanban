import frappe
from frappe.utils import cint


def responsibility_names(profile):
    return {row.responsibility for row in profile.responsibilities if row.responsibility}


def can_view_all_service_tasks(profile):
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and cint(profile.get("view_all_responsibilities"))
    )


def workstation_allowed(workstation, profile):
    allowed = {row.workstation for row in profile.allowed_workstations if row.workstation}
    return bool(not workstation or not allowed or workstation in allowed)


def responsibility_allowed(responsible_role, profile):
    responsibilities = responsibility_names(profile)
    return bool(
        can_view_all_service_tasks(profile)
        or not responsible_role
        or not responsibilities
        or responsible_role in responsibilities
    )


def can_access_service_task(task, profile):
    if not workstation_allowed(task.workstation, profile):
        return False
    if task.assigned_employee == profile.employee:
        return True
    if not responsibility_allowed(task.responsible_role, profile):
        return False
    if not task.assigned_employee:
        return True
    if can_view_all_service_tasks(profile):
        return True
    return bool(
        task.status == "Awaiting Verification"
        and cint(profile.get("can_verify_tasks"))
        and profile.kanban_role in ("Supervisor", "Development Proxy")
    )


def can_view_service_task(task, profile, assigned_operator_role=None):
    """Permit scoped monitoring without granting control of another operator's task."""
    if can_access_service_task(task, profile):
        return True
    if (
        profile.kanban_role not in ("Supervisor", "Development Proxy")
        or not task.assigned_employee
        or not task.started_on
        or task.status not in ("In Progress", "Overdue", "Correction Required")
        or not workstation_allowed(task.workstation, profile)
        or not responsibility_allowed(task.responsible_role, profile)
    ):
        return False
    if assigned_operator_role is None:
        assigned_operator_role = frappe.db.get_value(
            "CFG Kanban Operator Profile",
            {"employee": task.assigned_employee, "active": 1},
            "kanban_role",
        )
    return assigned_operator_role in ("Operator", "Senior Operator")


def assert_service_task_access(task, profile):
    if can_access_service_task(task, profile):
        return
    if task.assigned_employee and task.assigned_employee != profile.employee:
        frappe.throw(
            f"Task is assigned to Employee {task.assigned_employee}. "
            "Enable View All Service Tasks for controlled Supervisor access."
        )
    frappe.throw("Operator is not assigned to this Task responsibility")


def assert_responsibility(responsible_role, profile):
    if not responsibility_allowed(responsible_role, profile):
        frappe.throw("Operator is not assigned to this Task responsibility")

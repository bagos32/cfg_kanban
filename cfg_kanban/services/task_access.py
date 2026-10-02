import frappe
from frappe.utils import cint


def responsibility_names(profile):
    return {row.responsibility for row in profile.responsibilities if row.responsibility}


def can_view_all_service_tasks(profile):
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and cint(profile.get("view_all_responsibilities"))
    )


def responsibility_allowed(responsible_role, profile):
    responsibilities = responsibility_names(profile)
    return bool(
        can_view_all_service_tasks(profile)
        or not responsible_role
        or not responsibilities
        or responsible_role in responsibilities
    )


def can_access_service_task(task, profile):
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

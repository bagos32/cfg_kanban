import frappe

from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.media import list_reference_media
from cfg_kanban.services.standalone_tasks import (complete_task, create_manual, start_task,
                                                  disposition_task, reject_task, resolve_service_point,
                                                  progress_task, task_form, verify_task)
from cfg_kanban.services.printing import get_qr_svg


@frappe.whitelist()
def get_open_tasks(operator_session_token=None):
    profile, _session = require_operator(operator_session_token)
    filters = {"status": ["not in", ("Completed", "Cancelled", "Bypassed")]}
    allowed_workstations = [row.workstation for row in profile.allowed_workstations
                            if row.workstation]
    if allowed_workstations:
        filters["workstation"] = ["in", allowed_workstations]
    rows = frappe.get_all(
        "CFG Kanban Task", filters=filters,
        fields=["name", "task_name", "task_category", "status", "priority", "requested_on",
                "due_on", "assigned_employee", "workstation", "asset", "location",
                "verification_required", "task_schedule", "trigger_type", "started_on"],
        order_by="priority desc, due_on asc, creation asc", limit_page_length=200,
    )
    if profile.kanban_role != "Supervisor":
        rows = [row for row in rows
                if not row.assigned_employee or row.assigned_employee == profile.employee]
    return rows


@frappe.whitelist()
def get_request_schedules(operator_session_token=None):
    profile, _session = require_operator(operator_session_token, "task_start")
    if profile.kanban_role not in ("Senior Operator", "Supervisor", "Development Proxy"):
        frappe.throw("Only a Senior Operator or Supervisor can create an unplanned Service Task")
    return frappe.get_all(
        "CFG Kanban Task Schedule", filters={"active": 1},
        fields=["name", "schedule_name", "task_name", "task_category", "trigger_type",
                "priority", "workstation", "asset", "location"],
        order_by="task_name asc, schedule_name asc", limit_page_length=200,
    )


@frappe.whitelist()
def supervisor_request_task(schedule_name, request_source, priority=None, event_token=None,
                            operator_session_token=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    profile, _session = require_operator(
        operator_session_token, "task_start", workstation=schedule.workstation
    )
    if profile.kanban_role not in ("Senior Operator", "Supervisor", "Development Proxy"):
        frappe.throw("Only a Senior Operator or Supervisor can create an unplanned Service Task")
    return create_manual(schedule_name, request_source, priority, event_token).as_dict()


@frappe.whitelist()
def request_task(schedule_name, request_source, priority=None, event_token=None,
                 operator_session_token=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    if operator_session_token:
        require_operator(operator_session_token, "task_start", workstation=schedule.workstation)
    else:
        frappe.only_for(("Manufacturing Manager", "System Manager"))
    return create_manual(schedule_name, request_source, priority, event_token).as_dict()


@frappe.whitelist()
def get_task_form(task_name, capture_on="Complete", operator_session_token=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    action = {"Start": "task_start", "Verify": "task_verify"}.get(capture_on, "task_complete")
    require_operator(operator_session_token, action, workstation=task.workstation)
    result = task_form(task_name, capture_on)
    result["media"] = list_reference_media("CFG Kanban Task", task.name,
                                           permission_checked=True)
    return result


@frappe.whitelist()
def start(task_name, operator_session_token, values=None, notes=None):
    return start_task(task_name, operator_session_token, values).as_dict()


@frappe.whitelist()
def progress(task_name, operator_session_token, values=None, notes=None):
    return progress_task(task_name, operator_session_token, values, notes).as_dict()


@frappe.whitelist()
def complete(task_name, operator_session_token, values=None, checklist_results=None, notes=None):
    return complete_task(task_name, operator_session_token, values,
                         checklist_results, notes).as_dict()


@frappe.whitelist()
def verify(task_name, operator_session_token, values=None, notes=None):
    return verify_task(task_name, operator_session_token, values, notes).as_dict()


@frappe.whitelist()
def reject(task_name, operator_session_token, notes):
    return reject_task(task_name, operator_session_token, notes).as_dict()


@frappe.whitelist()
def resolve_service_scan(scan_value, operator_session_token):
    return resolve_service_point(scan_value, operator_session_token)


@frappe.whitelist()
def get_service_point_label(schedule_name):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    payload = schedule.service_point_code or f"CFG:SERVICE:SCHEDULE:{schedule.name}"
    return {"schedule": schedule.as_dict(), "payload": payload, "qr_svg": get_qr_svg(payload)}


@frappe.whitelist()
def supervisor_disposition(task_name, disposition, reason, operator_session_token):
    return disposition_task(task_name, operator_session_token, disposition, reason).as_dict()

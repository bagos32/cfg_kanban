import frappe

from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.media import list_reference_media
from cfg_kanban.services.standalone_tasks import (complete_task, create_manual, start_task,
                                                  disposition_task, reject_task, resolve_service_point,
                                                  progress_task, task_form, verify_task)
from cfg_kanban.services.printing import get_qr_svg
from cfg_kanban.services.task_access import (
    assert_responsibility,
    assert_service_task_access,
    can_access_service_task,
    can_view_all_service_tasks,
    responsibility_names,
)


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
                "verification_required", "task_schedule", "trigger_type", "started_on",
                "responsible_role", "progress_count", "last_progress_by",
                "last_progress_on", "last_progress_summary", "verification_notes",
                "verified_by", "verified_on", "modified"],
        order_by="priority desc, due_on asc, creation asc", limit_page_length=200,
    )
    return [row for row in rows if can_access_service_task(row, profile)]


@frappe.whitelist()
def get_request_schedules(operator_session_token=None):
    profile, _session = require_operator(operator_session_token, "task_start")
    if profile.kanban_role not in ("Senior Operator", "Supervisor", "Development Proxy"):
        frappe.throw("Only a Senior Operator or Supervisor can create an unplanned Service Task")
    rows = frappe.get_all(
        "CFG Kanban Task Schedule", filters={"active": 1},
        fields=["name", "schedule_name", "task_name", "task_category", "trigger_type",
                "priority", "workstation", "asset", "location", "responsible_role"],
        order_by="task_name asc, schedule_name asc", limit_page_length=200,
    )
    if can_view_all_service_tasks(profile) or not responsibility_names(profile):
        return rows
    return [row for row in rows
            if not row.responsible_role or row.responsible_role in responsibility_names(profile)]


@frappe.whitelist()
def supervisor_request_task(schedule_name, request_source, priority=None, event_token=None,
                            operator_session_token=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    profile, _session = require_operator(
        operator_session_token, "task_start", workstation=schedule.workstation
    )
    if profile.kanban_role not in ("Senior Operator", "Supervisor", "Development Proxy"):
        frappe.throw("Only a Senior Operator or Supervisor can create an unplanned Service Task")
    assert_responsibility(schedule.responsible_role, profile)
    task = create_manual(schedule_name, request_source, priority, event_token)
    assert_service_task_access(task, profile)
    return task.as_dict()


@frappe.whitelist()
def request_task(schedule_name, request_source, priority=None, event_token=None,
                 operator_session_token=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    profile = None
    if operator_session_token:
        profile, _session = require_operator(
            operator_session_token, "task_start", workstation=schedule.workstation
        )
        assert_responsibility(schedule.responsible_role, profile)
    else:
        frappe.only_for(("Manufacturing Manager", "System Manager"))
    task = create_manual(schedule_name, request_source, priority, event_token)
    if profile:
        assert_service_task_access(task, profile)
    return task.as_dict()


@frappe.whitelist()
def get_task_form(task_name, capture_on="Complete", operator_session_token=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    action = {"Start": "task_start", "Verify": "task_verify"}.get(capture_on, "task_complete")
    profile, _session = require_operator(
        operator_session_token, action, workstation=task.workstation
    )
    assert_service_task_access(task, profile)
    result = task_form(task_name, capture_on)
    result["media"] = list_reference_media("CFG Kanban Task", task.name,
                                           permission_checked=True)
    return result


@frappe.whitelist()
def get_task_progress(task_name, operator_session_token=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, _session = require_operator(operator_session_token, workstation=task.workstation)
    assert_service_task_access(task, profile)
    rows = [row.as_dict() for row in task.execution_values if row.capture_on == "Progress"]
    rows.sort(key=lambda row: str(row.get("captured_on") or ""), reverse=True)
    events = frappe.get_all(
        "CFG Kanban Event",
        filters={"standalone_task": task.name,
                 "event_type": "Standalone Task Progress Reported"},
        fields=["event_datetime", "operator", "notes", "reference_name"],
        order_by="event_datetime desc", limit_page_length=100,
    )
    return {
        "task": task.name,
        "progress_count": task.progress_count or 0,
        "last_progress_by": task.last_progress_by,
        "last_progress_on": task.last_progress_on,
        "last_progress_summary": task.last_progress_summary,
        "values": rows,
        "events": events,
    }


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

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from cfg_kanban.services.dynamic_forms import (normalized_values, standalone_definitions,
                                               validate_values)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator


def generate_due_tasks():
    """Hourly scheduler entry; generates only standalone tasks, never manufacturing records."""
    schedules = frappe.get_all(
        "CFG Kanban Task Schedule",
        filters={"active": 1, "trigger_type": ["in", ("Time Interval", "Calendar Schedule")],
                 "next_due_on": ["<=", now_datetime()]},
        fields=["name", "next_due_on"],
    )
    return [create_from_schedule(row.name, scheduled_for=row.next_due_on).name
            for row in schedules]


def create_from_schedule(schedule_name, scheduled_for=None, request_source=None,
                         generation_marker=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    if not schedule.active:
        frappe.throw("This Task Schedule is inactive")
    scheduled_for = scheduled_for or schedule.next_due_on or now_datetime()
    key = canonical_key("standalone-task", schedule.name, generation_marker or scheduled_for)
    existing = frappe.db.get_value("CFG Kanban Task", {"generation_key": key}, "name")
    if existing:
        return frappe.get_doc("CFG Kanban Task", existing)
    requested_on = now_datetime()
    due_on = add_to_date(requested_on, hours=schedule.default_due_hours or 24)
    task = frappe.get_doc({
        "doctype": "CFG Kanban Task",
        "task_name": schedule.task_name,
        "task_category": schedule.task_category,
        "task_schedule": schedule.name,
        "company": schedule.company,
        "trigger_type": schedule.trigger_type,
        "request_source": request_source or "Schedule",
        "generation_key": key,
        "status": "Due",
        "priority": schedule.priority,
        "requested_on": requested_on,
        "due_on": due_on,
        "responsible_role": schedule.responsible_role,
        "workstation": schedule.workstation,
        "asset": schedule.asset,
        "location": schedule.location,
        "checklist": schedule.checklist,
        "verification_required": schedule.require_supervisor_verification,
        "instructions": schedule.instructions,
    }).insert(ignore_permissions=True)
    schedule_values = {"last_generated_on": requested_on}
    if schedule.trigger_type in ("Time Interval", "Calendar Schedule"):
        schedule_values["next_due_on"] = _next_due(schedule, scheduled_for)
    schedule.db_set(schedule_values, update_modified=False)
    record("Standalone Task Created", reference_doctype=task.doctype,
           reference_name=task.name, standalone_task=task.name,
           notes=f"Generated from {schedule.name}")
    return task


def create_manual(schedule_name, request_source, priority=None, event_token=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    task = create_from_schedule(schedule.name, scheduled_for=now_datetime(),
                                request_source=request_source or "Manual Request",
                                generation_marker=event_token)
    if priority:
        task.db_set("priority", priority)
        task.priority = priority
    return task


def task_form(task_name, capture_on):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    rows = (standalone_definitions(task.task_schedule, capture_on)
            if task.task_schedule else [])
    return {"task": task.as_dict(), "fields": rows}


def start_task(task_name, session_token, values=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(session_token, "task_start", workstation=task.workstation)
    _validate_assignment(task, profile)
    if task.status == "In Progress":
        return task
    if task.status not in ("Planned", "Due", "Assigned", "Overdue"):
        frappe.throw(f"Task cannot start while it is {task.status}")
    _apply_values(task, "Start", values)
    task.status = "In Progress"
    task.assigned_employee = task.assigned_employee or profile.employee
    task.started_by = profile.employee
    task.started_on = now_datetime()
    task.save(ignore_permissions=True)
    _task_event("Standalone Task Started", task, profile, session)
    return task


def complete_task(task_name, session_token, values=None, checklist_results=None, notes=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(session_token, "task_complete", workstation=task.workstation)
    _validate_assignment(task, profile)
    if task.status == "Completed":
        return task
    if task.status not in ("Due", "Assigned", "In Progress", "Overdue"):
        frappe.throw(f"Task cannot complete while it is {task.status}")
    _apply_values(task, "Complete", values)
    _apply_checklist(task, checklist_results)
    task.completed_by = profile.employee
    task.completed_on = now_datetime()
    task.completion_notes = notes
    task.status = "Awaiting Verification" if task.verification_required else "Completed"
    task.save(ignore_permissions=True)
    _task_event("Standalone Task Completed" if task.status == "Completed"
                else "Standalone Task Awaiting Verification", task, profile, session)
    return task


def verify_task(task_name, session_token, values=None, notes=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(session_token, "task_verify", workstation=task.workstation)
    if task.status == "Completed":
        return task
    if task.status != "Awaiting Verification":
        frappe.throw(f"Task cannot be verified while it is {task.status}")
    if task.completed_by == profile.employee:
        frappe.throw("Task verification must be performed by a different operator")
    _apply_values(task, "Verify", values)
    task.status = "Completed"
    task.verified_by = profile.employee
    task.verified_on = now_datetime()
    task.completion_notes = notes or task.completion_notes
    task.save(ignore_permissions=True)
    _task_event("Standalone Task Verified", task, profile, session)
    return task


def update_overdue_tasks():
    current = now_datetime()
    names = frappe.get_all(
        "CFG Kanban Task",
        filters={"status": ["in", ("Planned", "Due", "Assigned", "In Progress")],
                 "due_on": ["<", current]}, pluck="name",
    )
    for name in names:
        frappe.db.set_value("CFG Kanban Task", name, "status", "Overdue")
    return names


def _apply_values(task, capture_on, supplied):
    rows = standalone_definitions(task.task_schedule, capture_on) if task.task_schedule else []
    supplied = frappe.parse_json(supplied) if isinstance(supplied, str) else (supplied or [])
    validate_values(rows, supplied)
    existing = {row.field_key: row for row in task.execution_values}
    for value in normalized_values(rows, supplied):
        if value["field_key"] in existing:
            existing[value["field_key"]].update(value)
        else:
            task.append("execution_values", value)


def _apply_checklist(task, supplied):
    expected = [line.strip() for line in (task.checklist or "").splitlines() if line.strip()]
    supplied = frappe.parse_json(supplied) if isinstance(supplied, str) else (supplied or [])
    completed = {row.get("item") for row in supplied if cint(row.get("completed"))}
    missing = [item for item in expected if item not in completed]
    if missing:
        frappe.throw("Complete all checklist items: " + ", ".join(missing))
    task.checklist_results = frappe.as_json(supplied)


def _next_due(schedule, base):
    if schedule.trigger_type == "Calendar Schedule":
        return add_to_date(base, days=schedule.calendar_repeat_days or 1)
    value = schedule.interval_value or 1
    kwargs = {"hours": value}
    if schedule.interval_unit == "Days":
        kwargs = {"days": value}
    elif schedule.interval_unit == "Weeks":
        kwargs = {"days": value * 7}
    elif schedule.interval_unit == "Months":
        kwargs = {"months": value}
    return add_to_date(base, **kwargs)


def _task_event(event_type, task, profile, session):
    record(event_type, reference_doctype=task.doctype, reference_name=task.name,
           standalone_task=task.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)


def _validate_assignment(task, profile):
    if (task.assigned_employee and task.assigned_employee != profile.employee
            and profile.kanban_role != "Supervisor"):
        frappe.throw(f"Task is assigned to Employee {task.assigned_employee}")

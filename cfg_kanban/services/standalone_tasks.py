import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

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
    created = []
    for row in schedules:
        task = create_from_schedule(row.name, scheduled_for=row.next_due_on)
        if task:
            created.append(task.name)
    return created


def create_from_schedule(schedule_name, scheduled_for=None, request_source=None,
                         generation_marker=None):
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    if not schedule.active:
        frappe.throw("This Task Schedule is inactive")
    if (schedule.overlap_policy or "Prevent While Open") == "Prevent While Open":
        open_name = frappe.db.get_value(
            "CFG Kanban Task",
            {"task_schedule": schedule.name,
             "status": ["not in", ("Completed", "Cancelled")]},
            "name", order_by="due_on asc, creation asc",
        )
        if open_name:
            return frappe.get_doc("CFG Kanban Task", open_name)
    scheduled_for = scheduled_for or schedule.next_due_on or now_datetime()
    if request_source in (None, "Schedule") and _is_skipped_holiday(schedule, scheduled_for):
        schedule.db_set({"last_generated_on": now_datetime(),
                         "next_due_on": _next_due(schedule, scheduled_for)},
                        update_modified=False)
        record("Scheduled Task Skipped for Holiday", reference_doctype=schedule.doctype,
               reference_name=schedule.name,
               notes=f"No occurrence generated for {scheduled_for}")
        return None
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
        "verification_status": "Pending" if schedule.require_supervisor_verification else "Not Required",
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


def resolve_service_point(scan_value, session_token):
    """Resolve a permanent schedule/location identity to its current task occurrence."""
    schedule_name = _service_schedule_name(scan_value)
    schedule = frappe.get_doc("CFG Kanban Task Schedule", schedule_name)
    profile, _session = require_operator(
        session_token, "task_start", workstation=schedule.workstation
    )
    open_name = frappe.db.get_value(
        "CFG Kanban Task",
        {"task_schedule": schedule.name,
         "status": ["not in", ("Completed", "Cancelled")]},
        "name", order_by="due_on asc, creation asc",
    )
    task = frappe.get_doc("CFG Kanban Task", open_name) if open_name else None
    generated = False
    if not task and schedule.active and schedule.next_due_on and \
            get_datetime(schedule.next_due_on) <= now_datetime():
        task = create_from_schedule(schedule.name, scheduled_for=schedule.next_due_on)
        generated = True
    return {
        "schedule": schedule.as_dict(),
        "task": task.as_dict() if task else None,
        "generated": generated,
        "operator": profile.employee,
        "message": ("Current Service Task resolved" if task else
                    f"No task is due. Next due: {schedule.next_due_on or 'not scheduled'}"),
    }


def disposition_task(task_name, session_token, disposition, reason):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(session_token, "task_verify", workstation=task.workstation)
    if profile.kanban_role not in ("Supervisor", "Development Proxy"):
        frappe.throw("Only a Supervisor can cancel or bypass a Service Task occurrence")
    if task.status in ("Completed", "Cancelled", "Bypassed"):
        frappe.throw(f"Task cannot be changed while it is {task.status}")
    if disposition not in ("Cancelled", "Bypassed"):
        frappe.throw("Unsupported supervisor disposition")
    if not (reason or "").strip():
        frappe.throw("Supervisor reason is required")
    task.status = disposition
    task.supervisor_disposition = disposition
    task.disposition_by = profile.employee
    task.disposition_on = now_datetime()
    task.disposition_reason = reason
    task.save(ignore_permissions=True)
    _task_event(f"Standalone Task {disposition}", task, profile, session, notes=reason)
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
    _apply_values(task, "Start", values, profile.employee)
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
    if task.status not in ("Due", "Assigned", "In Progress", "Overdue", "Correction Required"):
        frappe.throw(f"Task cannot complete while it is {task.status}")
    _apply_values(task, "Complete", values, profile.employee)
    _apply_checklist(task, checklist_results, profile.employee)
    task.completed_by = profile.employee
    task.completed_on = now_datetime()
    task.completion_notes = notes
    task.status = "Awaiting Verification" if task.verification_required else "Completed"
    task.verification_status = "Pending" if task.verification_required else "Not Required"
    task.verified_by = None
    task.verified_on = None
    task.verification_notes = None
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
    _apply_values(task, "Verify", values, profile.employee)
    task.status = "Completed"
    task.verification_status = "Approved"
    task.verified_by = profile.employee
    task.verified_on = now_datetime()
    task.verification_notes = notes
    task.save(ignore_permissions=True)
    _task_event("Standalone Task Verified", task, profile, session)
    return task


def reject_task(task_name, session_token, notes):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(session_token, "task_verify", workstation=task.workstation)
    if task.status != "Awaiting Verification":
        frappe.throw(f"Task cannot be rejected while it is {task.status}")
    if task.completed_by == profile.employee:
        frappe.throw("Task verification must be performed by a different operator")
    if not (notes or "").strip():
        frappe.throw("Verification remarks are required when a task is rejected")
    task.status = "Correction Required"
    task.verification_status = "Rejected"
    task.verified_by = profile.employee
    task.verified_on = now_datetime()
    task.verification_notes = notes
    task.save(ignore_permissions=True)
    _task_event("Standalone Task Verification Rejected", task, profile, session,
                notes=notes)
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


def _apply_values(task, capture_on, supplied, employee):
    rows = standalone_definitions(task.task_schedule, capture_on) if task.task_schedule else []
    supplied = frappe.parse_json(supplied) if isinstance(supplied, str) else (supplied or [])
    validate_values(rows, supplied)
    existing = {row.field_key: row for row in task.execution_values}
    for value in normalized_values(rows, supplied):
        value.update({"capture_on": capture_on, "captured_by": employee,
                      "captured_on": now_datetime()})
        if value["field_key"] in existing:
            existing[value["field_key"]].update(value)
        else:
            task.append("execution_values", value)


def _apply_checklist(task, supplied, employee):
    expected = [line.strip() for line in (task.checklist or "").splitlines() if line.strip()]
    supplied = frappe.parse_json(supplied) if isinstance(supplied, str) else (supplied or [])
    completed = {row.get("item") for row in supplied if cint(row.get("completed"))}
    missing = [item for item in expected if item not in completed]
    if missing:
        frappe.throw("Complete all checklist items: " + ", ".join(missing))
    task.checklist_results = frappe.as_json(supplied)
    task.set("checklist_evidence", [])
    captured_on = now_datetime()
    for index, item in enumerate(expected, start=1):
        task.append("checklist_evidence", {
            "item_key": f"item_{index}", "item": item, "result": "Pass",
            "captured_by": employee, "captured_on": captured_on,
        })


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


def _service_schedule_name(value):
    value = (value or "").strip()
    marker = "CFG:SERVICE:SCHEDULE:"
    if value.upper().startswith(marker):
        value = value[len(marker):]
    if not value or not frappe.db.exists("CFG Kanban Task Schedule", value):
        frappe.throw("Permanent Service Point QR is not recognised")
    return value


def _is_skipped_holiday(schedule, scheduled_for):
    if schedule.holiday_policy != "Skip Listed Holidays" or not schedule.holiday_list:
        return False
    return bool(frappe.db.exists(
        "Holiday", {"parent": schedule.holiday_list,
                    "holiday_date": get_datetime(scheduled_for).date()}
    ))


def _task_event(event_type, task, profile, session, notes=None):
    record(event_type, reference_doctype=task.doctype, reference_name=task.name,
           standalone_task=task.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           notes=notes)


def _validate_assignment(task, profile):
    if (task.assigned_employee and task.assigned_employee != profile.employee
            and profile.kanban_role != "Supervisor"):
        frappe.throw(f"Task is assigned to Employee {task.assigned_employee}")

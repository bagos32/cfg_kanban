import frappe
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

from cfg_kanban.services.dynamic_forms import definitions, normalized_values, validate_values
from cfg_kanban.services.events import record
from cfg_kanban.services.operator_auth import require_operator


SATISFIED_STATUSES = {"Completed"}


def on_cycle_created(doc, method=None):
    ensure_tasks(doc.name)


def ensure_tasks(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    created = []
    for profile in master.process_task_profiles:
        existing = frappe.db.get_value(
            "CFG Kanban Process Task",
            {"kanban_cycle": cycle.name, "task_key": profile.task_key}, "name",
        )
        if existing:
            created.append(existing)
            continue
        reusable = _reusable_task(master.name, profile)
        status = "Completed" if reusable else (
            "Ready" if profile.trigger_point == "Before Cycle Start" else "Not Ready"
        )
        task = frappe.get_doc({
            "doctype": "CFG Kanban Process Task",
            "kanban_cycle": cycle.name,
            "kanban_master": master.name,
            "task_key": profile.task_key,
            "task_name": profile.task_name,
            "sequence": profile.sequence,
            "task_category": profile.task_category,
            "task_type": profile.task_type,
            "trigger_point": profile.trigger_point,
            "linked_operation": profile.linked_operation,
            "status": status,
            "mandatory": profile.mandatory,
            "blocking": profile.blocking,
            "responsible_role": profile.responsible_role,
            "workstation": profile.workstation,
            "asset": profile.asset,
            "checklist": profile.checklist,
            "verification_required": (profile.require_supervisor_verification
                                      or profile.completion_rule == "Supervisor Verified"),
            "completed_on": reusable.completed_on if reusable else None,
            "completed_by": reusable.completed_by if reusable else None,
            "verified_by": reusable.verified_by if reusable else None,
            "verified_on": reusable.verified_on if reusable else None,
            "valid_until": reusable.valid_until if reusable else None,
            "reused_from_task": reusable.name if reusable else None,
        }).insert(ignore_permissions=True)
        created.append(task.name)
        if reusable:
            record("Process Task Reused", cycle=cycle.name, process_task=task.name,
                   reference_doctype=task.doctype, reference_name=task.name,
                   notes=f"Reused valid task {reusable.name}")
    return created


def refresh_task_readiness(cycle_name):
    """Expose tasks only when their production context exists; never advances production itself."""
    ensure_tasks(cycle_name)
    executions = frappe.get_all(
        "CFG Kanban Process Execution", filters={"kanban_cycle": cycle_name},
        fields=["operation", "status", "processed_qty", "target_qty"],
    )
    by_operation = {}
    for execution in executions:
        by_operation.setdefault(execution.operation, []).append(execution)
    all_complete = bool(executions) and all(row.status == "Completed" for row in executions)
    tasks = frappe.get_all(
        "CFG Kanban Process Task", filters={"kanban_cycle": cycle_name, "status": "Not Ready"},
        fields=["name", "trigger_point", "linked_operation"],
    )
    activated = []
    for task in tasks:
        lanes = by_operation.get(task.linked_operation, [])
        ready = task.trigger_point == "Before Cycle Start"
        if task.trigger_point == "Before Operation Start":
            ready = any(row.status in ("Ready", "In Progress", "Paused") for row in lanes)
        elif task.trigger_point == "After Operation Complete":
            ready = bool(lanes) and all(row.status == "Completed" for row in lanes)
        elif task.trigger_point == "Before WIP Release":
            ready = any(row.status in ("In Progress", "Paused", "Completed") for row in lanes)
        elif task.trigger_point in ("Before FG Release", "Before Cycle Close"):
            ready = all_complete or bool(executions) and all(
                row.status == "Completed" or flt(row.processed_qty) >= flt(row.target_qty)
                for row in executions
            )
        if ready:
            frappe.db.set_value("CFG Kanban Process Task", task.name, "status", "Ready")
            activated.append(task.name)
    return activated


def evaluate_gate(cycle_name, trigger_point, operation=None, *, activate=True):
    ensure_tasks(cycle_name)
    filters = {"kanban_cycle": cycle_name, "trigger_point": trigger_point}
    tasks = frappe.get_all(
        "CFG Kanban Process Task", filters=filters,
        fields=["name", "task_name", "status", "blocking", "mandatory", "valid_until",
                "linked_operation"],
        order_by="sequence asc, creation asc",
    )
    blockers = []
    current = now_datetime()
    for task in tasks:
        if operation and task.get("linked_operation") not in (None, "", operation):
            continue
        if task.status == "Completed" and task.valid_until and get_datetime(task.valid_until) <= current:
            frappe.db.set_value("CFG Kanban Process Task", task.name, "status", "Expired")
            task.status = "Expired"
        if activate and task.status == "Not Ready":
            frappe.db.set_value("CFG Kanban Process Task", task.name, "status", "Ready")
            task.status = "Ready"
        if cint(task.mandatory) and cint(task.blocking) and task.status not in SATISFIED_STATUSES:
            blockers.append({"name": task.name, "task_name": task.task_name, "status": task.status})
    return {"open": not blockers, "trigger_point": trigger_point,
            "operation": operation, "blockers": blockers, "tasks": tasks}


def assert_gate_open(cycle_name, trigger_point, operation=None):
    result = evaluate_gate(cycle_name, trigger_point, operation)
    if not result["open"]:
        detail = ", ".join(f"{row['task_name']} ({row['status']})" for row in result["blockers"])
        frappe.throw(f"{trigger_point} is blocked by required Process Task(s): {detail}")
    return result


def task_form(task_name, capture_on):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    rows = definitions(task.kanban_master, capture_on, process_task_key=task.task_key)
    return {"task": task.as_dict(), "fields": rows}


def start_task(task_name, session_token, values=None, notes=None):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    profile, session = require_operator(
        session_token, "task_start", operation=task.linked_operation,
        workstation=task.workstation,
    )
    if task.status == "In Progress":
        return task
    if task.status != "Ready":
        frappe.throw(f"Process Task cannot start while it is {task.status}")
    supplied = _parse_values(values)
    rows = definitions(task.kanban_master, "Start", process_task_key=task.task_key)
    validate_values(rows, supplied)
    _replace_values(task, normalized_values(rows, supplied))
    task.status = "In Progress"
    task.started_by = profile.employee
    task.assigned_employee = profile.employee
    task.started_on = now_datetime()
    task.notes = notes
    task.save(ignore_permissions=True)
    record("Process Task Started", cycle=task.kanban_cycle, process_task=task.name,
           reference_doctype=task.doctype, reference_name=task.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return task


def complete_task(task_name, session_token, values=None, checklist_results=None, notes=None):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    profile, session = require_operator(
        session_token, "task_complete", operation=task.linked_operation,
        workstation=task.workstation,
    )
    if task.status == "Completed":
        return task
    if task.status not in ("Ready", "In Progress"):
        frappe.throw(f"Process Task cannot complete while it is {task.status}")
    supplied = _parse_values(values)
    rows = definitions(task.kanban_master, "Complete", process_task_key=task.task_key)
    validate_values(rows, supplied)
    _validate_checklist(task, checklist_results)
    _replace_values(task, normalized_values(rows, supplied))
    parsed_checklist = (frappe.parse_json(checklist_results)
                        if isinstance(checklist_results, str) else (checklist_results or []))
    task.checklist_results = frappe.as_json(parsed_checklist)
    task.completed_by = profile.employee
    task.completed_on = now_datetime()
    task.notes = notes
    task.status = "Awaiting Verification" if task.verification_required else "Completed"
    if task.status == "Completed":
        _set_validity(task)
    task.save(ignore_permissions=True)
    record("Process Task Completed" if task.status == "Completed" else "Process Task Awaiting Verification",
           cycle=task.kanban_cycle, process_task=task.name,
           reference_doctype=task.doctype, reference_name=task.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return task


def verify_task(task_name, session_token, values=None, notes=None):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    profile, session = require_operator(
        session_token, "task_verify", operation=task.linked_operation,
        workstation=task.workstation,
    )
    if task.status == "Completed":
        return task
    if task.status != "Awaiting Verification":
        frappe.throw(f"Process Task cannot be verified while it is {task.status}")
    if task.completed_by == profile.employee:
        frappe.throw("Supervisor verification must be performed by a different operator")
    supplied = _parse_values(values)
    rows = definitions(task.kanban_master, "Verify", process_task_key=task.task_key)
    validate_values(rows, supplied)
    _replace_values(task, normalized_values(rows, supplied))
    task.status = "Completed"
    task.verified_by = profile.employee
    task.verified_on = now_datetime()
    task.notes = notes or task.notes
    _set_validity(task)
    task.save(ignore_permissions=True)
    record("Process Task Verified", cycle=task.kanban_cycle, process_task=task.name,
           reference_doctype=task.doctype, reference_name=task.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return task


def invalidate_valid_tasks(reason, *, asset=None, workstation=None):
    if not asset and not workstation:
        frappe.throw("Asset or Workstation is required to invalidate reusable Process Tasks")
    filters = {"status": "Completed", "valid_until": [">", now_datetime()]}
    if asset:
        filters["asset"] = asset
    if workstation:
        filters["workstation"] = workstation
    names = frappe.get_all("CFG Kanban Process Task", filters=filters, pluck="name")
    for name in names:
        task = frappe.get_doc("CFG Kanban Process Task", name)
        task.db_set({"status": "Expired", "valid_until": now_datetime(),
                     "notes": f"Invalidated: {reason}"}, update_modified=True)
        record("Process Task Validity Invalidated", cycle=task.kanban_cycle,
               process_task=task.name, reference_doctype=task.doctype,
               reference_name=task.name, notes=reason)
    return names


def _profile(master_name, task_key):
    master = frappe.get_doc("CFG Kanban Master", master_name)
    return next((row for row in master.process_task_profiles if row.task_key == task_key), None)


def _set_validity(task):
    profile = _profile(task.kanban_master, task.task_key)
    if profile and profile.reuse_while_valid and flt(profile.validity_duration_hours) > 0:
        task.valid_until = add_to_date(now_datetime(), hours=flt(profile.validity_duration_hours))


def _reusable_task(master_name, profile):
    if not profile.reuse_while_valid or flt(profile.validity_duration_hours) <= 0:
        return None
    filters = {"kanban_master": master_name, "task_key": profile.task_key,
               "status": "Completed", "valid_until": [">", now_datetime()]}
    if profile.workstation:
        filters["workstation"] = profile.workstation
    if profile.asset:
        filters["asset"] = profile.asset
    name = frappe.db.get_value("CFG Kanban Process Task", filters, "name",
                               order_by="completed_on desc")
    return frappe.get_doc("CFG Kanban Process Task", name) if name else None


def _validate_checklist(task, checklist_results):
    profile = _profile(task.kanban_master, task.task_key)
    if not profile or profile.completion_rule != "All Checklist Items":
        return
    expected = [line.strip() for line in (task.checklist or "").splitlines() if line.strip()]
    supplied = frappe.parse_json(checklist_results or "[]")
    completed = {row.get("item") for row in supplied if cint(row.get("completed"))}
    missing = [item for item in expected if item not in completed]
    if missing:
        frappe.throw("Complete all checklist items: " + ", ".join(missing))


def _replace_values(task, values):
    existing = {row.field_key: row for row in task.execution_values}
    for value in values:
        if value["field_key"] in existing:
            existing[value["field_key"]].update(value)
        else:
            task.append("execution_values", value)


def _parse_values(values):
    return frappe.parse_json(values) if isinstance(values, str) else (values or [])

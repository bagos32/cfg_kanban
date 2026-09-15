import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once


QUEUE_DOCTYPE = "CFG Kanban Dispatch Queue"
AUDIT_DOCTYPE = "CFG Kanban Sequence Change"
MOVABLE_STATUSES = ("Not Ready", "Ready", "Waiting Input", "Blocked")
PRIORITY_RANK = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}


def dispatch_schema_available():
    return frappe.db.table_exists(QUEUE_DOCTYPE)


def on_execution_update(doc, method=None):
    """Keep the dispatch projection current without changing the ERP route."""
    if dispatch_schema_available():
        ensure_queue_entry(doc)


def ensure_queue_entries(executions):
    if not executions or not dispatch_schema_available():
        return {}
    result = {}
    for execution in executions:
        entry = ensure_queue_entry(execution)
        if entry:
            result[execution.name] = entry
    return result


def ensure_queue_entry(execution):
    execution = _as_dict(execution)
    if not execution.get("name") or not execution.get("workstation"):
        return None
    cycle = _cycle_context(execution.get("kanban_cycle"))
    values = {
        "kanban_cycle": execution.get("kanban_cycle"),
        "kanban_master": execution.get("kanban_master"),
        "work_order": cycle.get("work_order"),
        "item_code": cycle.get("item_code"),
        "target_qty": execution.get("target_qty"),
        "job_card": execution.get("job_card"),
        "operation": execution.get("operation"),
        "workstation": execution.get("workstation"),
        "dispatch_status": execution.get("status") or "Not Ready",
        "readiness": _readiness(execution),
        "system_priority": cycle.get("priority") or "Normal",
    }
    name = frappe.db.get_value(QUEUE_DOCTYPE, {"process_execution": execution.name}, "name")
    if not name:
        values.update({
            "doctype": QUEUE_DOCTYPE,
            "process_execution": execution.name,
            "queue_position": _next_position(execution.workstation),
            "sequence_source": "System Recommendation",
        })
        try:
            return frappe.get_doc(values).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            name = frappe.db.get_value(QUEUE_DOCTYPE, {"process_execution": execution.name}, "name")
    entry = frappe.get_doc(QUEUE_DOCTYPE, name)
    if entry.workstation != execution.get("workstation"):
        values["queue_position"] = _next_position(execution.get("workstation"))
    changed = False
    for fieldname, value in values.items():
        if entry.get(fieldname) != value:
            entry.set(fieldname, value)
            changed = True
    if changed:
        entry.flags.ignore_permissions = True
        entry.save()
    return entry


def overlay_dispatch(executions):
    entries = ensure_queue_entries(executions)
    for row in executions:
        entry = entries.get(row.name)
        if not entry:
            row.update({"dispatch_queue": None, "queue_position": 999999,
                        "sequence_source": "System Recommendation", "expedite": 0,
                        "effective_priority": row.get("priority") or "Normal"})
            continue
        row.update({
            "dispatch_queue": entry.name,
            "queue_position": flt(entry.queue_position),
            "sequence_source": entry.sequence_source,
            "expedite": int(entry.expedite or 0),
            "effective_priority": entry.supervisor_priority or entry.system_priority or "Normal",
            "paused_for_queue_entry": entry.paused_for_queue_entry,
            "pause_reason": entry.pause_reason,
            "wip_disposition": entry.wip_disposition,
            "machine_condition": entry.machine_condition,
            "expected_resume_on": entry.expected_resume_on,
            "erp_timer_was_active": int(entry.erp_timer_was_active or 0),
            "paused_by": entry.paused_by,
            "paused_on": entry.paused_on,
        })
    return sorted(executions, key=_dispatch_sort_key)


@frappe.whitelist()
def reorder_queue(profile_name, workstation, ordered_queue_entries, reason):
    profile = _require_supervisor_profile(profile_name, workstation)
    reason = _required_reason(reason)
    requested = frappe.parse_json(ordered_queue_entries) if isinstance(ordered_queue_entries, str) else ordered_queue_entries
    requested = requested or []
    if len(requested) != len(set(requested)):
        frappe.throw("The requested queue order contains duplicate entries")
    if not requested:
        frappe.throw("Select at least one queued item to reorder")

    _lock_workstation(workstation)
    rows = _movable_rows(workstation)
    by_name = {row.name: row for row in rows}
    invalid = [name for name in requested if name not in by_name]
    if invalid:
        frappe.throw("One or more queue items changed or are no longer eligible. Refresh the dashboard and try again.")
    final_names = requested + [row.name for row in rows if row.name not in requested]
    changed = _apply_positions(final_names, by_name, set(requested), "Reorder", reason)
    _record_dispatch_event("Dispatch Queue Reordered", workstation, reason, changed, profile.name)
    return {"changed": len(changed), "workstation": workstation}


@frappe.whitelist()
def set_expedite(profile_name, queue_entry, expedite, reason):
    reason = _required_reason(reason)
    entry = frappe.get_doc(QUEUE_DOCTYPE, queue_entry)
    profile = _require_supervisor_profile(profile_name, entry.workstation)
    if entry.dispatch_status not in MOVABLE_STATUSES:
        frappe.throw("Only queued work that has not started can be expedited")
    _lock_workstation(entry.workstation)
    entry.reload()
    if entry.dispatch_status not in MOVABLE_STATUSES:
        frappe.throw("This work has started or its state changed. Refresh the dashboard and try again.")
    enable = bool(int(expedite))
    old_priority = entry.supervisor_priority or entry.system_priority
    old_position = flt(entry.queue_position)
    entry.expedite = enable
    entry.supervisor_priority = "Urgent" if enable else ""
    entry.sequence_source = "Supervisor Override"
    entry.last_changed_by = frappe.session.user
    entry.last_changed_on = now_datetime()
    entry.notes = reason
    entry.flags.ignore_permissions = True
    entry.save()
    rows = _movable_rows(entry.workstation)
    if enable:
        rows = [row for row in rows if row.name == entry.name] + [
            row for row in rows if row.name != entry.name
        ]
    for index, row in enumerate(rows, 1):
        new_position = index * 10
        row_old_position = old_position if row.name == entry.name else flt(row.queue_position)
        priority_changed = row.name == entry.name and old_priority != (
            row.supervisor_priority or row.system_priority)
        if row_old_position == new_position and not priority_changed:
            continue
        frappe.db.set_value(QUEUE_DOCTYPE, row.name, "queue_position", new_position,
                            update_modified=row.name == entry.name)
        action = ("Expedite" if enable else "Remove Expedite") if row.name == entry.name else "Reorder"
        audit = _audit(row, action, row_old_position, new_position,
                       old_priority if row.name == entry.name else row.supervisor_priority or row.system_priority,
                       row.supervisor_priority or row.system_priority, reason)
        frappe.db.set_value(QUEUE_DOCTYPE, row.name, "last_sequence_change", audit.name,
                            update_modified=False)
    _record_dispatch_event("Dispatch Expedite Changed", entry.workstation, reason,
                           [entry.name], profile.name)
    return {"queue_entry": entry.name, "expedite": enable}


@frappe.whitelist()
def pause_and_give_way(profile_name, execution_name, replacement_queue_entry, reason,
                       wip_disposition, machine_condition, expected_resume_on=None,
                       event_token=None):
    reason = _required_reason(reason)
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if _completed_interrupt_retry(execution, "Pause and Give Way", event_token, "Paused"):
        return {"execution": execution.name, "status": "Paused", "duplicate": True}
    profile = _require_supervisor_profile(profile_name, execution.workstation)
    if execution.status != "In Progress":
        frappe.throw("Only the currently In Progress execution can be paused")
    if not execution.job_card:
        frappe.throw("The current execution has no ERPNext Job Card to pause")
    replacement = frappe.get_doc(QUEUE_DOCTYPE, replacement_queue_entry)
    if replacement.workstation != execution.workstation:
        frappe.throw("The urgent replacement must use the same workstation")
    if replacement.dispatch_status != "Ready":
        frappe.throw("The urgent replacement must be Ready before current work can give way")
    if replacement.process_execution == execution.name:
        frappe.throw("Select a different execution as the urgent replacement")
    policy = _validate_interruption_compatibility(execution, replacement)
    if not wip_disposition or not machine_condition:
        frappe.throw("WIP disposition and machine condition are required")
    if wip_disposition == "Must Be Consumed Before Interruption":
        frappe.throw("This WIP must be consumed before interruption, so the execution cannot be paused")
    if policy == "Compatible Items Only" and machine_condition != "Ready for Compatible Product":
        frappe.throw("Compatible Items Only requires the machine to be Ready for Compatible Product")

    _lock_workstation(execution.workstation)
    execution.reload()
    replacement.reload()
    if execution.status != "In Progress" or replacement.dispatch_status != "Ready":
        frappe.throw("The workstation state changed. Refresh the dashboard and try again.")
    paused_on = now_datetime()
    erp_timer_was_active = _has_open_job_card_timer(execution.job_card)
    if erp_timer_was_active:
        _run_interrupt_command(execution, "Pause Job Card", event_token, {
            "paused_on": paused_on, "reason": reason,
        })
    execution.db_set("status", "Paused", update_modified=True)
    queue = ensure_queue_entry(execution)
    queue.db_set({
        "dispatch_status": "Paused", "readiness": "Paused",
        "paused_for_queue_entry": replacement.name, "pause_reason": reason,
        "wip_disposition": wip_disposition, "machine_condition": machine_condition,
        "expected_resume_on": expected_resume_on, "paused_by": frappe.session.user,
        "paused_on": paused_on, "erp_timer_was_active": int(erp_timer_was_active),
        "last_changed_by": frappe.session.user,
        "last_changed_on": paused_on,
    }, update_modified=True)
    audit = _audit(queue, "Pause and Give Way", queue.queue_position, queue.queue_position,
                   queue.supervisor_priority or queue.system_priority,
                   queue.supervisor_priority or queue.system_priority, reason,
                   replacement_queue_entry=replacement.name, wip_disposition=wip_disposition,
                   machine_condition=machine_condition, expected_resume_on=expected_resume_on)
    frappe.db.set_value(QUEUE_DOCTYPE, queue.name, "last_sequence_change", audit.name,
                        update_modified=False)
    set_expedite(profile.name, replacement.name, 1, reason)
    event_key = _interrupt_event_key(execution, "Pause and Give Way", event_token)
    record("Work Paused to Give Way", cycle=execution.kanban_cycle, execution=execution.name,
           reference_doctype=QUEUE_DOCTYPE, reference_name=replacement.name,
           notes=(f"WIP: {wip_disposition}; Machine: {machine_condition}; "
                  f"ERP timer active: {'yes' if erp_timer_was_active else 'no'}; "
                  f"Expected resume: {expected_resume_on or 'not set'}; Reason: {reason}"),
           device_id=event_key)
    return {"execution": execution.name, "status": "Paused",
            "replacement_queue_entry": replacement.name}


@frappe.whitelist()
def resume_paused_work(profile_name, execution_name, reason, event_token=None):
    reason = _required_reason(reason)
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if _completed_interrupt_retry(execution, "Resume Paused Work", event_token, "In Progress"):
        return {"execution": execution.name, "status": "In Progress", "duplicate": True}
    profile = _require_supervisor_profile(profile_name, execution.workstation)
    if execution.status != "Paused":
        frappe.throw("Only a paused execution can be resumed")
    if not execution.job_card:
        frappe.throw("The paused execution has no ERPNext Job Card to resume")
    _lock_workstation(execution.workstation)
    execution.reload()
    if execution.status != "Paused":
        frappe.throw("The paused execution state changed. Refresh and try again.")
    competing = frappe.db.get_value("CFG Kanban Process Execution", {
        "workstation": execution.workstation, "status": "In Progress", "name": ["!=", execution.name],
    }, "name")
    if competing:
        frappe.throw(f"Finish or pause current execution {competing} before resuming this work")
    queue = ensure_queue_entry(execution)
    erp_timer_was_active = bool(queue.erp_timer_was_active)
    if erp_timer_was_active:
        _run_interrupt_command(execution, "Resume Job Card", event_token, {
            "resumed_on": now_datetime(), "reason": reason,
        })
    execution.db_set("status", "In Progress", update_modified=True)
    audit = _audit(queue, "Resume Paused Work", queue.queue_position, queue.queue_position,
                   queue.supervisor_priority or queue.system_priority,
                   queue.supervisor_priority or queue.system_priority, reason,
                   replacement_queue_entry=queue.paused_for_queue_entry,
                   wip_disposition=queue.wip_disposition,
                   machine_condition=queue.machine_condition,
                   expected_resume_on=queue.expected_resume_on)
    queue.db_set({
        "dispatch_status": "In Progress", "readiness": "In Progress",
        "paused_for_queue_entry": None, "pause_reason": None,
        "wip_disposition": None, "machine_condition": None,
        "expected_resume_on": None, "paused_by": None, "paused_on": None,
        "erp_timer_was_active": 0,
        "last_sequence_change": audit.name, "last_changed_by": frappe.session.user,
        "last_changed_on": now_datetime(),
    }, update_modified=True)
    event_key = _interrupt_event_key(execution, "Resume Paused Work", event_token)
    record("Paused Work Resumed", cycle=execution.kanban_cycle, execution=execution.name,
           reference_doctype="Job Card", reference_name=execution.job_card,
           notes=(f"ERP timer restored: {'yes' if erp_timer_was_active else 'not applicable'}; "
                  f"Reason: {reason}"), device_id=event_key)
    return {"execution": execution.name, "status": "In Progress", "profile": profile.name}


def _apply_positions(names, by_name, explicitly_reordered, action, reason):
    changed = []
    for index, name in enumerate(names, 1):
        entry = by_name[name]
        new_position = index * 10
        old_position = flt(entry.queue_position)
        if old_position == new_position and name not in explicitly_reordered:
            continue
        frappe.db.set_value(QUEUE_DOCTYPE, name, {
            "queue_position": new_position,
            "sequence_source": "Supervisor Override",
            "last_changed_by": frappe.session.user,
            "last_changed_on": now_datetime(),
            "notes": reason,
        }, update_modified=True)
        entry.queue_position = new_position
        audit = _audit(entry, action, old_position, new_position,
                       entry.supervisor_priority or entry.system_priority,
                       entry.supervisor_priority or entry.system_priority, reason)
        frappe.db.set_value(QUEUE_DOCTYPE, name, "last_sequence_change", audit.name,
                            update_modified=False)
        changed.append(name)
    return changed


def _audit(entry, action, old_position, new_position, old_priority, new_priority, reason, **details):
    return frappe.get_doc({
        "doctype": AUDIT_DOCTYPE,
        "queue_entry": entry.name,
        "process_execution": entry.process_execution,
        "kanban_cycle": entry.kanban_cycle,
        "workstation": entry.workstation,
        "action": action,
        "old_position": old_position,
        "new_position": new_position,
        "old_priority": old_priority,
        "new_priority": new_priority,
        "reason": reason,
        "changed_by": frappe.session.user,
        "changed_on": now_datetime(),
        **details,
    }).insert(ignore_permissions=True)


def _run_interrupt_command(execution, command_type, event_token, extra_payload):
    employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user,
                                                   "status": "Active"}, "name")
    key = canonical_key("dispatch-interruption", execution.job_card, command_type,
                        event_token or execution.modified)
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": command_type,
        "kanban_cycle": execution.kanban_cycle, "process_execution": execution.name,
        "status": "Pending", "target_doctype": "Job Card",
        "request_payload": frappe.as_json({
            "job_card": execution.job_card, "process_execution": execution.name,
            "kanban_cycle": execution.kanban_cycle, "employee": employee,
            "operator_user": frappe.session.user, **extra_payload,
        }),
        "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    from cfg_kanban.integrations.erp_gateway import execute_command
    return execute_command(command.name)


def _completed_interrupt_retry(execution, action, event_token, expected_status):
    if not event_token or execution.status != expected_status:
        return False
    return bool(frappe.db.get_value("CFG Kanban Event", {
        "device_id": _interrupt_event_key(execution, action, event_token),
    }, "name"))


def _interrupt_event_key(execution, action, event_token):
    return canonical_key("dispatch-interruption-event", execution.name, action,
                         event_token) if event_token else None


def _has_open_job_card_timer(job_card):
    return bool(frappe.db.sql(
        "select name from `tabJob Card Time Log` where parent=%s and to_time is null limit 1",
        job_card,
    ))


def _validate_interruption_compatibility(execution, replacement):
    current = _operation_interruption_profile(execution.kanban_master, execution.operation)
    if not current or current.interruption_policy in (None, "", "Interruption Prohibited"):
        frappe.throw("This Kanban operation prohibits interruption. Update its Operation Profile policy first.")
    if current.interruption_policy != "Compatible Items Only":
        return current.interruption_policy
    target = _operation_interruption_profile(replacement.kanban_master, replacement.operation)
    if (not target or target.interruption_policy != "Compatible Items Only" or
            not current.setup_family or not current.cleaning_class):
        frappe.throw("Both operations require Setup Family and Cleaning Class before compatibility can be verified")
    if (current.setup_family != target.setup_family or
            current.cleaning_class != target.cleaning_class):
        frappe.throw("The urgent item is not in the same Setup Family and Cleaning Class")
    return current.interruption_policy


def _operation_interruption_profile(master, operation):
    return frappe.db.get_value("CFG Kanban Operation Profile", {
        "parent": master, "parenttype": "CFG Kanban Master", "operation": operation,
    }, ["interruption_policy", "setup_family", "cleaning_class"], as_dict=True)


def _record_dispatch_event(event_type, workstation, reason, changed, profile_name):
    record(event_type, reference_doctype="CFG Kanban Dashboard Profile",
           reference_name=profile_name, notes=(
               f"Workstation: {workstation}; Reason: {reason}; Queue entries: {', '.join(changed)}"
           ), system_generated=True)


def _require_supervisor_profile(profile_name, workstation):
    roles = set(frappe.get_roles())
    if not roles.intersection({"Manufacturing Manager", "System Manager"}):
        frappe.throw("Manufacturing Manager or System Manager role is required", frappe.PermissionError)
    profile = frappe.get_doc("CFG Kanban Dashboard Profile", profile_name)
    profile.check_permission("read")
    if profile.access_mode != "Supervisor":
        frappe.throw("This Dashboard Profile is not configured for Supervisor control")
    enabled = {row.workstation for row in profile.workstations if row.enabled}
    if workstation not in enabled:
        frappe.throw("The workstation is not enabled in this Dashboard Profile")
    return profile


def _required_reason(reason):
    value = (reason or "").strip()
    if not value:
        frappe.throw("Enter a supervisor reason for this sequence change")
    return value


def _lock_workstation(workstation):
    frappe.db.sql(
        "select name from `tabCFG Kanban Dispatch Queue` where workstation=%s "
        "and dispatch_status not in ('Completed','Cancelled') for update",
        workstation,
    )


def _movable_rows(workstation):
    return frappe.get_all(QUEUE_DOCTYPE, filters={
        "workstation": workstation, "dispatch_status": ["in", MOVABLE_STATUSES],
    }, fields=["*"], order_by="queue_position asc, creation asc",
       limit_page_length=1000)


def _next_position(workstation):
    value = frappe.db.sql(
        "select max(queue_position) from `tabCFG Kanban Dispatch Queue` where workstation=%s",
        workstation,
    )[0][0]
    return flt(value) + 10


def _cycle_context(cycle_name):
    if not cycle_name:
        return frappe._dict()
    return frappe.db.get_value("CFG Kanban Cycle", cycle_name,
                               ["work_order", "priority", "item_code"], as_dict=True) or frappe._dict()


def _as_dict(execution):
    if isinstance(execution, str):
        return frappe.db.get_value("CFG Kanban Process Execution", execution,
                                   ["name", "kanban_cycle", "kanban_master", "operation",
                                    "job_card", "workstation", "status", "blocked",
                                    "input_available_qty", "target_qty"], as_dict=True) or frappe._dict()
    return execution


def _readiness(row):
    if row.get("blocked") or row.get("status") == "Blocked":
        return "Blocked"
    if row.get("status") == "Waiting Input" or (
            row.get("status") == "Not Ready" and flt(row.get("input_available_qty")) <= 0):
        return "Waiting Input"
    return row.get("status") or "Not Ready"


def _dispatch_sort_key(row):
    active_rank = 0 if row.status == "In Progress" else 1 if row.status == "Paused" else 2
    return (active_rank, flt(row.get("queue_position")) or 999999,
            0 if row.get("expedite") else 1,
            PRIORITY_RANK.get(row.get("effective_priority"), 99), row.creation)

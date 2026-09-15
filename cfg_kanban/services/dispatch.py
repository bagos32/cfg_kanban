import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record


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


def _audit(entry, action, old_position, new_position, old_priority, new_priority, reason):
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
    }).insert(ignore_permissions=True)


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
        "and dispatch_status in ('Not Ready','Ready','Waiting Input','Blocked') for update",
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

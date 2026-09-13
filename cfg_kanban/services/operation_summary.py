import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.wip import available_operation_qty


def ensure_summary(cycle, master, profile):
    key = f"{cycle.name}::{profile.operation}"
    name = frappe.db.get_value("CFG Kanban Operation Summary", {"summary_key": key}, "name")
    if name:
        return frappe.get_doc("CFG Kanban Operation Summary", name)
    mode = ("Parallel Workstations" if profile.allow_parallel and
            profile.execution_mode in (None, "", "Single Workstation") else
            (profile.execution_mode or "Single Workstation"))
    return frappe.get_doc({
        "doctype": "CFG Kanban Operation Summary", "summary_key": key,
        "kanban_cycle": cycle.name, "kanban_master": master.name,
        "operation": profile.operation, "sequence": profile.sequence,
        "execution_mode": mode, "target_qty": cycle.planned_qty,
        "destination_operation": profile.destination_operation,
    }).insert(ignore_permissions=True)


def recalculate(cycle_name, operation):
    summary_name = frappe.db.get_value("CFG Kanban Operation Summary", {
        "kanban_cycle": cycle_name, "operation": operation,
    }, "name")
    if not summary_name:
        return None
    summary = frappe.get_doc("CFG Kanban Operation Summary", summary_name)
    rows = frappe.get_all("CFG Kanban Process Execution", filters={
        "kanban_cycle": cycle_name, "operation": operation, "status": ["!=", "Cancelled"],
    }, fields=["status", "allocated_qty", "target_qty", "processed_qty",
               "good_qty", "reject_qty", "released_qty"])
    completed = sum(1 for row in rows if row.status == "Completed")
    statuses = {row.status for row in rows}
    status = "Not Ready"
    if rows and completed == len(rows):
        status = "Completed"
    elif completed:
        status = "Partially Completed"
    elif statuses & {"In Progress", "Paused", "Waiting Input"}:
        status = "In Progress"
    elif "Ready" in statuses:
        status = "Ready"
    summary.db_set({
        "status": status, "execution_count": len(rows), "completed_execution_count": completed,
        "allocated_qty": sum(flt(row.allocated_qty or row.target_qty) for row in rows),
        "processed_qty": sum(flt(row.processed_qty) for row in rows),
        "good_qty": sum(flt(row.good_qty) for row in rows),
        "reject_qty": sum(flt(row.reject_qty) for row in rows),
        "released_qty": sum(flt(row.released_qty) for row in rows),
        "last_recalculated_on": now_datetime(),
    }, update_modified=True)
    return frappe.get_doc("CFG Kanban Operation Summary", summary.name)


def refresh_destination(cycle_name, source_operation, destination_operation):
    if not destination_operation:
        return
    source = recalculate(cycle_name, source_operation)
    destination = recalculate(cycle_name, destination_operation)
    if not source or not destination:
        return
    available = available_operation_qty(cycle_name, source_operation, destination_operation)
    destination.db_set("input_available_qty", available, update_modified=True)
    profile = frappe.db.get_value("CFG Kanban Operation Profile", {
        "parent": destination.kanban_master, "parenttype": "CFG Kanban Master",
        "operation": destination_operation,
    }, ["start_rule", "minimum_qty", "minimum_percentage", "execution_mode"], as_dict=True)
    if not profile:
        return
    ready = profile.start_rule == "No Dependency"
    if profile.start_rule == "Minimum Qty Available":
        ready = available >= flt(profile.minimum_qty)
    elif profile.start_rule == "Minimum Percentage Available":
        ready = available >= flt(destination.target_qty) * flt(profile.minimum_percentage) / 100
    elif profile.start_rule in ("Previous Operation Complete", "Full Batch Available"):
        ready = source.status == "Completed" and available >= flt(destination.target_qty)
    if ready:
        ready_executions(destination, profile.execution_mode)


def ready_executions(summary, execution_mode=None):
    rows = frappe.get_all("CFG Kanban Process Execution", filters={
        "operation_summary": summary.name, "status": "Not Ready",
    }, fields=["name", "lane_sequence"], order_by="lane_sequence asc")
    if (execution_mode or summary.execution_mode) == "Sequential Split":
        rows = rows[:1]
    for row in rows:
        frappe.db.set_value("CFG Kanban Process Execution", row.name, "status", "Ready")
        record("Execution Ready", cycle=summary.kanban_cycle, execution=row.name,
               previous_state="Not Ready", new_state="Ready")
    recalculate(summary.kanban_cycle, summary.operation)


def ready_next_sequential_lane(execution):
    if execution.execution_mode != "Sequential Split" or execution.status != "Completed":
        return
    next_name = frappe.db.get_value("CFG Kanban Process Execution", {
        "operation_summary": execution.operation_summary, "status": "Not Ready",
        "lane_sequence": [">", execution.lane_sequence],
    }, "name", order_by="lane_sequence asc")
    if next_name:
        frappe.db.set_value("CFG Kanban Process Execution", next_name, "status", "Ready")
        record("Sequential Execution Ready", cycle=execution.kanban_cycle,
               execution=next_name, previous_state="Not Ready", new_state="Ready")

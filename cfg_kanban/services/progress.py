import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.operation_summary import recalculate, refresh_destination
from cfg_kanban.services.wip import append_entry, releasable_increment
from cfg_kanban.services.process_tasks import assert_gate_open


def report(execution_name, good_qty, reject_qty=0, processed_qty=None, released_qty=None,
           values=None, notes=None, source="Operator", operator=None,
           operator_session=None, terminal_user=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    good_qty, reject_qty = flt(good_qty), flt(reject_qty)
    processed_qty = flt(processed_qty) if processed_qty is not None else good_qty + reject_qty
    if min(good_qty, reject_qty, processed_qty) < 0:
        frappe.throw("Progress quantities cannot be negative; use an explicit adjustment workflow")
    if flt(execution.processed_qty) + processed_qty > flt(execution.target_qty) + 0.000001:
        frappe.throw(f"Progress exceeds this Cycle allocation of {execution.target_qty}")
    progress = frappe.get_doc({
        "doctype": "CFG Kanban Operation Progress", "process_execution": execution.name,
        "kanban_cycle": execution.kanban_cycle, "posting_datetime": now_datetime(),
        "operator": operator, "operator_session": operator_session,
        "terminal_user": terminal_user or frappe.session.user,
        "good_qty": good_qty, "reject_qty": reject_qty,
        "processed_qty": processed_qty, "source": source, "linked_job_card": execution.job_card,
        "notes": notes,
    })
    for value in values or []:
        progress.append("execution_values", value)
    progress.insert(ignore_permissions=bool(operator_session))
    total_good = flt(execution.good_qty) + good_qty
    execution.db_set({"good_qty": total_good, "reject_qty": flt(execution.reject_qty) + reject_qty,
                      "processed_qty": flt(execution.processed_qty) + processed_qty,
                      "operator": operator or execution.operator}, update_modified=True)
    if execution.handoff_mode == "Digital Quantity Handoff":
        release = flt(released_qty) if released_qty is not None else releasable_increment(
            total_good, execution.released_qty, execution.transfer_multiple)
        if release:
            assert_gate_open(execution.kanban_cycle, "Before WIP Release", execution.operation)
            append_entry(execution.kanban_cycle, "Released", release, source_execution=execution.name,
                         source_operation=execution.operation,
                         destination_operation=execution.destination_operation,
                         source_progress=progress.name)
            execution.db_set("released_qty", flt(execution.released_qty) + release)
            progress.db_set("released_qty", release, update_modified=False)
            refresh_destination(execution.kanban_cycle, execution.operation,
                                execution.destination_operation)
    recalculate(execution.kanban_cycle, execution.operation)
    record("Operation Progress", cycle=execution.kanban_cycle, execution=execution.name,
           qty=good_qty, reference_doctype=progress.doctype, reference_name=progress.name,
           operator=operator, operator_session=operator_session, terminal_user=terminal_user)
    return progress


def complete_execution_handoff(execution_name):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if not execution.destination_operation:
        return
    if execution.handoff_mode in ("Full Batch Handoff", "Automatic Handoff"):
        release = max(0, flt(execution.good_qty) - flt(execution.released_qty))
        if release:
            assert_gate_open(execution.kanban_cycle, "Before WIP Release", execution.operation)
            append_entry(execution.kanban_cycle, "Released", release,
                source_execution=execution.name,
                source_operation=execution.operation,
                destination_operation=execution.destination_operation,
                notes=f"{execution.handoff_mode} on operation completion")
            execution.db_set("released_qty", flt(execution.released_qty) + release)
    recalculate(execution.kanban_cycle, execution.operation)
    refresh_destination(execution.kanban_cycle, execution.operation,
                        execution.destination_operation)

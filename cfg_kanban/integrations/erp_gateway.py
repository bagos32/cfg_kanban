import json

import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.state_machine import set_cycle_state, transition_card


HANDLERS = {}


def handler(command_type):
    def register(fn):
        HANDLERS[command_type] = fn
        return fn
    return register


def execute_command(command_name):
    command = frappe.get_doc("CFG ERP Command", command_name)
    if command.status == "Completed" and command.target_document:
        return frappe.get_doc(command.target_doctype, command.target_document)
    if command.status == "Running":
        frappe.throw("ERP command is already running")
    fn = HANDLERS.get(command.command_type)
    if not fn:
        frappe.throw(f"No ERP gateway handler for {command.command_type}")
    command.db_set({"status": "Running", "started_on": now_datetime(),
                    "attempt_count": (command.attempt_count or 0) + 1})
    try:
        result = fn(command, json.loads(command.request_payload or "{}"))
        command.db_set({"status": "Completed", "completed_on": now_datetime(),
                        "target_document": result.name,
                        "result_payload": frappe.as_json({"doctype": result.doctype, "name": result.name})})
        return result
    except Exception:
        command.db_set({"status": "Failed", "last_error": frappe.get_traceback()})
        raise


@handler("Create Work Order")
def create_work_order(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value("Work Order", {"cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]}, "name")
    if existing:
        return frappe.get_doc("Work Order", existing)
    work_order = frappe.get_doc({
        "doctype": "Work Order", "production_item": payload["production_item"],
        "bom_no": payload.get("bom_no"), "qty": payload["qty"], "company": payload["company"],
        "source_warehouse": payload.get("source_warehouse"), "wip_warehouse": payload.get("wip_warehouse"),
        "fg_warehouse": payload.get("fg_warehouse"), "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name, "cfg_kanban_signal": command.source_signal,
        "cfg_production_origin": "KANBAN",
    }).insert(ignore_permissions=True)
    settings = frappe.get_single("CFG Kanban Settings")
    if settings.auto_submit_work_order:
        work_order.submit()
    cycle.db_set("work_order", work_order.name)
    signal = frappe.get_doc("CFG Kanban Signal", command.source_signal)
    signal.db_set({"erp_reference_doctype": "Work Order", "erp_reference_name": work_order.name,
                   "status": "Completed"})
    set_cycle_state(cycle, "Released", event_type="Work Order Created",
                    reference_doctype="Work Order", reference_name=work_order.name)
    if cycle.kanban_card:
        transition_card(cycle.kanban_card, "Production Released", event_type="Production Released", cycle=cycle.name)
    return work_order


@handler("Start Job Card")
def start_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    job_card.run_method("start_job")
    return job_card


@handler("Complete Job Card")
def complete_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    job_card.run_method("complete_job")
    return job_card


@handler("Create Stock Entry")
def create_stock_entry(command, payload):
    doc = frappe.get_doc({"doctype": "Stock Entry", **payload, "cfg_kanban_controlled": 1,
                          "cfg_kanban_cycle": command.kanban_cycle,
                          "cfg_kanban_signal": command.source_signal}).insert(ignore_permissions=True)
    return doc


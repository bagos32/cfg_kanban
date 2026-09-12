import json

import frappe
from frappe.utils import now_datetime
from erpnext.manufacturing.doctype.work_order.work_order import get_item_details

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
    work_order = frappe.new_doc("Work Order")
    work_order.production_item = payload["production_item"]
    work_order.company = payload["company"]
    work_order.update(get_item_details(payload["production_item"]))
    work_order.update({
        "bom_no": payload.get("bom_no"), "qty": payload["qty"],
        "source_warehouse": payload.get("source_warehouse"), "wip_warehouse": payload.get("wip_warehouse"),
        "fg_warehouse": payload.get("fg_warehouse"), "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name, "cfg_kanban_signal": command.source_signal,
        "cfg_production_origin": "SALES ORDER" if cycle.get("sales_order") else "KANBAN",
        "cfg_sales_order": cycle.get("sales_order"), "cfg_planned_batch": cycle.batch_no,
    })
    work_order.get_items_and_operations_from_bom()
    if not work_order.required_items:
        frappe.throw(f"BOM {work_order.bom_no} did not provide any required material rows")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.operation_profiles and not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and "
                     "configure the ERPNext BOM route before creating a Kanban Work Order.")
    work_order.insert(ignore_permissions=True)
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


@frappe.whitelist()
def reload_draft_work_order_bom(work_order_name):
    """Repair a draft Kanban Work Order created before BOM population was added."""
    work_order = frappe.get_doc("Work Order", work_order_name)
    work_order.check_permission("write")
    if not work_order.cfg_kanban_cycle:
        frappe.throw("This Work Order is not linked to a CFG Kanban Cycle")
    if work_order.docstatus != 0:
        frappe.throw("BOM details can only be reloaded into a Draft Work Order")
    work_order.get_items_and_operations_from_bom()
    if not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and add the route first.")
    work_order.save()
    return {"work_order": work_order.name, "operations": len(work_order.operations),
            "required_items": len(work_order.required_items)}


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

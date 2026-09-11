import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.progress import report
from cfg_kanban.services.triggers import create_work_order_command


@frappe.whitelist()
def get_card_context(token):
    card_name = frappe.db.get_value(
        "CFG Kanban Card", {"qr_code": token}, "name"
    ) or frappe.db.get_value("CFG Kanban Card", {"card_number": token}, "name")
    if not card_name:
        frappe.throw("Kanban card was not found")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle) if card.active_cycle else None
    executions = []
    if cycle:
        executions = frappe.get_all(
            "CFG Kanban Process Execution",
            filters={"kanban_cycle": cycle.name},
            fields=["name", "operation", "sequence", "job_card", "workstation", "status",
                    "target_qty", "good_qty", "reject_qty", "released_qty", "handoff_mode"],
            order_by="sequence asc",
        )
    return {
        "card": card.as_dict(),
        "master": {"name": master.name, "kanban_name": master.kanban_name,
                   "item_code": master.item_code, "automation_level": master.automation_level},
        "cycle": cycle.as_dict() if cycle else None,
        "executions": executions,
    }


@frappe.whitelist()
def approve_signal(signal_name):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    if signal.status == "Completed":
        return {"signal": signal.name, "command": signal.command, "duplicate": True}
    if signal.status not in ("Waiting Approval", "Validated", "Failed"):
        frappe.throw(f"Signal cannot be approved while it is {signal.status}")
    signal.db_set({"status": "Validated", "validated_on": now_datetime()})
    command = create_work_order_command(signal.name)
    result = execute_command(command.name)
    return {"signal": signal.name, "command": command.name,
            "erp_document": result.name, "duplicate": False}


@frappe.whitelist()
def get_execution_form(execution_name, capture_on="Progress"):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    rows = frappe.get_all(
        "CFG Kanban Field Definition",
        filters={"parent": execution.kanban_master, "parenttype": "CFG Kanban Master",
                 "operation": execution.operation, "capture_on": capture_on},
        fields=["field_key", "label", "field_type", "mandatory", "options", "default_value",
                "precision", "min_value", "max_value", "unit", "read_only", "validation_message"],
        order_by="display_order asc, idx asc",
    )
    return {"execution": execution.as_dict(), "fields": rows}


@frappe.whitelist()
def submit_progress(execution_name, good_qty, reject_qty=0, processed_qty=None,
                    values=None, notes=None, event_token=None):
    values = frappe.parse_json(values) if isinstance(values, str) else (values or [])
    _validate_dynamic_values(execution_name, values)
    if event_token:
        key = canonical_key("operator-progress", execution_name, event_token)
        existing = frappe.db.get_value("CFG Kanban Event", {"device_id": key,
            "event_type": "Operation Progress"}, "reference_name")
        if existing:
            return {"name": existing, "duplicate": True}
    progress = report(execution_name, good_qty, reject_qty, processed_qty,
                      values=values, notes=notes)
    if event_token:
        frappe.db.set_value("CFG Kanban Event", {"reference_doctype": progress.doctype,
            "reference_name": progress.name, "event_type": "Operation Progress"}, "device_id", key)
    return {"name": progress.name, "duplicate": False}


@frappe.whitelist()
def run_job_card_action(execution_name, action, event_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if not execution.job_card:
        frappe.throw("This execution is not linked to an ERPNext Job Card")
    command_type = {"start": "Start Job Card", "complete": "Complete Job Card"}.get(action)
    if not command_type:
        frappe.throw("Unsupported Job Card action")
    key = canonical_key("job-card-action", execution.job_card, command_type,
                        event_token or execution.modified)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": command_type,
        "kanban_cycle": execution.kanban_cycle, "process_execution": execution.name,
        "status": "Pending", "target_doctype": "Job Card",
        "request_payload": frappe.as_json({"job_card": execution.job_card}),
        "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    result = execute_command(command.name)
    return {"command": command.name, "job_card": result.name, "duplicate": not created}


@frappe.whitelist()
def get_cycle_timeline(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    events = frappe.get_all(
        "CFG Kanban Event", filters={"kanban_cycle": cycle.name},
        fields=["name", "event_datetime", "event_type", "user", "process_execution",
                "previous_state", "new_state", "qty", "reference_doctype", "reference_name", "notes"],
        order_by="event_datetime desc, creation desc", limit_page_length=200,
    )
    return {"cycle": cycle.as_dict(), "events": events}


def _validate_dynamic_values(execution_name, values):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    definitions = frappe.get_all(
        "CFG Kanban Field Definition",
        filters={"parent": execution.kanban_master, "parenttype": "CFG Kanban Master",
                 "operation": execution.operation, "capture_on": "Progress"},
        fields=["field_key", "label", "field_type", "mandatory", "options",
                "min_value", "max_value", "validation_message"],
    )
    supplied = {row.get("field_key"): row.get("value") for row in values}
    for definition in definitions:
        value = supplied.get(definition.field_key)
        message = definition.validation_message or f"Invalid value for {definition.label}"
        if definition.mandatory and value in (None, ""):
            frappe.throw(f"{definition.label} is required")
        if value in (None, ""):
            continue
        if definition.field_type in ("Int", "Float"):
            numeric = flt(value)
            if definition.min_value is not None and numeric < flt(definition.min_value):
                frappe.throw(message)
            if definition.max_value is not None and numeric > flt(definition.max_value):
                frappe.throw(message)
        if definition.field_type == "Select" and definition.options:
            if str(value) not in definition.options.splitlines():
                frappe.throw(message)

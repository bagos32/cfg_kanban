import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.progress import report
from cfg_kanban.services.operation_summary import recalculate
from cfg_kanban.services.triggers import create_work_order_command
from cfg_kanban.services.runtime_selector import allocate as allocate_runtime_card
from cfg_kanban.services.runtime_selector import preview as preview_runtime_card
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


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
    work_orders = []
    route_warnings = []
    operation_summaries = []
    effective_work_order = None
    if cycle:
        work_orders = frappe.get_all("Work Order", filters={"cfg_kanban_cycle": cycle.name,
            "docstatus": ["<", 2]}, fields=["name", "status", "docstatus"], order_by="creation asc")
        effective_work_order = next((row for row in work_orders if row.name == cycle.work_order), None)
        if cycle.work_order and not effective_work_order:
            effective_work_order = frappe.db.get_value("Work Order", cycle.work_order,
                ["name", "status", "docstatus"], as_dict=True)
        effective_jobs = frappe.get_all("Job Card", filters={"work_order": cycle.work_order,
            "docstatus": ["<", 2]}, pluck="name") if cycle.work_order else []
        executions = frappe.get_all(
            "CFG Kanban Process Execution", filters={"kanban_cycle": cycle.name,
                "job_card": ["in", effective_jobs or ["__none__"]]},
            fields=["name", "operation", "sequence", "job_card", "workstation", "status",
                    "lane_sequence", "execution_mode", "runtime_allocation", "allocated_qty",
                    "target_qty", "processed_qty", "good_qty", "reject_qty", "released_qty",
                    "handoff_mode"],
            order_by="sequence asc",
        )
        for execution in executions:
            job = frappe.db.get_value("Job Card", execution.job_card,
                ["status", "docstatus", "for_quantity", "total_completed_qty"], as_dict=True)
            execution["job_card_status"] = job.status if job else "Missing"
            execution["job_card_docstatus"] = job.docstatus if job else None
            execution["job_card_target_qty"] = flt(job.for_quantity) if job else 0
            execution["job_card_completed_qty"] = flt(job.total_completed_qty) if job else 0
        operation_summaries = frappe.get_all("CFG Kanban Operation Summary",
            filters={"kanban_cycle": cycle.name}, fields=["name", "operation", "sequence",
                "status", "execution_mode", "target_qty", "allocated_qty", "input_available_qty",
                "processed_qty", "good_qty", "reject_qty", "released_qty", "execution_count",
                "completed_execution_count", "destination_operation"], order_by="sequence asc")
        expected = ({card.operation} if cycle.runtime_allocation else
                    {row.operation for row in master.operation_profiles})
        represented = {row.operation for row in executions}
        missing = expected - represented
        if missing:
            route_warnings.append("Missing effective Job Cards for: " + ", ".join(sorted(missing)))
        if len(work_orders) > 1:
            route_warnings.append("Multiple Work Orders still claim this Cycle; supervisor reconciliation is required")
    return {
        "card": card.as_dict(),
        "master": {"name": master.name, "kanban_name": master.kanban_name,
                   "item_code": master.item_code, "automation_level": master.automation_level,
                   "control_type": master.control_type,
                   "card_representation": master.card_representation,
                   "stock_uom": master.stock_uom},
        "cycle": cycle.as_dict() if cycle else None,
        "effective_work_order": effective_work_order,
        "selected_job_card": (frappe.db.get_value("Job Card", cycle.selected_job_card,
            ["name", "status", "docstatus", "for_quantity", "total_completed_qty"], as_dict=True)
            if cycle and cycle.selected_job_card else None),
        "executions": executions,
        "work_orders": work_orders,
        "route_warnings": route_warnings,
        "operation_summaries": operation_summaries,
    }


@frappe.whitelist()
def preview_runtime_selection(card_name, job_card=None):
    return preview_runtime_card(card_name, job_card)


@frappe.whitelist()
def confirm_runtime_selection(card_name, job_card, confirmation, override_reason=None):
    return allocate_runtime_card(card_name, job_card, confirmation, override_reason)


@frappe.whitelist()
def complete_runtime_cycle(execution_name, notes=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if not execution.runtime_allocation:
        frappe.throw("This is not a runtime-selected execution")
    if flt(execution.processed_qty) + 0.000001 < flt(execution.target_qty):
        frappe.throw(f"Report the full allocated quantity {execution.target_qty} before closing the Cycle")
    allocation = frappe.get_doc("CFG Kanban Runtime Allocation", execution.runtime_allocation)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    execution.db_set({"status": "Completed", "completed_on": now_datetime()})
    allocation.db_set({"status": "Completed", "completed_on": now_datetime(),
                       "good_qty": execution.good_qty, "reject_qty": execution.reject_qty,
                       "notes": notes}, update_modified=True)
    cycle.db_set({"completed_on": now_datetime(), "actual_good_qty": execution.good_qty,
                  "reject_qty": execution.reject_qty})
    set_cycle_state(cycle, "Completed", event_type="Runtime Cycle Completed",
                    reference_doctype="Job Card", reference_name=execution.job_card)
    recalculate(cycle.name, execution.operation)
    if card.current_state == "Production Released":
        transition_card(card, "In Production", event_type="Runtime Cycle Closing", cycle=cycle.name)
        card.reload()
    transition_card(card, "Produced", event_type="Runtime Cycle Completed", cycle=cycle.name,
                    notes=notes)
    card.reload()
    transition_card(card, "Available", event_type="Reusable Card Released", cycle=cycle.name)
    card.db_set("active_cycle", None, update_modified=False)
    record("Runtime Allocation Completed", card=card.name, cycle=cycle.name,
           execution=execution.name, qty=execution.good_qty, reference_doctype="Job Card",
           reference_name=execution.job_card, notes=notes)
    target_qty = flt(frappe.db.get_value("Job Card", execution.job_card, "for_quantity"))
    erp_completed = flt(frappe.db.get_value("Job Card", execution.job_card,
                                            "total_completed_qty"))
    kanban_completed = flt(frappe.db.sql("""
        select coalesce(sum(good_qty), 0)
        from `tabCFG Kanban Runtime Allocation`
        where job_card=%s and status='Completed'
    """, execution.job_card)[0][0])
    cumulative_completed = max(erp_completed, kanban_completed)
    target_reached = cumulative_completed + 0.000001 >= target_qty
    if target_reached:
        record("Job Card Kanban Target Reached", card=card.name, cycle=cycle.name,
               execution=execution.name, qty=cumulative_completed,
               reference_doctype="Job Card", reference_name=execution.job_card,
               notes="Confirm and complete the Job Card in ERPNext; Kanban does not bypass ERP validation")
    return {"cycle": cycle.name, "card": card.name, "job_card": execution.job_card,
            "good_qty": execution.good_qty, "reject_qty": execution.reject_qty,
            "cumulative_completed_qty": cumulative_completed,
            "job_card_target_qty": target_qty, "job_card_target_reached": target_reached,
            "job_card_kept_open": not target_reached}


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
    if action == "start":
        execution.db_set({"status": "In Progress", "started_on": now_datetime()})
        if execution.runtime_allocation:
            frappe.db.set_value("CFG Kanban Runtime Allocation", execution.runtime_allocation,
                                "status", "In Progress")
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

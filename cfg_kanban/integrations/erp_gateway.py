import json

import frappe
from frappe.utils import add_to_date, flt, get_datetime, now_datetime
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
        detail = getattr(result, "_cfg_command_result", None) or {
            "doctype": result.doctype, "name": result.name
        }
        command.db_set({"status": "Completed", "completed_on": now_datetime(),
                        "target_document": result.name,
                        "result_payload": frappe.as_json(detail)})
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
    if command.get("operator_session") and not payload.get("employee"):
        frappe.throw("An Employee is required for a Kanban operator Job Card action")
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if not any(not row.to_time for row in job_card.time_logs):
        started = now_datetime()
        job_card.append("time_logs", {
            "from_time": started, "employee": payload.get("employee")
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not start Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="started")
    return job_card


@handler("Pause Job Card")
def pause_job_card(command, payload):
    """Close only the active time log; ERPNext retains cumulative Job Card output."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status != "Work In Progress":
        frappe.throw(f"Job Card {job_card.name} must be Work In Progress before it can be paused")
    open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
    closed_time_log = None
    if open_row:
        open_row.to_time = get_datetime(payload.get("paused_on") or now_datetime())
        closed_time_log = open_row.name
        job_card.save(ignore_permissions=True)
    job_card.reload()
    job_card._cfg_command_result = _job_card_result(
        job_card, action="paused", closed_time_log=closed_time_log,
        kanban_pause=True,
    )
    return job_card


@handler("Resume Job Card")
def resume_job_card(command, payload):
    """Open a fresh time log on the same Job Card after a Kanban-controlled pause."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status not in ("Open", "Work In Progress"):
        frappe.throw(f"Job Card {job_card.name} cannot resume while its status is {job_card.status}")
    if not any(not row.to_time for row in job_card.time_logs):
        job_card.append("time_logs", {
            "from_time": get_datetime(payload.get("resumed_on") or now_datetime()),
            "employee": payload.get("employee"),
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not resume Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="resumed", kanban_pause=True)
    return job_card


@handler("Update Job Card")
def update_job_card(command, payload):
    required = ("job_card", "operation_progress", "incremental_good_qty")
    missing = [field for field in required if payload.get(field) in (None, "")]
    if missing:
        frappe.throw("Job Card progress payload is missing: " + ", ".join(missing))
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")

    progress_ref = payload["operation_progress"]
    # The app-owned child-row link makes a retry independently detectable even when
    # the original CFG command is manually re-created by a supervisor.
    existing = next((row for row in job_card.time_logs
                     if row.get("cfg_kanban_progress") == progress_ref), None)
    before_qty = flt(job_card.total_completed_qty)
    delta = flt(payload["incremental_good_qty"])
    if not existing:
        end_time = get_datetime(payload.get("to_time") or now_datetime())
        start_time = get_datetime(payload.get("from_time") or add_to_date(end_time, minutes=-1))
        closed_rows = [row for row in job_card.time_logs if row.to_time]
        if closed_rows:
            start_time = max(start_time, max(get_datetime(row.to_time) for row in closed_rows))
        if start_time >= end_time:
            start_time = add_to_date(end_time, minutes=-1)
        open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
        if open_row:
            open_row.to_time = end_time
            open_row.completed_qty = delta
            open_row.employee = open_row.employee or payload.get("employee")
            open_row.cfg_kanban_progress = progress_ref
        else:
            job_card.append("time_logs", {
                "from_time": start_time, "to_time": end_time,
                "completed_qty": delta, "employee": payload.get("employee"),
                "cfg_kanban_progress": progress_ref,
            })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    after_qty = flt(job_card.total_completed_qty)
    expected_qty = before_qty if existing else before_qty + delta
    if after_qty + 0.000001 < expected_qty:
        frappe.throw(f"ERPNext Job Card {job_card.name} quantity verification failed: "
                     f"expected at least {expected_qty}, found {after_qty}")
    auto_submitted = False
    settings = frappe.get_single("CFG Kanban Settings")
    if (settings.get("auto_submit_job_card") and job_card.docstatus == 0 and
            after_qty + 0.000001 >= flt(job_card.for_quantity)):
        job_card.submit()
        job_card.reload()
        auto_submitted = True
        if job_card.status != "Completed":
            frappe.throw(f"ERPNext submitted Job Card {job_card.name}, but its status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(
        job_card, action="progress_updated", before_qty=before_qty,
        applied_qty=0 if existing else delta, operation_progress=progress_ref,
        duplicate=bool(existing), reject_qty=flt(payload.get("reject_qty")),
        auto_submitted=auto_submitted,
    )
    return job_card


@handler("Complete Job Card")
def complete_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus == 0:
        if flt(job_card.total_completed_qty) + 0.000001 < flt(job_card.for_quantity):
            frappe.throw(f"Job Card {job_card.name} cannot be completed: ERP completed quantity "
                         f"is {job_card.total_completed_qty} of {job_card.for_quantity}")
        job_card.submit()
    job_card.reload()
    if job_card.status != "Completed":
        frappe.throw(f"ERPNext did not complete Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="completed")
    return job_card


def _job_card_result(job_card, action, **details):
    return {
        "doctype": job_card.doctype, "name": job_card.name, "action": action,
        "status": job_card.status, "docstatus": job_card.docstatus,
        "for_quantity": flt(job_card.for_quantity),
        "total_completed_qty": flt(job_card.total_completed_qty),
        "time_log_rows": len(job_card.time_logs), **details,
    }


@handler("Cancel Signal and Rollback")
def cancel_signal_and_rollback(command, payload):
    from cfg_kanban.services.signal_cancellation import cancel_and_rollback

    return cancel_and_rollback(payload["signal"], payload.get("reason"))


@handler("Create Stock Entry")
def create_stock_entry(command, payload):
    doc = frappe.get_doc({"doctype": "Stock Entry", **payload, "cfg_kanban_controlled": 1,
                          "cfg_kanban_cycle": command.kanban_cycle,
                          "cfg_kanban_signal": command.source_signal}).insert(ignore_permissions=True)
    return doc

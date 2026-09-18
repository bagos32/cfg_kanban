import frappe
from frappe.utils import cint, flt, get_url, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.operator_auth import (close_session, credential_hash, get_session,
                                               new_credential, open_development_proxy_session,
                                               open_session, require_operator)
from cfg_kanban.services.progress import report
from cfg_kanban.services.printing import get_qr_svg
from cfg_kanban.services.operation_summary import recalculate
from cfg_kanban.services.triggers import create_work_order_command
from cfg_kanban.services.runtime_selector import allocate as allocate_runtime_card
from cfg_kanban.services.runtime_selector import preview as preview_runtime_card
from cfg_kanban.services.signal_cancellation import cancel_and_rollback
from cfg_kanban.services.state_machine import set_cycle_state, transition_card
from cfg_kanban.services.process_tasks import (assert_gate_open, ensure_tasks,
                                               refresh_task_readiness)
from cfg_kanban.services.dynamic_forms import definitions, validate_values


@frappe.whitelist()
def login_operator(token, pin=None, station=None):
    return open_session(token, pin=pin, station=station)


@frappe.whitelist()
def operator_session_status(operator_session_token):
    return get_session(operator_session_token)


@frappe.whitelist()
def logout_operator(operator_session_token):
    return close_session(operator_session_token)


@frappe.whitelist()
def login_development_proxy(employee, station=None):
    return open_development_proxy_session(employee, station=station)


@frappe.whitelist()
def issue_operator_credential(profile_name):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    profile = frappe.get_doc("CFG Kanban Operator Profile", profile_name)
    profile.check_permission("write")
    token = new_credential()
    profile.db_set("qr_token_hash", credential_hash(token), update_modified=True)
    login_url = get_url(f"/app/kanban-operator#operator={token}")
    employee = frappe.db.get_value(
        "Employee", profile.employee,
        ["employee_name", "department", "designation", "image"], as_dict=True,
    )
    return {
        "operator_profile": profile.name, "employee": profile.employee,
        "employee_name": employee.employee_name if employee else profile.employee,
        "department": employee.department if employee else None,
        "designation": employee.designation if employee else None,
        "employee_image": employee.image if employee else None,
        "kanban_role": profile.kanban_role,
        "allowed_operations": [row.operation for row in profile.allowed_operations],
        "allowed_workstations": [row.workstation for row in profile.allowed_workstations],
        "qr_token": token, "login_url": login_url, "qr_svg": get_qr_svg(login_url, 220),
    }


@frappe.whitelist()
def get_console_access():
    if frappe.session.user in (None, "", "Guest"):
        frappe.throw("ERP login is required")
    roles = set(frappe.get_roles(frappe.session.user))
    return {
        "terminal_user": frappe.session.user,
        "can_manage_operators": bool({"Manufacturing Manager", "System Manager"} & roles),
        "is_terminal_user": bool({"Kanban Terminal", "Manufacturing Manager", "System Manager"} & roles),
        "can_use_development_proxy": bool(
            frappe.session.user == "Administrator" and
            cint(frappe.db.get_single_value("CFG Kanban Settings",
                                            "enable_administrator_operator_bypass"))
        ),
    }


@frappe.whitelist()
def get_scanner_command_sheet(quantity_steps=None):
    """Return fixed, non-secret command labels for the floor scanner station."""
    allowed_roles = {"Kanban Terminal", "Manufacturing User", "Manufacturing Manager", "System Manager"}
    if not allowed_roles.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw("You are not permitted to print Kanban scanner controls", frappe.PermissionError)
    if isinstance(quantity_steps, str):
        try:
            quantity_steps = frappe.parse_json(quantity_steps)
        except (TypeError, ValueError):
            quantity_steps = quantity_steps.split(",")
    if quantity_steps and not isinstance(quantity_steps, (list, tuple)):
        quantity_steps = [quantity_steps]
    quantity_steps = quantity_steps or (1, 5, 10, 100)
    normalized_steps = []
    for value in quantity_steps[:12]:
        number = flt(value)
        if number <= 0 or number > 1000000:
            frappe.throw("Quantity label values must be greater than zero and not exceed 1,000,000")
        if number not in normalized_steps:
            normalized_steps.append(number)
    commands = [
        ("Switch Operator", "CFG:CMD:SWITCH_OPERATOR", "F2"),
        ("Next Card / Clear", "CFG:CMD:NEXT_CARD", "F3"),
        ("Camera Scan", "CFG:CMD:CAMERA_CARD", "F4"),
        ("End Operator Session", "CFG:CMD:END_SESSION", "F8"),
        ("Start Operation", "CFG:CMD:START", ""),
        ("Report Progress", "CFG:CMD:REPORT_PROGRESS", ""),
    ]
    commands.extend([
        (f"Good +{number:g}", f"CFG:QTY:GOOD:+{number:g}", "")
        for number in normalized_steps
    ])
    commands.extend([
        ("Reject +1", "CFG:QTY:REJECT:+1", ""),
        ("Confirm / Submit", "CFG:CMD:CONFIRM", ""),
        ("Cancel", "CFG:CMD:CANCEL", ""),
        ("Dismiss Message", "CFG:CMD:DISMISS", ""),
    ])
    return [{"label": label, "payload": payload, "key": key,
             "qr_svg": get_qr_svg(payload, 180)} for label, payload, key in commands]


@frappe.whitelist()
def get_card_context(token, operator_session_token=None):
    require_operator(operator_session_token)
    card_name = frappe.db.get_value(
        "CFG Kanban Card", {"qr_code": token}, "name"
    ) or frappe.db.get_value("CFG Kanban Card", {"card_number": token}, "name")
    if not card_name:
        frappe.throw("Kanban card was not found")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if card.card_type in ("Asset Card", "Location Card", "Task Card"):
        task_filters = {"status": ["not in", ("Completed", "Cancelled")]}
        if card.card_type == "Asset Card":
            task_filters["asset"] = card.asset
        elif card.card_type == "Location Card":
            task_filters["location"] = card.location_reference
        else:
            task_filters["task_schedule"] = card.task_schedule
        service_tasks = frappe.get_all(
            "CFG Kanban Task", filters=task_filters,
            fields=["name", "task_name", "status", "priority", "due_on",
                    "assigned_employee", "workstation", "asset", "location"],
            order_by="due_on asc, creation asc", limit_page_length=50,
        )
        return {
            "card": card.as_dict(), "master": {}, "cycle": None,
            "effective_work_order": None, "work_order_attention": None,
            "selected_job_card": None, "executions": [], "work_orders": [],
            "route_warnings": [], "operation_summaries": [], "process_tasks": [],
            "service_tasks": service_tasks, "service_identity_card": True,
        }
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle) if card.active_cycle else None
    executions = []
    work_orders = []
    route_warnings = []
    operation_summaries = []
    effective_work_order = None
    work_order_attention = None
    process_tasks = []
    if cycle:
        ensure_tasks(cycle.name)
        refresh_task_readiness(cycle.name)
        process_tasks = frappe.get_all(
            "CFG Kanban Process Task", filters={"kanban_cycle": cycle.name},
            fields=["name", "task_name", "sequence", "task_type", "trigger_point",
                    "linked_operation", "status", "blocking", "workstation",
                    "verification_required", "valid_until", "reused_from_task",
                    "qc_controlled", "qc_result", "sample_id", "test_method",
                    "specification_reference", "exception"],
            order_by="sequence asc, creation asc",
        )
        work_orders = frappe.get_all("Work Order", filters={"cfg_kanban_cycle": cycle.name,
            "docstatus": ["<", 2]}, fields=["name", "status", "docstatus"], order_by="creation asc")
        effective_work_order = None
        if cycle.work_order:
            effective_work_order = frappe.db.get_value("Work Order", cycle.work_order,
                ["name", "status", "docstatus", "skip_transfer", "transfer_material_against"],
                as_dict=True)
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
                ["name", "status", "docstatus", "for_quantity", "total_completed_qty"], as_dict=True)
            execution["job_card_status"] = job.status if job else "Missing"
            execution["job_card_docstatus"] = job.docstatus if job else None
            execution["job_card_target_qty"] = flt(job.for_quantity) if job else 0
            execution["job_card_completed_qty"] = flt(job.total_completed_qty) if job else 0
            execution["job_card_target_reached"] = bool(
                job and flt(job.total_completed_qty) + 0.000001 >= flt(job.for_quantity)
            )
            execution["job_card_needs_submit"] = bool(
                execution["job_card_target_reached"] and job.docstatus == 0
            ) if job else False
            readiness = _runtime_close_readiness(execution, effective_work_order, job)
            execution["can_close_runtime_cycle"] = readiness["ready"]
            execution["close_block_reason"] = readiness["reason"]
        kanban_processed = sum(flt(row.processed_qty) for row in executions)
        if (effective_work_order and effective_work_order.status == "Not Started" and
                cycle.status in ("Released", "In Production", "Packing In Progress",
                                 "Production Complete", "Waiting FG Receipt")):
            job_in_progress = any(
                row.job_card_status in ("Work In Progress", "Completed")
                for row in executions
            )
            skip_transfer_active = bool(effective_work_order.skip_transfer and job_in_progress)
            work_order_attention = {
                "severity": "info" if skip_transfer_active else "warning",
                "work_order": effective_work_order.name,
                "work_order_status": effective_work_order.status,
                "cycle_status": cycle.status, "kanban_processed_qty": kanban_processed,
                "message": (("Work Order uses Skip Transfer and its Job Card is already in progress. "
                             "The Work Order header may remain Not Started until ERPNext posts more "
                             "production activity; Job Card quantity synchronization remains mandatory.")
                            if skip_transfer_active else
                            (f"Kanban Cycle is {cycle.status}"
                             + (f" with {kanban_processed} processed" if kanban_processed else "")
                             + ", but the ERPNext Work Order is still Not Started. Check material "
                               "transfer or ERP production prerequisites before continuing.")),
            }
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
        "work_order_attention": work_order_attention,
        "selected_job_card": (frappe.db.get_value("Job Card", cycle.selected_job_card,
            ["name", "status", "docstatus", "for_quantity", "total_completed_qty"], as_dict=True)
            if cycle and cycle.selected_job_card else None),
        "executions": executions,
        "work_orders": work_orders,
        "route_warnings": route_warnings,
        "operation_summaries": operation_summaries,
        "process_tasks": process_tasks,
        "service_tasks": [],
        "service_identity_card": False,
    }


@frappe.whitelist()
def preview_runtime_selection(card_name, job_card=None, operator_session_token=None):
    require_operator(operator_session_token)
    return preview_runtime_card(card_name, job_card)


@frappe.whitelist()
def confirm_runtime_selection(card_name, job_card, confirmation, override_reason=None,
                              operator_session_token=None):
    action = "override" if override_reason else "start"
    scope = frappe.db.get_value("Job Card", job_card, ["operation", "workstation"], as_dict=True)
    if not scope:
        frappe.throw("Job Card was not found")
    require_operator(operator_session_token, action, operation=scope.operation,
                     workstation=scope.workstation)
    return allocate_runtime_card(card_name, job_card, confirmation, override_reason)


@frappe.whitelist()
def complete_runtime_cycle(execution_name, notes=None, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(operator_session_token, "complete", execution=execution)
    assert_gate_open(execution.kanban_cycle, "Before Cycle Close")
    if not execution.runtime_allocation:
        frappe.throw("This is not a runtime-selected execution")
    if flt(execution.processed_qty) + 0.000001 < flt(execution.target_qty):
        frappe.throw(f"Report the full allocated quantity {execution.target_qty} before closing the Cycle")
    allocation = frappe.get_doc("CFG Kanban Runtime Allocation", execution.runtime_allocation)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    work_order = frappe.db.get_value("Work Order", cycle.work_order,
        ["name", "status", "docstatus", "skip_transfer", "transfer_material_against"],
        as_dict=True)
    job_card = frappe.db.get_value("Job Card", execution.job_card,
        ["name", "status", "docstatus", "for_quantity", "total_completed_qty"], as_dict=True)
    readiness = _runtime_close_readiness(execution, work_order, job_card)
    if not readiness["ready"]:
        frappe.throw(readiness["reason"])
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
           reference_name=execution.job_card, notes=notes, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)
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
               notes="ERPNext Job Card is completed and the cumulative Kanban target is reached")
    return {"cycle": cycle.name, "card": card.name, "job_card": execution.job_card,
            "good_qty": execution.good_qty, "reject_qty": execution.reject_qty,
            "cumulative_completed_qty": cumulative_completed,
            "job_card_target_qty": target_qty, "job_card_target_reached": target_reached,
            "job_card_submitted": bool(job_card and job_card.docstatus == 1),
            "job_card_kept_open": not target_reached}


def _runtime_close_readiness(execution, work_order, job_card):
    if not execution.get("runtime_allocation"):
        return {"ready": True, "reason": None}
    job_in_progress = bool(job_card and job_card.status in ("Work In Progress", "Completed"))
    work_order_started = bool(work_order and (
        work_order.status in ("In Process", "Started", "Completed") or
        (work_order.status == "Not Started" and work_order.skip_transfer and job_in_progress)
    ))
    if not work_order_started:
        status = work_order.status if work_order else "Missing"
        return {"ready": False, "reason": (f"Cannot close the Kanban Cycle while ERPNext Work Order "
                f"is {status}. Start the Work Order and satisfy any material-transfer prerequisites first.")}
    if not job_card or job_card.status not in ("Work In Progress", "Completed"):
        status = job_card.status if job_card else "Missing"
        return {"ready": False, "reason": (f"Cannot close the Kanban Cycle while ERPNext Job Card "
                f"is {status}. Start the Job Card and record its production time log first.")}
    if (flt(job_card.total_completed_qty) + 0.000001 >= flt(job_card.for_quantity) and
            job_card.docstatus == 0):
        return {"ready": False, "reason": (
            f"Cannot close the final Kanban Cycle while ERPNext Job Card {job_card.name} is still Draft. "
            "Use Complete Job Card first, or enable Auto-submit Job Card at Target in Kanban Settings."
        )}
    prior_good = flt(frappe.db.sql("""
        select coalesce(sum(good_qty), 0)
        from `tabCFG Kanban Runtime Allocation`
        where job_card=%s and status='Completed' and name != %s
    """, (execution.job_card, execution.runtime_allocation))[0][0])
    required_erp_qty = prior_good + flt(execution.good_qty)
    erp_qty = flt(job_card.total_completed_qty)
    if erp_qty + 0.000001 < required_erp_qty:
        return {"ready": False, "reason": (f"Cannot close the Kanban Cycle: cumulative Kanban good "
                f"quantity is {required_erp_qty}, but ERPNext Job Card completed quantity is only {erp_qty}. "
                "Update the Job Card time log, save it, and reload the Operator panel.")}
    return {"ready": True, "reason": None}


@frappe.whitelist()
def approve_signal(signal_name):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    if signal.status == "Completed":
        return {"signal": signal.name, "command": signal.command, "duplicate": True}
    if signal.status not in ("Waiting Approval", "Validated", "Failed"):
        frappe.throw(f"Signal cannot be approved while it is {signal.status}")
    assert_gate_open(signal.kanban_cycle, "Before Cycle Start")
    signal.db_set({"status": "Validated", "validated_on": now_datetime()})
    command = create_work_order_command(signal.name)
    result = execute_command(command.name)
    return {"signal": signal.name, "command": command.name,
            "erp_document": result.name, "duplicate": False}


@frappe.whitelist()
def cancel_signal(signal_name, reason):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    signal.check_permission("write")
    if signal.status == "Cancelled":
        cycle = frappe.get_doc("CFG Kanban Cycle", signal.kanban_cycle)
        active_cycle = (frappe.db.get_value("CFG Kanban Card", signal.kanban_card,
                                            "active_cycle") if signal.kanban_card else None)
        if cycle.status == "Cancelled" and active_cycle != cycle.name:
            return {"signal": signal.name, "duplicate": True}
    key = canonical_key("cancel-signal", signal.name)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Cancel Signal and Rollback",
        "source_signal": signal.name, "kanban_cycle": signal.kanban_cycle,
        "status": "Pending", "target_doctype": "CFG Kanban Signal",
        "request_payload": frappe.as_json({"signal": signal.name, "reason": reason}),
        "requested_on": now_datetime(), "created_by_system": 1,
    }), key)
    if not created and command.status == "Completed":
        # Repair an inconsistent result produced by an older rollback implementation.
        result = cancel_and_rollback(signal.name, reason)
    else:
        result = execute_command(command.name)
    frappe.db.set_value("CFG Kanban Signal", result.name, "command", command.name,
                        update_modified=False)
    return {"signal": result.name, "command": command.name, "duplicate": not created}


@frappe.whitelist()
def get_execution_form(execution_name, capture_on="Progress", operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "report_progress", execution=execution)
    rows = definitions(execution.kanban_master, capture_on, operation=execution.operation)
    return {"execution": execution.as_dict(), "fields": rows}


@frappe.whitelist()
def submit_progress(execution_name, good_qty, reject_qty=0, processed_qty=None,
                    values=None, notes=None, event_token=None, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(operator_session_token, "report_progress", execution=execution)
    if flt(reject_qty) > 0:
        require_operator(operator_session_token, "report_reject", execution=execution)
    values = frappe.parse_json(values) if isinstance(values, str) else (values or [])
    _validate_dynamic_values(execution_name, values)
    if event_token:
        key = canonical_key("operator-progress", execution_name, event_token)
        existing = frappe.db.get_value("CFG Kanban Event", {"device_id": key,
            "event_type": "Operation Progress"}, "reference_name")
        if existing:
            return {"name": existing, "duplicate": True}
    progress = report(execution_name, good_qty, reject_qty, processed_qty,
                      values=values, notes=notes, operator=profile.employee,
                      operator_session=session.name, terminal_user=session.terminal_user)
    erp_command = None
    if execution.job_card and flt(good_qty):
        payload = _job_card_progress_payload(execution, progress, event_token,
                                             employee=profile.employee,
                                             operator_user=session.terminal_user)
        key = canonical_key("job-card-progress", execution.job_card, progress.name)
        command, _created = insert_once(frappe.get_doc({
            "doctype": "CFG ERP Command", "command_type": "Update Job Card",
            "kanban_cycle": execution.kanban_cycle, "process_execution": execution.name,
            "status": "Pending", "target_doctype": "Job Card",
            "request_payload": frappe.as_json(payload),
            "requested_on": now_datetime(), "created_by_system": 1,
            "requested_by_operator": profile.employee, "operator_session": session.name,
            "terminal_user": session.terminal_user,
        }), key, ignore_permissions=True)
        execute_command(command.name)
        erp_command = command.name
    if event_token:
        frappe.db.set_value("CFG Kanban Event", {"reference_doctype": progress.doctype,
            "reference_name": progress.name, "event_type": "Operation Progress"}, "device_id", key)
    return {"name": progress.name, "erp_command": erp_command, "duplicate": False}


def _job_card_progress_payload(execution, progress, event_token=None, employee=None,
                               operator_user=None):
    return {
        "job_card": execution.job_card,
        "work_order": frappe.db.get_value("Job Card", execution.job_card, "work_order"),
        "kanban_cycle": execution.kanban_cycle,
        "process_execution": execution.name,
        "runtime_allocation": execution.runtime_allocation,
        "operation_progress": progress.name,
        "incremental_good_qty": flt(progress.good_qty),
        "reject_qty": flt(progress.reject_qty),
        "processed_qty": flt(progress.processed_qty),
        "operator_user": operator_user or frappe.session.user,
        "employee": employee,
        "from_time": execution.started_on,
        "to_time": progress.posting_datetime,
        "notes": progress.notes,
        "event_token": event_token,
    }


@frappe.whitelist()
def run_job_card_action(execution_name, action, event_token=None, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(operator_session_token, action, execution=execution)
    if not execution.job_card:
        frappe.throw("This execution is not linked to an ERPNext Job Card")
    if action == "start":
        assert_gate_open(execution.kanban_cycle, "Before Operation Start", execution.operation)
        master = frappe.get_doc("CFG Kanban Master", execution.kanban_master)
        operation_profile = next(
            (row for row in master.operation_profiles if row.operation == execution.operation), None
        )
        if operation_profile and operation_profile.dependency_operation:
            assert_gate_open(execution.kanban_cycle, "After Operation Complete",
                             operation_profile.dependency_operation)
    command_type = {"start": "Start Job Card", "complete": "Complete Job Card"}.get(action)
    if not command_type:
        frappe.throw("Unsupported Job Card action")
    key = canonical_key("job-card-action", execution.job_card, command_type,
                        event_token or execution.modified)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": command_type,
        "kanban_cycle": execution.kanban_cycle, "process_execution": execution.name,
        "status": "Pending", "target_doctype": "Job Card",
        "request_payload": frappe.as_json({
            "job_card": execution.job_card, "kanban_cycle": execution.kanban_cycle,
            "process_execution": execution.name, "runtime_allocation": execution.runtime_allocation,
            "operator_user": session.terminal_user,
            "employee": profile.employee,
            "event_token": event_token,
        }),
        "requested_on": now_datetime(), "created_by_system": 1,
        "requested_by_operator": profile.employee, "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }), key, ignore_permissions=True)
    result = execute_command(command.name)
    if action == "start":
        execution.db_set({"status": "In Progress", "started_on": now_datetime()})
        if execution.runtime_allocation:
            frappe.db.set_value("CFG Kanban Runtime Allocation", execution.runtime_allocation,
                                "status", "In Progress")
    record(f"Operator Job Card {action.title()}", cycle=execution.kanban_cycle,
           execution=execution.name, reference_doctype="Job Card", reference_name=result.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return {"command": command.name, "job_card": result.name, "duplicate": not created}


@frappe.whitelist()
def get_cycle_timeline(cycle_name, operator_session_token=None):
    require_operator(operator_session_token)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    events = frappe.get_all(
        "CFG Kanban Event", filters={"kanban_cycle": cycle.name},
        fields=["name", "event_datetime", "event_type", "user", "operator", "process_execution",
                "process_task",
                "previous_state", "new_state", "qty", "reference_doctype", "reference_name", "notes"],
        order_by="event_datetime desc, creation desc", limit_page_length=200,
    )
    return {"cycle": cycle.as_dict(), "events": events}


def _validate_dynamic_values(execution_name, values):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    rows = definitions(execution.kanban_master, "Progress", operation=execution.operation)
    validate_values(rows, values)

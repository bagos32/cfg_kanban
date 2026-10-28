import hashlib

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
from cfg_kanban.services.purchase_replenishment import (
    continue_purchase_execution,
    create_material_request_command,
)
from cfg_kanban.services.runtime_selector import allocate as allocate_runtime_card
from cfg_kanban.services.runtime_selector import preview as preview_runtime_card
from cfg_kanban.services.signal_cancellation import cancel_and_rollback
from cfg_kanban.services.state_machine import set_cycle_state, transition_card
from cfg_kanban.services.process_tasks import (assert_gate_open, ensure_tasks,
                                               refresh_task_readiness)
from cfg_kanban.services.dynamic_forms import definitions, validate_values
from cfg_kanban.services.production_trace import SUPPORTED_PURPOSES
from cfg_kanban.services.crew_authorization import (
    enforce_execution_crew,
    enforce_operation_crew,
    evaluate_execution_crew,
)


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
        "is_terminal_user": bool({"Kanban Terminal", "Manufacturing Manager", "Stock User",
                                  "Stock Manager", "System Manager"} & roles),
        "can_use_development_proxy": bool(
            frappe.session.user == "Administrator" and
            cint(frappe.db.get_single_value("CFG Kanban Settings",
                                            "enable_administrator_operator_bypass"))
        ),
    }


def _require_scanner_command_print_permission():
    allowed_roles = {"Kanban Terminal", "Manufacturing User", "Manufacturing Manager", "System Manager"}
    if not allowed_roles.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw("You are not permitted to print Kanban scanner controls", frappe.PermissionError)


def _normalise_scanner_quantity_steps(quantity_steps=None):
    if isinstance(quantity_steps, str):
        try:
            quantity_steps = frappe.parse_json(quantity_steps)
        except (TypeError, ValueError):
            quantity_steps = quantity_steps.split(",")
    if quantity_steps and not isinstance(quantity_steps, (list, tuple)):
        quantity_steps = [quantity_steps]
    quantity_steps = quantity_steps or (1, 5, 10, 50, 100)
    normalized_steps = []
    for value in quantity_steps[:12]:
        number = flt(value)
        if number <= 0 or number > 1000000:
            frappe.throw("Quantity label values must be greater than zero and not exceed 1,000,000")
        if number not in normalized_steps:
            normalized_steps.append(number)
    return normalized_steps


def _scanner_command_catalog(quantity_steps=None):
    normalized_steps = _normalise_scanner_quantity_steps(quantity_steps)
    command_groups = [
        ("Session Controls", [
            ("Scanner Help", "CFG:CMD:HELP", "F1"),
            ("Switch Operator", "CFG:CMD:SWITCH_OPERATOR", "F2"),
            ("Next Card / Clear", "CFG:CMD:NEXT_CARD", "F3"),
            ("Camera Scan", "CFG:CMD:CAMERA_CARD", "F4"),
            ("End Operator Session", "CFG:CMD:END_SESSION", "F8"),
        ]),
        ("Card and Operation", [
            ("Activate / Consume Card", "CFG:CMD:ACTIVATE", ""),
            ("Accept Cycle Ownership", "CFG:CMD:ACCEPT_OWNER", ""),
            ("Transfer Cycle Ownership", "CFG:CMD:TRANSFER_OWNER", ""),
            ("Report Correction", "CFG:CMD:REQUEST_CORRECTION", ""),
            ("Start Operation", "CFG:CMD:START", ""),
            ("Report Progress", "CFG:CMD:REPORT_PROGRESS", ""),
            ("Go to Current Work", "CFG:CMD:GO_TO_CURRENT_WORK", ""),
            ("Close Kanban Cycle", "CFG:CMD:CLOSE_CYCLE", ""),
        ]),
        ("Production Material and WIP", [
            ("Prepare Transfer / Consumption", "CFG:CMD:PREPARE_MATERIALS", ""),
            ("Record Loose WIP Use", "CFG:CMD:RECORD_LOOSE_WIP_USE", ""),
            ("Prepare Consolidated Loose WIP Consumption", "CFG:CMD:PREPARE_LOOSE_WIP_CONSUMPTION", ""),
            ("Prepare Manufacture Receipt", "CFG:CMD:PREPARE_RECEIPT", ""),
            ("Scan Material Tags", "CFG:CMD:SCAN_MATERIALS", ""),
            ("WIP Bin: Use ERP-only Source", "CFG:CMD:NO_SOURCE", ""),
            ("WIP Bin: Restore Full-bin Mode", "CFG:CMD:FULL_BIN", ""),
            ("Submit Material Entry", "CFG:CMD:SUBMIT_MATERIALS", ""),
        ]),
        ("Crew Controls", [
            ("Crew Controls", "CFG:CMD:CREW", ""),
            ("Crew: Open Session", "CFG:CMD:CREW_OPEN", ""),
            ("Crew: Join Direct", "CFG:CMD:CREW_JOIN", ""),
            ("Crew: Join Oversight", "CFG:CMD:CREW_JOIN_OVERSIGHT", ""),
            ("Crew: Join Temporary Support", "CFG:CMD:CREW_JOIN_TEMP", ""),
            ("Crew: Start Break", "CFG:CMD:CREW_BREAK", ""),
            ("Crew: Resume", "CFG:CMD:CREW_RESUME", ""),
            ("Crew: Leave", "CFG:CMD:CREW_LEAVE", ""),
            ("Crew: Change Main Operator", "CFG:CMD:CREW_MAIN", ""),
            ("Crew: Use Current Operation", "CFG:CMD:CREW_CONTEXT", ""),
            ("Crew: Close Session", "CFG:CMD:CREW_CLOSE", ""),
        ]),
    ]
    command_groups.extend([
        ("Numbered Selection", [
            (f"Select Option {number}", f"CFG:SELECT:{number}", "")
            for number in range(1, 11)
        ]),
        ("Good Quantity", [
            (f"Good +{number:g}", f"CFG:QTY:GOOD:+{number:g}", "")
            for number in normalized_steps
        ]),
        ("Material Quantity", [
            (f"Material Qty {number:g}", f"CFG:QTY:MATERIAL:{number:g}", "")
            for number in normalized_steps
        ]),
        ("Confirmation", [
            ("Reject +1", "CFG:QTY:REJECT:+1", ""),
            ("Confirm / Submit", "CFG:CMD:CONFIRM", ""),
            ("Cancel", "CFG:CMD:CANCEL", ""),
            ("Dismiss Message", "CFG:CMD:DISMISS", ""),
        ]),
    ])
    return [
        {"category": category, "label": label, "payload": payload, "key": key}
        for category, commands in command_groups
        for label, payload, key in commands
    ]


@frappe.whitelist()
def get_scanner_command_catalog(quantity_steps=None):
    """Return printable command metadata without generating every QR image."""
    _require_scanner_command_print_permission()
    return _scanner_command_catalog(quantity_steps)


@frappe.whitelist()
def get_scanner_command_sheet(
    quantity_steps=None, selected_payloads=None, custom_labels=None, print_all=0
):
    """Return validated, selected non-secret command labels with their printable QR images."""
    _require_scanner_command_print_permission()
    catalog = _scanner_command_catalog(quantity_steps)
    by_payload = {row["payload"]: row for row in catalog}
    if isinstance(selected_payloads, str):
        selected_payloads = frappe.parse_json(selected_payloads)
    if isinstance(custom_labels, str):
        custom_labels = frappe.parse_json(custom_labels)
    custom_labels = custom_labels or {}
    if not isinstance(custom_labels, dict):
        frappe.throw("Custom command labels must be a payload-to-label mapping")
    unknown_custom = set(custom_labels) - set(by_payload)
    if unknown_custom:
        frappe.throw(f"Unknown scanner command label: {sorted(unknown_custom)[0]}")

    # Preserve compatibility with the previous API, where omitting a selection
    # generated the complete sheet. The new UI sends an explicit list for
    # selective printing and print_all=1 for the full catalogue.
    if cint(print_all) or selected_payloads is None:
        selected = set(by_payload)
    else:
        if not isinstance(selected_payloads, (list, tuple)) or not selected_payloads:
            frappe.throw("Select at least one scanner command to print")
        selected = set(selected_payloads)
        unknown = selected - set(by_payload)
        if unknown:
            frappe.throw(f"Unknown scanner command: {sorted(unknown)[0]}")

    rows = []
    for row in catalog:
        if row["payload"] not in selected:
            continue
        custom_label = str(custom_labels.get(row["payload"]) or "").strip()
        if len(custom_label) > 100:
            frappe.throw("A custom scanner command label cannot exceed 100 characters")
        rows.append({
            **row,
            "custom_label": custom_label,
            "qr_svg": get_qr_svg(row["payload"], 180),
        })
    return rows


@frappe.whitelist()
def get_execution_crew_panel(execution_name, operator_session_token=None):
    """Return the scanner-facing crew context for one production execution."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, _session = require_operator(operator_session_token, execution=execution)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    master = frappe.get_cached_doc("CFG Kanban Master", execution.kanban_master)

    decision = evaluate_execution_crew(
        execution.name, "Operator Crew Panel", persist=False
    )
    active_crew = None
    from cfg_kanban.services.crew_registry import (
        get_active_workstation_crew,
        get_crew_session,
    )

    registered_crew = get_active_workstation_crew(
        master.company, execution.workstation
    )
    crew_name = (
        registered_crew["session"].name if registered_crew
        else decision.get("crew_session")
    )
    if crew_name:
        active_crew = get_crew_session(crew_name, operator_session_token)

    templates = frappe.get_all(
        "CFG Kanban Crew Template",
        filters={
            "company": master.company,
            "workstation": execution.workstation,
            "active": 1,
            "docstatus": 1,
        },
        fields=["name", "template_code", "template_name", "operation", "revision"],
        order_by="template_name asc",
        limit_page_length=0,
    )
    templates = [
        row for row in templates
        if not row.operation or row.operation == execution.operation
    ]
    actor_membership = None
    if active_crew:
        actor_membership = next(
            (
                row for row in active_crew.get("members") or []
                if row.employee == profile.employee and row.status in ("Active", "On Break")
            ),
            None,
        )
    can_override = bool(
        cint(profile.get("can_override")) or profile.get("kanban_role") == "Supervisor"
    )
    policy = decision.get("policy") or {}
    return {
        "execution": {
            "name": execution.name,
            "operation": execution.operation,
            "workstation": execution.workstation,
            "status": execution.status,
            "job_card": execution.job_card,
            "kanban_cycle": cycle.name,
        },
        "company": master.company,
        "configured": bool(decision.get("configured")),
        "allowed": bool(decision.get("allowed")),
        "findings": decision.get("findings") or [],
        "policy": {
            "crew_mode": policy.get("crew_mode"),
            "minimum_direct_workers": policy.get("minimum_direct_workers") or 0,
            "minimum_assistants": policy.get("minimum_assistants") or 0,
            "supervision_required": bool(policy.get("supervision_required")),
            "trainee_policy": policy.get("trainee_policy"),
        },
        "crew": active_crew,
        "templates": templates,
        "actor_membership": actor_membership,
        "can_manage": bool(
            (actor_membership and actor_membership.status == "Active") or can_override
        ),
        "can_override": can_override,
    }


@frappe.whitelist()
def open_execution_crew_session(
    execution_name,
    operator_session_token,
    crew_template=None,
    notes=None,
):
    """Open a crew only from server-derived Company/Workstation/Operation context."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, execution=execution)
    master = frappe.get_cached_doc("CFG Kanban Master", execution.kanban_master)
    from cfg_kanban.services.crew_registry import open_workstation_crew_session

    return open_workstation_crew_session(
        master.company,
        execution.workstation,
        operator_session_token,
        operation=execution.operation,
        crew_template=crew_template or None,
        notes=notes,
    )


@frappe.whitelist()
def get_card_context(token, operator_session_token=None):
    profile, _session = require_operator(operator_session_token)
    card_name = _resolve_card_name(token)
    if not card_name:
        frappe.throw("Kanban card was not found")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    production_reconciliation = None
    if card.active_cycle and card.card_type in ("Physical Unit Card", "Physical Batch Card"):
        from cfg_kanban.integrations.erp_feedback import reconcile_physical_production_cycle
        production_reconciliation = reconcile_physical_production_cycle(card.active_cycle)
        card.reload()
    if card.card_type == "DocType Action Card":
        frappe.throw(
            "This is a non-production DocType Action Card. Open it in the Service Task panel; "
            "the production operator panel cannot create Signals, Cycles, or Work Orders from it."
        )
    if card.card_type == "Workstation Queue Card":
        if not card.active or card.blocked:
            frappe.throw("Workstation Queue Card is inactive or blocked")
        require_operator(operator_session_token, workstation=card.current_station)
        return {
            "card": card.as_dict(), "master": {}, "cycle": None,
            "effective_work_order": None, "work_order_attention": None,
            "selected_job_card": None, "executions": [], "work_orders": [],
            "route_warnings": [], "operation_summaries": [],
            "production_stock_entries": [], "production_material_flow": None,
            "process_tasks": [], "service_tasks": [],
            "job_ownership": None,
            "job_role_compliance": None,
            "correction_requests": [],
            "service_identity_card": False, "workstation_queue_card": True,
            "workstation_queue": _workstation_queue_context(card, profile),
        }
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
            "route_warnings": [], "operation_summaries": [],
            "production_stock_entries": [], "production_material_flow": None,
            "process_tasks": [],
            "job_ownership": None,
            "job_role_compliance": None,
            "correction_requests": [],
            "service_tasks": service_tasks, "service_identity_card": True,
        }
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle) if card.active_cycle else None
    executions = []
    work_orders = []
    route_warnings = []
    operation_summaries = []
    production_stock_entries = []
    production_material_flow = None
    production_material_owner_cycle = None
    operation_material_job = None
    effective_work_order = None
    work_order_attention = None
    process_tasks = []
    job_ownership = None
    job_role_compliance = None
    correction_requests = []
    if cycle:
        from cfg_kanban.services.job_ownership import ownership_context
        job_ownership = ownership_context(cycle, profile)
        from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
        job_role_compliance = evaluate_cycle_roles(cycle.name, persist=True)
        from cfg_kanban.integrations.erp_feedback import reconcile_cycle_job_card_progress
        reconcile_cycle_job_card_progress(cycle.name)
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
                    "handoff_mode", "crew_compliance_status", "last_crew_compliance_check",
                    "crew_compliance_hold"],
            order_by="sequence asc",
        )
        from cfg_kanban.services.action_approval import (
            close_on_behalf_requirement,
            ownership_transfer_requirement,
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
            execution["wip_bin_erp_posting_pending"] = readiness.get(
                "wip_bin_erp_posting_pending", False
            )
            execution["wip_bin_pending_entries"] = readiness.get(
                "wip_bin_pending_entries", []
            )
            execution["close_approval"] = close_on_behalf_requirement(execution, profile)
            execution["close_requires_supervisor_approval"] = bool(
                execution["close_approval"].get("required")
            )
            execution["crew"] = _execution_crew_summary(execution, master.company)
        if job_ownership and executions:
            transfer_execution = next(
                (
                    row for row in executions
                    if row.status not in ("Completed", "Cancelled")
                ),
                executions[0],
            )
            job_ownership["transfer"] = ownership_transfer_requirement(
                transfer_execution, profile
            )
            job_ownership["transfer_execution"] = transfer_execution.name
        correction_requests = frappe.get_all(
            "CFG Kanban Correction Request",
            filters={
                "kanban_cycle": cycle.name,
                "requested_by_employee": profile.employee,
            },
            fields=[
                "name", "status", "correction_category", "affected_scope",
                "affected_doctype", "affected_document", "reason", "requested_on",
                "review_decision", "reviewed_by_name", "reviewed_on",
            ],
            order_by="requested_on desc",
            limit_page_length=20,
        )
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
        material_cycle, operation_material_job = _material_control_scope(cycle)
        production_stock_entries = _production_stock_entries(
            material_cycle, job_card=operation_material_job
        ) if material_cycle else []
        if material_cycle:
            from cfg_kanban.services.production_material_flow import get_cycle_material_flow
            production_material_flow = get_cycle_material_flow(
                material_cycle.name, operator_session_token=operator_session_token
            )
            production_material_owner_cycle = material_cycle.name
            if operation_material_job:
                production_material_flow = _operation_material_flow_scope(
                    production_material_flow, cycle, operation_material_job
                )
    return {
        "card": card.as_dict(),
        "master": {"name": master.name, "kanban_name": master.kanban_name,
                   "item_code": master.item_code, "automation_level": master.automation_level,
                   "control_type": master.control_type,
                   "card_representation": master.card_representation,
                   "stock_uom": master.stock_uom,
                   "purchase_uom": master.get("purchase_uom"),
                   "purchase_uom_conversion_factor": master.get("purchase_uom_conversion_factor"),
                   "purchase_replenishment_qty": master.get("purchase_replenishment_qty")},
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
        "production_progress": _production_progress(operation_summaries),
        "production_stock_entries": production_stock_entries,
        "production_material_flow": production_material_flow,
        "production_material_owner_cycle": production_material_owner_cycle,
        "operation_material_job": operation_material_job,
        "process_tasks": process_tasks,
        "job_ownership": job_ownership,
        "job_role_compliance": job_role_compliance,
        "correction_requests": correction_requests,
        "service_tasks": [],
        "service_identity_card": False,
        "workstation_queue_card": False,
        "production_reconciliation": production_reconciliation,
    }


def _production_progress(summaries):
    """Return a compact route-level view without replacing per-operation results."""
    if not summaries:
        return None
    rows = sorted(summaries, key=lambda row: (flt(row.sequence), row.operation or ""))
    route_target = sum(flt(row.target_qty) for row in rows)
    route_good = sum(min(flt(row.good_qty), flt(row.target_qty)) for row in rows)
    final = rows[-1]
    return {
        "route_good_qty": route_good,
        "route_target_qty": route_target,
        "route_percent": min(100, (route_good / route_target * 100) if route_target else 0),
        "completed_operations": sum(row.status == "Completed" for row in rows),
        "operation_count": len(rows),
        "final_operation": final.operation,
        "final_good_qty": flt(final.good_qty),
        "final_target_qty": flt(final.target_qty),
    }


def _execution_crew_summary(execution, company):
    from cfg_kanban.services.crew_registry import get_active_workstation_crew

    crew = get_active_workstation_crew(company, execution.get("workstation"))
    members = list((crew or {}).get("members") or [])
    active = [row for row in members if row.status == "Active"]
    on_break = [row for row in members if row.status == "On Break"]
    return {
        "session": crew["session"].name if crew else None,
        "main_employee": crew["session"].main_employee if crew else None,
        "main_employee_name": crew["session"].main_employee_name if crew else None,
        "operation_context": crew["session"].operation_context if crew else None,
        "active_count": len(active),
        "break_count": len(on_break),
        "direct_count": sum(
            row.work_category == "Direct Participation" for row in active
        ),
        "oversight_count": sum(
            row.work_category == "Oversight Only" for row in active
        ),
        "compliance_status": execution.get("crew_compliance_status") or "Not Checked",
        "compliance_check": execution.get("last_crew_compliance_check"),
        "compliance_hold": execution.get("crew_compliance_hold"),
    }


@frappe.whitelist()
def get_card_live_revision(token, operator_session_token=None):
    """Return a cheap change token without rebuilding the operator card context."""
    require_operator(operator_session_token)
    card_name = _resolve_card_name(token)
    if not card_name:
        frappe.throw("Kanban card was not found")
    card = frappe.db.get_value(
        "CFG Kanban Card", card_name,
        ["name", "card_type", "current_state", "active_cycle", "current_station",
         "task_schedule", "asset", "location_reference", "modified"],
        as_dict=True,
    )
    markers = [
        f"card:{card.name}:{card.current_state}:{card.active_cycle or ''}:{card.modified}"
    ]
    signal_modified = frappe.db.get_value(
        "CFG Kanban Signal", {"kanban_card": card.name}, "max(modified)"
    )
    if signal_modified:
        markers.append(f"signal:{signal_modified}")

    cycle = None
    if card.active_cycle:
        cycle = frappe.db.get_value(
            "CFG Kanban Cycle", card.active_cycle,
            ["name", "status", "work_order", "modified"], as_dict=True,
        )
    if cycle:
        markers.append(f"cycle:{cycle.name}:{cycle.status}:{cycle.modified}")
        for doctype, filters in (
            ("CFG Kanban Process Execution", {"kanban_cycle": cycle.name}),
            ("CFG Kanban Operation Summary", {"kanban_cycle": cycle.name}),
            ("CFG Kanban Process Task", {"kanban_cycle": cycle.name}),
            ("CFG ERP Command", {"kanban_cycle": cycle.name}),
            ("CFG Kanban Cycle Role Assignment", {"kanban_cycle": cycle.name}),
            ("CFG Kanban Correction Request", {"kanban_cycle": cycle.name}),
        ):
            modified = frappe.db.get_value(doctype, filters, "max(modified)")
            if modified:
                markers.append(f"{doctype}:{modified}")
        if cycle.work_order:
            for doctype, filters in (
                ("Work Order", {"name": cycle.work_order}),
                ("Job Card", {"work_order": cycle.work_order, "docstatus": ["<", 2]}),
                ("Stock Entry", {"work_order": cycle.work_order, "docstatus": ["<", 2]}),
                ("CFG Kanban WIP Bin Reconciliation", {"work_order": cycle.work_order}),
            ):
                modified = frappe.db.get_value(doctype, filters, "max(modified)")
                if modified:
                    markers.append(f"{doctype}:{modified}")
        workstations = frappe.get_all(
            "CFG Kanban Process Execution",
            filters={"kanban_cycle": cycle.name},
            pluck="workstation",
        )
        for workstation in sorted(set(filter(None, workstations))):
            crew_event_modified = frappe.db.get_value(
                "CFG Kanban Crew Event", {"workstation": workstation}, "max(modified)"
            )
            if crew_event_modified:
                markers.append(f"crew:{workstation}:{crew_event_modified}")
    elif card.card_type == "Workstation Queue Card" and card.current_station:
        modified = frappe.db.get_value(
            "CFG Kanban Dispatch Queue",
            {"workstation": card.current_station,
             "dispatch_status": ["not in", ("Completed", "Cancelled")]},
            "max(modified)",
        )
        if modified:
            markers.append(f"queue:{modified}")
    elif card.card_type in ("Asset Card", "Location Card", "Task Card"):
        filters = {"status": ["not in", ("Completed", "Cancelled")]}
        if card.card_type == "Asset Card":
            filters["asset"] = card.asset
        elif card.card_type == "Location Card":
            filters["location"] = card.location_reference
        else:
            filters["task_schedule"] = card.task_schedule
        modified = frappe.db.get_value("CFG Kanban Task", filters, "max(modified)")
        if modified:
            markers.append(f"task:{modified}")

    revision = hashlib.sha256("|".join(markers).encode("utf-8")).hexdigest()
    return {"card": card.name, "revision": revision, "checked_at": now_datetime()}


def _resolve_card_name(token):
    return (
        frappe.db.get_value("CFG Kanban Card", {"qr_code": token}, "name")
        or frappe.db.get_value("CFG Kanban Card", {"card_number": token}, "name")
    )


def _workstation_queue_context(card, profile):
    """Return a read-only, operator-scoped queue for one permanent workstation card."""
    rows = frappe.get_all(
        "CFG Kanban Dispatch Queue",
        filters={
            "workstation": card.current_station,
            "dispatch_status": ["not in", ("Completed", "Cancelled")],
        },
        fields=[
            "name", "process_execution", "kanban_cycle", "kanban_master", "item_code",
            "target_qty", "work_order", "job_card", "operation", "workstation",
            "dispatch_status", "readiness", "queue_position", "system_priority",
            "supervisor_priority", "expedite", "sequence_source", "creation",
        ],
        order_by="queue_position asc, creation asc",
        limit_page_length=500,
    )
    allowed_operations = {
        row.operation for row in profile.allowed_operations if row.operation
    }
    master_names = {row.kanban_master for row in rows if row.kanban_master}
    masters = {
        row.name: row for row in frappe.get_all(
            "CFG Kanban Master",
            filters={"name": ["in", list(master_names) or ["__none__"]]},
            fields=["name", "company"], limit_page_length=500,
        )
    }
    cycle_names = {row.kanban_cycle for row in rows if row.kanban_cycle}
    cycles = {
        row.name: row for row in frappe.get_all(
            "CFG Kanban Cycle",
            filters={"name": ["in", list(cycle_names) or ["__none__"]]},
            fields=["name", "kanban_card", "status", "priority"],
            limit_page_length=500,
        )
    }
    card_names = {row.kanban_card for row in cycles.values() if row.kanban_card}
    cards = {
        row.name: row for row in frappe.get_all(
            "CFG Kanban Card",
            filters={"name": ["in", list(card_names) or ["__none__"]]},
            fields=["name", "card_number", "qr_code"], limit_page_length=500,
        )
    }
    execution_names = {row.process_execution for row in rows if row.process_execution}
    executions = {
        row.name: row for row in frappe.get_all(
            "CFG Kanban Process Execution",
            filters={"name": ["in", list(execution_names) or ["__none__"]]},
            fields=["name", "good_qty", "processed_qty", "reject_qty", "target_qty"],
            limit_page_length=500,
        )
    }
    visible = []
    for row in rows:
        master = masters.get(row.kanban_master) or frappe._dict()
        if card.queue_company and master.company != card.queue_company:
            continue
        if allowed_operations and row.operation not in allowed_operations:
            continue
        cycle = cycles.get(row.kanban_cycle) or frappe._dict()
        production_card = cards.get(cycle.kanban_card) or frappe._dict()
        execution = executions.get(row.process_execution) or frappe._dict()
        row.update({
            "cycle_status": cycle.status,
            "priority": row.supervisor_priority or cycle.priority or row.system_priority or "Normal",
            "kanban_card": cycle.kanban_card,
            "card_number": production_card.card_number,
            "card_qr_code": production_card.qr_code,
            "good_qty": flt(execution.good_qty),
            "processed_qty": flt(execution.processed_qty),
            "reject_qty": flt(execution.reject_qty),
            "target_qty": flt(execution.target_qty or row.target_qty),
        })
        visible.append(row)
    return {
        "company": card.queue_company,
        "workstation": card.current_station,
        "active": [row for row in visible if row.dispatch_status == "In Progress"],
        "paused": [row for row in visible if row.dispatch_status == "Paused"],
        "queue": [row for row in visible if row.dispatch_status not in ("In Progress", "Paused")],
        "total": len(visible),
    }


def _material_control_scope(cycle):
    """Return the Work Order-owning Cycle and optional operation Job Card scope."""
    if not cycle or not cycle.work_order:
        return None, None
    owner_name = frappe.db.get_value("Work Order", cycle.work_order, "cfg_kanban_cycle")
    if not owner_name:
        return None, None
    if owner_name == cycle.name:
        if frappe.db.get_value("CFG Kanban Master", cycle.kanban_master,
                               "control_type") != "Production":
            return None, None
        return cycle, None
    if not cycle.runtime_allocation or not cycle.selected_job_card:
        return None, None
    job_work_order = frappe.db.get_value("Job Card", cycle.selected_job_card, "work_order")
    if job_work_order != cycle.work_order:
        return None, None
    owner = frappe.get_doc("CFG Kanban Cycle", owner_name)
    if owner.work_order != cycle.work_order:
        return None, None
    if frappe.db.get_value("CFG Kanban Master", owner.kanban_master,
                           "control_type") != "Production":
        return None, None
    return owner, cycle.selected_job_card


def _operation_material_flow_scope(flow, requesting_cycle, job_card):
    """Limit an operation Card to its selected Job Card's material responsibilities."""
    scoped_jobs = [row for row in (flow.get("jobs") or []) if row.get("name") == job_card]
    flow["jobs"] = scoped_jobs
    flow["wip_bin_reconciliations"] = [
        row for row in (flow.get("wip_bin_reconciliations") or [])
        if row.get("job_card") == job_card
    ]
    flow["materials"] = []
    flow["has_pending_materials"] = any(
        row.get("has_pending_materials") for row in scoped_jobs
    )
    flow["all_job_cards_completed"] = False
    flow["incomplete_job_cards"] = []
    flow["remaining_output_qty"] = 0
    flow["operation_card_scope"] = True
    flow["requesting_cycle"] = requesting_cycle.name
    flow["selected_job_card"] = job_card
    return flow


def _production_stock_entries(cycle, job_card=None):
    """Return only ERP transactions belonging to the scanned production Work Order."""
    if not cycle.work_order:
        return []
    fields = ["name", "purpose", "stock_entry_type", "docstatus", "posting_date",
              "posting_time", "fg_completed_qty", "cfg_kanban_cycle", "job_card",
              "cfg_kanban_job_card", "cfg_wip_bin_return_load", "modified"]
    rows = frappe.get_all(
        "Stock Entry",
        filters={
            "work_order": cycle.work_order,
            "docstatus": ["<", 2],
            "purpose": ["in", sorted(SUPPORTED_PURPOSES)],
        },
        fields=fields,
        order_by="modified desc",
        limit_page_length=20,
    )
    rows = [row for row in rows
            if not row.cfg_kanban_cycle or row.cfg_kanban_cycle == cycle.name]
    return_names = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        filters={"kanban_cycle": cycle.name,
                 "return_stock_entry": ["is", "set"]},
        pluck="return_stock_entry", limit_page_length=0,
    )
    if return_names:
        rows.extend(frappe.get_all(
            "Stock Entry",
            filters={"name": ["in", list(dict.fromkeys(return_names))],
                     "docstatus": ["<", 2]},
            fields=fields, order_by="modified desc", limit_page_length=0,
        ))
        rows = list({row.name: row for row in rows}.values())
        rows.sort(key=lambda row: row.modified, reverse=True)
    if job_card:
        rows = [row for row in rows
                if (row.cfg_kanban_job_card or row.job_card) == job_card
                and (
                    row.purpose in (
                        "Material Transfer for Manufacture",
                        "Material Consumption for Manufacture",
                    )
                    or bool(row.cfg_wip_bin_return_load)
                )]
    if not rows:
        return []
    traces = frappe.get_all(
        "CFG Kanban Material Trace",
        filters={"stock_entry": ["in", [row.name for row in rows]]},
        fields=["name", "stock_entry", "status"],
    )
    trace_by_entry = {row.stock_entry: row for row in traces}
    from cfg_kanban.services.production_material_flow import (
        operation_consumption_submission_readiness,
    )
    produced_qty = flt(frappe.db.get_value("Work Order", cycle.work_order, "produced_qty"))
    for row in rows:
        trace = trace_by_entry.get(row.name)
        row["erp_status"] = "Draft" if row.docstatus == 0 else "Submitted"
        row["trace"] = trace.name if trace else None
        row["trace_status"] = trace.status if trace else "Not Started"
        row["is_wip_bin_return"] = bool(row.cfg_wip_bin_return_load)
        row["can_stage_trace"] = row.docstatus == 0 and not row.is_wip_bin_return
        owning_job_card = row.cfg_kanban_job_card or row.job_card
        route_readiness = (
            operation_consumption_submission_readiness(
                cycle.work_order,
                owning_job_card,
                required_qty=flt(row.fg_completed_qty) + produced_qty,
            )
            if row.purpose == "Material Consumption for Manufacture"
            and owning_job_card
            else ({"ready": False,
                   "reason": "Operation consumption is missing its audited Job Card"}
                  if row.purpose == "Material Consumption for Manufacture"
                  else {"ready": True, "reason": None})
        )
        row["erp_route_ready"] = route_readiness["ready"]
        row["submit_block_reason"] = (
            route_readiness["reason"] if not row["erp_route_ready"] else None
        )
        row["can_submit"] = row.docstatus == 0 and row["erp_route_ready"]
        row["submit_permission"] = (
            "material_transfer" if row.purpose in (
                "Material Transfer",
                "Material Transfer for Manufacture",
                "Material Consumption for Manufacture",
            )
            else "production_receipt"
        )
    return rows


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
    preview_runtime_card(card_name, job_card)
    profile, session = require_operator(
        operator_session_token, action, operation=scope.operation,
        workstation=scope.workstation,
    )
    card = frappe.get_doc("CFG Kanban Card", card_name)
    enforce_operation_crew(
        card.kanban_master,
        scope.operation,
        scope.workstation,
        "Before Runtime Allocation",
        card_name=card.name,
        actor=_crew_actor(profile, session),
    )
    result = allocate_runtime_card(card_name, job_card, confirmation, override_reason)
    actor = _crew_actor(profile, session)
    compliance = evaluate_execution_crew(
        result["execution"], "Runtime Allocation", actor=actor, persist=True
    )
    if not compliance.get("configured"):
        from cfg_kanban.services.job_participation import sync_execution_participation
        sync_execution_participation(
            result["execution"], actor=actor, source_event="Runtime Allocation"
        )
    return result


@frappe.whitelist()
def approve_supervisor_action(action_code, execution_name, supervisor_qr_token, reason,
                              operator_session_token=None, supervisor_pin=None,
                              subject_qr_token=None, subject_pin=None):
    """Issue a short-lived, one-time approval without changing the active operator."""
    from cfg_kanban.services.action_approval import approve_action
    return approve_action(
        action_code=action_code,
        execution_name=execution_name,
        approver_qr_token=supervisor_qr_token,
        reason=reason,
        operator_session_token=operator_session_token,
        approver_pin=supervisor_pin,
        subject_qr_token=subject_qr_token,
        subject_pin=subject_pin,
    )


@frappe.whitelist()
def submit_correction_request(
    execution_name,
    correction_category,
    affected_scope,
    reason,
    requested_change,
    evidence_notes=None,
    event_token=None,
    operator_session_token=None,
):
    """Record a correction request without mutating its affected record."""
    from cfg_kanban.services.correction_requests import create_correction_request
    return create_correction_request(
        execution_name=execution_name,
        correction_category=correction_category,
        affected_scope=affected_scope,
        reason=reason,
        requested_change=requested_change,
        evidence_notes=evidence_notes,
        event_token=event_token,
        operator_session_token=operator_session_token,
    )


@frappe.whitelist()
def preview_job_ownership_transfer(
    execution_name,
    replacement_qr_token,
    operator_session_token=None,
    replacement_pin=None,
):
    """Validate and name the scanned replacement without changing ownership."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, execution=execution)
    from cfg_kanban.services.action_approval import profile_from_credential
    replacement = profile_from_credential(replacement_qr_token, replacement_pin)
    from cfg_kanban.services.job_ownership import validate_transfer_target
    validate_transfer_target(execution.kanban_cycle, execution, replacement)
    return {
        "employee": replacement.employee,
        "employee_name": (
            replacement.employee_name
            or frappe.db.get_value("Employee", replacement.employee, "employee_name")
            or replacement.employee
        ),
        "operator_profile": replacement.name,
    }


@frappe.whitelist()
def transfer_job_ownership(
    execution_name,
    replacement_qr_token,
    reason,
    supervisor_approval_token,
    operator_session_token=None,
    replacement_pin=None,
):
    """Consume an exact-action pass and atomically transfer live Cycle ownership."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    requester, session = require_operator(
        operator_session_token, execution=execution
    )
    if not (reason or "").strip():
        frappe.throw("An ownership transfer reason is required")
    from cfg_kanban.services.action_approval import (
        consume_action_approval,
        profile_from_credential,
    )
    replacement = profile_from_credential(replacement_qr_token, replacement_pin)
    approval = consume_action_approval(
        supervisor_approval_token,
        "TRANSFER_CYCLE_OWNERSHIP",
        execution,
        requester,
        session,
        subject_profile=replacement,
        reason=reason,
    )
    from cfg_kanban.services.job_ownership import transfer_cycle_ownership
    return transfer_cycle_ownership(
        execution.kanban_cycle,
        execution,
        replacement,
        requester,
        session,
        reason,
        approval,
    )


@frappe.whitelist()
def complete_runtime_cycle(execution_name, notes=None, operator_session_token=None,
                           supervisor_approval_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(operator_session_token, "complete", execution=execution)
    enforce_execution_crew(
        execution.name, "Before Completion", actor=_crew_actor(profile, session)
    )
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
    from cfg_kanban.services.action_approval import (
        close_on_behalf_requirement,
        consume_action_approval,
    )
    from cfg_kanban.services.runtime_roles import evaluate_cycle_roles
    evaluate_cycle_roles(cycle.name, persist=True)
    close_approval = close_on_behalf_requirement(execution, profile)
    consumed_approval = None
    if close_approval["required"]:
        consumed_approval = consume_action_approval(
            supervisor_approval_token,
            "CLOSE_CYCLE_ON_BEHALF",
            execution,
            profile,
            session,
        )
    execution.db_set({"status": "Completed", "completed_on": now_datetime()})
    from cfg_kanban.services.job_participation import close_execution_participation
    close_execution_participation(
        execution.name,
        actor=_crew_actor(profile, session),
        source_event="Runtime Cycle Completed",
        reason="Runtime-selected Kanban Cycle completed",
    )
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
    pending_wip_entries = readiness.get("wip_bin_pending_entries", [])
    if pending_wip_entries:
        pending_stock_entries = readiness.get("wip_bin_pending_stock_entries", [])
        reference_doctype = (
            "Stock Entry" if pending_stock_entries else "CFG Kanban WIP Bin Load"
        )
        reference_name = (
            pending_stock_entries[0] if pending_stock_entries
            else readiness.get("wip_bin_pending_loads", [pending_wip_entries[0]])[0]
        )
        record(
            "Operation Closed with ERP Consumption Pending",
            card=card.name, cycle=cycle.name, execution=execution.name,
            qty=execution.good_qty, reference_doctype=reference_doctype,
            reference_name=reference_name, operator=profile.employee,
            operator_session=session.name, terminal_user=session.terminal_user,
            notes=("Physical WIP-bin use was fully scanned; ERP posting remains pending in "
                   + ", ".join(pending_wip_entries)),
        )
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
            "job_card_kept_open": not target_reached,
            "wip_bin_erp_posting_pending": bool(pending_wip_entries),
            "wip_bin_pending_entries": pending_wip_entries,
            "supervisor_action_approval": (
                consumed_approval.name if consumed_approval else None
            )}


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
    from cfg_kanban.services.wip_bin_loads import job_card_wip_bin_close_readiness
    wip_bin_readiness = job_card_wip_bin_close_readiness(job_card.name)
    if not wip_bin_readiness["ready"]:
        return {"ready": False, "reason": wip_bin_readiness["reason"]}
    pending_wip_stock_entries = [
        row.name for row in wip_bin_readiness.get("pending_erp_entries", [])
    ]
    pending_wip_loads = [
        row.name for row in wip_bin_readiness.get("pending_wip_loads", [])
    ]
    pending_wip_entries = pending_wip_stock_entries + pending_wip_loads
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
    return {
        "ready": True,
        "reason": wip_bin_readiness.get("reason"),
        "wip_bin_erp_posting_pending": bool(pending_wip_entries),
        "wip_bin_pending_entries": pending_wip_entries,
        "wip_bin_pending_stock_entries": pending_wip_stock_entries,
        "wip_bin_pending_loads": pending_wip_loads,
    }


@frappe.whitelist()
def approve_signal(signal_name):
    frappe.only_for(("Manufacturing Manager", "Purchase Manager", "Stock Manager", "System Manager"))
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    if signal.status == "Completed":
        return {"signal": signal.name, "command": signal.command, "duplicate": True}
    if signal.status not in ("Waiting Approval", "Validated", "Failed"):
        frappe.throw(f"Signal cannot be approved while it is {signal.status}")
    assert_gate_open(signal.kanban_cycle, "Before Cycle Start")
    signal.db_set({"status": "Validated", "validated_on": now_datetime()})
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type == "Transfer":
        from cfg_kanban.services.internal_transfer import create_transfer_manifest
        manifest = create_transfer_manifest(signal.name)
        return {"signal": signal.name, "manifest": manifest.name,
                "erp_document": None, "duplicate": False}
    if master.control_type == "Withdrawal":
        from cfg_kanban.services.withdrawal import release_withdrawal
        cycle = release_withdrawal(signal.name)
        return {"signal": signal.name, "cycle": cycle.name,
                "erp_document": None, "duplicate": False}
    command = (create_material_request_command(signal.name)
               if master.control_type == "Purchase Replenishment"
               else create_work_order_command(signal.name))
    result = execute_command(command.name)
    purchase_execution = (continue_purchase_execution(signal.kanban_cycle)
                          if master.control_type == "Purchase Replenishment" else None)
    return {"signal": signal.name, "command": command.name,
            "erp_document": result.name, "purchase_execution": purchase_execution,
            "duplicate": False}


@frappe.whitelist()
def cancel_signal(signal_name, reason):
    frappe.only_for(("Manufacturing Manager", "Purchase Manager", "Stock Manager",
                     "System Manager"))
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
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
    crew_result = enforce_execution_crew(
        execution.name, "Progress", actor=_crew_actor(profile, session)
    )
    from cfg_kanban.services.job_ownership import accept_cycle_ownership
    accept_cycle_ownership(
        execution.kanban_cycle, profile, session, crew_result=crew_result
    )
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
    from cfg_kanban.services.job_participation import sync_execution_participation
    sync_execution_participation(
        execution.name,
        actor=_crew_actor(profile, session),
        source_event="Operation Progress",
    )
    erp_command = None
    erp_result = None
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
        job_card = execute_command(command.name)
        erp_result = getattr(job_card, "_cfg_command_result", None)
        erp_command = command.name
    if event_token:
        frappe.db.set_value("CFG Kanban Event", {"reference_doctype": progress.doctype,
            "reference_name": progress.name, "event_type": "Operation Progress"}, "device_id", key)
    return {
        "name": progress.name, "erp_command": erp_command,
        "erp_result": erp_result,
        "duplicate": False,
    }


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
    crew_result = enforce_execution_crew(
        execution.name,
        "Before Operation Start" if action == "start" else "Before Completion",
        actor=_crew_actor(profile, session),
    )
    if action == "start":
        _assert_materials_ready_for_job_card(execution.job_card)
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
    from cfg_kanban.services.job_ownership import accept_cycle_ownership
    accept_cycle_ownership(
        execution.kanban_cycle,
        profile,
        session,
        crew_result=crew_result,
    )
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
        from cfg_kanban.services.job_participation import sync_execution_participation
        sync_execution_participation(
            execution.name,
            actor=_crew_actor(profile, session),
            source_event="Job Card Started",
        )
    record(f"Operator Job Card {action.title()}", cycle=execution.kanban_cycle,
           execution=execution.name, reference_doctype="Job Card", reference_name=result.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return {"command": command.name, "job_card": result.name, "duplicate": not created}


@frappe.whitelist()
def accept_job_ownership(execution_name, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(
        operator_session_token, "start", execution=execution
    )
    crew_result = enforce_execution_crew(
        execution.name,
        "Owner Acceptance",
        actor=_crew_actor(profile, session),
    )
    from cfg_kanban.services.job_ownership import accept_cycle_ownership
    return accept_cycle_ownership(
        execution.kanban_cycle,
        profile,
        session,
        crew_result=crew_result,
    )


def _crew_actor(profile, session):
    return {
        "employee": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }


def _assert_materials_ready_for_job_card(job_card_name):
    from cfg_kanban.services.production_material_flow import job_card_material_readiness
    readiness = job_card_material_readiness(job_card_name)
    if not readiness["ready"]:
        frappe.throw(readiness["reason"])


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

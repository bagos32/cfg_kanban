"""High-frequency operation Material Run lifecycle.

This first package creates the immutable run boundary only. Material draws, exact serial
reservations, progress closure, carry-forward and ERP settlement attach to this identity in
the following packages. ERPNext remains the manufacturing and stock system of record.
"""

import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, get_existing
from cfg_kanban.services.operator_auth import require_operator


ACTIVE_EXECUTION_STATES = {"In Progress", "Paused"}
CONTROL_MODES = {"Optional", "Required Before Progress"}
BOUNDARY_MODES = {"None", "First Run Only", "Every Material Run"}


@frappe.whitelist()
def get_material_run_context(execution_name, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(
        operator_session_token, "report_progress", execution=execution,
        touch_activity=False,
    )
    return _context_payload(execution)


@frappe.whitelist()
def start_scanner_run(
    execution_name,
    event_token,
    output_serial_boundary=None,
    operator_session_token=None,
):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(
        operator_session_token, "report_progress", execution=execution
    )
    _assert_enabled(execution)
    if execution.status not in ACTIVE_EXECUTION_STATES:
        frappe.throw(
            _("Start the operation before opening a Material Run. {0} is currently {1}.").format(
                execution.operation, execution.status
            )
        )
    if not event_token:
        frappe.throw(_("A stable scanner event token is required"))

    boundary = _normalise_boundary(output_serial_boundary)
    _assert_boundary(execution, boundary)
    key = canonical_key("operation-material-run", execution.name, event_token)
    existing = get_existing("CFG Kanban Operation Material Run", key)
    if existing:
        _assert_idempotent_match(existing, execution.name, boundary)
        return _run_payload(existing, duplicate=True)

    active = _open_run(execution.name)
    if active:
        return _run_payload(active, already_open=True)

    work_order = frappe.db.get_value("Job Card", execution.job_card, "work_order") \
        if execution.job_card else None
    run = frappe.get_doc({
        "doctype": "CFG Kanban Operation Material Run",
        "status": "Open",
        "run_number": _next_run_number(execution.name),
        "kanban_cycle": execution.kanban_cycle,
        "kanban_master": execution.kanban_master,
        "process_execution": execution.name,
        "runtime_allocation": execution.runtime_allocation,
        "work_order": work_order,
        "job_card": execution.job_card,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "output_serial_boundary": boundary,
        "opened_on": now_datetime(),
        "opened_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
        "active_execution_key": execution.name,
        "idempotency_key": key,
    })
    try:
        run.insert(ignore_permissions=True)
    except frappe.UniqueValidationError:
        existing = get_existing("CFG Kanban Operation Material Run", key)
        if existing:
            _assert_idempotent_match(existing, execution.name, boundary)
            return _run_payload(existing, duplicate=True)
        active = _open_run(execution.name)
        if active:
            return _run_payload(active, already_open=True)
        raise

    execution.db_set("open_material_run", run.name, update_modified=True)
    record(
        "Operation Material Run Started",
        cycle=execution.kanban_cycle,
        execution=execution.name,
        reference_doctype=run.doctype,
        reference_name=run.name,
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
        input_source="Scanner",
        source_event_id=event_token,
        work_order=work_order,
        job_card=execution.job_card,
        operation=execution.operation,
        workstation=execution.workstation,
        output_serial_boundary=boundary,
        notes=_("Material Run {0} opened for high-frequency operation evidence").format(
            run.run_number
        ),
        idempotency_key=canonical_key("operation-material-run-event", run.name),
    )
    return _run_payload(run)


@frappe.whitelist()
def cancel_scanner_run(
    execution_name,
    event_token,
    reason="Operator cancelled an open Material Run started by mistake",
    operator_session_token=None,
):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    profile, session = require_operator(
        operator_session_token, "report_progress", execution=execution
    )
    run = _open_run(execution.name)
    if not run:
        return {"execution": execution.name, "cancelled": False, "already_closed": True}
    if run.progress or run.material_draw_count:
        frappe.throw(
            _("Material Run {0} already has production evidence and requires controlled correction").format(
                run.name
            )
        )
    reason = str(reason or "").strip()
    if not reason:
        frappe.throw(_("A cancellation reason is required"))
    key = canonical_key("cancel-operation-material-run", run.name, event_token or "")
    existing = frappe.db.get_value(
        "CFG Kanban Event", {"idempotency_key": key}, "name"
    )
    if existing:
        return {"name": run.name, "cancelled": run.status == "Cancelled", "duplicate": True}

    cancelled_on = now_datetime()
    run.db_set({
        "status": "Cancelled",
        "active_execution_key": None,
        "cancelled_on": cancelled_on,
        "closed_on": cancelled_on,
        "cancellation_reason": reason,
    }, update_modified=True)
    execution.db_set("open_material_run", None, update_modified=True)
    record(
        "Operation Material Run Cancelled",
        cycle=execution.kanban_cycle,
        execution=execution.name,
        reference_doctype=run.doctype,
        reference_name=run.name,
        previous_state="Open",
        new_state="Cancelled",
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
        input_source="Scanner",
        source_event_id=event_token,
        work_order=run.work_order,
        job_card=execution.job_card,
        operation=execution.operation,
        workstation=execution.workstation,
        output_serial_boundary=run.output_serial_boundary,
        notes=reason,
        idempotency_key=key,
    )
    return {"name": run.name, "cancelled": True, "duplicate": False}


def open_run_for_execution(execution_name):
    """Return the current open run for internal progress linkage."""
    return _open_run(execution_name)


def close_run_with_progress(
    run,
    progress,
    *,
    operator=None,
    operator_session=None,
    terminal_user=None,
):
    """Atomically bind an open run to the progress that ends its floor interval."""
    run = run if getattr(run, "doctype", None) else frappe.get_doc(
        "CFG Kanban Operation Material Run", run
    )
    if run.status != "Open":
        frappe.throw(_("Material Run {0} is no longer open").format(run.name))
    if progress.process_execution != run.process_execution:
        frappe.throw(_("Progress does not belong to the open Material Run execution"))
    closed_on = now_datetime()
    run.db_set({
        "status": "Progress Posted",
        "progress": progress.name,
        "closed_on": closed_on,
        "active_execution_key": None,
    }, update_modified=True)
    execution = frappe.get_doc("CFG Kanban Process Execution", run.process_execution)
    if execution.open_material_run == run.name:
        execution.db_set("open_material_run", None, update_modified=True)
    record(
        "Operation Material Run Progress Posted",
        cycle=run.kanban_cycle,
        execution=run.process_execution,
        qty=progress.good_qty,
        reference_doctype=run.doctype,
        reference_name=run.name,
        previous_state="Open",
        new_state="Progress Posted",
        operator=operator,
        operator_session=operator_session,
        terminal_user=terminal_user,
        work_order=run.work_order,
        job_card=run.job_card,
        operation=run.operation,
        workstation=run.workstation,
        output_serial_boundary=run.output_serial_boundary,
        notes=_("Closed by progress record {0}").format(progress.name),
        idempotency_key=canonical_key("operation-material-run-progress", run.name, progress.name),
    )
    return run


def _context_payload(execution):
    mode = execution.material_run_control or "Disabled"
    boundary_mode = execution.material_run_output_boundary or "None"
    open_run = _open_run(execution.name)
    prior_count = frappe.db.count(
        "CFG Kanban Operation Material Run",
        {"process_execution": execution.name, "status": ["!=", "Cancelled"]},
    )
    return {
        "execution": execution.name,
        "operation": execution.operation,
        "workstation": execution.workstation,
        "job_card": execution.job_card,
        "execution_status": execution.status,
        "control_mode": mode,
        "boundary_mode": boundary_mode,
        "boundary_required": _boundary_required(boundary_mode, prior_count),
        "allow_material_carry_forward": bool(execution.allow_material_carry_forward),
        "settlement_timing": execution.material_run_settlement_timing,
        "open_run": _run_payload(open_run) if open_run else None,
        "prior_run_count": prior_count,
    }


def _assert_enabled(execution):
    if (execution.material_run_control or "Disabled") not in CONTROL_MODES:
        frappe.throw(
            _("Material Run Control is disabled for operation {0}").format(
                execution.operation
            )
        )


def _assert_boundary(execution, boundary):
    boundary_mode = execution.material_run_output_boundary or "None"
    if boundary_mode not in BOUNDARY_MODES:
        frappe.throw(_("Unsupported Material Run output boundary setting"))
    prior_count = frappe.db.count(
        "CFG Kanban Operation Material Run",
        {"process_execution": execution.name, "status": ["!=", "Cancelled"]},
    )
    if _boundary_required(boundary_mode, prior_count) and not boundary:
        frappe.throw(_("Scan the first output serial or production boundary for this Material Run"))


def _boundary_required(boundary_mode, prior_count):
    return boundary_mode == "Every Material Run" or (
        boundary_mode == "First Run Only" and not prior_count
    )


def _normalise_boundary(value):
    boundary = str(value or "").strip()
    if not boundary:
        return None
    if len(boundary) > 140 or re.search(r"[\x00-\x1f\x7f]", boundary):
        frappe.throw(_("Output serial boundary is invalid"))
    return boundary


def _open_run(execution_name):
    name = frappe.db.get_value(
        "CFG Kanban Operation Material Run",
        {"process_execution": execution_name, "status": "Open"},
        "name",
        order_by="opened_on desc, creation desc",
    )
    return frappe.get_doc("CFG Kanban Operation Material Run", name) if name else None


def _next_run_number(execution_name):
    last = frappe.db.get_value(
        "CFG Kanban Operation Material Run",
        {"process_execution": execution_name},
        "max(run_number)",
    )
    return int(last or 0) + 1


def _assert_idempotent_match(run, execution_name, boundary):
    if run.process_execution != execution_name or run.output_serial_boundary != boundary:
        frappe.throw(
            _("This Material Run scanner token was already used for different data; rescan to create a new run"),
            frappe.ValidationError,
        )


def _run_payload(run, duplicate=False, already_open=False):
    return {
        "name": run.name,
        "status": run.status,
        "run_number": run.run_number,
        "process_execution": run.process_execution,
        "operation": run.operation,
        "workstation": run.workstation,
        "job_card": run.job_card,
        "output_serial_boundary": run.output_serial_boundary,
        "opened_on": run.opened_on,
        "opened_by_operator": run.opened_by_operator,
        "duplicate": duplicate,
        "already_open": already_open,
    }

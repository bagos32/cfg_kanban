"""High-frequency operation Material Run and scanner material-draw lifecycle.

Material Draws are operational reservations against a physical source tag. They prevent
parallel floor runs from declaring the same tagged quantity twice, but deliberately do not
post ERPNext stock or mutate the Handling Unit ledger. A later native ERP transaction binds
the draw to final consumption. ERPNext remains the manufacturing and stock system of record.
"""

import re

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, get_existing
from cfg_kanban.services.operator_auth import require_operator


ACTIVE_EXECUTION_STATES = {"In Progress", "Paused"}
CONTROL_MODES = {"Optional", "Required Before Progress"}
BOUNDARY_MODES = {"None", "First Run Only", "Every Material Run"}
TRACKED_MODE = "Source Tag Quantity"
ACTIVE_DRAW_STATUSES = ("Open", "Partially Used", "Carry Forward", "Used")
TOLERANCE = 0.000001


def build_material_run_rule_snapshot(master, operation):
    """Freeze the material rules that apply when one Process Execution is released."""
    master = master if getattr(master, "doctype", None) else frappe.get_doc(
        "CFG Kanban Master", master
    )
    rules = []
    for row in master.material_flow_rules:
        if row.operation != operation or (row.material_run_tracking_mode or "No Run Tracking") != TRACKED_MODE:
            continue
        rules.append({
            "rule_row": row.name,
            "item_code": row.item_code,
            "operation": row.operation,
            "source_warehouse": row.source_warehouse,
            "scan_warehouse": row.material_run_scan_warehouse,
            "stock_uom": row.stock_uom,
            "qty_per_output": flt(row.material_run_qty_per_output),
        })
    return frappe.as_json(rules)


def material_run_rules(execution):
    raw = execution.material_run_rules_json or "[]"
    parsed = frappe.parse_json(raw) or []
    return [frappe._dict(row) for row in parsed if row.get("item_code")]


@frappe.whitelist()
def get_material_run_context(execution_name, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(
        operator_session_token, "report_progress", execution=execution,
        touch_activity=False,
    )
    return _context_payload(execution)


@frappe.whitelist()
def preview_material_draw(execution_name, scan_value, quantity, operator_session_token=None):
    """Resolve one physical source scan without changing operational or ERP stock."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(
        operator_session_token, "report_progress", execution=execution,
        touch_activity=False,
    )
    _assert_enabled(execution)
    qty = flt(quantity)
    if qty <= 0:
        frappe.throw(_("Scan a positive Material Quantity before the source Stock Tag"))
    unit, physical_container = _resolve_material_source(scan_value)
    rule = _match_source_rule(execution, unit)
    available = _operationally_available_source_qty(unit)
    if available + TOLERANCE < qty:
        frappe.throw(
            _("Source tag {0} has {1} {2} available after other Material Run reservations; requested {3}").format(
                unit.handling_unit_id, available, unit.stock_uom, qty
            )
        )
    return _draw_preview_payload(rule, unit, physical_container, qty, available)


@frappe.whitelist()
def start_scanner_run(
    execution_name,
    event_token,
    output_serial_boundary=None,
    material_draws=None,
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
    draw_requests = _normalise_draw_requests(material_draws)
    draw_fingerprint = canonical_key("operation-material-draw-request", draw_requests)
    key = canonical_key("operation-material-run", execution.name, event_token)
    existing = get_existing("CFG Kanban Operation Material Run", key)
    if existing:
        _assert_idempotent_match(existing, execution.name, boundary, draw_fingerprint)
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
        "material_draw_fingerprint": draw_fingerprint,
        "idempotency_key": key,
    })
    try:
        run.insert(ignore_permissions=True)
    except frappe.UniqueValidationError:
        existing = get_existing("CFG Kanban Operation Material Run", key)
        if existing:
            _assert_idempotent_match(existing, execution.name, boundary, draw_fingerprint)
            return _run_payload(existing, duplicate=True)
        active = _open_run(execution.name)
        if active:
            return _run_payload(active, already_open=True)
        raise

    created_draws = _create_material_draws(
        execution, run, draw_requests, profile=profile, session=session,
        event_token=event_token,
    )
    _assert_tracked_materials_ready(execution, run)
    if created_draws:
        run.db_set({
            "material_draw_count": len(created_draws),
            "drawn_qty": sum(flt(row.drawn_qty) for row in created_draws),
        }, update_modified=False)

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
    run.reload()
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
    frappe.db.sql(
        "select name from `tabCFG Kanban Operation Material Run` where name=%s for update",
        run.name,
    )
    run.reload()
    if run.status != "Open":
        return {"name": run.name, "cancelled": False, "already_closed": True}
    if run.progress:
        frappe.throw(
            _("Material Run {0} already has progress evidence and requires controlled correction").format(
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
    frappe.db.set_value(
        "CFG Kanban Operation Material Draw",
        {"material_run": run.name, "status": ["in", ACTIVE_DRAW_STATUSES]},
        "status", "Cancelled", update_modified=True,
    )
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
    frappe.db.set_value(
        "CFG Kanban Operation Material Draw",
        {
            "material_run": run.name,
            "status": ["in", ("Open", "Partially Used")],
            "remaining_qty": [">", TOLERANCE],
        },
        "status", "Carry Forward", update_modified=True,
    )
    _refresh_run_totals(run)
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


def validate_progress_materials(execution, run, processed_qty):
    """Build a deterministic FIFO usage plan without mutating audit rows yet."""
    mode = execution.material_run_control or "Disabled"
    if mode == "Required Before Progress" and not run:
        frappe.throw(
            _("Start a Material Run and scan its required source materials before reporting progress for {0}").format(
                execution.operation
            )
        )
    if not run:
        return []
    frappe.db.sql(
        "select name from `tabCFG Kanban Operation Material Run` where name=%s for update",
        run.name,
    )
    run.reload()
    if run.process_execution != execution.name or run.status != "Open":
        frappe.throw(_("The selected Material Run is not the open run for this operation"))
    rules = material_run_rules(execution)
    if not rules:
        return []
    plan = []
    carry = bool(execution.allow_material_carry_forward)
    for rule in rules:
        required = flt(processed_qty) * flt(rule.qty_per_output)
        if required <= TOLERANCE:
            continue
        filters = {
            "process_execution": execution.name,
            "material_flow_rule_row": rule.rule_row,
            "status": ["in", ("Open", "Partially Used", "Carry Forward")],
            "remaining_qty": [">", TOLERANCE],
        }
        if not carry:
            filters["material_run"] = run.name
        draws = frappe.get_all(
            "CFG Kanban Operation Material Draw", filters=filters,
            fields=["name", "material_run", "remaining_qty"],
            order_by="drawn_on asc, creation asc", limit_page_length=0,
        )
        available = sum(flt(row.remaining_qty) for row in draws)
        if available + TOLERANCE < required:
            frappe.throw(
                _("Material Run needs {0} {1} of {2} for this progress, but only {3} is scanned and unconsumed").format(
                    required, rule.stock_uom, rule.item_code, available
                )
            )
        if not carry and abs(available - required) > TOLERANCE:
            frappe.throw(
                _("This operation does not allow material carry-forward. Scan exactly {0} {1} of {2} for this progress; current run has {3}").format(
                    required, rule.stock_uom, rule.item_code, available
                )
            )
        remaining = required
        for draw in draws:
            take = min(remaining, flt(draw.remaining_qty))
            if take > TOLERANCE:
                plan.append({"draw": draw.name, "qty": take, "rule": rule})
                remaining -= take
            if remaining <= TOLERANCE:
                break
    return plan


def apply_progress_material_plan(plan, progress, closing_run):
    """Consume the previously validated FIFO plan and preserve its scanner lineage."""
    if not plan:
        return
    used_total = 0
    for allocation in plan:
        draw = frappe.get_doc("CFG Kanban Operation Material Draw", allocation["draw"])
        frappe.db.sql(
            "select name from `tabCFG Kanban Operation Material Draw` where name=%s for update",
            draw.name,
        )
        draw.reload()
        qty = flt(allocation["qty"])
        if flt(draw.remaining_qty) + TOLERANCE < qty:
            frappe.throw(_("Material Draw {0} changed while progress was being posted; rescan").format(draw.name))
        used = flt(draw.used_qty) + qty
        remaining = max(0, flt(draw.remaining_qty) - qty)
        status = "Used" if remaining <= TOLERANCE else "Carry Forward"
        draw.db_set({
            "used_qty": used,
            "remaining_qty": remaining,
            "status": status,
            "last_progress": progress.name,
            "last_used_material_run": closing_run.name,
        }, update_modified=True)
        used_total += qty
    _refresh_run_totals(closing_run)
    record(
        "Operation Material Draws Used",
        cycle=closing_run.kanban_cycle,
        execution=closing_run.process_execution,
        qty=used_total,
        reference_doctype=progress.doctype,
        reference_name=progress.name,
        work_order=closing_run.work_order,
        job_card=closing_run.job_card,
        operation=closing_run.operation,
        workstation=closing_run.workstation,
        notes=_("Scanner material reservations consumed by Material Run {0}").format(closing_run.name),
        idempotency_key=canonical_key("operation-material-draw-use", progress.name),
    )


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
        "material_rules": _material_rule_context(execution),
    }


def _material_rule_context(execution):
    result = []
    for rule in material_run_rules(execution):
        carry_qty = frappe.db.get_value(
            "CFG Kanban Operation Material Draw",
            {
                "process_execution": execution.name,
                "material_flow_rule_row": rule.rule_row,
                "status": ["in", ("Open", "Partially Used", "Carry Forward")],
            },
            "sum(remaining_qty)",
        ) or 0
        result.append({
            **dict(rule),
            "carry_forward_qty": flt(carry_qty),
        })
    return result


def _normalise_draw_requests(value):
    if not value:
        return []
    parsed = frappe.parse_json(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        frappe.throw(_("Material Draw scanner data must be a list"))
    result = []
    for index, row in enumerate(parsed, 1):
        if not isinstance(row, dict):
            frappe.throw(_("Material Draw row {0} is invalid").format(index))
        scan_value = str(row.get("scan_value") or "").strip()
        qty = flt(row.get("qty"))
        if not scan_value or qty <= 0:
            frappe.throw(
                _("Material Draw row {0} requires a source Stock Tag and positive quantity").format(index)
            )
        result.append({"scan_value": scan_value, "qty": qty})
    return result


def _resolve_material_source(scan_value):
    from cfg_kanban.services.logistics_foundation import resolve_logistics_scan

    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(_("Scan an active Stock Tag or loaded Production Output Container"))
    scanned = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    physical_container = None
    if scanned.tag_kind == "Reusable Container":
        if scanned.reusable_container_role != "Production Output Container":
            frappe.throw(
                _("Reusable Container {0} is not a loaded Production Output Container").format(
                    scanned.handling_unit_id
                )
            )
        from cfg_kanban.services.container_contents import (
            production_output_content,
            validate_production_container_location,
        )

        container, content, _membership = production_output_content(scanned.name)
        validate_production_container_location(container, content)
        physical_container = container
        scanned = content
    else:
        from cfg_kanban.services.container_contents import assert_not_loaded_in_container

        assert_not_loaded_in_container(
            scanned.name, "declaring it as an Operation Material Run source"
        )
    if scanned.identity_state != "Active" or scanned.quality_state != "Released":
        frappe.throw(
            _("Source tag {0} is {1} / {2}, not Active / Released").format(
                scanned.handling_unit_id, scanned.identity_state, scanned.quality_state
            )
        )
    if not scanned.item_code or not scanned.stock_uom or not scanned.current_warehouse:
        frappe.throw(_("Source tag {0} is missing Item, UOM, or Warehouse").format(scanned.handling_unit_id))
    if flt(scanned.available_qty) <= TOLERANCE:
        frappe.throw(_("Source tag {0} has no available quantity").format(scanned.handling_unit_id))
    return scanned, physical_container


def _match_source_rule(execution, unit):
    matches = [rule for rule in material_run_rules(execution) if rule.item_code == unit.item_code]
    if not matches:
        frappe.throw(
            _("Item {0} is not configured for source-tag tracking in operation {1}").format(
                unit.item_code, execution.operation
            )
        )
    rule = matches[0]
    if unit.current_warehouse != rule.scan_warehouse:
        frappe.throw(
            _("Tag {0} is in {1}; this operation requires {2}").format(
                unit.handling_unit_id, unit.current_warehouse, rule.scan_warehouse
            )
        )
    if unit.stock_uom != rule.stock_uom:
        frappe.throw(
            _("Tag {0} uses UOM {1}; this material rule requires {2}").format(
                unit.handling_unit_id, unit.stock_uom, rule.stock_uom
            )
        )
    company = frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "company")
    if unit.inventory_company != company:
        frappe.throw(
            _("Tag {0} belongs to {1}, not production Company {2}").format(
                unit.handling_unit_id, unit.inventory_company, company
            )
        )
    return rule


def _source_reserved_qty(unit_name):
    return flt(frappe.db.get_value(
        "CFG Kanban Operation Material Draw",
        {
            "source_handling_unit": unit_name,
            "status": ["in", ACTIVE_DRAW_STATUSES],
        },
        "sum(drawn_qty)",
    ) or 0)


def _operationally_available_source_qty(unit):
    return max(0, flt(unit.available_qty) - _source_reserved_qty(unit.name))


def _draw_preview_payload(rule, unit, physical_container, qty, available):
    return {
        "rule_row": rule.rule_row,
        "item_code": rule.item_code,
        "stock_uom": rule.stock_uom,
        "scan_warehouse": rule.scan_warehouse,
        "qty_per_output": flt(rule.qty_per_output),
        "source_handling_unit": unit.name,
        "source_visible_code": unit.handling_unit_id,
        "physical_container": physical_container.name if physical_container else None,
        "physical_container_code": (
            physical_container.handling_unit_id if physical_container else None
        ),
        "batch_no": unit.batch_no,
        "qty": qty,
        "available_before_draw": available,
        "available_after_draw": max(0, available - qty),
    }


def _create_material_draws(execution, run, requests, *, profile, session, event_token):
    created = []
    seen_rules = set()
    for index, request in enumerate(requests, 1):
        unit, physical_container = _resolve_material_source(request["scan_value"])
        rule = _match_source_rule(execution, unit)
        if rule.rule_row in seen_rules:
            frappe.throw(
                _("Scan only one source tag for {0} in each Material Run. Report progress, then start a new run when the source changes.").format(
                    rule.item_code
                )
            )
        seen_rules.add(rule.rule_row)
        frappe.db.sql(
            "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
            unit.name,
        )
        unit.reload()
        available = _operationally_available_source_qty(unit)
        qty = flt(request["qty"])
        if available + TOLERANCE < qty:
            frappe.throw(
                _("Source tag {0} now has only {1} {2} available after other Material Run reservations").format(
                    unit.handling_unit_id, available, unit.stock_uom
                )
            )
        key = canonical_key("operation-material-draw", run.name, index)
        draw = frappe.get_doc({
            "doctype": "CFG Kanban Operation Material Draw",
            "status": "Open",
            "material_run": run.name,
            "kanban_cycle": execution.kanban_cycle,
            "kanban_master": execution.kanban_master,
            "process_execution": execution.name,
            "work_order": run.work_order,
            "job_card": execution.job_card,
            "operation": execution.operation,
            "workstation": execution.workstation,
            "material_flow_rule_row": rule.rule_row,
            "item_code": unit.item_code,
            "batch_no": unit.batch_no,
            "stock_uom": unit.stock_uom,
            "source_warehouse": unit.current_warehouse,
            "source_handling_unit": unit.name,
            "source_visible_code": unit.handling_unit_id,
            "physical_container": physical_container.name if physical_container else None,
            "qty_per_output": rule.qty_per_output,
            "drawn_qty": qty,
            "used_qty": 0,
            "remaining_qty": qty,
            "drawn_on": now_datetime(),
            "drawn_by_operator": profile.employee,
            "operator_session": session.name,
            "terminal_user": session.terminal_user,
            "idempotency_key": key,
        }).insert(ignore_permissions=True)
        created.append(draw)
        record(
            "Operation Material Source Scanned",
            cycle=execution.kanban_cycle,
            execution=execution.name,
            qty=qty,
            handling_unit=unit.name,
            reference_doctype=draw.doctype,
            reference_name=draw.name,
            operator=profile.employee,
            operator_session=session.name,
            terminal_user=session.terminal_user,
            input_source="Scanner",
            source_event_id=event_token,
            work_order=run.work_order,
            job_card=execution.job_card,
            operation=execution.operation,
            workstation=execution.workstation,
            notes=_("Reserved {0} {1} from source tag {2} for Material Run {3}").format(
                qty, unit.stock_uom, unit.handling_unit_id, run.name
            ),
            idempotency_key=canonical_key("operation-material-draw-event", draw.name),
        )
    return created


def _assert_tracked_materials_ready(execution, run):
    missing = []
    for rule in material_run_rules(execution):
        filters = {
            "process_execution": execution.name,
            "material_flow_rule_row": rule.rule_row,
            "status": ["in", ("Open", "Partially Used", "Carry Forward")],
            "remaining_qty": [">", TOLERANCE],
        }
        if not execution.allow_material_carry_forward:
            filters["material_run"] = run.name
        available = frappe.db.get_value(
            "CFG Kanban Operation Material Draw", filters, "sum(remaining_qty)"
        ) or 0
        if flt(available) <= TOLERANCE:
            missing.append(rule.item_code)
    if missing:
        frappe.throw(
            _("Scan a Material Quantity and source Stock Tag for: {0}").format(
                ", ".join(missing)
            )
        )


def _refresh_run_totals(run):
    totals = frappe.db.get_value(
        "CFG Kanban Operation Material Draw",
        {"material_run": run.name, "status": ["!=", "Cancelled"]},
        ["count(name) as draw_count", "sum(drawn_qty) as drawn", "sum(used_qty) as used", "sum(remaining_qty) as remaining"],
        as_dict=True,
    ) or {}
    run.db_set({
        "material_draw_count": int(totals.get("draw_count") or 0),
        "drawn_qty": flt(totals.get("drawn")),
        "used_qty": flt(totals.get("used")),
        "carry_forward_qty": flt(totals.get("remaining")),
    }, update_modified=False)


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


def _assert_idempotent_match(run, execution_name, boundary, draw_fingerprint):
    if (run.process_execution != execution_name
            or run.output_serial_boundary != boundary
            or run.material_draw_fingerprint != draw_fingerprint):
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

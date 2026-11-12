import hashlib
import json

import frappe
from frappe.utils import add_days, cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    assert_erp_stock,
    post_quantity_event,
    resolve_logistics_scan,
)
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


TOLERANCE = 0.000001


def release_certificate_process(signal_name):
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type != "Certificate Process":
        frappe.throw("Signal is not a Certificate Process")
    existing = frappe.db.get_value(
        "CFG Process Certificate Run", {"kanban_cycle": signal.kanban_cycle}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Process Certificate Run", existing)
    item = frappe.db.get_value(
        "Item", master.item_code, ["stock_uom", "has_batch_no"], as_dict=True
    )
    run = frappe.get_doc({
        "doctype": "CFG Process Certificate Run",
        "status": "Ready",
        "kanban_cycle": signal.kanban_cycle,
        "kanban_master": master.name,
        "kanban_card": signal.kanban_card,
        "company": master.company,
        "item_code": master.item_code,
        "stock_uom": item.stock_uom,
        "operation": master.certificate_process_operation,
        "progress_mode": (
            master.certificate_process_progress_mode or "Single Completion"
        ),
        "planned_qty": signal.requested_qty,
        "item_batch_controlled": cint(item.has_batch_no),
        "source_warehouse": master.source_warehouse,
        "output_warehouse": master.destination_warehouse or master.source_warehouse,
        "posting_mode": master.certificate_process_posting_mode,
        "idempotency_key": canonical_key("certificate-process-run", signal.kanban_cycle),
    }).insert(ignore_permissions=True)
    cycle = frappe.get_doc("CFG Kanban Cycle", signal.kanban_cycle)
    set_cycle_state(cycle, "Released", event_type="Certificate Process Released",
                    reference_doctype=run.doctype, reference_name=run.name)
    card = frappe.get_doc("CFG Kanban Card", signal.kanban_card)
    if card.current_state == "Signal Created":
        transition_card(card, "Replenishment Requested",
                        event_type="Certificate Process Requested", cycle=cycle.name)
    transition_card(card, "Production Released", event_type="Certificate Process Released",
                    cycle=cycle.name)
    signal.db_set({"status": "Completed", "erp_reference_doctype": run.doctype,
                   "erp_reference_name": run.name})
    return run


def get_certificate_process_context(cycle_name, operator_session_token=None):
    require_operator(operator_session_token)
    run_name = frappe.db.get_value(
        "CFG Process Certificate Run", {"kanban_cycle": cycle_name}, "name"
    )
    if not run_name:
        return None
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    if run.status == "Awaiting ERP Submission" and run.repack_stock_entry:
        reconcile_certificate_process(run.name)
        run.reload()
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    recovery = (
        frappe.db.get_value(
            "CFG Process Certificate Recovery",
            {"certificate_process_run": run.name}, "name",
        )
        if frappe.db.table_exists("CFG Process Certificate Recovery") else None
    )
    return {
        "run": run.as_dict(),
        "progress_rows": frappe.get_all(
            "CFG Certificate Process Progress",
            filters={"certificate_process_run": run.name, "status": ["!=", "Cancelled"]},
            fields=[
                "name", "sequence", "status", "good_qty", "reject_qty",
                "output_tag_code", "output_handling_unit", "output_tag_mode",
                "result_certificate_set", "output_batch", "printed_expiry",
                "first_output_serial", "last_output_serial", "recorded_on",
                "recorded_by_operator", "repack_stock_entry",
            ],
            order_by="sequence asc",
            limit_page_length=0,
        ) if frappe.db.table_exists("CFG Certificate Process Progress") else [],
        "recovery": recovery,
        "allow_partial_qty": bool(cint(master.certificate_process_allow_partial_qty)),
        "reuse_source_tag": bool(cint(master.certificate_process_reuse_source_tag)),
        "capture_expiry": bool(cint(master.certificate_process_capture_expiry)),
        "capture_serial_boundary": bool(cint(master.certificate_process_capture_serial_boundary)),
        "batch_controlled": bool(cint(run.item_batch_controlled)),
        "required_certificates": _requirement_rows(master),
        "output_rules": _output_rows(master),
    }


@frappe.whitelist()
def start_certificate_process(cycle_name, source_scan, qty, event_token,
                              operator_session_token=None):
    profile, session = require_operator(operator_session_token, "start")
    run = _locked_run(cycle_name)
    profile, session = _require_run_operator(run, operator_session_token, "start")
    if run.status == "In Progress":
        return get_certificate_process_context(cycle_name, operator_session_token)
    if run.status != "Ready":
        frappe.throw(f"Certificate Process cannot start while it is {run.status}")
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    unit = _resolve_active_unit(source_scan)
    selected_qty = flt(qty)
    if selected_qty <= 0:
        frappe.throw("Selected quantity must be positive")
    if selected_qty > flt(run.planned_qty) + TOLERANCE:
        frappe.throw("Selected quantity exceeds this Card quantity")
    if selected_qty > flt(unit.available_qty) + TOLERANCE:
        frappe.throw("Selected quantity exceeds the available source-tag quantity")
    if not cint(master.certificate_process_allow_partial_qty) and (
            abs(selected_qty - flt(run.planned_qty)) > TOLERANCE):
        frappe.throw("This Certificate Process requires the full Card quantity")
    _validate_source_unit(run, unit)
    _validate_certificate_requirements(master, unit)
    assert_erp_stock(unit, run.source_warehouse, selected_qty)
    reserve = post_quantity_event(
        event_type="Reserve", qty=selected_qty, stock_uom=run.stock_uom,
        idempotency_key=canonical_key("certificate-process-reserve", run.name, event_token),
        source_handling_unit=unit.name, item_code=run.item_code, batch_no=unit.batch_no,
        source_company=run.company, source_warehouse=run.source_warehouse,
        reference_doctype=run.doctype, reference_name=run.name,
        operator=profile.employee, operator_session=session.name,
        reason=f"Certificate Process {run.operation} source reservation",
    )
    run.db_set({
        "status": "In Progress", "selected_qty": selected_qty,
        "source_handling_unit": unit.name,
        "source_certificate_set": unit.process_certificate_set,
        "source_batch": unit.batch_no if cint(run.item_batch_controlled) else None,
        "started_on": now_datetime(), "started_by_operator": profile.employee,
        "operator_session": session.name,
    })
    cycle = frappe.get_doc("CFG Kanban Cycle", run.kanban_cycle)
    set_cycle_state(cycle, "In Production", event_type="Certificate Process Started",
                    reference_doctype=reserve.doctype, reference_name=reserve.name)
    card = frappe.get_doc("CFG Kanban Card", run.kanban_card)
    transition_card(card, "In Production", event_type="Certificate Process Started",
                    cycle=run.kanban_cycle)
    return get_certificate_process_context(cycle_name, operator_session_token)


@frappe.whitelist()
def complete_certificate_process(cycle_name, good_qty, reject_qty=0,
                                 output_tag_scan=None, output_batch=None,
                                 printed_expiry=None, first_output_serial=None,
                                 last_output_serial=None, event_token=None,
                                 operator_session_token=None):
    profile, session = require_operator(operator_session_token, "complete")
    run = _locked_run(cycle_name)
    profile, session = _require_run_operator(run, operator_session_token, "complete")
    if run.status not in ("In Progress", "Awaiting ERP Submission"):
        frappe.throw(f"Certificate Process cannot complete while it is {run.status}")
    if run.status == "Awaiting ERP Submission":
        return get_certificate_process_context(cycle_name, operator_session_token)
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    if run.progress_mode == "Consolidated Partial Progress":
        frappe.throw(
            "Use Report Certificate Progress for each partial result, then Close Certificate "
            "Process to create the consolidated Repack"
        )
    good_qty, reject_qty = flt(good_qty), flt(reject_qty)
    if good_qty <= 0:
        frappe.throw("Good quantity must be positive")
    if abs(good_qty + reject_qty - flt(run.selected_qty)) > TOLERANCE:
        frappe.throw("Good plus Reject quantity must equal the selected quantity")
    source = frappe.get_doc("CFG Kanban Handling Unit", run.source_handling_unit)
    full_reuse = bool(
        cint(master.certificate_process_reuse_source_tag)
        and reject_qty <= TOLERANCE
        and abs(good_qty - flt(source.current_qty)) <= TOLERANCE
    )
    if not cint(run.item_batch_controlled) and output_batch:
        frappe.throw("Output Batch is not accepted because this Item is not Batch controlled")
    _validate_retain_evidence(master, source)
    resolved_batch = _resolve_output_batch(
        run.item_code, run.source_batch, output_batch, printed_expiry
    ) if cint(run.item_batch_controlled) else None
    result_set = _result_certificate_set(master, run.source_certificate_set)
    output_identity = {
        "mode": "Reuse Source", "pending_code": None,
        "handling_unit": source.name, "qty_before": flt(source.current_qty),
    } if full_reuse else _resolve_output_tag(
        output_tag_scan, run, source, result_set.name, resolved_batch
    )
    _claim_output_identity(run, output_identity)
    entry = _create_repack_entry(run, good_qty, result_set.name, resolved_batch)
    run.db_set({
        "good_qty": good_qty, "reject_qty": reject_qty,
        "pending_output_tag_code": output_identity["pending_code"],
        "output_handling_unit": output_identity["handling_unit"],
        "output_tag_mode": output_identity["mode"],
        "output_tag_qty_before": output_identity["qty_before"],
        "result_certificate_set": result_set.name,
        "output_batch": resolved_batch,
        "printed_expiry": printed_expiry if cint(master.certificate_process_capture_expiry) else None,
        "first_output_serial": (first_output_serial
                                if cint(master.certificate_process_capture_serial_boundary) else None),
        "last_output_serial": (last_output_serial
                               if cint(master.certificate_process_capture_serial_boundary) else None),
        "repack_stock_entry": entry.name,
        "status": "Awaiting ERP Submission",
    })
    record("Certificate Process Repack Draft Created", card=run.kanban_card,
           cycle=run.kanban_cycle, handling_unit=source.name, qty=good_qty,
           reference_doctype="Stock Entry", reference_name=entry.name,
           operator=profile.employee, operator_session=session.name)
    if master.certificate_process_posting_mode == "Submit on Operator Confirmation":
        return submit_certificate_process(
            run.name, event_token=event_token,
            operator_session_token=operator_session_token,
        )
    return get_certificate_process_context(cycle_name, operator_session_token)


@frappe.whitelist()
def record_certificate_process_progress(
        cycle_name, good_qty, reject_qty=0, output_tag_scan=None,
        output_batch=None, printed_expiry=None, first_output_serial=None,
        last_output_serial=None, event_token=None, operator_session_token=None):
    """UI outcome envelope: only rolled-back, absent events permit correction.

    Unexpected errors propagate and remain ambiguous to the client. Existing-token
    conflicts (including legacy evidence) never become permission to start again.
    No explicit commit: Frappe commits this POST before delivering the response.
    """
    require_operator(operator_session_token, "complete")
    run = _locked_run(cycle_name)
    _require_run_operator(run, operator_session_token, "complete")
    if not isinstance(event_token, str) or not event_token.strip():
        frappe.throw("Certificate partial progress requires a non-empty event token")
    # Acquire the run lock BEFORE the savepoint so rollback retains serialization.
    savepoint = "certificate_progress_attempt"
    frappe.db.savepoint(savepoint)
    try:
        context = report_certificate_process_progress(
            cycle_name, good_qty, reject_qty, output_tag_scan, output_batch,
            printed_expiry, first_output_serial, last_output_serial,
            event_token, operator_session_token,
        )
    except frappe.ValidationError:
        frappe.db.rollback(save_point=savepoint)
        key = canonical_key("certificate-process-progress", run.name, event_token)
        if frappe.db.get_value("CFG Certificate Process Progress", {"idempotency_key": key}, "name"):
            raise
        return {"outcome": "rejected", "event_token": event_token}
    return {"outcome": "recorded", "event_token": event_token, "context": context}


@frappe.whitelist()
def report_certificate_process_progress(
        cycle_name, good_qty, reject_qty=0, output_tag_scan=None,
        output_batch=None, printed_expiry=None, first_output_serial=None,
        last_output_serial=None, event_token=None, operator_session_token=None):
    profile, session = require_operator(operator_session_token, "complete")
    run = _locked_run(cycle_name)
    profile, session = _require_run_operator(run, operator_session_token, "complete")
    if not isinstance(event_token, str) or not event_token.strip():
        frappe.throw("Certificate partial progress requires a non-empty event token")
    good_qty, reject_qty = flt(good_qty), flt(reject_qty)
    request_fingerprint = canonical_key(
        "certificate-progress-request-v1", good_qty, reject_qty,
        str(output_tag_scan or "").strip(), str(output_batch or "").strip(),
        str(printed_expiry or "").strip(), str(first_output_serial or "").strip(),
        str(last_output_serial or "").strip(),
    )
    key = canonical_key("certificate-process-progress", run.name, event_token)
    existing = frappe.db.get_value(
        "CFG Certificate Process Progress", {"idempotency_key": key},
        ["name", "request_fingerprint"], as_dict=True,
    )
    if existing:
        if not existing.request_fingerprint:
            frappe.throw(
                "This earlier progress record has no request fingerprint. "
                "Review its recorded evidence; do not retry it with a new token."
            )
        if existing.request_fingerprint != request_fingerprint:
            frappe.throw("This progress event token was already used with different request data")
        return get_certificate_process_context(cycle_name, operator_session_token)
    if run.status != "In Progress":
        frappe.throw(f"Certificate Process progress cannot be reported while it is {run.status}")
    if run.progress_mode != "Consolidated Partial Progress":
        frappe.throw("This Certificate Process uses Single Completion")
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    good_qty, reject_qty = flt(good_qty), flt(reject_qty)
    if good_qty <= 0 or reject_qty < 0:
        frappe.throw("Partial progress requires positive Good and non-negative Reject quantity")
    next_total = flt(run.good_qty) + flt(run.reject_qty) + good_qty + reject_qty
    if next_total > flt(run.selected_qty) + TOLERANCE:
        frappe.throw(
            f"Partial progress exceeds the selected quantity by "
            f"{next_total - flt(run.selected_qty)} {run.stock_uom}"
        )
    if not cint(run.item_batch_controlled) and output_batch:
        frappe.throw("Output Batch is not accepted because this Item is not Batch controlled")
    source = frappe.get_doc("CFG Kanban Handling Unit", run.source_handling_unit)
    _validate_retain_evidence(master, source)
    resolved_batch = _resolve_output_batch(
        run.item_code, run.source_batch, output_batch, printed_expiry
    ) if cint(run.item_batch_controlled) else None
    result_set = _result_certificate_set(master, run.source_certificate_set)
    if run.result_certificate_set and run.result_certificate_set != result_set.name:
        frappe.throw("Certificate output rules changed after partial progress started")
    output_identity = _progress_output_identity(
        run, source, output_tag_scan, result_set.name, resolved_batch
    )
    _validate_progress_output_details(
        run, resolved_batch, printed_expiry, output_identity
    )
    _claim_output_identity(run, output_identity)
    sequence = cint(frappe.db.get_value(
        "CFG Certificate Process Progress",
        {"certificate_process_run": run.name}, "max(sequence)",
    )) + 1
    progress = frappe.get_doc({
        "doctype": "CFG Certificate Process Progress",
        "status": "Recorded", "sequence": sequence,
        "certificate_process_run": run.name, "kanban_cycle": run.kanban_cycle,
        "kanban_master": run.kanban_master, "kanban_card": run.kanban_card,
        "company": run.company, "item_code": run.item_code,
        "stock_uom": run.stock_uom, "operation": run.operation,
        "good_qty": good_qty, "reject_qty": reject_qty,
        "source_handling_unit": source.name,
        "output_tag_code": output_identity["visible_code"],
        "output_handling_unit": output_identity["handling_unit"],
        "output_tag_mode": output_identity["mode"],
        "result_certificate_set": result_set.name,
        "output_batch": resolved_batch,
        "printed_expiry": (
            printed_expiry if cint(master.certificate_process_capture_expiry) else None
        ),
        "first_output_serial": (
            first_output_serial
            if cint(master.certificate_process_capture_serial_boundary) else None
        ),
        "last_output_serial": (
            last_output_serial
            if cint(master.certificate_process_capture_serial_boundary) else None
        ),
        "recorded_on": now_datetime(), "recorded_by_operator": profile.employee,
        "operator_session": session.name, "terminal_user": frappe.session.user,
        "idempotency_key": key, "request_fingerprint": request_fingerprint,
    }).insert(ignore_permissions=True)
    run.db_set({
        "good_qty": flt(run.good_qty) + good_qty,
        "reject_qty": flt(run.reject_qty) + reject_qty,
        "pending_output_tag_code": output_identity["pending_code"],
        "output_handling_unit": output_identity["handling_unit"],
        "output_tag_mode": output_identity["mode"],
        "output_tag_qty_before": output_identity["qty_before"],
        "result_certificate_set": result_set.name,
        "output_batch": resolved_batch,
        "printed_expiry": printed_expiry or run.printed_expiry,
        "first_output_serial": run.first_output_serial or first_output_serial,
        "last_output_serial": last_output_serial or run.last_output_serial,
    }, update_modified=True)
    record(
        "Certificate Process Partial Progress Recorded", card=run.kanban_card,
        cycle=run.kanban_cycle, handling_unit=source.name, qty=good_qty,
        reference_doctype=progress.doctype, reference_name=progress.name,
        operator=profile.employee, operator_session=session.name,
        notes=(f"Partial run {sequence}; pending output {output_identity['visible_code']}; "
               f"result set {result_set.name}; ERP consolidation pending"),
    )
    return get_certificate_process_context(cycle_name, operator_session_token)


@frappe.whitelist()
def close_consolidated_certificate_process(
        cycle_name, event_token=None, operator_session_token=None):
    profile, session = require_operator(operator_session_token, "complete")
    run = _locked_run(cycle_name)
    profile, session = _require_run_operator(run, operator_session_token, "complete")
    if run.status == "Awaiting ERP Submission":
        return get_certificate_process_context(cycle_name, operator_session_token)
    if run.status != "In Progress" or run.progress_mode != "Consolidated Partial Progress":
        frappe.throw("No consolidated Certificate Process is ready to close")
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    reported = flt(run.good_qty) + flt(run.reject_qty)
    if flt(run.good_qty) <= 0 or reported <= TOLERANCE:
        frappe.throw("Record at least one positive Certificate Process partial result first")
    if reported > flt(run.selected_qty) + TOLERANCE:
        frappe.throw("Recorded Certificate Process progress exceeds selected quantity")
    if not cint(master.certificate_process_allow_partial_qty) and (
            abs(reported - flt(run.selected_qty)) > TOLERANCE):
        frappe.throw("This Certificate Process requires the complete selected quantity")
    if not run.result_certificate_set or not (
            run.pending_output_tag_code or run.output_handling_unit):
        frappe.throw("Recorded partial progress has no controlled output identity")
    _validate_consolidated_output_at_close(run)
    entry = _create_repack_entry(
        run, run.good_qty, run.result_certificate_set, run.output_batch
    )
    run.db_set({
        "repack_stock_entry": entry.name,
        "status": "Awaiting ERP Submission",
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Certificate Process Progress",
        {"certificate_process_run": run.name, "status": "Recorded"},
        "repack_stock_entry", entry.name, update_modified=False,
    )
    record(
        "Certificate Process Consolidated Repack Created", card=run.kanban_card,
        cycle=run.kanban_cycle, handling_unit=run.source_handling_unit,
        qty=run.good_qty, reference_doctype="Stock Entry", reference_name=entry.name,
        operator=profile.employee, operator_session=session.name,
        notes=(f"Consolidated partial progress; reject {run.reject_qty} {run.stock_uom}; "
               f"unprocessed {max(flt(run.selected_qty) - reported, 0)} {run.stock_uom}"),
    )
    if master.certificate_process_posting_mode == "Submit on Operator Confirmation":
        return submit_certificate_process(
            run.name, event_token=event_token,
            operator_session_token=operator_session_token,
        )
    return get_certificate_process_context(cycle_name, operator_session_token)


@frappe.whitelist()
def submit_certificate_process(run_name, event_token=None, operator_session_token=None):
    require_operator(operator_session_token, "complete")
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    _require_run_operator(run, operator_session_token, "complete")
    if run.status == "Completed":
        return get_certificate_process_context(run.kanban_cycle, operator_session_token)
    if run.status != "Awaiting ERP Submission" or not run.repack_stock_entry:
        frappe.throw("No Certificate Process Repack is ready to submit")
    entry = frappe.get_doc("Stock Entry", run.repack_stock_entry)
    if entry.docstatus == 0:
        entry.submit()
    if entry.docstatus != 1:
        frappe.throw("ERPNext did not submit the Certificate Process Repack")
    reconcile_certificate_process(run.name)
    return get_certificate_process_context(run.kanban_cycle, operator_session_token)


@frappe.whitelist()
def reconcile_submitted_certificate_process(run_name):
    """Manager repair for a Repack submitted before ERP feedback completed."""
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    if run.status == "Completed":
        return {
            "run": run.name,
            "status": run.status,
            "output_handling_unit": run.output_handling_unit,
        }
    if run.status != "Awaiting ERP Submission" or not run.repack_stock_entry:
        frappe.throw("This Certificate Process has no submitted Repack awaiting reconciliation")
    entry = frappe.get_doc("Stock Entry", run.repack_stock_entry)
    if entry.docstatus != 1:
        frappe.throw(f"Submit ERPNext Repack {entry.name} before reconciliation")
    run = reconcile_certificate_process(run.name)
    return {
        "run": run.name,
        "status": run.status,
        "output_handling_unit": run.output_handling_unit,
    }


@frappe.whitelist()
def cancel_certificate_process(run_name, reason, event_token=None,
                               operator_session_token=None):
    profile, session = require_operator(operator_session_token, "start")
    if not (reason or "").strip():
        frappe.throw("Cancellation reason is required")
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    profile, session = _require_run_operator(run, operator_session_token, "start")
    if run.status == "Cancelled":
        return {"cancelled": True, "run": run.name}
    if run.status not in ("Ready", "In Progress"):
        frappe.throw(
            "A Certificate Process with an ERPNext Repack must be recovered through "
            "controlled supervisor cancellation"
        )
    if run.status == "In Progress" and flt(run.selected_qty) > 0:
        post_quantity_event(
            event_type="Unreserve", qty=run.selected_qty, stock_uom=run.stock_uom,
            idempotency_key=canonical_key("certificate-process-cancel-unreserve", run.name),
            source_handling_unit=run.source_handling_unit, item_code=run.item_code,
            batch_no=run.source_batch, source_company=run.company,
            source_warehouse=run.source_warehouse, reference_doctype=run.doctype,
            reference_name=run.name, operator=profile.employee,
            operator_session=session.name, reason=reason.strip(),
        )
    if frappe.db.table_exists("CFG Certificate Process Progress"):
        frappe.db.set_value(
            "CFG Certificate Process Progress",
            {"certificate_process_run": run.name, "status": "Recorded"},
            {
                "status": "Cancelled", "cancelled_on": now_datetime(),
                "cancellation_reason": reason.strip(),
            },
            update_modified=False,
        )
    run.db_set({
        "status": "Cancelled", "exception_notes": reason.strip(),
        "output_claim_key": None,
    })
    cycle = frappe.get_doc("CFG Kanban Cycle", run.kanban_cycle)
    set_cycle_state(cycle, "Cancelled", event_type="Certificate Process Cancelled",
                    reference_doctype=run.doctype, reference_name=run.name)
    card = frappe.get_doc("CFG Kanban Card", run.kanban_card)
    if card.current_state == "Production Released":
        transition_card(card, "Blocked", event_type="Certificate Process Cancellation",
                        cycle=run.kanban_cycle, notes=reason.strip())
    elif card.current_state == "In Production":
        transition_card(card, "Blocked", event_type="Certificate Process Cancellation",
                        cycle=run.kanban_cycle, notes=reason.strip())
    transition_card(card, "Available", event_type="Certificate Process Card Released",
                    cycle=run.kanban_cycle, notes=reason.strip())
    card.db_set("active_cycle", None, update_modified=True)
    return {"cancelled": True, "run": run.name}


def reconcile_certificate_process(run_name):
    frappe.db.sql(
        "select name from `tabCFG Process Certificate Run` where name=%s for update",
        (run_name,),
    )
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    if run.status == "Completed":
        return run
    if run.status != "Awaiting ERP Submission" or not run.repack_stock_entry:
        return run
    entry = frappe.get_doc("Stock Entry", run.repack_stock_entry)
    if entry.docstatus != 1:
        return run
    source = frappe.get_doc("CFG Kanban Handling Unit", run.source_handling_unit)
    post_quantity_event(
        event_type="Unreserve", qty=run.selected_qty, stock_uom=run.stock_uom,
        idempotency_key=canonical_key("certificate-process-unreserve", run.name),
        source_handling_unit=source.name, item_code=run.item_code,
        batch_no=run.source_batch, source_company=run.company,
        source_warehouse=run.source_warehouse, reference_doctype=run.doctype,
        reference_name=run.name, reason="ERPNext Repack submitted",
    )
    if run.output_handling_unit == source.name:
        frappe.db.set_value("CFG Kanban Handling Unit", source.name, {
            "process_certificate_set": run.result_certificate_set,
            "batch_no": run.output_batch,
            "current_warehouse": run.output_warehouse,
        }, update_modified=True)
        output = frappe.get_doc("CFG Kanban Handling Unit", source.name)
    elif run.output_tag_mode == "Merge Existing":
        output = frappe.get_doc("CFG Kanban Handling Unit", run.output_handling_unit)
        post_quantity_event(
            event_type="Merge", qty=run.good_qty, stock_uom=run.stock_uom,
            idempotency_key=canonical_key("certificate-process-merge-existing", run.name),
            source_handling_unit=source.name, destination_handling_unit=output.name,
            item_code=run.item_code, batch_no=run.output_batch,
            source_company=run.company, destination_company=run.company,
            source_warehouse=run.source_warehouse,
            destination_warehouse=run.output_warehouse,
            reference_doctype=run.doctype, reference_name=run.name,
            reason="ERPNext Repack submitted; certified output merged into compatible tag",
        )
    else:
        output = _activate_output_unit(run, source)
        post_quantity_event(
            event_type="Split", qty=run.good_qty, stock_uom=run.stock_uom,
            idempotency_key=canonical_key("certificate-process-split", run.name),
            source_handling_unit=source.name, destination_handling_unit=output.name,
            item_code=run.item_code, batch_no=run.output_batch,
            source_company=run.company, destination_company=run.company,
            source_warehouse=run.source_warehouse,
            destination_warehouse=run.output_warehouse,
            reference_doctype=run.doctype, reference_name=run.name,
            reason="ERPNext Repack submitted; output certificate state activated",
        )
    _issue_output_certificates(run, output)
    if frappe.db.table_exists("CFG Certificate Process Progress"):
        frappe.db.set_value(
            "CFG Certificate Process Progress",
            {"certificate_process_run": run.name, "status": "Recorded"},
            {
                "status": "ERP Posted", "repack_stock_entry": entry.name,
                "posted_on": now_datetime(),
            },
            update_modified=False,
        )
    run.db_set({
        "status": "Completed", "output_handling_unit": output.name,
        "output_claim_key": None, "completed_on": now_datetime(),
    })
    cycle = frappe.get_doc("CFG Kanban Cycle", run.kanban_cycle)
    cycle.db_set({"actual_good_qty": run.good_qty, "reject_qty": run.reject_qty})
    set_cycle_state(cycle, "Completed", event_type="Certificate Process Completed",
                    reference_doctype="Stock Entry", reference_name=entry.name)
    card = frappe.get_doc("CFG Kanban Card", run.kanban_card)
    transition_card(card, "Produced", event_type="Certificate Process Completed",
                    cycle=run.kanban_cycle)
    transition_card(card, "Available", event_type="Certificate Process Card Released",
                    cycle=run.kanban_cycle)
    card.db_set("active_cycle", None, update_modified=True)
    return frappe.get_doc("CFG Process Certificate Run", run.name)


def _require_run_operator(run, session_token, action):
    return require_operator(
        session_token, action, operation=run.operation,
        workstation=getattr(run, "workstation", None),
    )


def _locked_run(cycle_name):
    name = frappe.db.get_value("CFG Process Certificate Run", {"kanban_cycle": cycle_name}, "name")
    if not name:
        frappe.throw("Certificate Process Run was not released")
    frappe.db.sql("select name from `tabCFG Process Certificate Run` where name=%s for update", name)
    return frappe.get_doc("CFG Process Certificate Run", name)


def _resolve_active_unit(scan_value):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Handling Unit / Stock Tag")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw("Source Stock Tag must be Active and Released")
    return unit


def _validate_source_unit(run, unit):
    actual = (unit.item_code, unit.stock_uom, unit.inventory_company, unit.current_warehouse)
    expected = (run.item_code, run.stock_uom, run.company, run.source_warehouse)
    if actual != expected:
        frappe.throw("Source tag does not match this Item, UOM, Company, or Source Warehouse")
    if cint(run.item_batch_controlled) and not unit.batch_no:
        frappe.throw("ERPNext Batch is required on the source tag for this Batch-controlled Item")
    if not cint(run.item_batch_controlled) and unit.batch_no:
        frappe.throw("Source tag carries a Batch but this Item is not currently Batch controlled")


def _requirement_rows(master):
    return [row.as_dict() for row in master.certificate_requirements
            if row.operation == master.certificate_process_operation]


def _output_rows(master):
    return [row.as_dict() for row in master.certificate_output_rules
            if row.operation == master.certificate_process_operation]


def _validate_certificate_requirements(master, unit):
    requirements = [row for row in master.certificate_requirements
                    if row.operation == master.certificate_process_operation
                    and row.gate_stage == "Before Operation Start"]
    if not requirements:
        return
    members = {}
    if unit.process_certificate_set:
        certificate_set = frappe.get_doc("CFG Process Certificate Set", unit.process_certificate_set)
        members = {row.certificate_type: cint(row.revision_snapshot)
                   for row in certificate_set.members}
    groups = {}
    for row in requirements:
        passed = members.get(row.certificate_type, 0) >= cint(row.minimum_revision)
        if passed and cint(row.require_unexpired):
            issued = frappe.get_all("CFG Process Certificate", filters={
                "handling_unit": unit.name, "certificate_type": row.certificate_type,
                "status": "Active",
            }, fields=["valid_until"], limit_page_length=0)
            passed = any(
                not certificate.valid_until
                or certificate.valid_until >= now_datetime()
                for certificate in issued
            )
        groups.setdefault(row.requirement_group, {"logic": row.group_logic, "checks": []})[
            "checks"
        ].append((row.certificate_type, passed))
    failed = []
    for group, values in groups.items():
        checks = values["checks"]
        okay = all(value for _name, value in checks) if values["logic"] == "All Required" \
            else any(value for _name, value in checks)
        if not okay:
            failed.append(f"{group}: " + ", ".join(name for name, _value in checks))
    if failed:
        frappe.throw("Source tag does not satisfy Certificate gate: " + "; ".join(failed))


def _result_certificate_set(master, source_set_name):
    source_members = {}
    if source_set_name:
        source_set = frappe.get_doc("CFG Process Certificate Set", source_set_name)
        source_members = {
            row.certificate_type: cint(row.revision_snapshot)
            for row in source_set.members
        }
    members = {}
    for rule in master.certificate_output_rules:
        if rule.operation != master.certificate_process_operation:
            continue
        if rule.action == "Revoke":
            members.pop(rule.certificate_type, None)
        elif rule.action == "Issue":
            members[rule.certificate_type] = cint(frappe.db.get_value(
                "CFG Process Certificate Type", rule.certificate_type, "revision"
            ))
        elif rule.action == "Retain":
            if rule.certificate_type not in source_members:
                frappe.throw(
                    f"Output rule cannot retain {rule.certificate_type}; it is not present "
                    "on the source Certificate Set"
                )
            members[rule.certificate_type] = source_members[rule.certificate_type]
    if not members:
        frappe.throw("Certificate Process output rules produce an empty Certificate Set")
    canonical = sorted([[name, revision] for name, revision in members.items()])
    signature = hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
    existing = frappe.db.get_value("CFG Process Certificate Set", {"signature_hash": signature}, "name")
    if existing:
        return frappe.get_doc("CFG Process Certificate Set", existing)
    return frappe.get_doc({
        "doctype": "CFG Process Certificate Set", "active": 1,
        "members": [{"certificate_type": name} for name in sorted(members)],
        "notes": f"Generated by Certificate Process Master {master.name}",
    }).insert(ignore_permissions=True)


def _resolve_output_tag(scan_value, run, source, result_set, output_batch):
    code = normalize_physical_code(scan_value)
    identity = resolve_logistics_scan(code)
    if identity and identity.get("identity_type") == "Handling Unit":
        output = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
        if output.name == source.name:
            frappe.throw(
                "The source tag can be reused only when the complete source quantity is processed"
            )
        expected = (
            run.item_code, run.stock_uom, run.company, run.output_warehouse,
            output_batch or None, result_set,
        )
        actual = (
            output.item_code, output.stock_uom, output.inventory_company,
            output.current_warehouse, output.batch_no or None,
            output.process_certificate_set or None,
        )
        if actual != expected:
            frappe.throw(
                "Existing output tag must match the Item, UOM, Company, Output Warehouse, "
                "Batch, and resulting Process Certificate Set"
            )
        if output.identity_state != "Active" or output.quality_state != "Released":
            frappe.throw("Existing output tag must be Active and Released")
        if flt(output.current_qty) <= TOLERANCE:
            frappe.throw("Existing output tag has no active quantity; use an unused output tag")
        if flt(output.reserved_qty) > TOLERANCE:
            frappe.throw(
                f"Existing output tag has {output.reserved_qty} {output.stock_uom} reserved"
            )
        return {
            "mode": "Merge Existing", "pending_code": None,
            "handling_unit": output.name, "qty_before": flt(output.current_qty),
            "visible_code": output.handling_unit_id,
        }
    if not identity or identity.get("identity_type") not in (
            "Registered Tag Identity", "Tag Range Candidate"):
        frappe.throw("Output tag is not covered by an active Tag Family or Tag Range")
    if identity.get("tag_role") != "Main":
        frappe.throw("Certificate Process output requires an unused main Stock Tag")
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(f"Output tag is {identity.get('state')}")
    return {
        "mode": "New Tag", "pending_code": code,
        "handling_unit": None, "qty_before": 0, "visible_code": code,
    }


def _progress_output_identity(run, source, scan_value, result_set, output_batch):
    if run.pending_output_tag_code or run.output_handling_unit:
        code = normalize_physical_code(scan_value)
        if run.output_handling_unit:
            identity = resolve_logistics_scan(code)
            if not identity or identity.get("identity_type") != "Handling Unit" or (
                    identity.get("name") != run.output_handling_unit):
                frappe.throw(
                    "Every partial report in one consolidated Certificate Process must scan "
                    "the same existing output tag"
                )
            output = frappe.get_doc("CFG Kanban Handling Unit", run.output_handling_unit)
            return {
                "mode": "Merge Existing", "pending_code": None,
                "handling_unit": output.name,
                "qty_before": flt(run.output_tag_qty_before),
                "visible_code": output.handling_unit_id,
            }
        if code != run.pending_output_tag_code:
            frappe.throw(
                "Every partial report in one consolidated Certificate Process must scan "
                "the same unused output tag"
            )
        _validate_pending_unused_output_tag(code)
        return {
            "mode": "New Tag", "pending_code": code, "handling_unit": None,
            "qty_before": 0, "visible_code": code,
        }
    identity = _resolve_output_tag(scan_value, run, source, result_set, output_batch)
    if identity["handling_unit"]:
        output = frappe.get_doc("CFG Kanban Handling Unit", identity["handling_unit"])
        identity["visible_code"] = output.handling_unit_id
    return identity


def _validate_pending_unused_output_tag(code):
    identity = resolve_logistics_scan(code)
    if not identity or identity.get("identity_type") not in (
            "Registered Tag Identity", "Tag Range Candidate"):
        frappe.throw("Pending output tag is no longer covered by its Tag Family or Tag Range")
    if identity.get("tag_role") != "Main" or identity.get("state") not in (
            "Unused", "Unmaterialized"):
        frappe.throw("Pending consolidated output tag is no longer an unused main Stock Tag")


def _validate_progress_output_details(run, output_batch, printed_expiry, identity):
    if run.result_certificate_set and identity["mode"] != run.output_tag_mode:
        frappe.throw("Output tag mode changed after partial progress was recorded")
    if run.output_batch and (run.output_batch or None) != (output_batch or None):
        frappe.throw("Output Batch must remain the same across consolidated partial progress")
    if run.printed_expiry and printed_expiry and run.printed_expiry != printed_expiry:
        frappe.throw("Printed Expiry must remain the same across consolidated partial progress")


def _claim_output_identity(run, identity):
    visible_identity = identity.get("pending_code") or identity.get("handling_unit")
    claim_key = (
        f"NEW:{visible_identity}"
        if identity.get("pending_code") else f"HU:{visible_identity}"
    )
    if run.output_claim_key:
        if run.output_claim_key != claim_key:
            frappe.throw("This Certificate Process already claimed a different output tag")
        return
    existing = frappe.db.get_value(
        "CFG Process Certificate Run",
        {"output_claim_key": claim_key, "name": ["!=", run.name]},
        "name",
    )
    if existing:
        frappe.throw(
            f"Output tag is already claimed by open Certificate Process Run {existing}"
        )
    try:
        run.db_set("output_claim_key", claim_key, update_modified=True)
    except frappe.UniqueValidationError:
        frappe.throw("Output tag was claimed by another Certificate Process; rescan another tag")


def _validate_consolidated_output_at_close(run):
    expected_claim = (
        f"NEW:{run.pending_output_tag_code}"
        if run.pending_output_tag_code else f"HU:{run.output_handling_unit}"
    )
    if run.output_claim_key != expected_claim:
        frappe.throw("The consolidated output-tag claim is missing or changed")
    if run.pending_output_tag_code:
        _validate_pending_unused_output_tag(run.pending_output_tag_code)
        return
    output = frappe.get_doc("CFG Kanban Handling Unit", run.output_handling_unit)
    expected = (
        run.item_code, run.stock_uom, run.company, run.output_warehouse,
        run.output_batch or None, run.result_certificate_set,
    )
    actual = (
        output.item_code, output.stock_uom, output.inventory_company,
        output.current_warehouse, output.batch_no or None,
        output.process_certificate_set or None,
    )
    if actual != expected or output.identity_state != "Active" or (
            output.quality_state != "Released"):
        frappe.throw(
            "The consolidated output tag changed after partial progress was recorded; "
            "use controlled cancellation and investigate the physical tag"
        )
    if abs(flt(output.current_qty) - flt(run.output_tag_qty_before)) > TOLERANCE or (
            flt(output.reserved_qty) > TOLERANCE):
        frappe.throw(
            "The consolidated output tag quantity or reservation changed after partial "
            "progress was recorded; use controlled cancellation and investigate"
        )


def _resolve_output_batch(item_code, source_batch, requested_batch, printed_expiry):
    requested_batch = (requested_batch or "").strip()
    if not requested_batch:
        return source_batch
    existing = (frappe.db.get_value("Batch", requested_batch, ["name", "item"], as_dict=True)
                or frappe.db.get_value("Batch", {"batch_id": requested_batch},
                                       ["name", "item"], as_dict=True))
    if existing:
        if existing.item != item_code:
            frappe.throw(f"Batch {requested_batch} does not belong to Item {item_code}")
        return existing.name
    values = {"doctype": "Batch", "batch_id": requested_batch, "item": item_code}
    if printed_expiry:
        values["expiry_date"] = printed_expiry
    return frappe.get_doc(values).insert(ignore_permissions=True).name


def _create_repack_entry(run, qty, result_set, output_batch):
    entry = frappe.get_doc({
        "doctype": "Stock Entry", "stock_entry_type": "Repack", "purpose": "Repack",
        "company": run.company, "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": run.kanban_cycle,
    })
    source_row = {"item_code": run.item_code, "s_warehouse": run.source_warehouse,
                  "qty": qty, "uom": run.stock_uom, "stock_uom": run.stock_uom,
                  "conversion_factor": 1, "batch_no": run.source_batch}
    output_row = {"item_code": run.item_code, "t_warehouse": run.output_warehouse,
                  "qty": qty, "uom": run.stock_uom, "stock_uom": run.stock_uom,
                  "conversion_factor": 1, "batch_no": output_batch,
                  "allow_zero_valuation_rate": 1}
    detail_meta = frappe.get_meta("Stock Entry Detail")
    if detail_meta.has_field("process_certificate_set"):
        source_row["process_certificate_set"] = run.source_certificate_set
    if detail_meta.has_field("to_process_certificate_set"):
        output_row["to_process_certificate_set"] = result_set
    else:
        frappe.throw(
            "Target Process Certificate Set Inventory Dimension is missing. "
            "Run the CFG Kanban migration before creating a certified Repack."
        )
    entry.append("items", source_row)
    entry.append("items", output_row)
    entry.insert(ignore_permissions=True)
    return entry


def _activate_output_unit(run, source):
    output = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": run.pending_output_tag_code,
        "tag_kind": "Main Stock Tag", "item_code": run.item_code,
        "qty": run.good_qty, "stock_uom": run.stock_uom,
        "inventory_company": run.company, "current_warehouse": run.output_warehouse,
        "batch_no": run.output_batch, "process_certificate_set": run.result_certificate_set,
        "kanban_cycle": run.kanban_cycle, "kanban_card": run.kanban_card,
        "origin_reference_doctype": run.doctype, "origin_reference_name": run.name,
    })
    output.flags.skip_initial_ledger = True
    output.flags.activation_reason = "Certificate Process output after submitted ERPNext Repack"
    output.insert(ignore_permissions=True)
    return output


def _issue_output_certificates(run, output):
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
    for rule in master.certificate_output_rules:
        if (rule.operation != master.certificate_process_operation
                or rule.action not in ("Issue", "Retain")):
            continue
        key = canonical_key(
            f"certificate-process-{rule.action.lower()}", run.name,
            rule.certificate_type,
        )
        if frappe.db.exists("CFG Process Certificate", {"idempotency_key": key}):
            continue
        certificate_type = frappe.get_doc("CFG Process Certificate Type", rule.certificate_type)
        source_certificate = None
        if rule.action == "Retain":
            source_certificate = _active_source_certificate(
                run.source_handling_unit, rule.certificate_type
            )
        validity_days = cint(rule.validity_days_override or certificate_type.validity_days)
        valid_from = (
            source_certificate.valid_from if source_certificate else now_datetime()
        )
        valid_until = (
            source_certificate.valid_until if source_certificate
            else add_days(valid_from, validity_days) if validity_days else None
        )
        frappe.get_doc({
            "doctype": "CFG Process Certificate", "status": "Active",
            "certificate_type": rule.certificate_type,
            "certificate_set": run.result_certificate_set,
            "handling_unit": output.name, "item_code": run.item_code,
            "certified_qty": run.good_qty, "stock_uom": run.stock_uom,
            "inventory_company": run.company, "warehouse": run.output_warehouse,
            "batch_no": run.output_batch, "kanban_cycle": run.kanban_cycle,
            "kanban_master": run.kanban_master, "kanban_card": run.kanban_card,
            "operation": run.operation, "issued_on": valid_from,
            "issued_by_operator": run.started_by_operator,
            "operator_session": run.operator_session,
            "terminal_user": frappe.session.user, "valid_from": valid_from,
            "valid_until": valid_until,
            "source_reference_doctype": (
                "CFG Process Certificate" if source_certificate else "Stock Entry"
            ),
            "source_reference_name": (
                source_certificate.name if source_certificate else run.repack_stock_entry
            ),
            "evidence_references": (
                source_certificate.evidence_references if source_certificate else None
            ),
            "idempotency_key": key,
        }).insert(ignore_permissions=True)


def _validate_retain_evidence(master, source):
    for rule in master.certificate_output_rules:
        if (rule.operation == master.certificate_process_operation
                and rule.action == "Retain"):
            _active_source_certificate(source.name, rule.certificate_type)


def _active_source_certificate(handling_unit, certificate_type):
    rows = frappe.get_all(
        "CFG Process Certificate",
        filters={
            "handling_unit": handling_unit,
            "certificate_type": certificate_type,
            "status": "Active",
        },
        fields=["name", "valid_from", "valid_until", "evidence_references"],
        order_by="issued_on desc", limit_page_length=1,
    )
    if not rows:
        frappe.throw(
            f"Cannot retain {certificate_type}; the source tag has no active issued "
            "certificate evidence"
        )
    certificate = rows[0]
    if certificate.valid_until and certificate.valid_until < now_datetime():
        frappe.throw(
            f"Cannot retain {certificate_type}; its source certificate expired on "
            f"{certificate.valid_until}"
        )
    return certificate

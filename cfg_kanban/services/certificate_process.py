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
    if run.status not in ("In Progress", "Awaiting ERP Submission"):
        frappe.throw(f"Certificate Process cannot complete while it is {run.status}")
    if run.status == "Awaiting ERP Submission":
        return get_certificate_process_context(cycle_name, operator_session_token)
    master = frappe.get_doc("CFG Kanban Master", run.kanban_master)
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
    pending_output = None
    if not full_reuse:
        pending_output = normalize_physical_code(output_tag_scan)
        _validate_unused_output_tag(pending_output)
    if not cint(run.item_batch_controlled) and output_batch:
        frappe.throw("Output Batch is not accepted because this Item is not Batch controlled")
    _validate_retain_evidence(master, source)
    resolved_batch = _resolve_output_batch(
        run.item_code, run.source_batch, output_batch, printed_expiry
    ) if cint(run.item_batch_controlled) else None
    result_set = _result_certificate_set(master, run.source_certificate_set)
    entry = _create_repack_entry(run, good_qty, result_set.name, resolved_batch)
    run.db_set({
        "good_qty": good_qty, "reject_qty": reject_qty,
        "pending_output_tag_code": pending_output,
        "output_handling_unit": source.name if full_reuse else None,
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
def submit_certificate_process(run_name, event_token=None, operator_session_token=None):
    require_operator(operator_session_token, "complete")
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
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
def cancel_certificate_process(run_name, reason, event_token=None,
                               operator_session_token=None):
    profile, session = require_operator(operator_session_token, "start")
    if not (reason or "").strip():
        frappe.throw("Cancellation reason is required")
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
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
    run.db_set({"status": "Cancelled", "exception_notes": reason.strip()})
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
    run.db_set({"status": "Completed", "output_handling_unit": output.name,
                "completed_on": now_datetime()})
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


def _validate_unused_output_tag(code):
    identity = resolve_logistics_scan(code)
    if not identity or identity.get("identity_type") not in (
            "Registered Tag Identity", "Tag Range Candidate"):
        frappe.throw("Output tag is not covered by an active Tag Family or Tag Range")
    if identity.get("tag_role") != "Main":
        frappe.throw("Certificate Process output requires an unused main Stock Tag")
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(f"Output tag is {identity.get('state')}")


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
        output_row["process_certificate_set"] = result_set
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

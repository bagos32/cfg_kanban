import json

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


RECOVERY_DOCTYPE = "CFG Process Certificate Recovery"
MANAGER_ROLES = ("Manufacturing Manager", "System Manager")
TOLERANCE = 0.000001


def _require_manager():
    frappe.only_for(MANAGER_ROLES)


@frappe.whitelist()
def request_certificate_process_recovery(run_name, reason):
    _require_manager()
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("A controlled recovery reason is required")
    frappe.db.sql(
        "select name from `tabCFG Process Certificate Run` where name=%s for update",
        (run_name,),
    )
    run = frappe.get_doc("CFG Process Certificate Run", run_name)
    existing = frappe.db.get_value(
        RECOVERY_DOCTYPE, {"certificate_process_run": run.name}, "name"
    )
    if existing:
        return _public_result(frappe.get_doc(RECOVERY_DOCTYPE, existing))
    if not run.repack_stock_entry:
        frappe.throw("Use normal Certificate Process cancellation before a Repack exists")
    if run.status not in ("Awaiting ERP Submission", "Completed"):
        frappe.throw(f"Certificate Process recovery is not available while Run is {run.status}")

    cycle = frappe.get_doc("CFG Kanban Cycle", run.kanban_cycle)
    card = frappe.get_doc("CFG Kanban Card", run.kanban_card)
    if card.active_cycle and card.active_cycle != cycle.name:
        frappe.throw(
            f"Card {card.name} is already active in Cycle {card.active_cycle}. "
            "Resolve that later Cycle before reversing this completed Certificate Process."
        )
    entry = frappe.get_doc("Stock Entry", run.repack_stock_entry)
    blocker = _physical_reversal_blocker(run) if run.status == "Completed" else None
    if blocker:
        frappe.throw(blocker)

    status = "Pending ERP Reversal" if entry.docstatus == 1 else "Ready to Finalize"
    recovery = frappe.get_doc({
        "doctype": RECOVERY_DOCTYPE,
        "status": status,
        "certificate_process_run": run.name,
        "kanban_cycle": run.kanban_cycle,
        "kanban_master": run.kanban_master,
        "kanban_card": run.kanban_card,
        "company": run.company,
        "item_code": run.item_code,
        "operation": run.operation,
        "reason": reason,
        "previous_run_status": run.status,
        "repack_stock_entry_name": entry.name,
        "repack_docstatus_snapshot": entry.docstatus,
        "repack_snapshot": json.dumps(entry.as_dict(), sort_keys=True, default=str),
        "source_handling_unit": run.source_handling_unit,
        "output_handling_unit": run.output_handling_unit,
        "source_certificate_set": run.source_certificate_set,
        "result_certificate_set": run.result_certificate_set,
        "physical_reversal_required": 1 if run.status == "Completed" else 0,
        "requested_by": frappe.session.user,
        "requested_on": now_datetime(),
    }).insert(ignore_permissions=True)

    run.db_set({
        "status": "Exception",
        "exception_notes": _append_note(
            run.exception_notes, f"Controlled recovery {recovery.name}: {reason}"
        ),
    }, update_modified=True)
    set_cycle_state(
        cycle, "Blocked", event_type="Certificate Process Recovery Requested",
        reference_doctype=recovery.doctype, reference_name=recovery.name,
    )
    cycle.db_set("blocked", 1, update_modified=False)
    if card.current_state != "Blocked":
        transition_card(
            card, "Blocked", event_type="Certificate Process Recovery Requested",
            cycle=cycle.name, notes=reason,
        )
    card.db_set({"blocked": 1, "blocked_reason": reason}, update_modified=True)
    record(
        "Certificate Process Recovery Requested", card=card.name, cycle=cycle.name,
        handling_unit=run.output_handling_unit or run.source_handling_unit,
        reference_doctype=recovery.doctype, reference_name=recovery.name,
        notes=f"Run {run.name}; Repack {entry.name}; {reason}",
        system_generated=False,
    )
    return _public_result(recovery)


@frappe.whitelist()
def refresh_certificate_process_recovery(recovery_name):
    _require_manager()
    recovery, run = _locked_recovery(recovery_name)
    if recovery.status == "Completed":
        return _public_result(recovery)
    blocker = _current_blocker(recovery, run)
    status = _recovery_status(recovery, blocker)
    recovery.db_set({"status": status, "blocking_reason": blocker}, update_modified=True)
    return _public_result(frappe.get_doc(RECOVERY_DOCTYPE, recovery.name))


@frappe.whitelist()
def cancel_certificate_process_repack(recovery_name, reversal_notes):
    _require_manager()
    notes = (reversal_notes or "").strip()
    if not notes:
        frappe.throw("ERP reversal notes are required")
    recovery, run = _locked_recovery(recovery_name)
    if recovery.status == "Completed":
        return _public_result(recovery)
    entry = _get_repack(recovery)
    if not entry:
        frappe.throw("The Repack Stock Entry no longer exists; refresh the recovery assessment")
    if entry.docstatus == 2:
        _mark_erp_reversed(recovery)
        return refresh_certificate_process_recovery(recovery.name)
    if entry.docstatus != 1:
        frappe.throw("Only a submitted ERPNext Repack uses the controlled Cancel action")
    blocker = _physical_reversal_blocker(run)
    if blocker:
        recovery.db_set({"status": "Blocked", "blocking_reason": blocker})
        frappe.throw(blocker)

    entry.flags.ignore_permissions = True
    # The immutable Certificate Process Run intentionally keeps its Link to this
    # submitted ERP document for audit.  The controlled recovery has already
    # validated that no downstream tag activity exists, so permit ERPNext's native
    # cancellation without deleting or temporarily unlinking that audit record.
    entry.flags.ignore_links = True
    entry.cancel()
    if entry.docstatus != 2:
        frappe.throw(f"ERPNext did not cancel Repack {entry.name}")
    _mark_erp_reversed(recovery)
    record(
        "Certificate Process ERP Repack Cancelled", card=recovery.kanban_card,
        cycle=recovery.kanban_cycle, reference_doctype="Stock Entry",
        reference_name=entry.name, notes=notes, system_generated=False,
    )
    recovery.db_set({"status": "Ready to Finalize", "blocking_reason": None})
    return _public_result(frappe.get_doc(RECOVERY_DOCTYPE, recovery.name))


@frappe.whitelist()
def finalize_certificate_process_recovery(recovery_name, reconciliation_evidence):
    _require_manager()
    evidence = (reconciliation_evidence or "").strip()
    if not evidence:
        frappe.throw("Final ERP and physical reconciliation evidence is required")
    recovery, run = _locked_recovery(recovery_name)
    if recovery.status == "Completed":
        return _public_result(recovery)
    blocker = _current_blocker(recovery, run)
    if blocker:
        recovery.db_set({"status": "Blocked", "blocking_reason": blocker})
        frappe.throw(blocker)

    entry = _get_repack(recovery)
    draft_discarded = False
    if entry and entry.docstatus == 0:
        frappe.delete_doc(
            "Stock Entry", entry.name, ignore_permissions=True, ignore_links=True,
        )
        record(
            "Certificate Process Draft Repack Discarded",
            card=recovery.kanban_card, cycle=recovery.kanban_cycle,
            reference_doctype=recovery.doctype, reference_name=recovery.name,
            notes=f"Draft Stock Entry {entry.name}; {evidence}", system_generated=False,
        )
        draft_discarded = True
    elif entry and entry.docstatus != 2:
        frappe.throw(f"Cancel submitted ERPNext Repack {entry.name} before finalization")

    _reverse_physical_projection(recovery, run)
    cycle = frappe.get_doc("CFG Kanban Cycle", recovery.kanban_cycle)
    card = frappe.get_doc("CFG Kanban Card", recovery.kanban_card)
    run.db_set({
        "status": "Cancelled",
        "repack_stock_entry": None if draft_discarded else run.repack_stock_entry,
        "exception_notes": _append_note(
            run.exception_notes, f"Recovery {recovery.name} completed: {evidence}"
        ),
    }, update_modified=True)
    cycle.db_set("blocked", 0, update_modified=False)
    set_cycle_state(
        cycle, "Cancelled", event_type="Certificate Process Recovery Completed",
        reference_doctype=recovery.doctype, reference_name=recovery.name,
    )
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "status": "Cancelled", "cancelled_on": now_datetime(),
            "cancelled_by": frappe.session.user,
            "cancellation_reason": recovery.reason,
        }, update_modified=True)
    card.reload()
    if card.current_state != "Available":
        transition_card(
            card, "Available", event_type="Certificate Process Recovery Card Released",
            cycle=cycle.name, notes=evidence,
        )
    card.db_set({
        "active_cycle": None, "blocked": 0, "blocked_reason": None,
    }, update_modified=True)
    recovery.db_set({
        "status": "Completed", "blocking_reason": None,
        "final_reconciliation_evidence": evidence,
        "finalized_by": frappe.session.user, "finalized_on": now_datetime(),
    }, update_modified=True)
    record(
        "Certificate Process Recovery Completed", card=card.name, cycle=cycle.name,
        handling_unit=run.output_handling_unit or run.source_handling_unit,
        reference_doctype=recovery.doctype, reference_name=recovery.name,
        notes=evidence, system_generated=False,
    )
    return _public_result(frappe.get_doc(RECOVERY_DOCTYPE, recovery.name))


def sync_recovery_from_stock_entry(doc):
    """Move an existing recovery forward when ERPNext cancellation occurs elsewhere."""
    if not frappe.db.table_exists(RECOVERY_DOCTYPE):
        return
    recovery_name = frappe.db.get_value(
        RECOVERY_DOCTYPE, {"repack_stock_entry_name": doc.name,
                           "status": ["!=", "Completed"]}, "name"
    )
    if not recovery_name:
        return
    recovery = frappe.get_doc(RECOVERY_DOCTYPE, recovery_name)
    _mark_erp_reversed(recovery)
    run = frappe.get_doc("CFG Process Certificate Run", recovery.certificate_process_run)
    blocker = (
        _physical_reversal_blocker(run)
        if recovery.previous_run_status == "Completed" else None
    )
    recovery.db_set({
        "status": "Blocked" if blocker else "Ready to Finalize",
        "blocking_reason": blocker,
    })


def _reverse_physical_projection(recovery, run):
    if recovery.previous_run_status == "Awaiting ERP Submission":
        _release_run_reservation(run, recovery)
        return
    if recovery.previous_run_status != "Completed":
        return
    blocker = _physical_reversal_blocker(run)
    if blocker:
        frappe.throw(blocker)
    source = frappe.get_doc("CFG Kanban Handling Unit", run.source_handling_unit)
    if run.output_handling_unit == source.name:
        frappe.db.set_value("CFG Kanban Handling Unit", source.name, {
            "process_certificate_set": run.source_certificate_set,
            "batch_no": run.source_batch,
            "current_warehouse": run.source_warehouse,
            "identity_state": "Active", "movement_state": "Received",
        }, update_modified=True)
        return

    output = frappe.get_doc("CFG Kanban Handling Unit", run.output_handling_unit)
    post_quantity_event(
        event_type="Merge", qty=run.good_qty, stock_uom=run.stock_uom,
        idempotency_key=canonical_key("certificate-process-recovery-merge", recovery.name),
        source_handling_unit=output.name, destination_handling_unit=source.name,
        item_code=run.item_code, batch_no=run.output_batch,
        source_company=run.company, destination_company=run.company,
        source_warehouse=run.output_warehouse,
        destination_warehouse=run.source_warehouse,
        reference_doctype=recovery.doctype, reference_name=recovery.name,
        reason=f"Controlled reversal of Certificate Process Run {run.name}",
    )
    frappe.db.set_value("CFG Kanban Handling Unit", source.name, {
        "process_certificate_set": run.source_certificate_set,
        "batch_no": run.source_batch,
        "current_warehouse": run.source_warehouse,
        "identity_state": "Active", "movement_state": "Received",
    }, update_modified=True)
    frappe.db.set_value("CFG Kanban Handling Unit", output.name, {
        "state": "Void", "identity_state": "Void", "movement_state": "Empty",
        "process_certificate_set": None,
        "void_reason": f"Certificate Process Recovery {recovery.name}",
    }, update_modified=True)


def _release_run_reservation(run, recovery):
    reserved = flt(frappe.db.sql("""
        select coalesce(sum(source_reserved_delta), 0)
          from `tabCFG Kanban Handling Unit Quantity Ledger`
         where reference_doctype='CFG Process Certificate Run'
           and reference_name=%s and source_handling_unit=%s
    """, (run.name, run.source_handling_unit))[0][0])
    if reserved <= TOLERANCE:
        return
    post_quantity_event(
        event_type="Unreserve", qty=reserved, stock_uom=run.stock_uom,
        idempotency_key=canonical_key("certificate-process-recovery-unreserve", recovery.name),
        source_handling_unit=run.source_handling_unit,
        item_code=run.item_code, batch_no=run.source_batch,
        source_company=run.company, source_warehouse=run.source_warehouse,
        reference_doctype=recovery.doctype, reference_name=recovery.name,
        reason=f"Discarded Draft Repack for Certificate Process Run {run.name}",
    )


def _current_blocker(recovery, run):
    entry = _get_repack(recovery)
    if entry and entry.docstatus == 1:
        return f"Cancel submitted ERPNext Repack {entry.name} before finalization"
    if recovery.previous_run_status == "Completed":
        return _physical_reversal_blocker(run)
    return None


def _physical_reversal_blocker(run):
    if not run.output_handling_unit:
        return "The completed Certificate Process has no output Stock Tag to reconcile"
    source = frappe.get_doc("CFG Kanban Handling Unit", run.source_handling_unit)
    output = frappe.get_doc("CFG Kanban Handling Unit", run.output_handling_unit)
    if run.output_handling_unit == source.name:
        problems = _unit_mismatches(
            output, run.good_qty, run.output_warehouse, run.output_batch,
            run.result_certificate_set,
        )
        cutoff = run.completed_on
        units = [source.name]
    else:
        problems = _unit_mismatches(
            output, run.good_qty, run.output_warehouse, run.output_batch,
            run.result_certificate_set,
        )
        if source.current_warehouse != run.source_warehouse:
            problems.append(f"source tag moved to {source.current_warehouse}")
        if (source.batch_no or None) != (run.source_batch or None):
            problems.append("source tag Batch changed")
        if (source.process_certificate_set or None) != (run.source_certificate_set or None):
            problems.append("source tag certificate state changed")
        cutoff = frappe.db.get_value(
            "CFG Kanban Handling Unit Quantity Ledger",
            {"idempotency_key": canonical_key("certificate-process-split", run.name)},
            "creation",
        )
        units = [source.name, output.name]
    if cutoff and frappe.db.exists(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"creation": [">", cutoff],
         "source_handling_unit": ["in", units]},
    ):
        problems.append("tag has later quantity-ledger activity")
    if cutoff and frappe.db.exists(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"creation": [">", cutoff],
         "destination_handling_unit": ["in", units]},
    ):
        problems.append("tag has later quantity-ledger activity")
    if problems:
        return (
            "Certificate Process physical output is no longer untouched: "
            + "; ".join(dict.fromkeys(problems))
            + ". Reconcile downstream stock/tag activity before reversal."
        )
    return None


def _unit_mismatches(unit, qty, warehouse, batch_no, certificate_set):
    problems = []
    if unit.identity_state != "Active":
        problems.append(f"output tag is {unit.identity_state}")
    if abs(flt(unit.current_qty) - flt(qty)) > TOLERANCE:
        problems.append(f"output tag quantity is {unit.current_qty}, expected {qty}")
    if flt(unit.reserved_qty) > TOLERANCE:
        problems.append(f"output tag has {unit.reserved_qty} reserved")
    if unit.current_warehouse != warehouse:
        problems.append(f"output tag moved to {unit.current_warehouse}")
    if (unit.batch_no or None) != (batch_no or None):
        problems.append("output tag Batch changed")
    if (unit.process_certificate_set or None) != (certificate_set or None):
        problems.append("output tag certificate state changed")
    return problems


def _recovery_status(recovery, blocker):
    entry = _get_repack(recovery)
    if entry and entry.docstatus == 1:
        return "Pending ERP Reversal"
    return "Blocked" if blocker else "Ready to Finalize"


def _get_repack(recovery):
    name = recovery.repack_stock_entry_name
    if not name or not frappe.db.exists("Stock Entry", name):
        return None
    return frappe.get_doc("Stock Entry", name)


def _locked_recovery(recovery_name):
    frappe.db.sql(
        "select name from `tabCFG Process Certificate Recovery` where name=%s for update",
        (recovery_name,),
    )
    recovery = frappe.get_doc(RECOVERY_DOCTYPE, recovery_name)
    recovery.check_permission("read")
    return recovery, frappe.get_doc(
        "CFG Process Certificate Run", recovery.certificate_process_run
    )


def _mark_erp_reversed(recovery):
    recovery.db_set({
        "erp_reversed_by": frappe.session.user,
        "erp_reversed_on": now_datetime(),
    }, update_modified=True)


def _append_note(existing, note):
    return "\n".join(value for value in ((existing or "").strip(), note.strip()) if value)


def _public_result(recovery):
    return {
        "name": recovery.name,
        "status": recovery.status,
        "run": recovery.certificate_process_run,
        "stock_entry": recovery.repack_stock_entry_name,
        "blocking_reason": recovery.blocking_reason,
    }

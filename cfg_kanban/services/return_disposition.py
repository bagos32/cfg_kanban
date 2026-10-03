"""Controlled physical disposition of QC-accepted customer returns."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.logistics_foundation import validate_warehouse_company


DISPOSITION_ROLES = ("Stock Manager", "Quality Manager", "System Manager")
RECEIPT_DISPOSITIONS = {
    "Receive to Quarantine", "Receive for Rework", "Return to Available Stock",
}
DISPOSAL_DISPOSITION = "Dispose Without Stock Receipt"
ALL_DISPOSITIONS = RECEIPT_DISPOSITIONS | {DISPOSAL_DISPOSITION}


@frappe.whitelist()
def get_stock_disposition_context(return_case):
    _require_disposition_user()
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    case.check_permission("read")
    _assert_disposition_ready(case, allow_decided=True)
    return {
        "return_case": case.name,
        "selling_company": case.selling_company,
        "state": case.state,
        "disposition_status": case.disposition_status or "Not Started",
        "stock_entry": case.stock_disposition_entry,
        "stock_entry_status": case.stock_disposition_entry_status,
        "accepted_lines": [{
            "return_line": row.name,
            "item_code": row.item_code,
            "batch_no": row.batch_no,
            "stock_uom": row.stock_uom,
            "accepted_qty": flt(row.accepted_qty),
            "qc_disposition": row.qc_disposition,
            "qc_reason": row.qc_reason,
        } for row in case.lines if flt(row.accepted_qty) > 0],
        "existing_dispositions": [row.as_dict() for row in case.disposition_lines],
    }


@frappe.whitelist()
def prepare_stock_disposition(return_case, lines, decision_notes, event_token=None):
    _require_disposition_user()
    frappe.db.sql(
        "select name from `tabCFG Kanban Return Case` where name=%s for update",
        return_case,
    )
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    case.check_permission("read")
    _assert_disposition_ready(case, allow_decided=True)
    notes = (decision_notes or "").strip()
    if not notes:
        frappe.throw(_("Stock disposition decision notes are required"))
    active_entry = _active_stock_entry(case.stock_disposition_entry)
    if active_entry:
        return {
            "return_case": case.name,
            "stock_entry": active_entry,
            "stock_entry_status": case.stock_disposition_entry_status,
            "already_exists": True,
        }
    submitted = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    snapshots = _validate_disposition_lines(case, submitted)
    has_receipt = any(row["disposition"] in RECEIPT_DISPOSITIONS for row in snapshots)
    if has_receipt:
        _require_stock_entry_create()
    case.set("disposition_lines", snapshots)
    case.disposition_status = "Decision Recorded"
    case.disposition_decided_by = frappe.session.user
    case.disposition_decided_on = now_datetime()
    case.disposition_notes = notes
    case.save(ignore_permissions=True)
    case.reload()
    if not has_receipt:
        previous_state = case.state
        new_state = _state_after_disposition(case, completed=True)
        for row in case.disposition_lines:
            row.db_set("status", "Disposed", update_modified=False)
        case.db_set({
            "disposition_status": "Completed",
            "stock_disposition_entry": None,
            "stock_disposition_entry_status": "Not Required",
            "state": new_state,
        }, update_modified=True)
        record(
            "Customer Return Disposed Without Stock Receipt", return_case=case.name,
            previous_state=previous_state, new_state=new_state,
            qty=case.accepted_total_qty, reference_doctype=case.doctype,
            reference_name=case.name, device_id=event_token, notes=notes,
        )
        case.reload()
        return {
            "return_case": case.name, "stock_entry": None,
            "stock_entry_status": "Not Required", "completed": True,
        }
    revision = int(case.disposition_revision or 0)
    command_key = canonical_key("customer-return-material-receipt", case.name, revision)
    payload = frappe.as_json({
        "company": case.selling_company,
        "decision_notes": notes,
        "disposition_revision": revision,
        "disposition_lines": [{
            "disposition_line": row.name,
            "return_line": row.return_line,
            "item_code": row.item_code,
            "batch_no": row.batch_no,
            "stock_uom": row.stock_uom,
            "qty": flt(row.qty),
            "disposition": row.disposition,
            "target_warehouse": row.target_warehouse,
            "valuation_rate": flt(row.valuation_rate),
            "reason": row.reason,
        } for row in case.disposition_lines
        if row.disposition in RECEIPT_DISPOSITIONS],
    })
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Customer Return Material Receipt",
        "return_case": case.name,
        "status": "Pending",
        "target_doctype": "Stock Entry",
        "request_payload": payload,
        "terminal_user": frappe.session.user,
        "requested_on": now_datetime(),
        "created_by_system": 1,
    }), command_key, ignore_permissions=True)
    if not created and command.status == "Failed":
        command.db_set({
            "request_payload": payload,
            "terminal_user": frappe.session.user,
            "target_document": None,
            "last_error": None,
        }, update_modified=True)
        command.reload()
    stock_entry = execute_command(command.name)
    record(
        "Customer Return Material Receipt Draft Prepared", return_case=case.name,
        previous_state=case.state, new_state=case.state,
        qty=sum(flt(row.qty) for row in case.disposition_lines
                if row.disposition in RECEIPT_DISPOSITIONS),
        reference_doctype="Stock Entry", reference_name=stock_entry.name,
        device_id=command_key, notes=notes,
    )
    return {
        "return_case": case.name, "stock_entry": stock_entry.name,
        "stock_entry_status": "Draft", "already_exists": False,
    }


@frappe.whitelist()
def discard_stock_disposition_draft(return_case, reason):
    frappe.only_for(("Stock Manager", "System Manager"))
    explanation = (reason or "").strip()
    if not explanation:
        frappe.throw(_("A discard reason is required"))
    frappe.db.sql(
        "select name from `tabCFG Kanban Return Case` where name=%s for update",
        return_case,
    )
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    entry_name = case.stock_disposition_entry
    if not entry_name or frappe.db.get_value("Stock Entry", entry_name, "docstatus") != 0:
        frappe.throw(_("Only the linked Draft return Material Receipt can be discarded"))
    for row in case.disposition_lines:
        if row.disposition in RECEIPT_DISPOSITIONS:
            row.db_set({"status": "Cancelled", "stock_entry_detail": None},
                       update_modified=False)
    case.db_set({
        "disposition_status": "Decision Recorded",
        "stock_disposition_entry": None,
        "stock_disposition_entry_status": "Discarded",
        "disposition_revision": int(case.disposition_revision or 0) + 1,
    }, update_modified=True)
    for command_name in frappe.get_all(
        "CFG ERP Command",
        filters={"target_doctype": "Stock Entry", "target_document": entry_name},
        pluck="name",
    ):
        frappe.db.set_value("CFG ERP Command", command_name, {
            "status": "Cancelled",
            "target_document": None,
            "last_error": f"Draft {entry_name} discarded: {explanation}",
        }, update_modified=False)
    frappe.delete_doc("Stock Entry", entry_name, ignore_permissions=True)
    record(
        "Customer Return Material Receipt Draft Discarded", return_case=case.name,
        previous_state=case.state, new_state=case.state,
        qty=sum(flt(row.qty) for row in case.disposition_lines
                if row.disposition in RECEIPT_DISPOSITIONS),
        reference_doctype="Stock Entry", reference_name=entry_name,
        notes=explanation,
    )
    return {"return_case": case.name, "discarded_stock_entry": entry_name}


def _validate_disposition_lines(case, submitted):
    accepted = {row.name: row for row in case.lines if flt(row.accepted_qty) > 0}
    if not accepted:
        frappe.throw(_("Return Case has no QC-accepted quantity to disposition"))
    totals = {}
    result = []
    for raw in submitted:
        return_line = raw.get("return_line")
        qty = flt(raw.get("qty"))
        if not return_line and qty <= 0:
            continue
        source = accepted.get(return_line)
        if not source:
            frappe.throw(_("Disposition row does not belong to this Return Case"))
        if qty <= 0:
            frappe.throw(_("Disposition quantity must be greater than zero"))
        disposition = raw.get("disposition")
        if disposition not in ALL_DISPOSITIONS:
            frappe.throw(_("Select a valid physical disposition"))
        reason = (raw.get("reason") or "").strip()
        if not reason:
            frappe.throw(_("Disposition reason is required for {0}").format(source.item_code))
        warehouse = raw.get("target_warehouse")
        rate = flt(raw.get("valuation_rate"))
        if disposition in RECEIPT_DISPOSITIONS:
            if not warehouse:
                frappe.throw(_("Target Warehouse is required for {0}").format(source.item_code))
            validate_warehouse_company(warehouse, case.selling_company, "Return Target Warehouse")
            if frappe.db.get_value("Warehouse", warehouse, "is_group"):
                frappe.throw(_("Return Target Warehouse must not be a group Warehouse"))
            if rate < 0:
                frappe.throw(_("Valuation Rate cannot be negative"))
            if rate == 0 and not frappe.db.get_value(
                "Item", source.item_code, "allow_zero_valuation_rate"
            ):
                frappe.throw(_("Enter a positive Valuation Rate for {0}").format(source.item_code))
        else:
            if warehouse:
                frappe.throw(_("Disposal without stock receipt must not select a Warehouse"))
            rate = 0
        totals[return_line] = totals.get(return_line, 0) + qty
        result.append({
            "return_line": return_line,
            "item_code": source.item_code,
            "batch_no": source.batch_no,
            "stock_uom": source.stock_uom,
            "qty": qty,
            "disposition": disposition,
            "target_warehouse": warehouse,
            "valuation_rate": rate,
            "reason": reason,
            "status": "Decision Recorded",
        })
    if not result:
        frappe.throw(_("Add a disposition for every QC-accepted quantity"))
    for name, source in accepted.items():
        if abs(flt(totals.get(name)) - flt(source.accepted_qty)) > 0.000001:
            frappe.throw(_("Disposition quantities for {0} must equal QC-accepted quantity {1}").format(
                source.item_code, source.accepted_qty
            ))
    return result


def _assert_disposition_ready(case, allow_decided=False):
    if case.return_flow != "Customer Return for QC" or not case.qc_completed_on:
        frappe.throw(_("Only a completed Customer Return QC case can be dispositioned"))
    if flt(case.accepted_total_qty) <= 0:
        frappe.throw(_("Return Case has no QC-accepted quantity"))
    allowed = {None, "", "Not Started"}
    if allow_decided:
        allowed.update({"Decision Recorded", "Stock Receipt Draft", "Exception"})
    if case.disposition_status not in allowed:
        frappe.throw(_("Accepted return stock disposition is already completed"))


def _active_stock_entry(stock_entry):
    if not stock_entry:
        return None
    return stock_entry if frappe.db.get_value("Stock Entry", stock_entry, "docstatus") in (0, 1) else None


def _state_after_disposition(case, completed):
    if completed and case.accounting_status in ("Completed", "No Credit Approved"):
        return "Closed"
    if case.accounting_status in ("Completed", "No Credit Approved"):
        return "Accounting Completed"
    return "QC Completed - Accounting Pending"


def _require_disposition_user():
    frappe.only_for(DISPOSITION_ROLES)


def _require_stock_entry_create():
    if not frappe.has_permission("Stock Entry", ptype="create"):
        frappe.throw(_("You need Create permission for Stock Entry to receive returned stock"),
                     frappe.PermissionError)

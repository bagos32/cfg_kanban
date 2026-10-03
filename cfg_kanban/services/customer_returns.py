"""Floor-side return custody, QC disposition, and wrong-Delivery-Note correction.

Customer Return for QC deliberately creates no ERP stock or accounting document.
Delivery Note Correction is the only floor flow allowed to create a Return Delivery Note.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.operator_auth import require_operator


CUSTOMER_RETURN_RESPONSIBILITY = "Customer Return"
CUSTOMER_RETURN_QC_RESPONSIBILITY = "Customer Return QC"
OPEN_RETURN_STATES = (
    "Awaiting QC Receipt", "QC In Progress", "QC Completed - Accounting Pending",
    "QC Rejected", "Delivery Correction Pending", "Delivery Correction Draft", "Exception",
)
CONDITIONS = (
    "Unknown", "Good / Unwanted", "Damaged", "Expired", "Pest or Contamination",
    "Customer Handling Damage", "Wrong Item or Quantity", "Other",
)
QC_DISPOSITIONS = (
    "Accept for Credit", "Reject Customer Claim", "Accept for Rework",
    "Accept for Disposal", "Hold for Investigation",
)
ACCOUNTING_ROLES = ("Accounts User", "Accounts Manager", "Sales Manager", "System Manager")


@frappe.whitelist()
def get_return_intake_context(customer_scan, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    _require_intake(profile)
    _assert_enabled()
    site = _resolve_site(customer_scan)
    if not site.enable_customer_return_qc:
        frappe.throw(_("Customer Return for QC is disabled at this Customer Site"))
    return {
        "customer_scan_point": site.name,
        "site_code": site.site_code,
        "site_name": site.site_name,
        "selling_company": site.selling_company,
        "customer": site.customer,
        "customer_address": site.customer_address,
        "inspection_location": site.return_inspection_location,
    }


@frappe.whitelist()
def create_qc_return_case(customer_scan, customer_return_reason, lines, event_token,
                          operator_session_token, customer_acknowledgement_name=None):
    profile, session = require_operator(operator_session_token, "start")
    _require_intake(profile)
    _assert_enabled()
    site = _resolve_site(customer_scan)
    if not site.enable_customer_return_qc:
        frappe.throw(_("Customer Return for QC is disabled at this Customer Site"))
    if not site.return_inspection_location:
        frappe.throw(_("Set Default Inspection Custody Location on the Customer Scan Point"))
    reason = (customer_return_reason or "").strip()
    if not reason:
        frappe.throw(_("Customer return reason is required"))
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    rows = _validate_free_intake_lines(lines)
    key = canonical_key("customer-return-qc-intake", site.name, event_token)
    existing = frappe.db.get_value("CFG Kanban Return Case", {"idempotency_key": key}, "name")
    if existing:
        return _return_case_result(frappe.get_doc("CFG Kanban Return Case", existing), profile)
    total = sum(flt(row["claimed_qty"]) for row in rows)
    acknowledgement = (customer_acknowledgement_name or "").strip()
    case, created = insert_once(frappe.get_doc({
        "doctype": "CFG Kanban Return Case",
        "state": "Awaiting QC Receipt",
        "return_flow": "Customer Return for QC",
        "customer_scan_point": site.name,
        "selling_company": site.selling_company,
        "customer": site.customer,
        "customer_address": site.customer_address,
        "site_code": site.site_code,
        "site_name": site.site_name,
        "inspection_location": site.return_inspection_location,
        "claimed_on": now_datetime(),
        "customer_return_reason": reason,
        "customer_acknowledgement_name": acknowledgement,
        "customer_acknowledged_on": now_datetime() if acknowledgement else None,
        "lines": rows,
        "claimed_total_qty": total,
        "accepted_total_qty": 0,
        "rejected_total_qty": 0,
        "accounting_status": "Pending Source Selection",
        "created_by_operator": profile.employee,
        "created_operator_session": session.name,
        "idempotency_key": key,
    }), key, ignore_permissions=True)
    if created:
        record(
            "Customer Return Intake Recorded", return_case=case.name,
            previous_state=None, new_state=case.state, qty=total,
            reference_doctype=case.doctype, reference_name=case.name,
            device_id=key, notes=reason, operator=profile.employee,
            operator_session=session.name, terminal_user=session.terminal_user,
        )
    return _return_case_result(case, profile)


@frappe.whitelist()
def get_delivery_correction_candidate(delivery_session, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    _require_intake(profile)
    _assert_enabled()
    delivery, site = _eligible_delivery(delivery_session)
    if not site.enable_delivery_note_correction:
        frappe.throw(_("Wrong Delivery Note Correction is disabled at this Customer Site"))
    if not site.correction_return_warehouse:
        frappe.throw(_("Set Delivery Correction Return Warehouse on the Customer Scan Point"))
    rows = []
    for allocation in _delivered_allocations(delivery.name):
        available = max(flt(allocation.delivered_qty) - _corrected_qty(allocation.name), 0)
        if available <= 0:
            continue
        rows.append({
            "original_delivery_allocation": allocation.name,
            "original_delivery_note_item": allocation.delivery_note_item,
            "original_handling_unit": allocation.handling_unit,
            "original_visible_code": allocation.visible_code,
            "item_code": allocation.item_code,
            "batch_no": allocation.batch_no,
            "stock_uom": allocation.stock_uom,
            "delivered_qty": flt(allocation.delivered_qty),
            "available_to_correct_qty": available,
            "claimed_qty": 0,
            "condition": "Wrong Item or Quantity",
            "details": "",
        })
    invoices = _submitted_invoices(delivery.delivery_note)
    return {
        "delivery_session": delivery.name,
        "delivery_note": delivery.delivery_note,
        "selling_company": delivery.selling_company,
        "customer": delivery.customer,
        "site_code": delivery.site_code,
        "site_name": delivery.site_name,
        "correction_return_warehouse": site.correction_return_warehouse,
        "auto_submit": bool(site.auto_submit_correction_return_dn and not invoices),
        "accounting_attention_required": bool(invoices),
        "linked_sales_invoices": invoices,
        "lines": rows,
    }


@frappe.whitelist()
def create_delivery_correction_case(delivery_session, customer_return_reason, lines,
                                    event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    _require_intake(profile)
    _assert_enabled()
    delivery, site = _eligible_delivery(delivery_session)
    if not site.enable_delivery_note_correction:
        frappe.throw(_("Wrong Delivery Note Correction is disabled at this Customer Site"))
    if not site.correction_return_warehouse:
        frappe.throw(_("Set Delivery Correction Return Warehouse on the Customer Scan Point"))
    reason = (customer_return_reason or "").strip()
    if not reason:
        frappe.throw(_("Delivery correction reason is required"))
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    submitted = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    _lock_allocations(submitted)
    rows = _validate_correction_lines(delivery, submitted)
    total = sum(flt(row["claimed_qty"]) for row in rows)
    key = canonical_key("delivery-note-correction", delivery.name, event_token)
    existing = frappe.db.get_value("CFG Kanban Return Case", {"idempotency_key": key}, "name")
    if existing:
        return _return_case_result(frappe.get_doc("CFG Kanban Return Case", existing), profile)
    invoices = _submitted_invoices(delivery.delivery_note)
    case, created = insert_once(frappe.get_doc({
        "doctype": "CFG Kanban Return Case",
        "state": "Delivery Correction Pending",
        "return_flow": "Delivery Note Correction",
        "customer_scan_point": delivery.customer_scan_point,
        "original_delivery_session": delivery.name,
        "original_delivery_note": delivery.delivery_note,
        "delivery_proof": delivery.delivery_proof,
        "selling_company": delivery.selling_company,
        "customer": delivery.customer,
        "customer_address": delivery.customer_address,
        "site_code": delivery.site_code,
        "site_name": delivery.site_name,
        "correction_return_warehouse": site.correction_return_warehouse,
        "claimed_on": now_datetime(),
        "received_on": now_datetime(),
        "customer_return_reason": reason,
        "lines": rows,
        "claimed_total_qty": total,
        "accounting_status": "Credit Pending" if invoices else "Not Required",
        "created_by_operator": profile.employee,
        "created_operator_session": session.name,
        "idempotency_key": key,
    }), key, ignore_permissions=True)
    if not created:
        return _return_case_result(case, profile)
    command_key = canonical_key("return-delivery-note", case.name)
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Correction Return Delivery Note",
        "return_case": case.name,
        "delivery_session": delivery.name,
        "status": "Pending",
        "target_doctype": "Delivery Note",
        "request_payload": frappe.as_json({
            "original_delivery_note": delivery.delivery_note,
            "return_warehouse": site.correction_return_warehouse,
            "submit": bool(site.auto_submit_correction_return_dn and not invoices),
            "lines": rows,
        }),
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
        "requested_on": now_datetime(),
        "created_by_system": 1,
    }), command_key, ignore_permissions=True)
    try:
        return_dn = execute_command(command.name)
    except Exception:
        case.db_set({"state": "Exception", "correction_document_status": "Failed"},
                    update_modified=True)
        raise
    state = "Delivery Correction Posted" if return_dn.docstatus == 1 else "Delivery Correction Draft"
    case.db_set({
        "state": state,
        "correction_return_delivery_note": return_dn.name,
        "correction_document_status": "Submitted" if return_dn.docstatus == 1 else "Draft",
    }, update_modified=True)
    case.reload()
    record(
        "Delivery Note Correction Requested", return_case=case.name,
        delivery_session=delivery.name, previous_state="Delivery Correction Pending",
        new_state=state, qty=total, reference_doctype="Delivery Note",
        reference_name=return_dn.name, device_id=command_key,
        notes=("Accounting attention required: " + ", ".join(invoices)) if invoices else reason,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
    )
    return _return_case_result(case, profile)


@frappe.whitelist()
def start_qc_inspection(return_case, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_qc(profile)
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if case.return_flow != "Customer Return for QC":
        frappe.throw(_("Only Customer Return for QC can enter inspection"))
    if case.state == "QC In Progress":
        return _return_case_result(case, profile)
    if case.state != "Awaiting QC Receipt":
        frappe.throw(_("Return Case cannot start QC while it is {0}").format(case.state))
    case.db_set({
        "state": "QC In Progress", "received_on": now_datetime(),
        "qc_started_on": now_datetime(), "qc_operator": profile.employee,
    }, update_modified=True)
    case.reload()
    record(
        "Customer Return QC Started", return_case=case.name,
        previous_state="Awaiting QC Receipt", new_state=case.state,
        qty=case.claimed_total_qty, reference_doctype=case.doctype,
        reference_name=case.name, device_id=event_token,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
    )
    return _return_case_result(case, profile)


@frappe.whitelist()
def complete_qc_inspection(return_case, lines, qc_notes, event_token,
                           operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    _require_qc(profile)
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if case.return_flow != "Customer Return for QC" or case.state != "QC In Progress":
        frappe.throw(_("Start QC inspection before recording its result"))
    submitted = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    by_name = {row.name: row for row in case.lines}
    accepted_total = rejected_total = 0
    seen = set()
    for result in submitted:
        row_name = result.get("name")
        row = by_name.get(row_name)
        if not row:
            frappe.throw(_("QC result contains an unknown Return Line"))
        if row_name in seen:
            frappe.throw(_("QC result contains the same Return Line more than once"))
        seen.add(row_name)
        received = flt(result.get("received_qty"))
        accepted = flt(result.get("accepted_qty"))
        rejected = flt(result.get("rejected_qty"))
        disposition = result.get("qc_disposition")
        if min(received, accepted, rejected) < 0 or received > flt(row.claimed_qty) + 0.000001:
            frappe.throw(_("QC quantities for {0} are invalid").format(row.item_code))
        if abs((accepted + rejected) - received) > 0.000001:
            frappe.throw(_("Accepted plus rejected must equal received for {0}").format(row.item_code))
        if disposition not in QC_DISPOSITIONS:
            frappe.throw(_("Select a QC disposition for {0}").format(row.item_code))
        row.db_set({
            "received_qty": received, "accepted_qty": accepted, "rejected_qty": rejected,
            "qc_disposition": disposition,
            "qc_reason": (result.get("qc_reason") or "").strip(),
        }, update_modified=False)
        accepted_total += accepted
        rejected_total += rejected
    if seen != set(by_name):
        frappe.throw(_("Record QC results for every returned item"))
    state = "QC Completed - Accounting Pending" if accepted_total > 0 else "QC Rejected"
    case.db_set({
        "state": state, "qc_completed_on": now_datetime(), "qc_operator": profile.employee,
        "qc_notes": (qc_notes or "").strip(), "accepted_total_qty": accepted_total,
        "rejected_total_qty": rejected_total,
        "accounting_status": "Pending Source Selection" if accepted_total > 0 else "No Credit Approved",
    }, update_modified=True)
    case.reload()
    record(
        "Customer Return QC Completed", return_case=case.name,
        previous_state="QC In Progress", new_state=state, qty=accepted_total,
        reference_doctype=case.doctype, reference_name=case.name,
        device_id=event_token, notes=(qc_notes or "").strip(),
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
    )
    return _return_case_result(case, profile)


@frappe.whitelist()
def get_accounting_context(return_case):
    """Return the accountant-only decision context after QC is complete."""
    _require_accounting_user()
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    case.check_permission("read")
    _assert_accounting_ready(case, allow_selected=True)
    accepted = _accepted_item_totals(case)
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "company": case.selling_company, "customer": case.customer,
            "docstatus": 1, "is_return": 0,
        },
        fields=["name", "posting_date", "grand_total", "currency", "status"],
        order_by="posting_date desc, creation desc", limit_page_length=50,
    )
    item_codes = set(accepted)
    invoice_names = [row.name for row in invoices]
    covered = {}
    if invoice_names:
        for row in frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": ["in", invoice_names], "item_code": ["in", list(item_codes)]},
            fields=["parent", "item_code", "stock_qty"], limit_page_length=500,
        ):
            invoice_items = covered.setdefault(row.parent, {})
            invoice_items[row.item_code] = (
                invoice_items.get(row.item_code, 0) + abs(flt(row.stock_qty))
            )
        returned = _submitted_credit_totals(invoice_names)
        for invoice_name, items in covered.items():
            for item_code in tuple(items):
                items[item_code] = max(
                    flt(items[item_code])
                    - flt(returned.get(invoice_name, {}).get(item_code)),
                    0,
                )
    for invoice in invoices:
        coverage = covered.get(invoice.name, {})
        invoice["covers_qc_items"] = all(
            flt(coverage.get(item_code)) + 0.000001 >= qty
            for item_code, qty in accepted.items()
        )
    return {
        "return_case": case.name, "state": case.state,
        "accounting_status": case.accounting_status,
        "selling_company": case.selling_company, "customer": case.customer,
        "accepted_items": [
            {"item_code": item_code, "accepted_qty": qty,
             "stock_uom": frappe.db.get_value("Item", item_code, "stock_uom")}
            for item_code, qty in accepted.items()
        ],
        "candidate_invoices": invoices,
        "selected_source": case.accounting_reference,
        "credit_document": case.credit_document,
        "credit_document_status": case.credit_document_status,
    }


@frappe.whitelist()
def prepare_accounting_decision(return_case, source_basis, decision_notes,
                                source_sales_invoice=None, event_token=None):
    """Close as no-credit or prepare a Draft ERPNext Sales Invoice Return.

    This Desk action is deliberately unavailable to floor operator sessions. The
    generated accounting document remains Draft for tax/e-Invoice review.
    """
    _require_accounting_user()
    frappe.db.sql(
        "select name from `tabCFG Kanban Return Case` where name=%s for update",
        return_case,
    )
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    case.check_permission("read")
    _assert_accounting_ready(case, allow_selected=True)
    notes = (decision_notes or "").strip()
    if not notes:
        frappe.throw(_("Accounting decision notes are required"))
    if source_basis == "No Credit":
        if source_sales_invoice:
            frappe.throw(_("No Credit decision must not select a Sales Invoice"))
        if case.credit_document and frappe.db.get_value(
            "Sales Invoice", case.credit_document, "docstatus"
        ) in (0, 1):
            frappe.throw(_("Cancel the existing Sales Invoice Return before choosing No Credit"))
        previous_state = case.state
        new_state = "Closed" if case.disposition_status == "Completed" else "Accounting Completed"
        case.db_set({
            "state": new_state, "accounting_status": "No Credit Approved",
            "accounting_source_basis": source_basis,
            "accounting_reference_doctype": None, "accounting_reference": None,
            "accounting_decided_by": frappe.session.user,
            "accounting_decided_on": now_datetime(),
            "accounting_decision_notes": notes,
            "credit_document_doctype": None, "credit_document": None,
            "credit_document_status": "Not Required",
        }, update_modified=True)
        record(
            "Customer Return No Credit Approved", return_case=case.name,
            previous_state=previous_state, new_state=new_state,
            qty=case.accepted_total_qty, reference_doctype=case.doctype,
            reference_name=case.name, device_id=event_token, notes=notes,
        )
        case.reload()
        return case.as_dict()
    if source_basis not in ("Exact Sales Invoice", "Substitute Historical Sales Invoice"):
        frappe.throw(_("Select Exact Sales Invoice, Substitute Historical Sales Invoice, or No Credit"))
    _require_sales_invoice_create()
    source = _validate_accounting_source(case, source_sales_invoice)
    if case.credit_document and frappe.db.get_value(
        "Sales Invoice", case.credit_document, "docstatus"
    ) in (0, 1):
        return {
            "return_case": case.name, "credit_document": case.credit_document,
            "credit_document_status": case.credit_document_status,
            "already_exists": True,
        }
    revision = int(case.accounting_revision or 0)
    command_key = canonical_key("customer-credit-return", case.name, revision)
    command_payload = frappe.as_json({
        "source_sales_invoice": source.name,
        "source_basis": source_basis,
        "accepted_items": _accepted_item_totals(case),
        "decision_notes": notes,
        "accounting_revision": revision,
    })
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Customer Credit Return",
        "return_case": case.name,
        "status": "Pending",
        "target_doctype": "Sales Invoice",
        "request_payload": command_payload,
        "terminal_user": frappe.session.user,
        "requested_on": now_datetime(), "created_by_system": 1,
    }), command_key, ignore_permissions=True)
    if not created and command.status == "Failed":
        command.db_set({
            "request_payload": command_payload,
            "terminal_user": frappe.session.user,
            "target_document": None,
            "last_error": None,
        }, update_modified=True)
        command.reload()
    credit = execute_command(command.name)
    case.reload()
    record(
        "Customer Credit Return Draft Prepared", return_case=case.name,
        previous_state=case.state, new_state=case.state,
        qty=case.accepted_total_qty, reference_doctype="Sales Invoice",
        reference_name=credit.name, device_id=command_key,
        notes=f"{source_basis}: {source.name}. {notes}",
    )
    return {
        "return_case": case.name, "credit_document": credit.name,
        "credit_document_status": "Draft", "already_exists": False,
    }


@frappe.whitelist()
def get_return_case(return_case, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    if not (_intake_allowed(profile) or _qc_allowed(profile)):
        frappe.throw(_("Operator is not assigned to Customer Return or Customer Return QC"),
                     frappe.PermissionError)
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if not _can_view_all(profile) and not (
        case.created_by_operator == profile.employee or _qc_allowed(profile)
    ):
        frappe.throw(_("Operator cannot access this Return Case"), frappe.PermissionError)
    return _return_case_result(case, profile)


def return_case_summaries(profile, limit=30):
    if not (_intake_allowed(profile) or _qc_allowed(profile)):
        return []
    filters = {"state": ["in", list(OPEN_RETURN_STATES)]}
    if not _can_view_all(profile) and not _qc_allowed(profile):
        filters["created_by_operator"] = profile.employee
    return frappe.get_all(
        "CFG Kanban Return Case", filters=filters,
        fields=["name", "state", "return_flow", "site_code", "site_name", "customer",
                "selling_company", "claimed_total_qty", "claimed_on",
                "original_delivery_note", "correction_return_delivery_note"],
        order_by="modified desc", limit_page_length=limit,
    )


def _assert_enabled():
    if not frappe.db.get_single_value("CFG Kanban Settings", "enable_customer_returns"):
        frappe.throw(_("Customer Return workflows are disabled in CFG Kanban Settings"))


def _resolve_site(scan_value):
    from cfg_kanban.services.customer_delivery import _resolve_customer_site
    return _resolve_customer_site(scan_value)


def _eligible_delivery(delivery_session):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    if delivery.state not in ("Delivered", "Closed", "Invoiced"):
        frappe.throw(_("Delivery Note Correction requires an ERP-confirmed customer delivery"))
    if not delivery.delivery_note or frappe.db.get_value(
        "Delivery Note", delivery.delivery_note, "docstatus"
    ) != 1:
        frappe.throw(_("The original Delivery Note must be submitted"))
    return delivery, frappe.get_doc("CFG Kanban Customer Scan Point", delivery.customer_scan_point)


def _validate_free_intake_lines(lines):
    submitted = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    result = []
    for raw in submitted:
        item_code = raw.get("item_code")
        qty = flt(raw.get("claimed_qty"))
        if not item_code and qty <= 0:
            continue
        if not item_code or not frappe.db.exists("Item", item_code):
            frappe.throw(_("Select a valid Item on every return line"))
        if qty <= 0:
            frappe.throw(_("Returned quantity for {0} must be greater than zero").format(item_code))
        stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        _validate_whole_number(stock_uom, qty, item_code)
        batch_no = raw.get("batch_no")
        if batch_no and frappe.db.get_value("Batch", batch_no, "item") != item_code:
            frappe.throw(_("Batch {0} does not belong to Item {1}").format(batch_no, item_code))
        result.append({
            "original_visible_code": (raw.get("original_visible_code") or "").strip(),
            "item_code": item_code, "batch_no": batch_no,
            "expiry_date": raw.get("expiry_date"), "stock_uom": stock_uom,
            "claimed_qty": qty, "received_qty": 0, "accepted_qty": 0,
            "rejected_qty": 0, "condition": _condition(raw.get("condition")),
            "qc_disposition": "Pending", "details": (raw.get("details") or "").strip(),
        })
    if not result:
        frappe.throw(_("Add at least one returned Item and quantity"))
    return result


def _validate_correction_lines(delivery, submitted):
    delivered = {row.name: row for row in _delivered_allocations(delivery.name)}
    result, seen = [], set()
    for raw in submitted:
        allocation = raw.get("original_delivery_allocation")
        qty = flt(raw.get("claimed_qty"))
        if qty <= 0:
            continue
        if allocation in seen or allocation not in delivered:
            frappe.throw(_("Correction line does not belong to the original delivery"))
        seen.add(allocation)
        source = delivered[allocation]
        remaining = flt(source.delivered_qty) - _corrected_qty(source.name)
        _validate_whole_number(source.stock_uom, qty, source.item_code)
        if qty > remaining + 0.000001:
            frappe.throw(_("Correction quantity for {0} exceeds {1}").format(
                source.visible_code, remaining
            ))
        result.append({
            "original_delivery_allocation": source.name,
            "original_delivery_note_item": source.delivery_note_item,
            "original_handling_unit": source.handling_unit,
            "original_visible_code": source.visible_code,
            "item_code": source.item_code, "batch_no": source.batch_no,
            "stock_uom": source.stock_uom, "delivered_qty": flt(source.delivered_qty),
            "claimed_qty": qty, "received_qty": qty, "accepted_qty": qty,
            "rejected_qty": 0, "condition": "Wrong Item or Quantity",
            "qc_disposition": "Accept for Credit",
            "details": (raw.get("details") or "").strip(),
        })
    if not result:
        frappe.throw(_("Enter a correction quantity for at least one delivered line"))
    return result


def _delivered_allocations(delivery_session):
    return frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery_session, "state": "Delivered"},
        fields=["name", "handling_unit", "visible_code", "item_code", "batch_no",
                "stock_uom", "delivered_qty", "delivery_note_item"],
        order_by="reserved_on asc", limit_page_length=500,
    )


def _lock_allocations(submitted):
    for name in sorted({row.get("original_delivery_allocation") for row in submitted
                        if row.get("original_delivery_allocation")}):
        frappe.db.sql(
            "select name from `tabCFG Kanban Delivery Allocation` where name=%s for update", name
        )


def _corrected_qty(delivery_allocation):
    value = frappe.db.sql("""
        select coalesce(sum(line.claimed_qty), 0)
        from `tabCFG Kanban Return Line` line
        inner join `tabCFG Kanban Return Case` parent on parent.name=line.parent
        where line.original_delivery_allocation=%s
          and parent.return_flow='Delivery Note Correction'
          and parent.state not in ('Cancelled', 'Exception')
    """, (delivery_allocation,))[0][0]
    return flt(value)


def _submitted_invoices(delivery_note):
    names = frappe.get_all(
        "Sales Invoice Item", filters={"delivery_note": delivery_note},
        pluck="parent", group_by="parent", limit_page_length=100,
    )
    return [name for name in names if frappe.db.get_value("Sales Invoice", name, "docstatus") == 1]


def _validate_whole_number(uom, qty, item_code):
    if frappe.get_cached_value("UOM", uom, "must_be_whole_number") and abs(qty - round(qty)) > 0.000001:
        frappe.throw(_("Quantity for {0} must be a whole number in {1}").format(item_code, uom))


def _require_accounting_user():
    frappe.only_for(ACCOUNTING_ROLES)


def _require_sales_invoice_create():
    if not frappe.has_permission("Sales Invoice", ptype="create"):
        frappe.throw(_("You need Create permission for Sales Invoice to prepare a credit return"),
                     frappe.PermissionError)


def _assert_accounting_ready(case, allow_selected=False):
    if case.return_flow != "Customer Return for QC":
        frappe.throw(_("Only QC-governed Customer Returns use accounting source selection"))
    allowed_statuses = {"Pending Source Selection"}
    if allow_selected:
        allowed_statuses.update({"Source Selected", "Credit Pending"})
    if case.state != "QC Completed - Accounting Pending" or \
            case.accounting_status not in allowed_statuses or flt(case.accepted_total_qty) <= 0:
        frappe.throw(_("Return Case is not ready for an accounting decision"))


def _accepted_item_totals(case):
    totals = {}
    for row in case.lines:
        qty = flt(row.accepted_qty)
        if qty > 0:
            totals[row.item_code] = totals.get(row.item_code, 0) + qty
    if not totals:
        frappe.throw(_("Return Case has no QC-accepted quantity"))
    return totals


def _validate_accounting_source(case, source_sales_invoice):
    if not source_sales_invoice:
        frappe.throw(_("Select the submitted Sales Invoice used as the credit source"))
    source = frappe.get_doc("Sales Invoice", source_sales_invoice)
    source.check_permission("read")
    if source.docstatus != 1 or source.is_return:
        frappe.throw(_("Credit source must be a submitted, non-return Sales Invoice"))
    if source.company != case.selling_company or source.customer != case.customer:
        frappe.throw(_("Credit source Company and Customer must match the Return Case"))
    available = {}
    for row in source.items:
        available[row.item_code] = available.get(row.item_code, 0) + abs(flt(row.stock_qty))
    returned = _submitted_credit_totals([source.name]).get(source.name, {})
    for item_code in tuple(available):
        available[item_code] = max(
            flt(available[item_code]) - flt(returned.get(item_code)), 0
        )
    for item_code, qty in _accepted_item_totals(case).items():
        if flt(available.get(item_code)) + 0.000001 < qty:
            frappe.throw(_("Sales Invoice {0} does not contain enough {1} for QC-accepted quantity {2}").format(
                source.name, item_code, qty
            ))
    return source


def _submitted_credit_totals(source_invoices):
    if not source_invoices:
        return {}
    placeholders = ", ".join(["%s"] * len(source_invoices))
    rows = frappe.db.sql(
        f"""
        select invoice.return_against, item.item_code, sum(abs(item.stock_qty)) as returned_qty
        from `tabSales Invoice` invoice
        inner join `tabSales Invoice Item` item on item.parent=invoice.name
        where invoice.docstatus=1 and invoice.is_return=1
          and invoice.return_against in ({placeholders})
        group by invoice.return_against, item.item_code
        """,
        tuple(source_invoices), as_dict=True,
    )
    totals = {}
    for row in rows:
        totals.setdefault(row.return_against, {})[row.item_code] = flt(row.returned_qty)
    return totals


def _condition(value):
    value = value or "Unknown"
    if value not in CONDITIONS:
        frappe.throw(_("Invalid reported return condition"))
    return value


def _return_case_result(doc, profile=None):
    result = doc.as_dict()
    result["lines"] = [row.as_dict() for row in doc.lines]
    result["can_start_qc"] = bool(
        profile and _qc_allowed(profile) and doc.state == "Awaiting QC Receipt"
    )
    result["can_complete_qc"] = bool(
        profile and _qc_allowed(profile) and doc.state == "QC In Progress"
    )
    return result


def _responsibilities(profile):
    return {row.responsibility for row in profile.responsibilities if row.responsibility}


def _intake_allowed(profile):
    return bool(_can_view_all(profile) or CUSTOMER_RETURN_RESPONSIBILITY in _responsibilities(profile))


def _qc_allowed(profile):
    return bool(_can_view_all(profile) or CUSTOMER_RETURN_QC_RESPONSIBILITY in _responsibilities(profile))


def _require_intake(profile):
    if not _intake_allowed(profile):
        frappe.throw(_("Operator is not assigned to Customer Return"), frappe.PermissionError)


def _require_qc(profile):
    if not _qc_allowed(profile):
        frappe.throw(_("Operator is not assigned to Customer Return QC"), frappe.PermissionError)


def _can_view_all(profile):
    return bool(profile.kanban_role in ("Supervisor", "Development Proxy")
                and profile.get("view_all_responsibilities"))

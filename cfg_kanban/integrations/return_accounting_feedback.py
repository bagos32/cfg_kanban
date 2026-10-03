"""ERPNext feedback for accountant-controlled customer credit returns."""

import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record


def on_submit(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    _validate_linked_credit(doc, case)
    if case.accounting_status == "Completed" and case.credit_document_status == "Submitted":
        return
    previous_state = case.state
    case.db_set({
        "state": "Accounting Completed",
        "accounting_status": "Completed",
        "credit_document_doctype": "Sales Invoice",
        "credit_document": doc.name,
        "credit_document_status": "Submitted",
    }, update_modified=True)
    record(
        "Customer Credit Return Submitted", return_case=case.name,
        previous_state=previous_state, new_state="Accounting Completed",
        qty=case.accepted_total_qty, reference_doctype="Sales Invoice",
        reference_name=doc.name,
        notes="Accountant submitted the non-stock ERPNext Sales Invoice Return.",
    )


def on_cancel(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if case.credit_document and case.credit_document != doc.name:
        frappe.throw("Cancelled Sales Invoice Return does not match the Return Case credit document")
    previous_state = case.state
    case.db_set({
        "state": "QC Completed - Accounting Pending",
        "accounting_status": "Source Selected",
        "credit_document_doctype": "Sales Invoice",
        "credit_document": doc.name,
        "credit_document_status": "Cancelled",
        "accounting_revision": int(case.accounting_revision or 0) + 1,
    }, update_modified=True)
    record(
        "Customer Credit Return Cancelled", return_case=case.name,
        previous_state=previous_state, new_state="QC Completed - Accounting Pending",
        qty=case.accepted_total_qty, reference_doctype="Sales Invoice",
        reference_name=doc.name,
        notes="Cancelled credit return requires accountant review and a controlled replacement draft.",
    )


def _validate_linked_credit(doc, case):
    if case.return_flow != "Customer Return for QC":
        frappe.throw("Sales Invoice Return is linked to an incompatible CFG Kanban Return Case")
    if not doc.is_return or not doc.return_against:
        frappe.throw("CFG Kanban customer credit document must be a Sales Invoice Return")
    if doc.company != case.selling_company or doc.customer != case.customer:
        frappe.throw("Sales Invoice Return Company and Customer must match the Return Case")
    if doc.return_against != case.accounting_reference:
        frappe.throw("Sales Invoice Return source does not match the approved accounting source")
    if int(doc.update_stock or 0):
        frappe.throw("CFG Kanban customer credit return must not update stock; physical custody is separate")
    if case.credit_document and case.credit_document != doc.name:
        frappe.throw("Return Case is already linked to another credit document")
    expected = _accepted_totals(case)
    actual = {}
    for row in doc.items:
        actual[row.item_code] = actual.get(row.item_code, 0) + abs(flt(row.stock_qty or row.qty))
    if set(actual) != set(expected) or any(
        abs(flt(actual.get(item_code)) - qty) > 0.000001
        for item_code, qty in expected.items()
    ):
        frappe.throw("Sales Invoice Return item quantities must exactly match the QC-accepted quantities")


def _accepted_totals(case):
    totals = {}
    for row in case.lines:
        qty = flt(row.accepted_qty)
        if qty > 0:
            totals[row.item_code] = totals.get(row.item_code, 0) + qty
    if not totals:
        frappe.throw("Return Case has no QC-accepted quantity")
    return totals

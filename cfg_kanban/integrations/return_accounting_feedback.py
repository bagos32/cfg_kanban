"""ERPNext feedback for accountant-controlled customer credit returns."""
from math import isfinite

import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record


def on_submit(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    frappe.db.sql("select name from `tabCFG Kanban Return Case` where name=%s for update", return_case)
    case = frappe.get_doc("CFG Kanban Return Case", return_case, for_update=True)
    _validate_linked_credit(doc, case)
    custom = case.get("credit_document_doctype") == "Credit Note"
    if (case.accounting_status == "Completed" and
            (case.get("accounting_sales_invoice") or case.credit_document) == doc.name):
        return
    previous_state = case.state
    new_state = "Closed" if case.disposition_status == "Completed" else "Accounting Completed"
    values = {"state": new_state, "accounting_status": "Completed",
              "accounting_sales_invoice": doc.name, "accounting_sales_invoice_status": "Submitted"}
    if not custom:
        values.update(credit_document_doctype="Sales Invoice", credit_document=doc.name,
                      credit_document_status="Submitted")
    case.db_set(values, update_modified=True)
    record("Customer Credit Return Submitted", return_case=case.name,
        previous_state=previous_state, new_state=new_state, qty=case.accepted_total_qty,
        reference_doctype="Sales Invoice", reference_name=doc.name,
        notes="Accountant submitted the non-stock ERPNext Sales Invoice Return.")


def on_cancel(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    frappe.db.sql("select name from `tabCFG Kanban Return Case` where name=%s for update", return_case)
    case = frappe.get_doc("CFG Kanban Return Case", return_case, for_update=True)
    custom = case.get("credit_document_doctype") == "Credit Note"
    if custom:
        if (doc.get("return_against_credit_note") != case.credit_document or
                (case.get("accounting_sales_invoice") and case.accounting_sales_invoice != doc.name)):
            frappe.throw("Cancelled Sales Invoice Return does not match the Return Case Credit Note")
    elif case.credit_document and case.credit_document != doc.name:
        frappe.throw("Cancelled Sales Invoice Return does not match the Return Case credit document")
    previous_state = case.state
    values = {"state": "QC Completed - Accounting Pending",
              "accounting_status": "Credit Pending" if custom else "Source Selected",
              "accounting_sales_invoice": doc.name, "accounting_sales_invoice_status": "Cancelled"}
    if not custom:
        values.update(credit_document_doctype="Sales Invoice", credit_document=doc.name,
                      credit_document_status="Cancelled", accounting_revision=int(case.accounting_revision or 0) + 1)
    case.db_set(values, update_modified=True)
    record("Customer Credit Return Cancelled", return_case=case.name,
        previous_state=previous_state, new_state="QC Completed - Accounting Pending",
        qty=case.accepted_total_qty, reference_doctype="Sales Invoice", reference_name=doc.name,
        notes="Cancelled credit return requires accountant review and a controlled replacement draft.")


def _validate_linked_credit(doc, case):
    if case.return_flow != "Customer Return for QC":
        frappe.throw("Sales Invoice Return is linked to an incompatible CFG Kanban Return Case")
    if not doc.is_return or not doc.return_against:
        frappe.throw("CFG Kanban customer credit document must be a Sales Invoice Return or Credit Note")
    if doc.company != case.selling_company or doc.customer != case.customer:
        frappe.throw("Credit document Company and Customer must match the Return Case")
    if doc.return_against != case.accounting_reference:
        frappe.throw("Credit document source does not match the approved accounting source")
    if int(doc.get("update_stock") or 0):
        frappe.throw("CFG Kanban customer credit return must not update stock; physical custody is separate")
    kind = doc.get("doctype") or "Sales Invoice"
    primary = case.get("credit_document_doctype") or "Sales Invoice"
    if primary == "Credit Note" and kind == "Sales Invoice":
        if doc.get("return_against_credit_note") != case.credit_document:
            frappe.throw("Sales Invoice Return must reference the exact approved Credit Note")
        note = frappe.get_doc("Credit Note", case.credit_document)
        if note.docstatus != 1 or note.get("cfg_return_case") != case.name:
            frappe.throw("Sales Invoice Return requires its submitted Kanban Credit Note")
        linked = case.get("accounting_sales_invoice")
        if linked and linked != doc.name:
            if (frappe.db.get_value("Sales Invoice", linked, "docstatus") != 2 or
                    doc.get("amended_from") != linked):
                frappe.throw("Return Case is already linked to another accounting Sales Invoice Return")
    elif kind != primary or (case.credit_document and case.credit_document != doc.name):
        frappe.throw("Return Case is already linked to another credit document")
    expected = _accepted_totals(case)
    units = {row.item_code: row.stock_uom for row in case.lines if flt(row.accepted_qty) > 0}
    actual = {}
    for row in doc.items:
        qty = flt(row.qty)
        factor = flt(row.get("conversion_factor") or 1)
        stock_qty = flt(row.stock_qty or qty * factor)
        if (not all(isfinite(value) for value in (qty, factor, stock_qty)) or
                qty >= 0 or factor <= 0 or stock_qty >= 0 or abs(stock_qty - qty * factor) > 0.000001):
            frappe.throw("Credit quantities must be negative with matching stock-UOM conversion")
        if units.get(row.item_code) and row.get("stock_uom") != units[row.item_code]:
            frappe.throw("Credit item stock UOM must match the QC-accepted UOM")
        actual[row.item_code] = actual.get(row.item_code, 0) + abs(stock_qty)
    if set(actual) != set(expected) or any(
        abs(flt(actual.get(item_code)) - qty) > 0.000001 for item_code, qty in expected.items()
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

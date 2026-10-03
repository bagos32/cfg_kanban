"""ERPNext Stock Entry feedback for accepted customer return disposition."""

import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record


RECEIPT_DISPOSITIONS = {
    "Receive to Quarantine", "Receive for Rework", "Return to Available Stock",
}


def validate(doc):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if case.return_flow != "Customer Return for QC" or not case.qc_completed_on:
        frappe.throw("Stock Entry is linked to an incompatible Customer Return Case")
    if doc.stock_entry_type != "Material Receipt":
        frappe.throw("Accepted customer returns must use a Material Receipt Stock Entry")
    if doc.company != case.selling_company:
        frappe.throw("Return Material Receipt Company must match the Return Case")
    if case.stock_disposition_entry and case.stock_disposition_entry != doc.name:
        frappe.throw("Return Case is already linked to another Material Receipt")
    expected = {
        row.name: row for row in case.disposition_lines
        if row.disposition in RECEIPT_DISPOSITIONS
    }
    seen = set()
    for item in doc.items:
        line_name = item.get("cfg_return_disposition_line")
        line = expected.get(line_name)
        if not line or line_name in seen:
            frappe.throw("Material Receipt contains a row outside the controlled disposition")
        seen.add(line_name)
        if item.item_code != line.item_code:
            frappe.throw("Material Receipt Item cannot differ from the disposition decision")
        if item.t_warehouse != line.target_warehouse:
            frappe.throw("Material Receipt target Warehouse cannot differ from the disposition decision")
        if abs(flt(item.qty) - flt(line.qty)) > 0.000001:
            frappe.throw("Material Receipt quantity cannot differ from the disposition decision")
        if line.batch_no and item.batch_no and item.batch_no != line.batch_no:
            frappe.throw("Material Receipt Batch cannot differ from the return intake snapshot")
        if abs(flt(item.basic_rate) - flt(line.valuation_rate)) > 0.000001:
            frappe.throw("Material Receipt Valuation Rate cannot differ from the approved disposition")
    if seen != set(expected):
        frappe.throw("Material Receipt must retain every stock-receipt disposition row")


def on_submit(doc):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    validate(doc)
    previous_state = case.state
    for row in case.disposition_lines:
        status = "Posted" if row.disposition in RECEIPT_DISPOSITIONS else "Disposed"
        row.db_set("status", status, update_modified=False)
    new_state = _combined_state(case, disposition_complete=True)
    case.db_set({
        "state": new_state,
        "disposition_status": "Completed",
        "stock_disposition_entry": doc.name,
        "stock_disposition_entry_status": "Submitted",
    }, update_modified=True)
    record(
        "Customer Return Stock Disposition Posted", return_case=case.name,
        previous_state=previous_state, new_state=new_state,
        qty=sum(flt(row.qty) for row in case.disposition_lines
                if row.disposition in RECEIPT_DISPOSITIONS),
        reference_doctype="Stock Entry", reference_name=doc.name,
        notes="Submitted ERPNext Material Receipt confirmed accepted return stock disposition.",
    )


def on_cancel(doc):
    return_case = doc.get("cfg_return_case")
    if not return_case:
        return
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    if case.stock_disposition_entry and case.stock_disposition_entry != doc.name:
        frappe.throw("Cancelled Material Receipt does not match the Return Case")
    previous_state = case.state
    for row in case.disposition_lines:
        status = "Cancelled" if row.disposition in RECEIPT_DISPOSITIONS else "Decision Recorded"
        row.db_set("status", status, update_modified=False)
    new_state = _combined_state(case, disposition_complete=False)
    case.db_set({
        "state": new_state,
        "disposition_status": "Decision Recorded",
        "stock_disposition_entry": doc.name,
        "stock_disposition_entry_status": "Cancelled",
        "disposition_revision": int(case.disposition_revision or 0) + 1,
    }, update_modified=True)
    record(
        "Customer Return Material Receipt Cancelled", return_case=case.name,
        previous_state=previous_state, new_state=new_state,
        qty=sum(flt(row.qty) for row in case.disposition_lines
                if row.disposition in RECEIPT_DISPOSITIONS),
        reference_doctype="Stock Entry", reference_name=doc.name,
        notes="Cancelled Material Receipt requires a controlled replacement disposition.",
    )


def _combined_state(case, disposition_complete):
    accounting_complete = case.accounting_status in ("Completed", "No Credit Approved")
    if accounting_complete and disposition_complete:
        return "Closed"
    if accounting_complete:
        return "Accounting Completed"
    return "QC Completed - Accounting Pending"

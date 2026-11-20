"""Optional adapter for the site's Credit Note -> Sales Invoice Return workflow.

Credit Note is owned by the site's custom app. Core never imports its controller
or creates that DocType; native controllers still calculate, name and post records.
"""
import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record

NOTE = 'Credit Note'
CASE = 'CFG Kanban Return Case'
SYSTEM_FIELDS = {'name', 'doctype', 'owner', 'creation', 'modified', 'modified_by',
    'docstatus', 'idx', 'parent', 'parentfield', 'parenttype', 'amended_from',
    'naming_series', 'status', 'workflow_state', 'return_against_credit_note',
    'cfg_return_case', 'cfg_scan_event'}
LAYOUT_FIELDS = {'Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Image', 'Fold'}


def available():
    if not frappe.db.exists('DocType', NOTE):
        return False
    meta = frappe.get_meta(NOTE)
    return bool(meta.has_field('cfg_return_case') and meta.has_field('cfg_scan_event')
        and frappe.has_permission(NOTE, ptype='create')
        and frappe.has_permission(NOTE, ptype='read'))


def assert_available():
    if not frappe.db.exists('DocType', NOTE):
        frappe.throw('The optional Credit Note DocType is not installed on this site')
    meta = frappe.get_meta(NOTE)
    required = ('company', 'customer', 'is_return', 'return_against', 'items',
                'cfg_return_case', 'cfg_scan_event')
    if not meta.is_submittable or any(not meta.has_field(field) for field in required):
        frappe.throw('Credit Note schema/traceability is incomplete; migrate CFG Kanban and review the custom DocType')
    field = meta.get_field('items')
    item = frappe.get_meta(field.options)
    if field.fieldtype != 'Table' or any(not item.has_field(name) for name in
            ('item_code', 'qty', 'uom', 'stock_uom', 'conversion_factor', 'stock_qty', 'sales_invoice_item')):
        frappe.throw('Credit Note Item must support exact source rows, UOM and stock quantities')
    reference = frappe.get_meta('Sales Invoice').get_field('return_against_credit_note')
    if not reference or reference.fieldtype != 'Link' or reference.options != NOTE:
        frappe.throw('Sales Invoice requires its native custom-app Return Against Credit Note link')
    if not frappe.has_permission(NOTE, ptype='create') or not frappe.has_permission(NOTE, ptype='read'):
        frappe.throw('You need Read and Create permission for Credit Note', frappe.PermissionError)


def build_draft(mapped_return, source_invoice=None):
    """Copy compatible business fields from the QC-trimmed native return mapper."""
    assert_available()
    if source_invoice:
        _validate_source_rows(mapped_return, source_invoice)
    target = frappe.new_doc(NOTE)
    for field in target.meta.fields:
        name = field.fieldname
        if name in SYSTEM_FIELDS or name.startswith('_') or field.fieldtype in LAYOUT_FIELDS:
            continue
        source = mapped_return.meta.get_field(name)
        if not source or source.fieldtype != field.fieldtype:
            continue
        value = mapped_return.get(name)
        if field.fieldtype == 'Table':
            if source.options != field.options and name != 'items' and value:
                frappe.throw('Credit Note table '+name+' is incompatible with the native Sales Invoice Return')
            child = frappe.get_meta(field.options)
            fields = [row.fieldname for row in child.fields
                      if row.fieldname not in SYSTEM_FIELDS and row.fieldtype not in LAYOUT_FIELDS]
            target.set(name, [{key: row.get(key) for key in fields if key in row.as_dict()}
                              for row in value or []])
        elif value is not None:
            target.set(name, value)
    target.is_return = 1
    target.return_against = mapped_return.return_against
    if target.meta.has_field('update_stock'):
        target.update_stock = 0
    return target


def _locked_case(name):
    frappe.db.sql('select name from `tabCFG Kanban Return Case` where name=%s for update', name)
    return frappe.get_doc(CASE, name, for_update=True)


def _case_for_note(doc):
    name = doc.get('cfg_return_case')
    if not name:
        return None
    case = _locked_case(name)
    if case.credit_document_doctype != NOTE or case.credit_document != doc.name:
        frappe.throw('Credit Note does not match the approved Return Case accounting document')
    return case


def _invoices(note, active_only=True):
    filters = {'return_against_credit_note': note}
    if active_only:
        filters['docstatus'] = ['<', 2]
    return frappe.get_all('Sales Invoice', filters=filters,
        fields=['name', 'docstatus'], order_by='name asc', limit_page_length=0)


def _validate(doc, case):
    from cfg_kanban.integrations.return_accounting_feedback import _validate_linked_credit
    _validate_linked_credit(doc, case)


def _validate_source_rows(credit, source):
    for row in credit.items:
        matches = [item for item in source.items if item.item_code == row.item_code and item.uom == row.uom]
        if len(matches) != 1:
            frappe.throw('The custom Credit Note controller cannot distinguish repeated Item/UOM or missing source rows; use the standard Sales Invoice Return for this source')
        original = matches[0]
        if (row.get('sales_invoice_item') != original.name or row.stock_uom != original.stock_uom or
                abs(flt(row.conversion_factor) - flt(original.conversion_factor)) > 0.000001):
            frappe.throw('Credit Note item source row and UOM conversion must match the approved Sales Invoice')


def before_submit(doc, method=None):
    case = _case_for_note(doc)
    if not case:
        return
    _validate(doc, case)
    if _invoices(doc.name):
        frappe.throw('This Credit Note already has an active Sales Invoice Return; review it instead of creating another')
    source = frappe.get_doc('Sales Invoice', case.accounting_reference)
    if source.docstatus != 1 or source.is_return:
        frappe.throw('Credit Note source must remain a submitted non-return Sales Invoice')
    _validate_source_rows(doc, source)
    from cfg_kanban.integrations.erp_gateway import _remaining_sales_invoice_quantities
    remaining = _remaining_sales_invoice_quantities(source)
    from cfg_kanban.integrations.return_accounting_feedback import _accepted_totals
    if any(qty > flt(remaining.get(code)) + 0.000001 for code, qty in _accepted_totals(case).items()):
        frappe.throw('The source Sales Invoice no longer covers these QC-accepted credit quantities')


def bind_invoice(doc, method=None):
    """Bind a native return produced by the custom controller, using its exact Link."""
    note_name = doc.get('return_against_credit_note')
    if not note_name or not frappe.db.exists('DocType', NOTE):
        return
    note = frappe.get_doc(NOTE, note_name)
    if not note.get('cfg_return_case'):
        return
    case = _case_for_note(note)
    if note.docstatus != 1:
        frappe.throw('Submit the approved Credit Note before creating its linked Sales Invoice Return')
    if doc.get('cfg_return_case') and doc.cfg_return_case != case.name:
        frappe.throw('Sales Invoice Return and Credit Note belong to different Return Cases')
    if any(row.name != doc.name for row in _invoices(note.name)):
        frappe.throw('This Credit Note already has another active Sales Invoice Return')
    doc.cfg_return_case = case.name
    doc.cfg_scan_event = note.cfg_scan_event
    _validate(doc, case)


def on_submit(doc, method=None):
    case = _case_for_note(doc)
    if not case:
        return
    _validate(doc, case)
    invoices = _invoices(doc.name)
    if len(invoices) != 1:
        frappe.throw('The custom Credit Note controller must create exactly one Sales Invoice Return linked by Return Against Credit Note')
    invoice = frappe.get_doc('Sales Invoice', invoices[0].name)
    if invoice.get('cfg_return_case') != case.name:
        frappe.throw('Generated Sales Invoice Return is missing its Kanban Return Case; review the custom mapper and migrate CFG Kanban')
    _validate(invoice, case)
    case.db_set({'credit_document_status': 'Submitted',
        'accounting_sales_invoice': invoice.name,
        'accounting_sales_invoice_status': 'Submitted' if invoice.docstatus == 1 else 'Draft'}, update_modified=True)
    record('Custom Credit Note Submitted', return_case=case.name,
        reference_doctype=NOTE, reference_name=doc.name,
        notes='Custom controller created Sales Invoice Return '+invoice.name+
              '; accounting completes only on native invoice submission.')


def before_cancel(doc, method=None):
    case = _case_for_note(doc)
    if case and _invoices(doc.name):
        frappe.throw('Cancel the linked submitted Sales Invoice Return, or discard its Draft in ERPNext, before cancelling Credit Note')


def on_cancel(doc, method=None):
    case = _case_for_note(doc)
    if not case:
        return
    before_cancel(doc)
    if case.credit_document_status == 'Cancelled':
        return
    case.db_set({'state': 'QC Completed - Accounting Pending', 'accounting_status': 'Source Selected',
        'credit_document_status': 'Cancelled',
        'accounting_revision': int(case.accounting_revision or 0) + 1}, update_modified=True)
    record('Custom Credit Note Cancelled', return_case=case.name,
        reference_doctype=NOTE, reference_name=doc.name,
        notes='Accountant may prepare one controlled replacement; original credit history remains.')


def invoice_draft_deleted(doc, method=None):
    """Keep the Case link valid when accounting explicitly discards the generated Draft."""
    if doc.docstatus != 0 or not doc.get('return_against_credit_note') or not doc.get('cfg_return_case'):
        return
    case = _locked_case(doc.cfg_return_case)
    if case.credit_document_doctype != NOTE or case.credit_document != doc.return_against_credit_note:
        frappe.throw('Draft Sales Invoice Return does not match its Return Case Credit Note')
    if case.get('accounting_sales_invoice') == doc.name:
        case.db_set({'accounting_sales_invoice': None, 'accounting_sales_invoice_status': 'Draft Discarded'}, update_modified=True)
    record('Custom Credit Invoice Draft Discarded', return_case=case.name,
        reference_doctype=NOTE, reference_name=case.credit_document,
        notes='Accountant discarded generated Draft '+doc.name+'; no accounting was posted.',
        payload={'discarded_invoice': doc.as_dict()})

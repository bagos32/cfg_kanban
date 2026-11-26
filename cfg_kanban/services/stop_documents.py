"""Durable customer document checklist, over native invoice and mobile print services.

Scheduling never posts stock, maps invoices or renders prints. Execution is a separate
assigned-driver action so a setup failure cannot roll back a completed delivery.
"""
import frappe
from frappe.utils import cint, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once

TASK = 'CFG Kanban Stop Document Task'
SITE = 'CFG Kanban Customer Scan Point'
OPTIONS = ('auto_print_delivery_note', 'auto_create_draft_invoice',
           'auto_print_draft_invoice', 'auto_print_return_note')
DRAFT = 'Create Draft Invoice'
PRINT_DN = 'Print Delivery Note'
PRINT_SI = 'Print Draft Invoice'
PRINT_RETURN = 'Print Return Note'


def policy(trip, stop):
    if not stop.get('customer_scan_point'):
        return {}
    site = frappe.get_doc(SITE, stop.customer_scan_point)
    # This is office configuration, not authority to create/read ERP documents.
    choices = {field: bool(cint(site.get(field))) for field in OPTIONS}
    if any(choices.values()) and (site.selling_company != trip.company or site.customer != stop.customer):
        frappe.throw('Customer document policy belongs to another Company/customer')
    return choices


def _schedule(trip, stop, doctype, name, kind, operator):
    task = frappe.get_doc(dict(doctype=TASK, delivery_trip=trip.name, stop_key=stop.stop_key,
        company=trip.company, customer=stop.customer, customer_scan_point=stop.customer_scan_point,
        source_doctype=doctype, source_name=name, task_type=kind, status='Pending',
        copies=0 if kind == DRAFT else 2, scheduled_on=now_datetime(), scheduled_by=operator.employee))
    task.flags.cfg_stop_documents = True
    task, created = insert_once(task, canonical_key('stop-document', trip.name, stop.stop_key,
        doctype, name, kind), ignore_permissions=True)
    if created:
        record('Customer Stop Document Scheduled', reference_doctype=TASK,
            reference_name=task.name, operator=operator.employee, system_generated=True,
            payload=dict(task_type=kind, source_doctype=doctype, source_name=name, copies=task.copies))
    return task.name


def schedule_delivery(trip, stop, operator):
    choices = policy(trip, stop)
    if not any(choices.get(field) for field in OPTIONS[:3]):
        return []
    from cfg_kanban.services import mobile_printing as printing
    names = []
    for session in printing._sessions(trip, stop, operator):
        if not session.delivery_note:
            continue
        note = printing.delivery_note(trip, stop, session.delivery_note, operator)
        if note.docstatus != 1:
            continue
        for enabled, kind in [(choices['auto_print_delivery_note'], PRINT_DN),
                              (choices['auto_create_draft_invoice'], DRAFT),
                              (choices['auto_print_draft_invoice'], PRINT_SI)]:
            if enabled:
                names.append(_schedule(trip, stop, 'Delivery Note', note.name, kind, operator))
    return list(dict.fromkeys(names))


def schedule_return(trip, stop, case_name, operator):
    if not policy(trip, stop).get('auto_print_return_note'):
        return []
    from cfg_kanban.services import mobile_printing as printing
    case = printing.return_case(trip, stop, case_name)
    if case.get('state') == 'Cancelled':
        return []
    return [_schedule(trip, stop, printing.CASE, case.name, PRINT_RETURN, operator)]


def pending_names(trip, stop_key):
    # Completion feedback must not depend on printer permissions/setup. Jobs are
    # resolved only when the separate document panel is opened.
    return frappe.get_all(TASK, filters=dict(delivery_trip=trip.name, company=trip.company,
        stop_key=stop_key, status=['in', ['Pending', 'Prepared']]), pluck='name', limit_page_length=0)


def context(trip, stop_key, operator):
    """Read-only projection; no backfill of old completed customers."""
    result = []
    filters = dict(delivery_trip=trip.name, company=trip.company)
    if stop_key:
        filters['stop_key'] = stop_key
    for row in frappe.get_all(TASK, filters=filters, fields=['name', 'stop_key', 'customer',
            'source_doctype', 'source_name', 'task_type', 'copies', 'status', 'print_job', 'invoice'],
            order_by='scheduled_on, name', limit_page_length=0):
        from cfg_kanban.services import mobile_printing as printing
        stop = printing.saved_stop(trip, row.stop_key)
        if row.customer != stop.customer:
            frappe.throw('Customer document task belongs to another stop', frappe.PermissionError)
        row = dict(row)
        if row.get('print_job'):
            job = printing._read(printing.JOB, row['print_job'])
            row['status'] = job.status
            row['can_resume'] = job.operator == operator.employee and job.delivery_trip == trip.name
        result.append(row)
    order = {DRAFT: 0, PRINT_DN: 1, PRINT_SI: 2, PRINT_RETURN: 3}
    return sorted(result, key=lambda row: order[row['task_type']])


def _invoice(trip, stop, task, operator):
    from cfg_kanban.services import mobile_printing as printing
    # Print-only is independent: it never creates an Invoice implicitly.
    siblings = frappe.get_all(TASK, filters=dict(delivery_trip=trip.name, stop_key=stop.stop_key,
        source_doctype='Delivery Note', source_name=task.source_name, task_type=DRAFT),
        fields=['invoice', 'status'], limit_page_length=0)
    if siblings:
        if not siblings[0].invoice:
            frappe.throw('Create the queued Draft Invoice before printing it')
        names = [siblings[0].invoice]
    else:
        note = printing.delivery_note(trip, stop, task.source_name, operator, current=True)
        names = sorted(printing._invoice_names(note))
    invoices = []
    for name in names:
        invoice = printing._read('Sales Invoice', name)
        if invoice.docstatus == 0 and not cint(invoice.is_return):
            invoices.append(invoice)
    if len(invoices) != 1:
        frappe.throw('Automatic Draft Invoice print requires exactly one linked Draft. '
            'Create/review it in Documents / Print / Invoice or ask the office')
    invoice = invoices[0]
    if invoice.company != trip.company or invoice.customer != stop.customer or cint(invoice.update_stock):
        frappe.throw('Draft Invoice does not match this customer delivery')
    return invoice.name


def run(trip, stop_key, name, operator, session, token):
    """Trip is already locked by perform_driver_action. All native checks remain."""
    from cfg_kanban.services import mobile_printing as printing, mobile_invoicing
    task = frappe.get_doc(TASK, name, for_update=True)
    if task.delivery_trip != trip.name or task.stop_key != stop_key or task.company != trip.company:
        frappe.throw('Document task belongs to another Trip/stop', frappe.PermissionError)
    stop = printing.saved_stop(trip, stop_key)
    if task.customer != stop.customer:
        frappe.throw('Document task belongs to another customer', frappe.PermissionError)
    if task.source_doctype == 'Delivery Note':
        if not stop.get('driver_completed_on'):
            frappe.throw('Complete this customer delivery before preparing its automatic documents')
        printing.delivery_note(trip, stop, task.source_name, operator, current=True)
    else:
        printing.return_case(trip, stop, task.source_name, current=True)
    # A recorded source result wins over a retry, another driver, or later policy changes.
    if task.invoice or task.print_job:
        if task.print_job:
            job = printing._job(trip, task.print_job, operator, current=True)
            if job.status == 'Abandoned':
                frappe.throw('This automatic print was closed. Use a reviewed manual reprint if required')
            return dict(document_task=task.name, print_job=job.name, job_status=job.status)
        invoice = printing._read('Sales Invoice', task.invoice)
        if invoice.company != trip.company or invoice.customer != stop.customer or cint(invoice.is_return) or invoice.docstatus == 2:
            frappe.throw('The recorded Invoice changed or was cancelled; ask the office to review it')
        return dict(document_task=task.name, invoice=invoice.name, docstatus=invoice.docstatus)
    profile = printing.get_profile(trip.company, current=True)
    key = canonical_key('automatic-stop-document', task.name)
    if task.task_type == DRAFT:
        values = dict(delivery_note=task.source_name, profile_version=str(profile.modified),
                      invoice_mode=profile.invoice_mode)
        previous = getattr(frappe.local, 'cfg_mobile_invoice_token', None)
        frappe.local.cfg_mobile_invoice_token = token
        try:
            result = mobile_invoicing.create(trip, stop, values, operator, session, profile, key,
                                             draft_only=True)
        finally:
            frappe.local.cfg_mobile_invoice_token = previous
        if result['docstatus'] != 0:
            frappe.throw('Automatic customer invoicing must remain Draft')
        task.db_set(dict(invoice=result['invoice'], status='Completed'), update_modified=True)
    else:
        doctype, source = task.source_doctype, task.source_name
        if task.task_type == PRINT_SI:
            doctype, source = 'Sales Invoice', _invoice(trip, stop, task, operator)
        # Fixed X2, office-selected native format and dimensions. Device keys never enter ERP.
        result = printing._prepare(trip, stop_key, dict(doctype=doctype, name=source,
            copies=2, print_format=printing.default_format(doctype, profile), no_letterhead=0),
            operator, session, key)
        task.db_set(dict(print_job=result['print_job'], status='Prepared'), update_modified=True)
    record('Customer Stop Document Prepared', reference_doctype=TASK, reference_name=task.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        payload=result, system_generated=False)
    return dict(result, document_task=task.name)


def controlled(doc):
    if not doc.flags.get('cfg_stop_documents'):
        frappe.throw('Customer document tasks are controlled by delivery completion and return collection')


def no_delete():
    frappe.throw('Customer document checklist history cannot be deleted')

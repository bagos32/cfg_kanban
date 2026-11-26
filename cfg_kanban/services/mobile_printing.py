"""Scoped mobile print preparation and operator confirmation; never a printer ACK.

Native Print Formats own document layout. Only hashes and custody/job metadata are
persisted here; HTML, raster bytes and companion-app signing keys are transient.
"""
import hashlib
import json
import math

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

PROFILE = 'CFG Kanban Mobile Print Profile'
JOB = 'CFG Kanban Mobile Print Job'
LABEL = 'CFG Kanban Return Custody Label'
CASE = 'CFG Kanban Return Case'
TRIP = 'CFG Kanban Delivery Trip'
HU = 'CFG Kanban Handling Unit'
FORMAT_FIELDS = {
    'Delivery Note': 'delivery_note_format', 'Sales Invoice': 'sales_invoice_format',
    'Credit Note': 'credit_note_format', CASE: 'return_note_format',
    TRIP: 'trip_stock_format', HU: 'stock_tag_format', LABEL: 'custody_label_format',
}


def _read(doctype, name, current=False, printing=False):
    doc = frappe.get_doc(doctype, name, **({'for_update': True} if current else {}))
    doc.check_permission('read')
    if printing:
        doc.check_permission('print')
    return doc


def controlled_document(doc):
    if not doc.flags.get('cfg_mobile_control'):
        frappe.throw('Use the controlled Driver Route printing action to create this record')


def no_delete():
    frappe.throw('Mobile print and custody history cannot be deleted')


def validate_profile(doc):
    validate_dimensions(doc.printable_width, doc.dpi, doc.paper_width_mm)
    delivery_note_copies(doc)
    if doc.invoice_mode not in ('Disabled', 'Draft', 'Automatic Submission'):
        frappe.throw('Select a supported driver Invoice policy')
    employees = [r.employee for r in doc.get('invoice_operators') or []]
    if len(employees) != len(set(employees)) or (doc.invoice_mode == 'Automatic Submission' and not employees):
        frappe.throw('Automatic submission requires a non-duplicate list of authorized Employees')
    for doctype, field in FORMAT_FIELDS.items():
        if doc.get(field):
            format_doc(doctype, doc.get(field))


def validate_dimensions(width, dpi, paper):
    raw_width, raw_dpi, paper = flt(width), flt(dpi), flt(paper)
    if not all(math.isfinite(v) for v in (raw_width, raw_dpi, paper)) or raw_width != int(raw_width) or raw_dpi != int(raw_dpi):
        frappe.throw('Printable dot width and DPI must be finite whole numbers')
    width, dpi = int(raw_width), int(raw_dpi)
    if width < 128 or width > 2048 or width % 8 or dpi < 100 or dpi > 600 or not math.isfinite(paper) or not 20 <= paper <= 120:
        frappe.throw('Set a valid paper width, DPI and printable dot width (128–2048, divisible by 8)')
    if width / dpi * 25.4 > paper + 0.5:
        frappe.throw('Printable width is wider than the selected paper at this DPI')


def get_profile(company, current=False):
    name = frappe.db.get_value(PROFILE, {'company': company, 'enabled': 1}, 'name')
    if not name:
        frappe.throw('Office setup required: create an enabled CFG Kanban Mobile Print Profile for this Company')
    doc = _read(PROFILE, name, current=current)
    if doc.company != company or not cint(doc.enabled):
        frappe.throw('The Company Mobile Print Profile is no longer enabled')
    return doc


def delivery_note_copies(profile):
    raw = profile.get('delivery_note_copies')
    value = flt(2 if raw in (None, '') else raw)
    if not math.isfinite(value) or value != int(value) or not 1 <= value <= 5:
        frappe.throw('Delivery Note copies must be a whole number from 1 to 5')
    return int(value)


def format_doc(doctype, name):
    if not name or name == 'Standard':
        return None
    # Native Desk permits format selection without granting access to edit/read
    # the format definition. Source-document read/print and Company gates apply
    # before rendering; this helper never returns format HTML to an unscoped API.
    doc = frappe.get_doc('Print Format', name)
    if doc.doc_type != doctype or cint(doc.disabled) or cint(doc.raw_printing):
        frappe.throw('Select an enabled, non-raw ERPNext Print Format for this exact DocType')
    return doc


def default_format(doctype, profile):
    return (profile.get(FORMAT_FIELDS[doctype])
            or frappe.get_meta(doctype).get('default_print_format') or 'Standard')


def saved_stop(trip, key):
    stop = next((r for r in trip.stops if r.stop_key == key), None)
    if not stop:
        frappe.throw('Select an exact saved customer stop on this Trip')
    _read('Customer', stop.customer)
    return stop


def _sessions(trip, stop, operator):
    from cfg_kanban.services import trip_sales
    from cfg_kanban.services.customer_delivery import _can_view_delivery
    result = []
    for link in trip.dispatch_plans:
        if link.stop_key != stop.stop_key:
            continue
        plan = _read('CFG Kanban Dispatch Plan', link.dispatch_plan)
        if plan.company != trip.company or plan.customer != stop.customer:
            frappe.throw('Dispatch Plan no longer matches this Trip customer')
        if plan.delivery_session:
            session = _read('CFG Kanban Delivery Session', plan.delivery_session)
            if (session.dispatch_plan != plan.name or session.selling_company != trip.company
                    or session.customer != stop.customer or not _can_view_delivery(operator, session)):
                frappe.throw('Delivery Session does not belong to this Trip stop', frappe.PermissionError)
            result.append(session)
    if stop.stop_purpose == 'Visit Only' and trip.get('open_route_plan'):
        session = trip_sales.session(trip, stop, operator)
        if session:
            result.append(session)
    return result


def delivery_note(trip, stop, name, operator, current=False):
    sources = {s.delivery_note for s in _sessions(trip, stop, operator) if s.delivery_note}
    if name not in sources:
        frappe.throw('Delivery Note does not belong to this exact Trip stop', frappe.PermissionError)
    doc = _read('Delivery Note', name, current=current)
    if doc.company != trip.company or doc.customer != stop.customer or cint(doc.is_return):
        frappe.throw('Delivery Note does not match this Trip Company/customer')
    return doc


def return_case(trip, stop, name, current=False):
    doc = _read(CASE, name, current=current)
    if (doc.driver_trip != trip.name or doc.driver_stop_key != stop.stop_key
            or doc.selling_company != trip.company or doc.customer != stop.customer):
        frappe.throw('Return Case does not belong to this exact Trip stop', frappe.PermissionError)
    return doc


def _invoice_names(note):
    return {r.parent for r in frappe.db.sql('''SELECT DISTINCT i.parent
        FROM `tabSales Invoice Item` i INNER JOIN `tabSales Invoice` p ON p.name=i.parent
        WHERE p.docstatus<2 AND p.is_return=0 AND (i.delivery_note=%s OR i.dn_detail IN
        (SELECT name FROM `tabDelivery Note Item` WHERE parent=%s))''',
        (note.name, note.name), as_dict=True)} | {
            r.against_sales_invoice for r in note.items if r.get('against_sales_invoice')}


def _catalog(trip, stop_key, operator):
    """Discover only documents with explicit source links; no customer-wide invoice search."""
    entries = {}
    def add(doctype, name, label=None):
        if not name or not frappe.has_permission(doctype, 'read', doc=name) or not frappe.has_permission(doctype, 'print', doc=name):
            return
        doc = _read(doctype, name, printing=True)
        company = doc.get('company') or doc.get('selling_company') or doc.get('inventory_company')
        if company and company != trip.company:
            frappe.throw('Print source belongs to another Company', frappe.PermissionError)
        if doc.get('docstatus') == 2:
            return
        entries[(doctype, name)] = dict(doctype=doctype, name=name, label=label or doctype,
                                       docstatus=cint(doc.get('docstatus')),
                                       scan_code=('CFG:RETURN-CUSTODY:'+doc.name) if doctype == LABEL else (doc.get('handling_unit_id') or doc.name))
    add(TRIP, trip.name, 'Current lorry stock list')
    if not stop_key and trip.get('follow_on_of'):
        from cfg_kanban.services.return_custody import cases
        for case in cases(trip,history=False):
            add(CASE,case.name,'Carried customer return / pending QC')
            for label in frappe.get_list(LABEL,filters={'return_case':case.name},pluck='name',limit_page_length=0):
                add(LABEL,label,'Original return custody label')
    stops = [saved_stop(trip, stop_key)] if stop_key else [saved_stop(trip, r.stop_key) for r in trip.stops]
    for stop in stops:
        notes = []
        for session in _sessions(trip, stop, operator):
            if session.delivery_note:
                note = delivery_note(trip, stop, session.delivery_note, operator)
                notes.append(note)
                add('Delivery Note', note.name)
                for name in sorted(_invoice_names(note)):
                    invoice = _read('Sales Invoice', name) if frappe.has_permission('Sales Invoice', 'read', doc=name) else None
                    if invoice and (invoice.company != trip.company or invoice.customer != stop.customer):
                        frappe.throw('Linked Invoice does not match this Trip customer')
                    if invoice:
                        add('Sales Invoice', name, 'Sales Invoice')
        for name in frappe.get_list(CASE, filters={'driver_trip': trip.name, 'driver_stop_key': stop.stop_key},
                                    pluck='name', limit_page_length=0):
            case = return_case(trip, stop, name)
            add(CASE, name, 'Temporary Return Note / QC custody')
            for doctype, ref in [('Delivery Note', case.correction_return_delivery_note),
                                 (case.credit_document_doctype, case.credit_document),
                                 ('Sales Invoice', case.accounting_sales_invoice)]:
                if doctype in ('Delivery Note', 'Sales Invoice', 'Credit Note') and ref:
                    doc = _read(doctype, ref) if frappe.has_permission(doctype, 'read', doc=ref) else None
                    if doc and (doc.company != trip.company or doc.customer != stop.customer):
                        frappe.throw('Return accounting document does not match this customer')
                    if doc:
                        add(doctype, ref, 'Return / Credit document')
            for label in frappe.get_list(LABEL, filters={'return_case': case.name}, pluck='name', limit_page_length=0):
                add(LABEL, label, 'Return custody label')
        # Existing tags retain their own identity; printing cannot activate a blank tag.
        for session in _sessions(trip, stop, operator):
            for unit in frappe.get_all('CFG Kanban Delivery Allocation', filters={'delivery_session': session.name},
                                       pluck='handling_unit', limit_page_length=0):
                if unit:
                    add(HU, unit, 'Existing Stock Tag (current identity)')
    return list(entries.values())


def _formats(doctype):
    names = frappe.get_all('Print Format', filters={'doc_type': doctype, 'disabled': 0, 'raw_printing': 0},
                            pluck='name', order_by='name', limit_page_length=0)
    return ['Standard'] + names


def _custody_lines(trip, stop):
    rows = []
    if not stop:
        return rows
    for name in frappe.get_list(CASE, filters={'driver_trip': trip.name, 'driver_stop_key': stop.stop_key,
            'state': 'Awaiting QC Receipt', 'stock_already_owned': 0}, pluck='name', limit_page_length=0):
        case = return_case(trip, stop, name)
        if not case.collected_on:
            continue
        labels = frappe.get_all(LABEL, filters={'return_case': name}, fields=['return_line', 'qty'], limit_page_length=0)
        for row in case.lines:
            remaining = flt(row.claimed_qty) - sum(flt(label.qty) for label in labels if label.return_line == row.name)
            if remaining > 0.000001:
                rows.append(dict(return_case=name, return_line=row.name, item_code=row.item_code,
                    batch_no=row.batch_no, expiry_date=row.expiry_date, stock_uom=row.stock_uom, remaining_qty=remaining))
    return rows


@frappe.whitelist()
def get_mobile_print_context(trip_name, operator_session_token, stop_key=None):
    from cfg_kanban.services import driver_routes, driver_route_actions
    operator, session = driver_routes._access(operator_session_token, 1)
    trip = driver_routes._trip(trip_name, operator)
    stop = saved_stop(trip, stop_key) if stop_key else None
    profile = get_profile(trip.company)
    entries = _catalog(trip, stop_key, operator)
    for entry in entries:
        entry['formats'] = _formats(entry['doctype'])
        entry['default_copies'] = delivery_note_copies(profile) if entry['doctype'] == 'Delivery Note' else 1
        chosen = default_format(entry['doctype'], profile)
        entry['default_format'] = chosen if chosen in entry['formats'] else 'Standard'
    invoice_sources = []
    if stop and profile.invoice_mode != 'Disabled' and frappe.has_permission('Sales Invoice', ptype='create'):
        for delivery in _sessions(trip, stop, operator):
            if delivery.delivery_note:
                note = delivery_note(trip, stop, delivery.delivery_note, operator)
                if note.docstatus == 1:
                    invoice_sources.append(note.name)
    return dict(trip=trip.name, stop_key=stop_key, company=trip.company,
        revision=cint(trip.driver_route_revision), scope_hash=driver_route_actions._core(trip),
        profile=profile.name, profile_version=str(profile.modified), defaults=dict(paper_width_mm=profile.paper_width_mm, printable_width=profile.printable_width,
            dpi=profile.dpi), documents=entries, invoice_sources=invoice_sources, invoice_mode=profile.invoice_mode,
        custody_lines=_custody_lines(trip, stop),
        active_jobs=_unfinished_jobs(trip, stop_key, operator, entries),
        stop_documents=_stop_documents(trip, stop_key, operator))


def _stop_documents(trip, stop_key, operator):
    from cfg_kanban.services.stop_documents import context
    return context(trip, stop_key, operator)


def _unfinished_jobs(trip, stop_key, operator, entries):
    """Expose document-wide blockers without granting another actor's print authority."""
    fields = ['name', 'delivery_trip', 'company', 'operator', 'document_type',
              'document_name', 'status', 'stop_key']
    filters = {'company': trip.company, 'status': ['in', ['Prepared', 'Awaiting Confirmation']]}
    own = frappe.get_list(JOB, filters={**filters, 'delivery_trip': trip.name,
        'operator': operator.employee}, fields=fields, order_by='creation desc', limit_page_length=0)
    result = {r.name: r for r in own if (r.stop_key or None) == (stop_key or None)}
    sources = {(r['doctype'], r['name']) for r in entries}
    if sources:
        blockers = frappe.get_list(JOB, filters={**filters,
            'document_type': ['in', sorted({dt for dt, name in sources})],
            'document_name': ['in', sorted({name for dt, name in sources})]},
            fields=fields, order_by='creation desc', limit_page_length=0)
        for row in blockers:
            if (row.document_type, row.document_name) in sources:
                result[row.name] = row
    for row in result.values():
        row['can_resume'] = row.delivery_trip == trip.name and row.operator == operator.employee
    return list(result.values())


@frappe.whitelist()
def get_driver_invoice_requirements(trip_name, stop_key, delivery_note, operator_session_token):
    from cfg_kanban.services import driver_routes, mobile_invoicing
    operator, session = driver_routes._access(operator_session_token, 1)
    trip = driver_routes._trip(trip_name, operator)
    return mobile_invoicing.requirements(trip, saved_stop(trip, stop_key), delivery_note, operator, get_profile(trip.company))


def _source(trip, stop_key, operator, doctype, name):
    if not any(r['doctype'] == doctype and r['name'] == name for r in _catalog(trip, stop_key, operator)):
        frappe.throw('Print document is not available on this Trip/stop', frappe.PermissionError)
    doc = _read(doctype, name, printing=True)
    _source_scope(trip, stop_key, doc)
    return doc


def _source_scope(trip, stop_key, doc):
    company = doc.get('company') or doc.get('selling_company') or doc.get('inventory_company')
    if company and company != trip.company:
        frappe.throw('Print document belongs to another Company', frappe.PermissionError)
    if stop_key and doc.doctype in ('Delivery Note', 'Sales Invoice', 'Credit Note', CASE):
        if doc.customer != saved_stop(trip, stop_key).customer:
            frappe.throw('Print document belongs to another customer stop', frappe.PermissionError)


def _render(doc, format_name, no_letterhead, prepared_on=None):
    acknowledgement = None
    if (doc.doctype == 'Delivery Note' and not cint(doc.get('is_return'))
            and get_profile(doc.company).get('require_dn_print_signature') not in (0, '0')):
        from cfg_kanban.services.delivery_note_printing import delivery_note_acknowledgement
        acknowledgement = delivery_note_acknowledgement(doc)
        if not acknowledgement or not acknowledgement['signatures']:
            frappe.throw('Capture and submit the customer signature before printing the signed Delivery Note copies')
    fmt = format_doc(doc.doctype, format_name)
    doc.flags.cfg_mobile_print_on = prepared_on
    html = frappe.get_print(doc.doctype, doc.name, print_format=format_name, doc=doc,
                            as_pdf=False, no_letterhead=cint(no_letterhead))
    if acknowledgement:
        _assert_printed_signatures(html, acknowledgement)
    version = canonical_key('native-print-format', str(fmt.modified) if fmt else 'Standard',
        doc.doctype)
    return html, version, hashlib.sha256(html.encode()).hexdigest()


def _assert_printed_signatures(html, acknowledgement):
    from html.parser import HTMLParser
    class Images(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = set()
        def handle_starttag(self, tag, attrs):
            if tag.lower() == 'img':
                self.sources.add(dict(attrs).get('src'))
    parser = Images()
    parser.feed(html)
    if any(row['src'] not in parser.sources for row in acknowledgement['signatures']):
        frappe.throw('Selected Delivery Note Print Format omits the captured signature. '
            'Select CFG Delivery Note 80mm or add its delivery_note_acknowledgement footer to the custom format')


def _prepare(trip, stop_key, values, operator, session, key):
    doc = _source(trip, stop_key, operator, values.get('doctype'), values.get('name'))
    doc = _read(doc.doctype, doc.name, current=True, printing=True)
    _source_scope(trip, stop_key, doc)
    unfinished = frappe.db.sql('''SELECT name FROM `tabCFG Kanban Mobile Print Job`
        WHERE document_type=%s AND document_name=%s
        AND status IN ('Prepared', 'Awaiting Confirmation') LIMIT 1 FOR UPDATE''',
        (doc.doctype, doc.name), as_dict=True)
    if unfinished:
        frappe.throw('This document has an unfinished print job: ' + unfinished[0].name
            + '. Open it under Unfinished print jobs in Documents / Print / Invoice. '
            'Resume your own job, or ask the office to close it with a reason in CFG Kanban Mobile Print Job')
    raw_copies = flt(values.get('copies', 1))
    if not math.isfinite(raw_copies) or raw_copies != int(raw_copies):
        frappe.throw('Select a whole number of copies')
    copies = int(raw_copies)
    if not 1 <= copies <= 5:
        frappe.throw('Select one to five complete copies')
    profile = get_profile(trip.company)
    settings = values.get('printer_settings') or {key: profile.get(key) for key in ('dpi', 'paper_width_mm', 'printable_width')}
    if not isinstance(settings, dict) or set(settings) != {'dpi', 'paper_width_mm', 'printable_width'}:
        frappe.throw('Select valid non-secret printer dimensions')
    validate_dimensions(settings['printable_width'], settings['dpi'], settings['paper_width_mm'])
    fmt = values.get('print_format') or default_format(doc.doctype, profile)
    prepared_on = now_datetime()
    html, version, digest = _render(doc, fmt, values.get('no_letterhead'), prepared_on)
    if doc.doctype in (LABEL, HU) and cint(doc.get('print_count')) and not str(values.get('reason') or '').strip():
        frappe.throw('Give a reason before preparing another copy of this tag')
    job = frappe.get_doc(dict(doctype=JOB, delivery_trip=trip.name, stop_key=stop_key or '', company=trip.company,
        operator=operator.employee, operator_session=session.name, idempotency_key=key,
        request_hash=canonical_key('mobile-print', values), printer_settings_json=frappe.as_json(settings), document_type=doc.doctype, document_name=doc.name,
        print_format=fmt, no_letterhead=cint(values.get('no_letterhead')), copies=copies,
        source_modified=str(doc.modified), format_version=version, render_hash=digest,
        status='Prepared', created_on=prepared_on, reason=values.get('reason')))
    job.flags.cfg_mobile_control = True
    job.insert(ignore_permissions=True)
    return dict(print_job=job.name)


def _label(trip, stop, values, operator, session, key):
    case = return_case(trip, stop, values.get('return_case'), current=True)
    if (case.state != 'Awaiting QC Receipt' or not case.collected_on or cint(case.stock_already_owned)
            or case.return_flow != 'Customer Return for QC'):
        frappe.throw('Custody labels can be created only for collected old returns awaiting QC receipt')
    line = next((r for r in case.lines if r.name == values.get('return_line')), None)
    if not line:
        frappe.throw('Select the exact returned Item row')
    qty = flt(values.get('qty'))
    used = sum(flt(r.qty) for r in frappe.db.sql('''SELECT qty FROM `tabCFG Kanban Return Custody Label`
        WHERE return_case=%s AND return_line=%s FOR UPDATE''', (case.name, line.name), as_dict=True))
    precision = line.precision('claimed_qty') or 6
    if (not math.isfinite(qty) or qty <= 0 or abs(qty-flt(qty, precision)) > 0.00000001
            or qty + used > flt(line.claimed_qty) + 10 ** (-precision) / 2):
        frappe.throw('Custody label quantity must fit the unlabelled returned quantity and UOM precision')
    if frappe.db.get_value('UOM', line.stock_uom, 'must_be_whole_number') and qty != int(qty):
        frappe.throw('This custody label UOM requires a whole quantity')
    label = frappe.get_doc(dict(doctype=LABEL, delivery_trip=trip.name, stop_key=stop.stop_key,
        company=trip.company, operator=operator.employee, operator_session=session.name,
        idempotency_key=key, request_hash=canonical_key('return-custody', values),
        return_case=case.name, return_line=line.name, item_code=line.item_code, batch_no=line.batch_no,
        expiry_date=line.expiry_date, stock_uom=line.stock_uom, qty=qty, created_on=now_datetime(),
        custody_notice='Pending QC — not available stock'))
    label.flags.cfg_mobile_control = True
    label.insert(ignore_permissions=True)
    return dict(custody_label=label.name, return_case=case.name)


def _job(trip, name, operator, current=False):
    doc = _read(JOB, name, current=current)
    if doc.delivery_trip != trip.name or doc.company != trip.company or doc.operator != operator.employee:
        frappe.throw('Print job belongs to another Trip or operator', frappe.PermissionError)
    return doc


def can_close_mobile_print_job(job):
    from cfg_kanban.services.delivery_trips import EDITORS
    return bool(set(frappe.get_roles()).intersection(EDITORS)
        and frappe.has_permission(JOB, 'read', doc=job.name)
        and frappe.has_permission(TRIP, 'read', doc=job.delivery_trip)
        and frappe.has_permission(TRIP, 'write', doc=job.delivery_trip)
        and frappe.has_permission('Company', 'read', doc=job.company))


def _close_job(job, reason, operator=None, session=None):
    reason = str(reason or '').strip()
    if not reason:
        frappe.throw('Give a reason to abandon an unfinished print job')
    if job.status not in ('Prepared', 'Awaiting Confirmation'):
        frappe.throw('This print job has ended; its closure and confirmations cannot be changed')
    previous, previous_reason = job.status, job.reason
    job.db_set(dict(status='Abandoned', reason=reason, closed_on=now_datetime(),
                    closed_by=frappe.session.user), update_modified=True)
    record('Mobile Print Job Closed', reference_doctype=JOB, reference_name=job.name,
        previous_state=previous, new_state='Abandoned', notes=reason,
        operator=operator.employee if operator else None,
        operator_session=session.name if session else None,
        payload=dict(delivery_trip=job.delivery_trip, stop_key=job.stop_key,
            document_type=job.document_type, document_name=job.document_name,
            prepared_by=job.operator, previous_reason=previous_reason,
            closure_source='Driver' if operator else 'Office'))
    return dict(print_job=job.name, job_status='Abandoned')


@frappe.whitelist(methods=['POST'])
def close_mobile_print_job(print_job, reason, expected_modified):
    """Office recovery also works after reassignment or closure of the original Trip."""
    from cfg_kanban.services.delivery_trips import EDITORS
    frappe.only_for(EDITORS)
    job = _read(JOB, print_job, current=True)
    _read('Company', job.company)
    trip = _read(TRIP, job.delivery_trip)
    trip.check_permission('write')
    if trip.company != job.company:
        frappe.throw('Print job Company does not match its original Trip', frappe.PermissionError)
    if not str(reason or '').strip():
        frappe.throw('Give a reason to abandon an unfinished print job')
    if job.status == 'Abandoned':
        return dict(print_job=job.name, job_status=job.status, already_closed=True)
    if not expected_modified or get_datetime(expected_modified) != get_datetime(job.modified):
        frappe.throw('Print job changed; reload it and review its latest segment status before closing')
    return _close_job(job, reason)


def _assert_print_review(job, source, format_version, render_hash):
    changes = []
    if str(source.modified) != job.source_modified:
        changes.append('source document version changed')
    if render_hash != job.render_hash:
        if format_version != job.format_version:
            changes.append('selected Print Format changed')
        changes.append('rendered print content changed')
    if changes:
        frappe.throw('Print job ' + job.name + ': ' + '; '.join(changes)
            + '. Close this job with a reason, then review a new print')
    # A native format save/migration can change its timestamp without changing
    # this document's HTML/CSS. Re-rendering still enforces native permission,
    # format validity and signature policy. Keep the original review immutable.
    return format_version != job.format_version


@frappe.whitelist()
def get_mobile_print_job(trip_name, print_job, operator_session_token):
    from cfg_kanban.services import driver_routes
    operator, session = driver_routes._access(operator_session_token, 1)
    trip = driver_routes._trip(trip_name, operator)
    job = _job(trip, print_job, operator)
    get_profile(trip.company)
    doc = _source(trip, job.stop_key or None, operator, job.document_type, job.document_name)
    html, version, digest = _render(doc, job.print_format, job.no_letterhead, job.created_on)
    if job.status in ('Operator Confirmed', 'Abandoned'):
        frappe.throw('This print job has ended; prepare a reviewed reprint if needed')
    _assert_print_review(job, doc, version, digest)
    return dict(name=job.name, html=html, render_hash=digest, copies=job.copies, status=job.status,
                segments=json.loads(job.segments_json or '{}'), print_format=job.print_format,
                document_name=job.document_name, document_type=job.document_type, stop_key=job.stop_key or None,
                printer_settings=json.loads(job.printer_settings_json))


def _segment(trip, values, operator, session=None):
    job = _job(trip, values.get('print_job'), operator, current=True)
    if job.status in ('Abandoned', 'Operator Confirmed'):
        frappe.throw('This print job has already ended')
    hashes = values.get('frame_hashes')
    if (not isinstance(hashes, list) or not hashes or len(hashes) > 1000
            or any(not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in hashes)
            or len(hashes) % job.copies):
        frappe.throw('Invalid print segment manifest')
    per_copy = len(hashes) // job.copies
    if any(hashes[offset:offset+per_copy] != hashes[:per_copy] for offset in range(0, len(hashes), per_copy)):
        frappe.throw('Every complete copy must have the same ordered segments')
    state = json.loads(job.segments_json or '{}')
    if state and state.get('hashes') != hashes:
        frappe.throw('Rendered segments changed; reconcile this job before a new print')
    state = state or dict(hashes=hashes, pages={})
    page = cint(values.get('page'))
    if not 1 <= page <= len(hashes):
        frappe.throw('Select a valid print segment')
    if any(state['pages'].get(str(n), {}).get('status') != 'Operator Confirmed' for n in range(1, page)):
        frappe.throw('Confirm the previous print segment before preparing the next one')
    prior = state['pages'].get(str(page), {})
    status = values.get('outcome')
    if status not in ('Awaiting Confirmation', 'Operator Confirmed', 'Outcome Unknown'):
        frappe.throw('Select a supported operator print outcome')
    if prior.get('status') == 'Operator Confirmed':
        frappe.throw('This segment is already confirmed; use a new reviewed reprint job')
    if status != 'Awaiting Confirmation' and not prior:
        frappe.throw('Prepare this segment for handoff before recording its outcome')
    revalidation = {}
    if status == 'Awaiting Confirmation':
        get_profile(trip.company)
        source = _source(trip, job.stop_key or None, operator, job.document_type, job.document_name)
        _html, version, digest = _render(source, job.print_format, job.no_letterhead, job.created_on)
        if _assert_print_review(job, source, version, digest):
            revalidation = dict(original_format_version=job.format_version,
                validated_format_version=version, render_hash=digest)
    if status == 'Awaiting Confirmation' and prior and not str(values.get('reason') or '').strip():
        frappe.throw('The previous physical outcome is uncertain; give a reason to retry this same segment')
    history = list(prior.get('history') or [])
    history.append(dict(status=status, on=str(now_datetime()), reason=values.get('reason') or ''))
    state['pages'][str(page)] = dict(status=status, on=str(now_datetime()), history=history,
        attempts=cint(prior.get('attempts')) + (1 if status == 'Awaiting Confirmation' else 0))
    complete = all(state['pages'].get(str(n), {}).get('status') == 'Operator Confirmed' for n in range(1, len(hashes)+1))
    job.db_set(dict(segments_json=frappe.as_json(state), status='Operator Confirmed' if complete else 'Awaiting Confirmation',
                    confirmed_on=now_datetime() if complete else None), update_modified=True)
    if complete:
        if job.document_type == LABEL:
            label = _read(LABEL, job.document_name, current=True)
            label.db_set('print_count', cint(label.print_count) + job.copies, update_modified=False)
        elif job.document_type == HU:
            from cfg_kanban.services.printing import record_print
            unit = _read(HU, job.document_name, current=True, printing=True)
            record_print(HU, unit.name, job.print_format, reason=job.reason)
    record('Mobile Print Segment ' + status, reference_doctype=JOB, reference_name=job.name,
        operator=operator.employee, operator_session=session.name if session else None,
        terminal_user=session.terminal_user if session else None, system_generated=False,
        notes=values.get('reason'), payload=dict(page=page, outcome=status,
            manifest_hash=canonical_key('print-frames', hashes), attempts=state['pages'][str(page)]['attempts'],
            **revalidation))
    return dict(print_job=job.name, page=page, outcome=status, job_status=job.status)


def action(trip, request, operator, session, token, key):
    from cfg_kanban.services import driver_route_actions, mobile_invoicing
    from cfg_kanban.services.operator_auth import require_operator
    require_operator(token, 'complete')
    values = request['payload']
    if request['dispatch_plan']:
        frappe.throw('Printing actions use the Trip and saved stop, not a substituted Plan')
    if request['action'] in ('Record Print Segment', 'Close Mobile Print'):
        job = _job(trip, values.get('print_job'), operator, current=True)
        if (job.stop_key or None) != request['stop_key']:
            frappe.throw('Print job belongs to another customer stop')
        if request['action'] == 'Record Print Segment':
            return _segment(trip, values, operator, session)
        return _close_job(job, values.get('reason'), operator, session)
    if request['scope_hash'] != driver_route_actions._core(trip) or request['expected_revision'] != cint(trip.driver_route_revision):
        frappe.throw('Trip changed; refresh before preparing new document details')
    if request['action'] == 'Run Stop Document':
        from cfg_kanban.services.stop_documents import run
        return run(trip, request['stop_key'], values.get('document_task'), operator, session, token)
    profile = get_profile(trip.company, current=request['action'] == 'Create Sales Invoice')
    if request['action'] == 'Prepare Mobile Print':
        return _prepare(trip, request['stop_key'], values, operator, session, key)
    stop = saved_stop(trip, request['stop_key'])
    if request['action'] == 'Create Custody Label':
        return _label(trip, stop, values, operator, session, key)
    if request['action'] == 'Create Sales Invoice':
        previous = getattr(frappe.local, 'cfg_mobile_invoice_token', None)
        frappe.local.cfg_mobile_invoice_token = token
        try:
            return mobile_invoicing.create(trip, stop, values, operator, session, profile, key)
        finally:
            frappe.local.cfg_mobile_invoice_token = previous
    frappe.throw('Unsupported mobile document action')


def trip_stock_rows(trip):
    """Native Print Format helper: ERP and tag views are deliberately not added together."""
    from cfg_kanban.services.vehicle_overview import _stock
    trip.check_permission('read')
    _read('Company', trip.company)
    from cfg_kanban.services.driver_routes import trip_vehicle_warehouse
    name=trip_vehicle_warehouse(trip)
    if trip.get('driver_route_snapshot_json') and trip.get('driver_route_state') in ('In Progress','Completed','Closed Incomplete'):
        from cfg_kanban.services.driver_route_actions import _core
        saved=json.loads(trip.driver_route_snapshot_json)
        if saved.get('scope_hash')!=_core(trip):frappe.throw('Reconcile the Trip departure before printing its lorry stock')
    if not name:
        return []
    vehicle = _read('Warehouse', name)
    if vehicle.company != trip.company:
        frappe.throw('Lorry Warehouse belongs to another Company', frappe.PermissionError)
    stock = _stock(vehicle)
    for row in stock['stock']:
        row['tags'] = [tag for tag in row['tags'] if frappe.has_permission(HU, 'read', doc=tag.name)]
        for tag in row['tags']:
            tag['effective_expiry'] = _stock_print_expiry(tag)
    return stock['stock']


def custody_case_scan(value):
    """Resolve a custody QR into the existing live Case, with native read/Company gates."""
    raw = str(value or '').strip()
    prefixed = raw.upper().startswith('CFG:RETURN-CUSTODY:')
    if not prefixed and not raw.upper().startswith('KRC-'):
        return raw
    name = raw.split(':', 2)[2] if prefixed else raw
    if not frappe.db.table_exists(LABEL) or not frappe.db.exists(LABEL, name):
        if prefixed:
            frappe.throw('Return custody label was not found')
        return raw
    label = _read(LABEL, name)
    case = _read(CASE, label.return_case)
    _read('Company', label.company)
    if case.selling_company != label.company or not any(r.name == label.return_line for r in case.lines):
        frappe.throw('Custody label no longer matches its Return Case; Supervisor review required')
    return case.name


def _stock_print_data(unit):
    from cfg_kanban.services.certificate_output_evidence import certificate_output_evidence, printed_expiry_dates
    batch_date = frappe.db.get_value('Batch', unit.batch_no, 'expiry_date') if unit.batch_no else None
    evidence = certificate_output_evidence(unit.name, unit.get('process_certificate_set'), unit.item_code, unit.stock_uom)
    dates = [str(value)[:10] for value in [unit.get('expiry_date'), batch_date, *printed_expiry_dates(evidence)] if value]
    return dict(expiry_date=min(dates) if dates else None, certificate_output_evidence=evidence)


def _stock_print_expiry(unit):
    return _stock_print_data(unit)['expiry_date']


def stock_tag_print_context(unit):
    unit.check_permission('read')
    unit.check_permission('print')
    if unit.get('inventory_company'):
        _read('Company', unit.inventory_company)
    result = _stock_print_data(unit)
    result['serial_nos'] = frappe.get_all('CFG Kanban Handling Unit Serial',
            filters={'handling_unit': unit.name, 'state': 'Active'}, pluck='serial_no',
            order_by='serial_no', limit_page_length=0)
    return result

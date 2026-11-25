"""Permission-aware return worklist; existing QC, accounting and stock services own mutations."""
from datetime import timedelta
from math import isfinite

import frappe
from frappe.utils import cint, flt, getdate, get_datetime, now_datetime
from cfg_kanban.services.operator_auth import require_operator, public_operator

CASE = 'CFG Kanban Return Case'
TERMINAL = {'Closed', 'Cancelled', 'Delivery Correction Posted'}
VIEWS = ('Needs Follow-up', 'All Returns', 'Closed / Cancelled')
FLOWS = ('Customer Return for QC', 'Delivery Note Correction')
HEADER = ('name', 'state', 'return_flow', 'intake_method', 'selling_company', 'customer',
          'site_name', 'inspection_location', 'claimed_on', 'creation', 'modified',
          'received_on', 'qc_started_on', 'qc_completed_on', 'qc_operator',
          'accepted_total_qty', 'accounting_status', 'disposition_status',
          'credit_document_status', 'accounting_sales_invoice_status', 'correction_document_status',
          'stock_disposition_entry_status', 'stock_already_owned', 'driver_trip',
          'collection_vehicle_warehouse', 'collected_on','custody_trip','custody_vehicle_warehouse')
FILTERS = {'view', 'company', 'customer', 'location', 'trip','custody_trip', 'state', 'flow',
           'from_date', 'to_date', 'search', 'sort'}
LINE_FIELDS = ('name', 'item_code', 'batch_no', 'expiry_date', 'stock_uom', 'original_visible_code',
               'claimed_qty', 'received_qty', 'accepted_qty', 'rejected_qty', 'condition',
               'qc_disposition', 'qc_reason', 'details')
LINK_TYPES = {'Sales Invoice', 'Credit Note', 'Delivery Note', 'Stock Entry',
              'CFG Kanban Delivery Trip', 'CFG Kanban Delivery Outcome'}


def _returns():
    from cfg_kanban.services import customer_returns
    return customer_returns


def _access(token, interactive=0):
    profile, session = require_operator(token, touch_activity=bool(cint(interactive)))
    _returns()._require_qc(profile)
    if session.employee!=profile.employee:
        frappe.throw('Operator profile identity changed; sign in again',frappe.PermissionError)
    if not frappe.has_permission(CASE, ptype='read'):
        frappe.throw('Read permission for Customer Return Cases is required', frappe.PermissionError)
    return profile, session


def _read(dt, name):
    doc = frappe.get_doc(dt, name)
    doc.check_permission('read')
    return doc


def _companies():
    # Both list queries and counts use the same native Company/Return Case permissions.
    return sorted(frappe.get_list('Company', pluck='name', limit_page_length=0))


def _text(value, limit=140):
    if value is None:return ''
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        frappe.throw('Enter a valid return filter or case number')
    return value.strip()


def _filters(raw, companies):
    values = frappe.parse_json(raw) if isinstance(raw, str) else (raw or {})
    if not isinstance(values, dict) or set(values)-FILTERS:
        frappe.throw('Unsupported customer-return filter')
    values = {k:_text(v, 100 if k=='search' else 140) for k,v in values.items()}
    values['view'] = values.get('view') or VIEWS[0]
    values['sort'] = values.get('sort') or 'Oldest intake first'
    if values['view'] not in VIEWS or values['sort'] not in ('Oldest intake first', 'Recently updated'):
        frappe.throw('Choose a valid worklist and sort order')
    if values.get('flow') and values['flow'] not in FLOWS:frappe.throw('Choose a valid return workflow')
    states = [s for s in (frappe.get_meta(CASE).get_field('state').options or '').splitlines() if s]
    if values.get('state') and values['state'] not in states:frappe.throw('Choose a valid Return Case state')
    if values.get('company') and values['company'] not in companies:
        frappe.throw('Company is not accessible to this terminal user', frappe.PermissionError)
    query = [['selling_company', 'in', [values['company']] if values.get('company') else companies]]
    if values['view'] != 'All Returns':
        query.append(['state', 'not in' if values['view']==VIEWS[0] else 'in', sorted(TERMINAL)])
    for key,field in (('customer','customer'),('location','inspection_location'),('trip','driver_trip'),('custody_trip','custody_trip'),('state','state'),('flow','return_flow')):
        if values.get(key):query.append([field,'=',values[key]])
    for key in ('from_date','to_date'):
        if values.get(key):
            try:values[key] = str(getdate(values[key]))
            except (ValueError, TypeError):frappe.throw('Enter a valid intake date')
    if values.get('from_date') and values.get('to_date') and values['from_date']>values['to_date']:
        frappe.throw('Intake date range is reversed')
    if values.get('from_date'):query.append(['claimed_on','>=',values['from_date']])
    if values.get('to_date'):query.append(['claimed_on','<',str(getdate(values['to_date'])+timedelta(days=1))])
    pattern = '%'+values['search'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%' if values.get('search') else None
    choices = [[field,'like',pattern] for field in ('name','customer','site_name','reported_source_reference')] if pattern else []
    order = 'claimed_on asc, name asc' if values['sort']=='Oldest intake first' else 'modified desc, name desc'
    return values, query, choices, order, states


def _page(value, default, maximum=None):
    try:
        if isinstance(value, bool):raise ValueError()
        number = int(default if value is None else value)
        if str(number) != str(default if value is None else value).strip():raise ValueError()
    except (ValueError, TypeError, OverflowError):frappe.throw('Enter a valid worklist page')
    if number < 0 or (maximum and (number < 1 or number > maximum)):frappe.throw('Enter a valid worklist page')
    return number


def _follow_up(case):
    """Parallel accounting/physical tracks stay separate; native state remains authoritative."""
    if case.state in TERMINAL:return []
    result = []
    def add(code,owner,label):result.append(dict(code=code,owner=owner,label=label))
    if case.state=='Exception' or case.disposition_status=='Exception':
        add('exception','Supervisor','Review the recorded exception and controlled recovery')
    if case.return_flow=='Delivery Note Correction':
        add('correction','Stock / Accounts','Review the Return Delivery Note and any accounting attention')
        return result
    if case.state=='Awaiting QC Receipt':
        add('receipt','QC','Receive the physical goods and start inspection')
        return result
    if case.state=='QC In Progress':
        add('inspection','QC','Complete inspection quantities, disposition and evidence')
        return result
    if not case.qc_completed_on:
        add('review','QC / Supervisor','Review the case state before continuing QC')
        return result
    if cint(case.get('stock_already_owned')):
        add('owned_stock','Supervisor / Stock','Resolve held company stock through the refusal release, recovery or disposal workflow')
        return result
    if case.state=='QC Rejected' or flt(case.accepted_total_qty)<=0:
        add('rejected','QC / Supervisor','Review the rejected claim and physical custody; no credit is approved')
        return result
    if case.accounting_status not in ('Completed','No Credit Approved','Not Required'):
        pending = case.accounting_status in ('Source Selected','Credit Pending')
        add('accounting','Accounts', 'Review/submit or recover the linked credit document' if pending else 'Select the accounting source or approve No Credit')
    if case.disposition_status!='Completed':
        draft = case.stock_disposition_entry_status=='Draft'
        add('stock','Stock / Quality Manager', 'Review/submit the return Material Receipt Draft' if draft else 'Prepare or recover the accepted stock disposition')
    if not result:add('review','Supervisor','Review the final case closure and native feedback')
    return result


def _age(value, now):
    if not value:return None
    try:return max(0, int((get_datetime(now)-get_datetime(value)).total_seconds()))
    except (ValueError, TypeError, OverflowError):return None


def _header(case, now):
    result = {k:case.get(k) for k in HEADER}
    result['stock_already_owned'] = bool(cint(case.get('stock_already_owned')))
    result['age_seconds'] = _age(case.get('claimed_on') or case.get('creation'), now)
    result['follow_up'] = _follow_up(case)
    result['kind'] = ('Company-owned refusal' if cint(case.get('stock_already_owned')) else
                      'Delivery correction' if case.return_flow==FLOWS[1] else 'Old customer goods')
    result['inspection'] = ('Not applicable' if case.return_flow!=FLOWS[0] else
                            'Completed' if case.qc_completed_on else 'In Progress' if case.qc_started_on else 'Awaiting receipt')
    return result


@frappe.whitelist()
def get_qc_worklist(operator_session_token, filters=None, start=0, page_length=10, interactive=0):
    profile, session = _access(operator_session_token, interactive)
    companies = _companies()
    values, query, choices, order, states = _filters(filters, companies)
    start, length = _page(start,0), _page(page_length,10,50)
    now = now_datetime()
    if not companies:
        rows, grouped = [], []
    else:
        rows = frappe.get_list(CASE, filters=query, or_filters=choices, fields=list(HEADER),
            order_by=order, limit_start=start, limit_page_length=length+1)
        grouped = frappe.get_list(CASE, filters=query, or_filters=choices,
            fields=['state','count(name) as total'], group_by='state', order_by='state asc', limit_page_length=0)
    counts = {r.state:cint(r.total) for r in grouped}
    # No quantity grand total: Items can use different stock UOMs.
    return dict(operator=public_operator(profile,session), rows=[_header(r,now) for r in rows[:length]],
        counts=counts, total=sum(counts.values()), has_more=len(rows)>length, start=start,
        page_length=length, filters=values, companies=companies, states=states, views=list(VIEWS),
        refreshed_on=now, read_only=True)


def _case(scan, companies, company=None):
    scan = _text(scan)
    if scan.upper().startswith(('CFG:RETURN-CUSTODY:', 'KRC-')):
        from cfg_kanban.services.mobile_printing import custody_case_scan
        scan = custody_case_scan(scan)
    if not scan:frappe.throw('Scan a Temporary Return Note or select a Return Case')
    if company and company not in companies:frappe.throw('Company is not accessible',frappe.PermissionError)
    names = frappe.get_list(CASE, filters={'selling_company':['in',[company] if company else companies]},
        or_filters=[['name','=',scan],['scan_token','=',scan]], pluck='name', limit_page_length=2) if companies else []
    if len(names)!=1:
        frappe.throw('Return Case is not accessible or the scan is ambiguous',frappe.PermissionError)
    case = _read(CASE,names[0])
    if case.selling_company not in companies or (company and case.selling_company!=company):
        frappe.throw('Return Case Company is not accessible',frappe.PermissionError)
    _read('Company',case.selling_company)
    return case


def _links(case):
    result = []
    candidates = [('CFG Kanban Delivery Trip',case.get('custody_trip'),'Current Custody Trip'),('CFG Kanban Delivery Trip',case.driver_trip,'Original Driver Trip'),
        ('CFG Kanban Delivery Outcome',case.driver_delivery_outcome,'Refusal / Current Held Stock'),
        ('Delivery Note',case.original_delivery_note,'Original Delivery Note'),
        ('Delivery Note',case.correction_return_delivery_note,'Return Delivery Note'),
        (case.credit_document_doctype or 'Sales Invoice',case.credit_document,'Credit Document'),
        ('Sales Invoice',case.accounting_sales_invoice,'Accounting Sales Invoice Return'),
        ('Stock Entry',case.stock_disposition_entry,'Return Material Receipt'),
        ('Stock Entry',case.owned_stock_issue,'Owned Stock Disposal')]
    for dt,name,label in candidates:
        if not name or dt not in LINK_TYPES or any(r['doctype']==dt and r['name']==name for r in result):continue
        try:doc = _read(dt,name)
        except (frappe.PermissionError,frappe.DoesNotExistError):continue
        company = doc.get('company')
        if company!=case.selling_company:continue
        if dt in ('Sales Invoice','Credit Note','Delivery Note') and doc.get('customer')!=case.customer:continue
        if dt=='CFG Kanban Delivery Outcome' and doc.get('delivery_trip')!=case.driver_trip:continue
        result.append(dict(doctype=dt,name=name,label=label,docstatus=doc.get('docstatus')))
    return result


def _owned_custody(case, links):
    if not cint(case.get('stock_already_owned')) or not any(r['doctype']=='CFG Kanban Delivery Outcome' for r in links):return []
    outcome = _read('CFG Kanban Delivery Outcome',case.driver_delivery_outcome)
    if outcome.company!=case.selling_company or outcome.delivery_trip!=case.driver_trip:return []
    ids = {r.driver_outcome_line for r in case.lines if r.driver_outcome_line}
    return [dict(item_code=r.item_code,batch_no=r.batch_no,stock_uom=r.stock_uom,
                 qty=flt(r.refused_qty),stock_state=r.stock_state,warehouse=r.current_warehouse,
                 visible_code=r.visible_code) for r in outcome.lines if r.name in ids and r.qc_return_case==case.name]


@frappe.whitelist()
def get_qc_case(scan_value, operator_session_token, company=None, interactive=0):
    profile, session = _access(operator_session_token,interactive)
    case = _case(scan_value,_companies(),_text(company))
    now = now_datetime(); result = _header(case,now)
    result.update({k:case.get(k) for k in ('customer_return_reason','qc_notes','reported_source_reference',
        'created_by_operator','collected_by','qc_operator','qc_started_on','qc_completed_on',
        'received_on','collected_on','accounting_decided_on','disposition_decided_on')})
    lines, totals, warnings = [], {}, []
    for row in case.lines:
        line = {k:row.get(k) for k in LINE_FIELDS}
        quantities = totals.setdefault(row.stock_uom or 'Unknown UOM',dict(claimed_qty=0,received_qty=0,accepted_qty=0,rejected_qty=0))
        for key in quantities:
            qty = flt(row.get(key))
            if not isfinite(qty):
                warnings.append('Invalid recorded quantity on return row '+str(row.idx));line[key]=None;quantities[key]=None
            elif quantities[key] is not None:quantities[key]+=qty
        lines.append(line)
    if case.state not in TERMINAL and any(r.qc_disposition=='Hold for Investigation' for r in case.lines):
        result['follow_up'].insert(0,dict(code='investigation',owner='QC / Supervisor',label='Review the recorded investigation hold and QC notes'))
    links = _links(case)
    result.update(lines=lines,totals_by_uom=totals,links=links,warnings=warnings,
        owned_custody=_owned_custody(case,links),
        actor=profile.employee,
        can_inspect=bool(case.return_flow==FLOWS[0] and
            ((case.state=='Awaiting QC Receipt' and profile.get('can_start')) or
             (case.state=='QC In Progress' and profile.get('can_complete')))),
        read_only=True,refreshed_on=now)
    return result

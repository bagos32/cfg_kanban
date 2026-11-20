"""Customer-selected return custody, without a Customer Scan Point.

The existing Return Case owns QC, evidence, accounting and physical disposition.
Intake itself posts no ERP stock or accounting document.
"""
from math import isfinite

import frappe
from frappe.utils import flt, getdate, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.operator_auth import require_operator

CASE = 'CFG Kanban Return Case'
METHOD = 'Direct Customer'


class DirectReturnReplayError(Exception):
    """One intake action cannot be reused for different physical return details."""


class DirectReturnVoidedError(Exception):
    """An explicitly abandoned, unrecorded action cannot arrive late and create a note."""


def _returns():
    from cfg_kanban.services import customer_returns
    return customer_returns


def _operator(token, permission=None):
    profile, session = require_operator(token, permission) if permission else require_operator(token)
    _returns()._require_intake(profile)
    return profile, session


def _text(value):
    return str(value or '').strip()


def _request(company, customer, inspection_location, customer_return_reason, lines,
             customer_address=None, customer_acknowledgement_name=None):
    submitted = frappe.parse_json(lines) if isinstance(lines, str) else lines
    if not isinstance(submitted, list):
        frappe.throw('Return lines must be a list of returned Items')
    rows = []
    for raw in submitted:
        if not isinstance(raw, dict):
            frappe.throw('Every return line must identify one returned Item')
        item = str(raw.get('item_code') or '').strip()
        try:
            qty = float(raw.get('claimed_qty') or 0)
        except (TypeError, ValueError):
            frappe.throw('Returned quantity must be a finite positive number')
        text = {field:str(raw.get(field) or '').strip() for field in
                ('batch_no','expiry_date','original_visible_code','details','stock_uom')}
        if not item and not qty and not any(text.values()):
            continue
        if not item or not isfinite(qty) or qty <= 0:
            frappe.throw('Every return line needs an Item and finite positive quantity')
        rows.append(dict(item_code=item, claimed_qty=qty,
            condition=str(raw.get('condition') or 'Unknown').strip(),
            batch_no=text['batch_no'] or None,
            expiry_date=str(getdate(text['expiry_date'])) if text['expiry_date'] else None,
            original_visible_code=text['original_visible_code'], details=text['details'],
            stock_uom=text['stock_uom'] or None))
    if not rows:
        frappe.throw('Add at least one returned Item and quantity')
    return dict(company=str(company or '').strip(), customer=str(customer or '').strip(),
        inspection_location=str(inspection_location or '').strip(),
        customer_return_reason=str(customer_return_reason or '').strip(),
        customer_address=str(customer_address or '').strip() or None,
        customer_acknowledgement_name=str(customer_acknowledgement_name or '').strip(), lines=rows)


def _parties(request):
    for field, label in (('company','Company'),('customer','Customer'),('inspection_location','Inspection Custody Location')):
        if not request[field]:
            frappe.throw(f'Select {label} for this direct return')
    company = frappe.get_doc('Company', request['company'])
    company.check_permission('read')
    if company.get('is_group') or company.get('disabled'):
        frappe.throw('Direct return requires an active transaction Company')
    customer = frappe.get_doc('Customer', request['customer'])
    customer.check_permission('read')
    if customer.get('disabled'):
        frappe.throw('Selected Customer is disabled')
    location = frappe.get_doc('Location', request['inspection_location'])
    location.check_permission('read')
    if location.get('disabled') or (location.get('company') and location.company != company.name):
        frappe.throw('Inspection Custody Location must be active and belong to the selected Company when company-specific')
    if request.get('customer_address'):
        address = frappe.get_doc('Address', request['customer_address'])
        address.check_permission('read')
        if address.get('disabled') or not frappe.db.exists('Dynamic Link', dict(parenttype='Address',
                parent=address.name, link_doctype='Customer', link_name=customer.name)):
            frappe.throw('Customer Address must be active and linked to the selected Customer')
    return company, customer, location


def _validated(request):
    company, customer, location = _parties(request)
    if not request['customer_return_reason']:
        frappe.throw('Customer return reason is required')
    for row in request['lines']:
        item = frappe.get_doc('Item', row['item_code'])
        item.check_permission('read')
        if row.get('stock_uom') and row['stock_uom'] != item.stock_uom:
            frappe.throw('Item stock UOM changed after review; refresh and review the return quantities again')
        if item.get('disabled') or item.get('is_group'):
            frappe.throw('Every returned Item must be active and identify an Item, not a group')
        if row.get('condition') not in _returns().CONDITIONS:
            frappe.throw('Select a valid reported condition for every returned Item')
        if row.get('batch_no'):
            frappe.get_doc('Batch', row['batch_no']).check_permission('read')
    rows = _returns()._validate_free_intake_lines(request['lines'])
    if not isfinite(sum(row['claimed_qty'] for row in rows)):
        frappe.throw('Total returned quantity must be finite')
    return dict(company=company.name, customer=customer.name,
        customer_name=customer.customer_name or customer.name, customer_address=request['customer_address'],
        inspection_location=location.name, lines=rows,
        customer_return_reason=request['customer_return_reason'],
        customer_acknowledgement_name=request['customer_acknowledgement_name'])


@frappe.whitelist()
def get_direct_return_setup(operator_session_token):
    profile, _session = _operator(operator_session_token)
    return dict(intake_method=METHOD, conditions=list(_returns().CONDITIONS),
        enabled=bool(frappe.db.get_single_value('CFG Kanban Settings','enable_customer_returns')),
        can_start=bool(profile.get('can_start')))


@frappe.whitelist()
def preview_direct_customer_return(company, customer, inspection_location, customer_return_reason,
        lines, operator_session_token, customer_address=None, customer_acknowledgement_name=None):
    _operator(operator_session_token, 'start')
    _returns()._assert_enabled()
    request = _request(company, customer, inspection_location, customer_return_reason,
                       lines, customer_address, customer_acknowledgement_name)
    return _validated(request)


def _key(profile, event_token):
    if not _text(event_token):
        frappe.throw('A stable event token is required for direct return intake')
    # One actor/token has one payload across Companies and browser tabs.
    return canonical_key('direct-customer-return-intake', profile.employee, _text(event_token))


def _lock(profile):
    frappe.db.sql('select name from `tabEmployee` where name=%s for update', profile.employee)


def _existing(key):
    return frappe.db.get_value(CASE, {'idempotency_key':key}, 'name', for_update=True)


def _voided(key):
    return frappe.db.get_value('CFG Kanban Event',
        {'idempotency_key':canonical_key('direct-customer-return-void',key)}, 'name', for_update=True)


def _result(case, profile):
    result = _returns()._return_case_result(case, profile)
    return dict(status='Recorded', return_case=result, event_token=None)


@frappe.whitelist()
def create_direct_customer_return(company, customer, inspection_location, customer_return_reason,
        lines, event_token, operator_session_token, customer_address=None, customer_acknowledgement_name=None):
    profile, session = _operator(operator_session_token, 'start')
    request = _request(company, customer, inspection_location, customer_return_reason,
                       lines, customer_address, customer_acknowledgement_name)
    fingerprint = canonical_key('direct-customer-return-payload', request)
    key = _key(profile, event_token)
    _lock(profile)
    existing = _existing(key)
    if existing:
        case = frappe.get_doc(CASE, existing, for_update=True)
        if case.get('intake_payload_hash') != fingerprint or case.get('intake_method') != METHOD:
            frappe.throw('This return action belongs to different intake details', DirectReturnReplayError)
        return _result(case, profile)
    if _voided(key):
        frappe.throw('This unrecorded return action was voided; open a new intake', DirectReturnVoidedError)
    _returns()._assert_enabled()
    context = _validated(request)
    case, created = insert_once(frappe.get_doc(dict(doctype=CASE,
        intake_method=METHOD, intake_payload_hash=fingerprint, return_flow='Customer Return for QC',
        state='Awaiting QC Receipt', selling_company=context['company'], customer=context['customer'],
        customer_address=context['customer_address'], customer_scan_point=None, site_code=None, site_name=None,
        inspection_location=context['inspection_location'], claimed_on=now_datetime(),
        customer_return_reason=context['customer_return_reason'],
        customer_acknowledgement_name=context['customer_acknowledgement_name'],
        customer_acknowledged_on=now_datetime() if context['customer_acknowledgement_name'] else None,
        lines=context['lines'], claimed_total_qty=sum(flt(row['claimed_qty']) for row in context['lines']),
        accepted_total_qty=0, rejected_total_qty=0, accounting_status='Pending Source Selection',
        created_by_operator=profile.employee, created_operator_session=session.name)), key, ignore_permissions=True)
    if case.intake_payload_hash != fingerprint:
        frappe.throw('This return action belongs to different intake details', DirectReturnReplayError)
    if created:
        record('Direct Customer Return Intake Recorded', return_case=case.name,
            idempotency_key=canonical_key('direct-customer-return-recorded',key),
            previous_state=None, new_state=case.state, qty=case.claimed_total_qty,
            reference_doctype=CASE, reference_name=case.name, device_id=key,
            operator=profile.employee, operator_session=session.name, terminal_user=session.terminal_user,
            notes=context['customer_return_reason'])
    return _result(case, profile)


@frappe.whitelist()
def get_direct_return_receipt(event_token, operator_session_token):
    profile, _session = _operator(operator_session_token)
    key = _key(profile, event_token)
    _lock(profile)
    existing = _existing(key)
    if existing:
        return _result(frappe.get_doc(CASE, existing, for_update=True), profile)
    return dict(status='Voided' if _voided(key) else 'Not Recorded')


@frappe.whitelist()
def void_unrecorded_direct_return(event_token, reason, operator_session_token):
    profile, session = _operator(operator_session_token, 'start')
    if not _text(reason):
        frappe.throw('A reason is required to abandon an unrecorded direct intake')
    key = _key(profile, event_token)
    _lock(profile)
    existing = _existing(key)
    if existing:
        return _result(frappe.get_doc(CASE, existing, for_update=True), profile)
    if _voided(key):
        return dict(status='Voided')
    # This audit event is a tombstone checked under the same actor lock by creation.
    record('Unrecorded Direct Return Intake Voided',
        idempotency_key=canonical_key('direct-customer-return-void',key),
        reference_doctype='Employee', reference_name=profile.employee,
        operator=profile.employee, operator_session=session.name, terminal_user=session.terminal_user,
        notes=_text(reason))
    return dict(status='Voided')

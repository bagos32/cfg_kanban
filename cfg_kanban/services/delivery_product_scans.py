"""Customer-drop identity checks. These acknowledgements never post or reserve stock."""
import json
import math

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

ALLOCATION = 'CFG Kanban Delivery Allocation'
FIELDS = ['name', 'delivery_session', 'state', 'handling_unit', 'visible_code',
          'container_handling_unit', 'container_visible_code', 'item_code', 'batch_no',
          'stock_uom', 'allocated_qty', 'source_warehouse', 'dispatch_allocation',
          'drop_scan_confirmed', 'drop_scan_evidence']


def _engine():
    from cfg_kanban.services import customer_delivery
    return customer_delivery


def _rows(delivery, current=False):
    return frappe.db.get_values(ALLOCATION, filters={
        'delivery_session': delivery.name, 'state': ['in', ['Reserved', 'Delivery Pending']]},
        fieldname=FIELDS, order_by='reserved_on asc, name asc', as_dict=True, for_update=current)


def _identity(delivery, row):
    return canonical_key('customer-drop-allocation', delivery.name, delivery.customer_scan_point,
        delivery.customer, delivery.selling_company, delivery.source_warehouse,
        {key: row.get(key) for key in FIELDS if key not in (
            'state', 'drop_scan_confirmed', 'drop_scan_evidence')})


def _verified(delivery, row):
    try:
        evidence = json.loads(row.get('drop_scan_evidence') or '{}')
    except (ValueError, TypeError):
        return False
    return bool(cint(row.get('drop_scan_confirmed')) and isinstance(evidence, dict)
        and evidence.get('source_hash') == _identity(delivery, row)
        and evidence.get('operator') and evidence.get('observed_on'))


def context(delivery):
    required = bool(cint(delivery.get('require_delivery_product_scan')))
    rows = _rows(delivery) if required else []
    result = [dict(name=r.name, item_code=r.item_code, batch_no=r.batch_no,
        stock_uom=r.stock_uom, qty=r.allocated_qty, visible_code=r.visible_code,
        container_visible_code=r.container_visible_code, tagged=bool(r.handling_unit),
        confirmed=_verified(delivery, r)) for r in rows]
    return dict(required=required, ready=bool(result) and all(r['confirmed'] for r in result), rows=result)


def assert_verified(delivery):
    if not cint(delivery.get('require_delivery_product_scan')):
        return
    rows = _rows(delivery, current=True)
    for row in rows:
        if not _verified(delivery, row):
            source = row.visible_code if row.handling_unit else 'untagged quantity'
            frappe.throw(f'Verify delivery goods before confirming: {row.item_code} / '
                f'{row.batch_no or "No Batch"} / {source} / {row.allocated_qty} {row.stock_uom}')
    if not rows:
        frappe.throw('Select delivery goods before verifying this customer drop')


def _ack(delivery, rows, operator, session, key, code, kind, observed_on=None):
    changed = []
    for row in rows:
        if _verified(delivery, row):
            continue
        evidence = dict(source_hash=_identity(delivery, row), kind=kind, scanned_code=code,
            qty=row.allocated_qty, stock_uom=row.stock_uom, operator=operator.employee,
            operator_session=session.name, observed_on=str(observed_on or now_datetime()), request_key=key)
        frappe.db.set_value(ALLOCATION, row.name, dict(drop_scan_confirmed=1,
            drop_scan_evidence=frappe.as_json(evidence)), update_modified=False)
        changed.append(row.name)
    if changed:
        record('Customer Drop Goods Verified', delivery_session=delivery.name,
            reference_doctype=delivery.doctype, reference_name=delivery.name,
            operator=operator.employee, operator_session=session.name,
            terminal_user=session.get('terminal_user'),
            idempotency_key=canonical_key('customer-drop-evidence', key),
            payload=dict(allocations=changed, kind=kind, scanned_code=code),
            notes='Identity/quantity acknowledgement only; no stock movement')
    return changed


def _physical_rows(delivery, rows, code):
    from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
    identity = resolve_logistics_scan(code)
    if not identity or identity.get('identity_type') != 'Handling Unit':
        frappe.throw('Scan a Stock Tag or loaded container allocated to this customer drop')
    name = identity['name']
    matched = [r for r in rows if r.handling_unit == name]
    if matched:
        return matched
    matched = [r for r in rows if r.container_handling_unit == name]
    if matched:
        from cfg_kanban.services.container_contents import active_container_contents
        contents = {r.content_handling_unit for r in active_container_contents(name)}
        allocated = {r.handling_unit for r in matched}
        if allocated != contents:
            frappe.throw('Container contents differ from this delivery; scan its individual allocated Stock Tags')
        return matched
    frappe.throw('This tag or container is not allocated to this customer drop')


def _check_sources(delivery, rows):
    from cfg_kanban.services.dispatch_fulfilment import assert_delivery_tag_expiry
    for row in rows:
        unit = frappe.get_doc('CFG Kanban Handling Unit', row.handling_unit)
        if (unit.inventory_company != delivery.selling_company
                or unit.current_warehouse != delivery.source_warehouse
                or unit.identity_state != 'Active' or unit.quality_state != 'Released'
                or any((unit.get(field) or '') != (row.get(field) or '') for field in ('item_code','batch_no','stock_uom'))
                or flt(unit.reserved_qty) + 0.000001 < flt(row.allocated_qty)):
            frappe.throw(f'Stock Tag {row.visible_code} no longer matches this reserved customer delivery')
        assert_delivery_tag_expiry(unit)


def _loose_rows(delivery, rows, code):
    from cfg_kanban.services.loose_tags import _pack
    pack = _pack(code, True)
    if (pack.delivery_session != delivery.name or pack.customer != delivery.customer
            or pack.company != delivery.selling_company or pack.state != 'In Delivery'
            or not pack.scanned_on):
        frappe.throw('This Loose Tag is not assigned and scanned at this customer drop')
    sources = {r.dispatch_allocation for r in pack.lines}
    matched = [r for r in rows if r.dispatch_allocation in sources]
    if not matched:
        frappe.throw('This Loose Tag has no accepted goods in this Delivery Session')
    return matched


def verify(delivery, values, operator, session, key):
    """Caller holds the authorized Delivery Session lock, including for duplicate requests."""
    if not cint(delivery.get('require_delivery_product_scan')):
        frappe.throw('Product verification is not required by this Delivery Session policy')
    if delivery.state not in ('Customer Identified', 'Allocating Stock', 'Awaiting Confirmation', 'ERP Document Pending'):
        frappe.throw('Product verification is closed for this Delivery Session; read its recorded outcome')
    if delivery.delivery_note and frappe.db.get_value('Delivery Note', delivery.delivery_note, 'docstatus') == 1:
        frappe.throw('This delivery is already posted; do not scan or deliver it again')
    rows = _rows(delivery, current=True)
    code = str(values.get('scan_value') or '').strip()
    allocation = values.get('delivery_allocation')
    if code and allocation:
        frappe.throw('Scan a physical tag or confirm one untagged quantity at a time')
    if code:
        matched = _loose_rows(delivery, rows, code) if code.startswith('CFG:LOOSE:') else _physical_rows(delivery, rows, code)
        if values.get('item_code') or values.get('qty') is not None:
            frappe.throw('Physical tag scans use the saved allocated Item and quantity')
        _check_sources(delivery, matched)
        kind = 'Physical QR'
    else:
        matched = [r for r in rows if r.name == allocation and not r.handling_unit]
        if len(matched) != 1:
            frappe.throw('Select an untagged allocation at this exact customer drop')
        row = matched[0]
        try:
            qty = float(values.get('qty'))
        except (ValueError, TypeError):
            frappe.throw('Enter the exact physically checked quantity in stock UOM')
        if (not math.isfinite(qty) or qty <= 0 or abs(qty-flt(row.allocated_qty)) > 0.000001
                or values.get('item_code') != row.item_code):
            frappe.throw(f'Confirm {row.item_code} / {row.batch_no or "No Batch"}: '
                f'exactly {row.allocated_qty} {row.stock_uom}')
        code = row.item_code
        kind = 'Untagged Item and quantity'
    changed = _ack(delivery, matched, operator, session, key, code, kind)
    return dict(changed=changed, product_verification=context(delivery))


@frappe.whitelist(methods=['POST'])
def verify_delivery_goods(delivery_session, event_token, operator_session_token, payload=None):
    operator, session = require_operator(operator_session_token, 'start')
    engine = _engine()
    engine._require_customer_delivery(operator)
    delivery = engine._delivery_for_operator(delivery_session, operator)
    values = frappe.parse_json(payload) if isinstance(payload, str) else ({} if payload is None else payload)
    if not isinstance(values, dict) or set(values)-{'scan_value','delivery_allocation','item_code','qty'}:
        frappe.throw('Unexpected delivery verification inputs')
    if not str(event_token or '').strip() or len(str(event_token)) > 200:
        frappe.throw('A stable delivery verification token is required')
    key = canonical_key('customer-drop-request', delivery.name, operator.employee, str(event_token))
    request_hash = canonical_key('customer-drop-request-inputs', values)
    prior = frappe.db.get_value('CFG Kanban Event', {'idempotency_key': key}, 'payload_json')
    if prior:
        receipt = json.loads(prior)
        if receipt.get('request_hash') != request_hash:
            frappe.throw('This verification token belongs to different original details')
        return receipt['result']
    result = verify(delivery, values, operator, session, key)
    record('Customer Drop Verification Recorded', delivery_session=delivery.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        idempotency_key=key, payload=dict(request_hash=request_hash, result=result))
    return result


def adopt_loose_scan(delivery, pack):
    """One existing box scan covers its accepted immutable allocation lines, including refusals."""
    if not cint(delivery.get('require_delivery_product_scan')) or not pack.scanned_on:
        return
    if (pack.delivery_session != delivery.name or pack.customer != delivery.customer
            or pack.company != delivery.selling_company or pack.state != 'In Delivery' or not pack.scanned_by):
        frappe.throw('Loose Tag verification belongs to another customer delivery')
    rows = _rows(delivery, current=True)
    sources = {r.dispatch_allocation for r in pack.lines}
    matched = [r for r in rows if r.dispatch_allocation in sources]
    operator = frappe._dict(employee=pack.scanned_by)
    # The immutable arrival audit owns the original scanner Session. Do not attribute
    # an assistant's earlier scan to whoever subsequently created this delivery.
    session = frappe._dict(name=None, terminal_user=frappe.session.user)
    _ack(delivery, matched, operator, session, canonical_key('loose-drop-scan', pack.name, delivery.name),
         pack.qr_payload, 'Loose Tag arrival scan', pack.scanned_on)


def validate_delivery_note(doc, method=None):
    """Also enforce the policy on ordinary ERPNext Draft submission, before any stock posting."""
    name = doc.get('cfg_delivery_session')
    if not name or doc.get('is_return'):
        return
    delivery = frappe.get_doc('CFG Kanban Delivery Session', name, for_update=True)
    if not cint(delivery.get('require_delivery_product_scan')):
        return
    if (doc.company != delivery.selling_company or doc.customer != delivery.customer
            or (delivery.delivery_note and delivery.delivery_note != doc.name)):
        frappe.throw('Delivery Note does not match the verified customer Delivery Session')
    assert_verified(delivery)

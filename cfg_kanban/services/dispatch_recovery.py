"""E5B1: guided whole-remainder recovery through the existing Manifest engine.

A recovery never reassigns the original vehicle, rewrites loading allocations or
settles a trip. Native movement feedback and a fresh D3 count remain mandatory.
"""
import json
from math import isfinite

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan

MANIFEST = 'CFG Kanban Movement Manifest'
ROUTE = 'CFG Kanban Logistics Route'
HU = 'CFG Kanban Handling Unit'
EPSILON = 0.000001
RECOVERY_ACTIONS = ('Returned to Warehouse', 'Transferred to Another Lorry')


class DispatchRecoveryReplayError(Exception):
    """A recovery request identity already belongs to different details."""


def _review_service():
    from cfg_kanban.services import dispatch_reconciliation
    return dispatch_reconciliation


def _logistics():
    from cfg_kanban.api import logistics
    return logistics


def _contents():
    from cfg_kanban.services import container_contents
    return container_contents


def _authorized(token, permission=None):
    review = _review_service()
    operator, session = review._authorized(token, permission)
    review._supervisor(operator)
    return operator, session


def _load(scan_value, operator):
    review = _review_service()
    value = str(scan_value or '').strip()
    name = value if frappe.db.exists(review.REVIEW, value) else None
    if not name and frappe.db.exists(MANIFEST, value):
        name = frappe.db.get_value(MANIFEST, value, 'dispatch_recovery_review')
    if not name:
        plan = review._plan(value, operator, current=True)
        name = plan.get('active_dispatch_review')
    if not name:
        frappe.throw('Begin a Dispatch Review before preparing a return or transfer')
    return review._locked_review(name, operator)


def _active(plan, review):
    if (review.state not in ('Reviewing', 'Held') or plan.state != 'Loaded'
            or plan.active_dispatch_review != review.name):
        frappe.throw('Recovery requires the active Reviewing or Held Dispatch Review')
    _review_service()._no_open_delivery(plan)


def _route(plan, name, operator=None):
    route = frappe.get_doc(ROUTE, name)
    if (not route.active or route.route_type != 'Internal Warehouse Transfer'
            or route.internal_transfer_mode != 'Direct Transfer'
            or route.source_company != plan.company or route.destination_company != plan.company
            or route.source_warehouse != plan.vehicle_warehouse
            or route.destination_warehouse == plan.vehicle_warehouse):
        frappe.throw('Choose an active same-Company Direct Transfer route from this Plan\'s lorry')
    review = _review_service()
    review._counts()._validate_vehicle_warehouse(plan.company, plan.vehicle_warehouse)
    wh = frappe.db.get_value('Warehouse', route.destination_warehouse,
        ['company', 'disabled', 'is_group', 'cfg_is_vehicle_warehouse', 'cfg_vehicle_reference'], as_dict=True)
    if not wh or wh.company != plan.company or wh.disabled or wh.is_group:
        frappe.throw('Recovery destination must be an active leaf Warehouse in this Company')
    action = RECOVERY_ACTIONS[1] if wh.cfg_is_vehicle_warehouse else RECOVERY_ACTIONS[0]
    if wh.cfg_is_vehicle_warehouse:
        review._counts()._validate_vehicle_warehouse(plan.company, route.destination_warehouse)
    if operator:
        for responsibility in (route.dispatch_responsibility, route.supervisor_responsibility):
            if not responsibility:
                frappe.throw('Recovery route must define Dispatch and Supervisor responsibilities')
            _logistics()._require_route_responsibility(operator, responsibility, 'recovery')
    return route, action


def _routes(plan, operator):
    result = []
    planning = _review_service()._planning()
    responsibilities = planning._responsibilities(operator)
    view_all = planning._view_all(operator)
    for route in frappe.get_all(ROUTE, filters=dict(active=1, route_type='Internal Warehouse Transfer',
            internal_transfer_mode='Direct Transfer', source_company=plan.company,
            destination_company=plan.company, source_warehouse=plan.vehicle_warehouse),
            fields=['name','destination_warehouse','dispatch_responsibility','supervisor_responsibility',
                    'auto_submit_internal_dispatch'], order_by='name', limit_page_length=0):
        required = {route.dispatch_responsibility, route.supervisor_responsibility}
        if None in required or '' in required or (not view_all and not required.issubset(responsibilities)):
            continue
        wh = frappe.db.get_value('Warehouse', route.destination_warehouse,
            ['company','disabled','is_group','cfg_is_vehicle_warehouse','cfg_vehicle_reference'], as_dict=True)
        if (not wh or wh.company != plan.company or wh.disabled or wh.is_group
                or route.destination_warehouse == plan.vehicle_warehouse
                or (wh.cfg_is_vehicle_warehouse and not wh.cfg_vehicle_reference)):
            continue
        action = RECOVERY_ACTIONS[1] if wh.cfg_is_vehicle_warehouse else RECOVERY_ACTIONS[0]
        result.append(dict(name=route.name, destination_warehouse=route.destination_warehouse,
            action=action, auto_submit=cint(route.auto_submit_internal_dispatch)))
    return result


def _recipe(rows):
    return [dict(dispatch_allocation=row['dispatch_allocation'], handling_unit=row['handling_unit'] or None,
        item_code=row['item_code'], batch_no=row['batch_no'] or None, stock_uom=row['stock_uom'],
        dispatch_qty=flt(row['remaining_qty'])) for row in rows if row['remaining_qty'] > EPSILON]


def _context(plan, review, token, manifest=None):
    result = _review_service()._current_context(plan, review)
    name = manifest.name if manifest else review.get('recovery_manifest')
    result['recovery_manifest'] = _logistics().get_manifest(name, token) if name else None
    result['recovery_routes'] = _routes(plan, _authorized(token)[0]) if review.state in ('Reviewing', 'Held') else []
    return result


@frappe.whitelist()
def get_dispatch_recovery_context(scan_value, operator_session_token):
    operator, _session = _authorized(operator_session_token)
    plan, review = _load(scan_value, operator)
    manifest = None
    if frappe.db.exists(MANIFEST, scan_value):
        candidate = frappe.get_doc(MANIFEST, scan_value)
        if candidate.dispatch_recovery_review == review.name:
            manifest = candidate
    return _context(plan, review, operator_session_token, manifest)


@frappe.whitelist()
def create_dispatch_recovery(dispatch_review, logistics_route, reason, balance_hash,
                             event_token, operator_session_token):
    review_service = _review_service()
    review_service._planning()._require_event_token(event_token)
    operator, session = _authorized(operator_session_token, 'override')
    plan, review = review_service._locked_review(dispatch_review, operator)
    reason = str(reason or '').strip()
    key = canonical_key('dispatch-recovery-create', review.name, event_token)
    fingerprint = canonical_key('dispatch-recovery-payload', logistics_route, reason, balance_hash)
    old = frappe.db.get_value(MANIFEST, {'preparation_key': key}, 'name', for_update=True)
    if old:
        manifest = frappe.get_doc(MANIFEST, old, for_update=True)
        if manifest.get('recovery_payload_hash') != fingerprint or manifest.dispatch_recovery_review != review.name:
            frappe.throw('This recovery token belongs to different details', DispatchRecoveryReplayError)
        return _context(plan, review, operator_session_token, manifest)
    _active(plan, review)
    if review.get('mixed_recovery_json'):
        from cfg_kanban.services.dispatch_recovery_mixed import active
        if active(review):
            frappe.throw('Use the frozen per-item recovery instead of creating a whole-remainder movement')
    if review.get('recovery_manifest'):
        old = frappe.get_doc(MANIFEST, review.recovery_manifest, for_update=True)
        if old.state != 'Cancelled':
            if old.recovery_payload_hash == fingerprint:
                return _context(plan, review, operator_session_token, old)
            frappe.throw('This Review already has a recovery Manifest; reopen it or cancel it before changing the destination')
    if not reason:
        frappe.throw('A Supervisor recovery reason is required')
    route, action = _route(plan, logistics_route, operator)
    rows = review_service._balances(plan, current=True)
    if not balance_hash or balance_hash != review_service._hash(rows):
        frappe.throw('Dispatch balances changed; refresh before preparing recovery')
    recipe = _recipe(rows)
    if not recipe:
        frappe.throw('No prepared stock remains to recover')
    review_service._at_source(plan, rows)
    _validate_loose(plan, recipe)
    manifest = frappe.get_doc(dict(doctype=MANIFEST, state='Draft', logistics_route=route.name,
        inventory_control_mode='ERP Stock', dispatch_recovery_review=review.name,
        recovery_action=action, recovery_reason=reason, recovery_snapshot_json=review_service._json(recipe),
        recovery_payload_hash=fingerprint, preparation_key=key,
        created_by_operator=operator.employee, created_operator_session=session.name,
        lines=[_manifest_line(plan, row, route.destination_warehouse) for row in recipe])).insert(ignore_permissions=True)
    review.db_set('recovery_manifest', manifest.name, update_modified=True)
    record('Dispatch Recovery Created', movement_manifest=manifest.name,
        reference_doctype=review.doctype, reference_name=review.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        device_id=key, notes=f'{action}; {route.destination_warehouse}; {reason}')
    return _context(plan, review, operator_session_token, manifest)


def _manifest_line(plan, row, destination):
    membership = _contents().active_container_membership(row['handling_unit']) if row['handling_unit'] else None
    container = membership.container_handling_unit if membership else None
    return dict(row, line_kind='Tagged Stock' if row['handling_unit'] else 'ERP Stock without Physical Tag',
        visible_code=frappe.db.get_value(HU, row['handling_unit'], 'handling_unit_id') if row['handling_unit'] else 'ERP STOCK',
        container_handling_unit=container,
        container_visible_code=frappe.db.get_value(HU, container, 'handling_unit_id') if container else None,
        source_company=plan.company, source_warehouse=plan.vehicle_warehouse,
        destination_company=plan.company, destination_warehouse=destination,
        available_qty_at_scan=row['dispatch_qty'], received_qty=0, loading_confirmed=0, state='Prepared')


def _locked_manifest(name, operator=None):
    link = frappe.db.get_value(MANIFEST, name, 'dispatch_recovery_review')
    if not link:
        frappe.throw('This Manifest is not a Dispatch Review recovery')
    review_service = _review_service()
    if operator:
        plan, review = review_service._locked_review(link, operator)
    else:
        # Native Stock Manager submission uses the saved Supervisor-approved recipe.
        plan_name = frappe.db.get_value(review_service.REVIEW, link, 'dispatch_plan')
        plan = frappe.get_doc('CFG Kanban Dispatch Plan', plan_name, for_update=True)
        review = frappe.get_doc(review_service.REVIEW, link, for_update=True)
    manifest = frappe.get_doc(MANIFEST, name, for_update=True)
    allowed = review.get('recovery_manifest') == name
    if manifest.get('recovery_bundle_key'):
        from cfg_kanban.services.dispatch_recovery_mixed import belongs
        allowed = belongs(review, manifest)
    if (not allowed or manifest.dispatch_recovery_review != review.name
            or review.company != plan.company or review.vehicle_warehouse != plan.vehicle_warehouse):
        frappe.throw('Recovery Manifest does not match its active Review and original lorry')
    return plan, review, manifest


def _validate_loose(plan, recipe):
    groups = {}
    for row in recipe:
        if row['handling_unit']:
            continue
        item = frappe.db.get_value('Item', row['item_code'],
            ['is_stock_item', 'has_serial_no', 'has_batch_no', 'stock_uom'], as_dict=True)
        if (not item or not item.is_stock_item or item.has_serial_no or item.stock_uom != row['stock_uom']
                or bool(item.has_batch_no) != bool(row['batch_no'])):
            frappe.throw('Loose recovery requires an exact stock Item/Batch/UOM; serial stock requires its physical tag')
        if row['batch_no'] and frappe.db.get_value('Batch', row['batch_no'], 'item') != row['item_code']:
            frappe.throw('Recovery Batch belongs to another Item')
        key = (row['item_code'], row['batch_no'])
        groups[key] = groups.get(key, 0) + row['dispatch_qty']
    planning = _review_service()._planning()
    for (item, batch), qty in groups.items():
        planning._lock_erp_bin(item, plan.vehicle_warehouse)
        available = planning._untagged_available(plan.company, plan.vehicle_warehouse, item, batch,
            exclude_prepared_plan=plan.name, current=True,
            **({'exclude_refusal_outcome':plan.driver_delivery_outcome} if plan.get('driver_delivery_outcome') else {}))
        if qty > available + EPSILON:
            frappe.throw('Loose recovery stock is missing or committed elsewhere; resolve it before moving leftovers')


def validate_recovery_manifest(manifest, operator=None, reserved=False, confirmed=True):
    plan, review, manifest = _locked_manifest(manifest.name, operator)
    _active(plan, review)
    route, action = _route(plan, manifest.logistics_route, operator)
    if (manifest.dispatch_plan or manifest.kanban_cycle or manifest.source_signal
            or manifest.manifest_type != 'Internal Warehouse Transfer'
            or manifest.inventory_control_mode != 'ERP Stock' or manifest.internal_transfer_mode != 'Direct Transfer'
            or manifest.source_company != plan.company or manifest.destination_company != plan.company
            or manifest.source_warehouse != plan.vehicle_warehouse
            or manifest.destination_warehouse != route.destination_warehouse or manifest.recovery_action != action):
        frappe.throw('Recovery Manifest route/source/destination differs from its approved recovery')
    expected = json.loads(manifest.recovery_snapshot_json or '[]')
    current = _recipe(_review_service()._balances(plan, current=True))
    if manifest.get('recovery_bundle_key'):
        from cfg_kanban.services.dispatch_recovery_mixed import expected_manifest
        current = expected_manifest(plan, review, manifest)
    if not expected or expected != current or len(manifest.lines) != len(expected):
        frappe.throw('Prepared remainder changed; cancel the unused recovery and review it again')
    by_allocation = {row['dispatch_allocation']: row for row in expected}
    seen = set()
    for row in manifest.lines:
        source = by_allocation.get(row.dispatch_allocation)
        if (not source or row.dispatch_allocation in seen
                or any((row.get(field) or None) != (source[field] or None)
                       for field in ('handling_unit', 'item_code', 'batch_no', 'stock_uom'))
                or abs(flt(row.dispatch_qty)-source['dispatch_qty']) > EPSILON
                or row.line_kind != ('Tagged Stock' if row.handling_unit else 'ERP Stock without Physical Tag')
                or row.source_company != plan.company or row.source_warehouse != plan.vehicle_warehouse
                or row.destination_company != plan.company or row.destination_warehouse != manifest.destination_warehouse):
            frappe.throw('Recovery lines must retain every exact prepared remainder and source allocation')
        seen.add(row.dispatch_allocation)
        if confirmed and not row.loading_confirmed:
            frappe.throw('Scan each physical recovery source and confirm every loose quantity first')
        if row.handling_unit:
            unit = frappe.get_doc(HU, row.handling_unit, for_update=True)
            refusal_reserve = _refused_reserve(plan, row.handling_unit)
            wanted_reserve = flt(row.dispatch_qty) if reserved else refusal_reserve
            if (unit.identity_state != 'Active' or unit.quality_state != 'Released'
                    or unit.inventory_company != plan.company or unit.current_warehouse != plan.vehicle_warehouse
                    or unit.item_code != row.item_code or (unit.batch_no or '') != (row.batch_no or '')
                    or unit.stock_uom != row.stock_uom or abs(flt(unit.current_qty)-flt(row.dispatch_qty)) > EPSILON
                    or abs(flt(unit.reserved_qty)-wanted_reserve) > EPSILON):
                frappe.throw('Recovery Stock Tag quantity/location/reservation changed; reconcile it before posting')
            _logistics()._assert_not_in_other_open_manifest(unit.name, manifest.name)
            _logistics()._assert_erp_stock(unit, manifest.source_warehouse, row.dispatch_qty)
            if not reserved and not refusal_reserve:
                _logistics()._validate_dispatch_unit(unit, manifest, expected_container=row.container_handling_unit or None)
            else:
                membership = _contents().active_container_membership(unit.name)
                if (membership.container_handling_unit if membership else None) != (row.container_handling_unit or None):
                    frappe.throw('Recovery Stock Tag container changed after its physical scan')
    _logistics()._validate_manifest_container_groups(manifest)
    _validate_loose(plan, expected)
    return plan, review, manifest


@frappe.whitelist()
def scan_dispatch_recovery(manifest_name, scan_value, event_token, operator_session_token):
    operator, session = _authorized(operator_session_token, 'start')
    _review_service()._planning()._require_event_token(event_token)
    plan, review, manifest = _locked_manifest(manifest_name, operator)
    if manifest.state != 'Draft':
        frappe.throw('Physical recovery confirmation requires a Draft Manifest')
    if str(scan_value or '').strip().startswith('CFG:LOOSE:'):
        from cfg_kanban.services.loose_tags import scan_group
        return scan_group(scan_value, lambda code: scan_dispatch_recovery(
            manifest_name, code, event_token, operator_session_token))
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity['identity_type'] != 'Handling Unit':
        frappe.throw('Scan an active Stock Tag or reusable container from this recovery')
    unit = frappe.get_doc(HU, identity['name'], for_update=True)
    container = unit if unit.tag_kind == 'Reusable Container' else None
    if container:
        _logistics()._validate_dispatch_container(container, manifest)
        units = [row.content_handling_unit for row in _contents().active_container_contents(container.name)]
        if not units:
            frappe.throw('Recovery container is empty')
    else:
        units = [unit.name]
    lines = [row for row in manifest.lines if row.handling_unit in units]
    if len(lines) != len(units):
        frappe.throw('Every tag in the scanned source must belong to this prepared remainder; split/repack other stock first')
    for row in lines:
        source = frappe.get_doc(HU, row.handling_unit, for_update=True)
        held = _refused_reserve(plan, source.name)
        if held and abs(held-flt(row.dispatch_qty)) > EPSILON:
            frappe.throw('Recovery reservation must cover this exact approved remainder')
        _logistics()._validate_dispatch_unit(source, manifest,
            expected_container=container.name if container else None,
            **({'allowed_reserved_qty':held} if held else {}))
        row.container_handling_unit = container.name if container else None
        row.container_visible_code = container.handling_unit_id if container else None
    for row in lines:
        row.loading_confirmed = 1
        row.loading_confirmed_by = operator.employee
        row.loading_confirmed_on = now_datetime()
    manifest.save(ignore_permissions=True)
    validate_recovery_manifest(manifest, operator, confirmed=False)
    record('Dispatch Recovery Source Scanned', movement_manifest=manifest.name,
        reference_doctype=HU, reference_name=unit.name, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        device_id=canonical_key('dispatch-recovery-scan', manifest.name, unit.name, event_token))
    return _context(plan, review, operator_session_token, manifest)


@frappe.whitelist()
def confirm_dispatch_recovery_loose(manifest_name, line_name, qty, event_token, operator_session_token):
    operator, session = _authorized(operator_session_token, 'start')
    _review_service()._planning()._require_event_token(event_token)
    plan, review, manifest = _locked_manifest(manifest_name, operator)
    if manifest.state != 'Draft':
        frappe.throw('Loose recovery confirmation requires a Draft Manifest')
    row = next((row for row in manifest.lines if row.name == line_name and not row.handling_unit), None)
    quantity = flt(qty)
    if not row or not isfinite(quantity) or quantity <= 0 or abs(quantity-flt(row.dispatch_qty)) > EPSILON:
        frappe.throw('Physically confirm the exact displayed loose Item/Batch/stock-UOM quantity')
    row.loading_confirmed = 1
    row.loading_confirmed_by = operator.employee
    row.loading_confirmed_on = now_datetime()
    manifest.save(ignore_permissions=True)
    validate_recovery_manifest(manifest, operator, confirmed=False)
    record('Dispatch Recovery Loose Stock Confirmed', movement_manifest=manifest.name,
        reference_doctype=manifest.doctype, reference_name=manifest.name, material_item=row.item_code,
        qty=quantity, operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        device_id=canonical_key('dispatch-recovery-loose', manifest.name, row.name, event_token))
    return _context(plan, review, operator_session_token, manifest)


def prepare_recovery_manifest(manifest, operator, session, event_token):
    _review_service()._supervisor(operator)
    _review_service()._planning()._require_event_token(event_token)
    # Refusal rows precede HU locks, matching Supervisor release order.
    if manifest.get('dispatch_recovery_review'):
        source_plan=frappe.db.get_value('CFG Kanban Dispatch Review',manifest.dispatch_recovery_review,'dispatch_plan')
        if source_plan and (frappe.db.get_value('CFG Kanban Dispatch Plan',source_plan,'driver_delivery_outcome') or frappe.db.get_value('CFG Kanban Dispatch Plan',source_plan,'has_loose_tags')):
            from cfg_kanban.services.driver_delivery_outcomes import lock_recovery_rows
            lock_recovery_rows(manifest)
        if source_plan and frappe.db.get_value('CFG Kanban Dispatch Plan',source_plan,'stop_cancellation'):
            from cfg_kanban.services.cancelled_stop_stock import lock_recovery_rows
            lock_recovery_rows(manifest)
    plan, review, manifest = validate_recovery_manifest(manifest, operator)
    if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
        from cfg_kanban.services.driver_delivery_outcomes import recovery_adopt
        recovery_adopt(manifest)
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import recovery_adopt
        recovery_adopt(manifest)
    for row in manifest.lines:
        if not row.handling_unit:
            continue
        _logistics().post_quantity_event(event_type='Reserve', qty=row.dispatch_qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key('manifest-reserve', manifest.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code, batch_no=row.batch_no,
            source_company=manifest.source_company, source_warehouse=manifest.source_warehouse,
            reference_doctype=manifest.doctype, reference_name=manifest.name,
            operator=operator.employee, operator_session=session.name, reason='Reserved for Dispatch Review recovery')
    manifest.db_set(dict(state='Prepared', prepared_on=now_datetime()), update_modified=True)
    record('Dispatch Recovery Prepared', movement_manifest=manifest.name,
        reference_doctype=review.doctype, reference_name=review.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user)


@frappe.whitelist()
def prepare_dispatch_recovery(manifest_name, event_token, operator_session_token):
    operator, _session = _authorized(operator_session_token, 'complete')
    plan, review, manifest = _locked_manifest(manifest_name, operator)
    _logistics().prepare_manifest(manifest.name, event_token, operator_session_token)
    return _context(plan, review, operator_session_token, manifest)


@frappe.whitelist()
def post_dispatch_recovery(manifest_name, event_token, operator_session_token, required_erp_inputs=None):
    operator, _session = _authorized(operator_session_token, 'complete')
    plan, review, manifest = _locked_manifest(manifest_name, operator)
    if manifest.state == 'Received':
        return _context(plan, review, operator_session_token, manifest)
    validate_recovery_manifest(manifest, operator, reserved=True)
    _logistics().confirm_dispatch(manifest.name, event_token, operator_session_token, required_erp_inputs)
    manifest.reload()
    return _context(plan, review, operator_session_token, manifest)


@frappe.whitelist()
def cancel_dispatch_recovery(manifest_name, reason, event_token, operator_session_token):
    operator, session = _authorized(operator_session_token, 'override')
    _review_service()._planning()._require_event_token(event_token)
    plan, review, manifest = _locked_manifest(manifest_name, operator)
    if manifest.state == 'Cancelled':
        return _context(plan, review, operator_session_token, manifest)
    _active(plan, review)
    if manifest.get('recovery_bundle_key'):
        frappe.throw('Cancel the whole unused per-item decision from Trip Handover; individual destination groups cannot be removed')
    reason = str(reason or '').strip()
    _cancel_unused(plan, review, manifest, reason, operator, session)
    return _context(plan, review, operator_session_token, manifest)


def _cancel_unused(plan, review, manifest, reason, operator, session):
    """Caller holds Plan/Review/member locks and has approved the complete cancellation."""
    if (manifest.state not in ('Draft', 'Prepared') or manifest.dispatch_stock_entry
            or manifest.dispatch_command or not reason):
        frappe.throw('Only an unused Draft/Prepared recovery can be cancelled, with a Supervisor reason; ERP work requires controlled resolution')
    if manifest.state == 'Prepared':
        for row in manifest.lines:
            if row.handling_unit:
                _logistics().post_quantity_event(event_type='Unreserve', qty=row.dispatch_qty, stock_uom=row.stock_uom,
                    idempotency_key=canonical_key('manifest-cancel-unreserve', manifest.name, row.name),
                    source_handling_unit=row.handling_unit, item_code=row.item_code, batch_no=row.batch_no,
                    source_company=plan.company, source_warehouse=plan.vehicle_warehouse,
                    reference_doctype=manifest.doctype, reference_name=manifest.name,
                    operator=operator.employee, operator_session=session.name, reason=reason)
    if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
        from cfg_kanban.services.driver_delivery_outcomes import recovery_restore
        recovery_restore(manifest)
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import recovery_restore
        recovery_restore(manifest)
    manifest.db_set(dict(state='Cancelled', cancelled_by=operator.employee,
        cancelled_on=now_datetime(), cancellation_reason=reason), update_modified=True)
    frappe.db.set_value('CFG Kanban Manifest Line', {'parent': manifest.name}, 'state', 'Cancelled', update_modified=False)
    record('Dispatch Recovery Cancelled', movement_manifest=manifest.name,
        reference_doctype=review.doctype, reference_name=review.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user, notes=reason)


def validate_recovery_stock_entry(doc):
    """Before native posting, including manual submission of a saved Stock Entry."""
    link = frappe.db.get_value(MANIFEST, doc.cfg_movement_manifest, 'dispatch_recovery_review')
    if not link:
        return
    manifest = frappe.get_doc(MANIFEST, doc.cfg_movement_manifest)
    if (doc.get('purpose') or doc.get('stock_entry_type')) != 'Material Transfer':
        frappe.throw('Recovery Stock Entry must remain a Material Transfer')
    if manifest.state not in ('Prepared', 'Dispatch Document Pending', 'Exception'):
        frappe.throw('Recovery Stock Entry requires its prepared recovery Manifest')
    if manifest.dispatch_stock_entry and manifest.dispatch_stock_entry != doc.name:
        frappe.throw('Submit the existing recovery Stock Entry; a substitute document is not allowed')
    validate_recovery_manifest(manifest, reserved=True)
    for row in doc.items:
        line = next((line for line in manifest.lines if line.name == row.get('cfg_manifest_line')), None)
        if (not line or (row.get('cfg_handling_unit') or None) != (line.handling_unit or None)
                or (row.stock_uom or row.uom) != line.stock_uom
                or (line.batch_no and not row.get('use_serial_batch_fields'))):
            frappe.throw('Recovery Stock Entry must retain its exact tag, Batch and stock UOM')


def assert_review_disposition(review, action=None, movement=None):
    """Do not abandon a reserved recovery or settle it against unrelated movement."""
    if review.get('mixed_recovery_json'):
        from cfg_kanban.services.dispatch_recovery_mixed import assert_disposition
        if assert_disposition(review, action, movement):
            return
    if not review.get('recovery_manifest'):
        return
    manifest = frappe.get_doc(MANIFEST, review.recovery_manifest, for_update=True)
    if manifest.state == 'Cancelled':
        return
    if (manifest.state != 'Received' or not movement or movement != manifest.dispatch_stock_entry
            or action != manifest.recovery_action):
        frappe.throw('Finish or cancel the linked recovery first; settlement must use its submitted Stock Entry and disposition')


def protect_recovery_draft_delete(doc, method=None):
    name = doc.get('cfg_movement_manifest')
    if name and frappe.db.get_value(MANIFEST, name, 'dispatch_recovery_review'):
        frappe.throw('Recovery Stock Entries are audit records; resolve the existing controlled movement instead of deleting its ERP document')


def protect_recovery_document_identity(doc, method=None):
    before = None if doc.is_new() else doc.get_doc_before_save()
    original = before.get('cfg_movement_manifest') if before else None
    if (original and original != doc.get('cfg_movement_manifest')
            and frappe.db.get_value(MANIFEST, original, 'dispatch_recovery_review')):
        frappe.throw('A saved recovery Stock Entry cannot be detached from its controlled Manifest')


def _refused_reserve(plan,unit):
    held=0
    if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
        from cfg_kanban.services.driver_delivery_outcomes import held_tag_qty
        held+=held_tag_qty(unit)
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import held_tag_qty
        held+=held_tag_qty(unit,dispatch_plan=plan.name,parent=plan.stop_cancellation)
    return held

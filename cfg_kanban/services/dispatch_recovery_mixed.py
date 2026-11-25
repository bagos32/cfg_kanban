"""E5B2: one frozen per-source decision, executed by existing recovery Manifests.

Stock stays committed until every movement and the final D3 count are settled.
Customer returns remain non-stock QC custody; no receipt or credit is created here.
"""
import json
from math import isfinite

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

KEEP = 'Keep on Lorry'
MOVE = 'Return / Transfer'
ACTION = 'Mixed Leftover Dispositions'
EPS = 0.000001


def _recovery():
    from cfg_kanban.services import dispatch_recovery
    return dispatch_recovery


def bundle(review):
    raw = review.get('mixed_recovery_json')
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        frappe.throw('The per-item recovery record needs Supervisor investigation')


def active(review):
    value = bundle(review)
    return value if value and value.get('active') else None


def belongs(review, manifest):
    value = active(review)
    return bool(value and manifest.get('recovery_bundle_key') == value['key']
        and manifest.name in [row['manifest'] for row in value['groups']])


def _native_route(plan, name, operator):
    recovery = _recovery()
    route, action = recovery._route(plan, name, operator)
    route.check_permission('read')
    for dt, identity in (('Company', plan.company), ('Warehouse', plan.vehicle_warehouse),
                         ('Warehouse', route.destination_warehouse)):
        frappe.get_doc(dt, identity).check_permission('read')
    return route, action


def _held(plan, source):
    held = []
    if plan.get('driver_delivery_outcome'):
        from cfg_kanban.services.driver_delivery_outcomes import held_rows
        held.extend(held_rows({'dispatch_allocation':source}, current=True))
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import rows, HELD, RECOVERY
        held.extend(rows({'dispatch_allocation':source, 'stock_state':['in',[HELD, RECOVERY]]}, True))
    return held


def _choices(plan, rows, raw, operator):
    if isinstance(raw, str):
        if len(raw) > 200000:
            frappe.throw('Too many per-item recovery choices')
        try:
            raw = json.loads(raw)
        except ValueError:
            frappe.throw('Enter valid per-item recovery choices')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
        frappe.throw('Choose the disposition of every remaining prepared source')
    sources = {row['dispatch_allocation']:row for row in rows if row['remaining_qty'] > EPS}
    totals, counts, choices, routes = {}, {}, [], {}
    for choice in raw:
        if not isinstance(choice, dict) or set(choice) != {'dispatch_allocation','action','logistics_route','qty'}:
            frappe.throw('Each recovery choice requires its exact source, action, route and quantity')
        name, action, route_name = choice['dispatch_allocation'], choice['action'], choice['logistics_route']
        if not isinstance(name, str) or name not in sources or action not in (KEEP, MOVE):
            frappe.throw('Choose a remaining source and a valid recovery action')
        source = sources[name]
        try:
            if isinstance(choice['qty'], bool):
                raise ValueError()
            qty = float(choice['qty'])
        except (TypeError, ValueError, OverflowError):
            frappe.throw('Recovery quantities must be positive finite stock-UOM quantities')
        if not isfinite(qty) or qty <= EPS:
            frappe.throw('Recovery quantities must be positive finite stock-UOM quantities')
        if frappe.db.get_value('UOM', source['stock_uom'], 'must_be_whole_number') and abs(qty-round(qty)) > EPS:
            frappe.throw('This stock UOM requires a whole-number recovery quantity')
        if action == KEEP:
            if route_name:
                frappe.throw('Stock kept on the lorry cannot have a transfer route')
            if _held(plan, name):
                frappe.throw('Refused or cancelled customer goods held for return cannot be released as next-trip stock; recover them first')
            route_name = None
        else:
            if not isinstance(route_name, str) or not route_name:
                frappe.throw('Select an approved destination route for each movement')
            if route_name not in routes:
                routes[route_name] = _native_route(plan, route_name, operator)
        totals[name] = totals.get(name, 0) + qty
        counts[name] = counts.get(name, 0) + 1
        choices.append(dict(dispatch_allocation=name, action=action, logistics_route=route_name, qty=qty))
    if set(totals) != set(sources) or any(abs(totals[name]-source['remaining_qty']) > EPS for name,source in sources.items()):
        frappe.throw('Per-item choices must account for every exact remaining quantity without gaps or excess')
    for name, source in sources.items():
        if counts[name] > 1 and (source['handling_unit'] or _held(plan, name)):
            frappe.throw('Keep each physical Stock Tag or held source together; use controlled split/repack before reviewing different destinations')
    merged = {}
    for choice in choices:
        key = (choice['dispatch_allocation'], choice['action'], choice['logistics_route'] or '')
        if key not in merged:
            merged[key] = dict(choice, qty=0)
        merged[key]['qty'] += choice['qty']
    return sorted(merged.values(), key=lambda row:(row['dispatch_allocation'],row['action'],row['logistics_route'] or '')), routes


def _recipe(value, route=None, keep=False):
    sources = {row['dispatch_allocation']:row for row in value['source_recipe']}
    result = []
    for choice in value['choices']:
        if (keep and choice['action'] == KEEP) or (not keep and choice['action'] == MOVE and choice['logistics_route'] == route):
            result.append(dict(sources[choice['dispatch_allocation']], dispatch_qty=choice['qty']))
    return result


def _unchanged(plan, value):
    recovery = _recovery()
    current = recovery._recipe(recovery._review_service()._balances(plan, current=True))
    if current != value['source_recipe']:
        frappe.throw('Prepared sources changed after per-item approval; investigate before recovery or settlement')


def expected_manifest(plan, review, manifest):
    for doc in (plan, review, manifest):
        doc.check_permission('read')
    _native_route(plan,manifest.logistics_route,None)
    value = active(review)
    if not belongs(review, manifest) or manifest.recovery_payload_hash != value['fingerprint']:
        frappe.throw('Recovery Manifest does not belong to the frozen per-item decision')
    if manifest.preparation_key != canonical_key('mixed-recovery-manifest', value['key'], manifest.logistics_route):
        frappe.throw('Recovery Manifest identity differs from the approved destination group')
    _unchanged(plan, value)
    return _recipe(value, manifest.logistics_route)


def context(plan, review):
    value = bundle(review)
    if not value:
        return None
    groups = []
    for group in value['groups']:
        doc = frappe.get_doc('CFG Kanban Movement Manifest', group['manifest'])
        doc.check_permission('read')
        groups.append(dict(manifest=doc.name, logistics_route=doc.logistics_route,
            destination_warehouse=doc.destination_warehouse, state=doc.state,
            stock_entry=doc.dispatch_stock_entry))
    return dict(active=bool(value['active']), choices=value['choices'], reason=value['reason'], groups=groups,
        all_received=all(row['state']=='Received' for row in groups),
        cancellation_allowed=bool(value['active']) and all(
            row['state'] in ('Draft','Prepared') and not row['stock_entry'] and
            not frappe.db.get_value('CFG Kanban Movement Manifest',row['manifest'],'dispatch_command') for row in groups))


@frappe.whitelist()
def get_plan_handover_context(dispatch_plan,operator_session_token):
    recovery=_recovery();service=recovery._review_service()
    operator,_session=recovery._authorized(operator_session_token)
    plan=service._plan(dispatch_plan,operator)
    plan.check_permission('read')
    for dt,name in (('Company',plan.company),('Warehouse',plan.vehicle_warehouse)):
        frappe.get_doc(dt,name).check_permission('read')
    review=frappe.get_doc(service.REVIEW,plan.active_dispatch_review) if plan.get('active_dispatch_review') else None
    if review:review.check_permission('read')
    result=service._current_context(plan,review)
    routes=[]
    for row in recovery._routes(plan,operator):
        if (frappe.has_permission(recovery.ROUTE,ptype='read',doc=row['name']) and
                frappe.has_permission('Warehouse',ptype='read',doc=row['destination_warehouse'])):
            routes.append(row)
    result['recovery_routes']=routes
    return result


@frappe.whitelist(methods=['POST'])
def create_mixed_dispatch_recovery(dispatch_review, dispositions, reason, balance_hash, event_token, operator_session_token):
    recovery = _recovery(); service = recovery._review_service()
    service._planning()._require_event_token(event_token)
    operator, session = recovery._authorized(operator_session_token, 'override')
    plan, review = service._locked_review(dispatch_review, operator)
    plan.check_permission('read'); review.check_permission('read')
    for dt,name in (('Company',plan.company),('Warehouse',plan.vehicle_warehouse)):
        frappe.get_doc(dt,name).check_permission('read')
    reason = str(reason or '').strip()
    if not reason:
        frappe.throw('A Supervisor reason is required for per-item recovery')
    # Replay uses the immutable original source quantities, not locations changed by posting.
    old = bundle(review)
    key = canonical_key('mixed-recovery-create', review.name, event_token)
    source_rows = [dict(row, remaining_qty=row['dispatch_qty']) for row in old['source_recipe']] if old and old['key']==key else service._balances(plan, current=True)
    choices, routes = _choices(plan, source_rows, dispositions, operator)
    fingerprint = canonical_key('mixed-recovery-payload', service._json(choices), reason, balance_hash)
    if old and old['key'] == key:
        if old['fingerprint'] != fingerprint:
            frappe.throw('This recovery token belongs to different per-item details', recovery.DispatchRecoveryReplayError)
        return recovery._context(plan, review, operator_session_token)
    recovery._active(plan, review)
    if old and old['active']:
        if old['fingerprint'] == fingerprint:
            return recovery._context(plan, review, operator_session_token)
        frappe.throw('Reopen the frozen per-item recovery or cancel it before changing destinations')
    if review.get('recovery_manifest'):
        previous = frappe.get_doc(recovery.MANIFEST, review.recovery_manifest, for_update=True)
        if previous.state != 'Cancelled':
            frappe.throw('Finish or cancel the existing whole-remainder recovery before choosing per-item dispositions')
    rows = service._balances(plan, current=True)
    if not balance_hash or balance_hash != service._hash(rows):
        frappe.throw('Dispatch balances changed; refresh before choosing per-item dispositions')
    service._at_source(plan, rows, current=True)
    source_recipe = recovery._recipe(rows)
    recovery._validate_loose(plan, source_recipe)
    value = dict(version=1,active=True,key=key,fingerprint=fingerprint,reason=reason,
                 source_recipe=source_recipe,choices=choices,groups=[])
    for route_name, (route, action) in sorted(routes.items()):
        recipe = _recipe(value, route_name)
        manifest = frappe.get_doc(dict(doctype=recovery.MANIFEST, state='Draft', logistics_route=route.name,
            inventory_control_mode='ERP Stock', dispatch_recovery_review=review.name,
            recovery_bundle_key=key, recovery_action=action, recovery_reason=reason,
            recovery_snapshot_json=service._json(recipe), recovery_payload_hash=fingerprint,
            preparation_key=canonical_key('mixed-recovery-manifest',key,route_name),
            created_by_operator=operator.employee, created_operator_session=session.name,
            lines=[recovery._manifest_line(plan,row,route.destination_warehouse) for row in recipe])).insert(ignore_permissions=True)
        value['groups'].append(dict(logistics_route=route_name,manifest=manifest.name))
    review.db_set(dict(mixed_recovery_json=service._json(value),
        recovery_manifest=value['groups'][0]['manifest'] if value['groups'] else None), update_modified=True)
    record('Per-item Dispatch Recovery Approved',reference_doctype=review.doctype,reference_name=review.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        device_id=key,notes=service._json(value))
    return recovery._context(plan,review,operator_session_token)


@frappe.whitelist(methods=['POST'])
def cancel_mixed_dispatch_recovery(dispatch_review, reason, event_token, operator_session_token):
    recovery = _recovery(); service = recovery._review_service()
    service._planning()._require_event_token(event_token)
    operator, session = recovery._authorized(operator_session_token,'override')
    plan, review = service._locked_review(dispatch_review,operator)
    plan.check_permission('read'); review.check_permission('read')
    value = bundle(review); reason = str(reason or '').strip()
    if not value or not reason:
        frappe.throw('Select a per-item recovery and provide a cancellation reason')
    key = canonical_key('mixed-recovery-cancel',review.name,event_token)
    if not value['active']:
        if value.get('cancel_key')==key and value.get('cancel_reason')!=reason:
            frappe.throw('This cancellation token belongs to a different reason',recovery.DispatchRecoveryReplayError)
        return recovery._context(plan,review,operator_session_token)
    recovery._active(plan,review)
    manifests = [frappe.get_doc(recovery.MANIFEST,row['manifest'],for_update=True) for row in value['groups']]
    if any(m.state not in ('Draft','Prepared') or m.dispatch_stock_entry or m.dispatch_command for m in manifests):
        frappe.throw('Per-item decisions cannot be cancelled after any ERP work begins; resolve the saved movements')
    # Validate every member before cancelling any; ordinary cancellation retains custody history.
    for manifest in manifests:
        recovery._cancel_unused(plan,review,manifest,reason,operator,session)
    value.update(active=False,cancel_key=key,cancel_reason=reason,cancelled_on=str(now_datetime()))
    review.db_set('mixed_recovery_json',service._json(value),update_modified=True)
    record('Per-item Dispatch Recovery Cancelled',reference_doctype=review.doctype,reference_name=review.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        device_id=key,notes=service._json(value))
    return recovery._context(plan,review,operator_session_token)


def assert_disposition(review, action=None, movement=None):
    value = active(review)
    if not value:
        return False
    if action != ACTION or movement:
        frappe.throw('Finish the frozen per-item recovery with Mixed Leftover Dispositions; it cannot be resumed or replaced by one movement')
    for row in value['groups']:
        manifest=frappe.get_doc('CFG Kanban Movement Manifest',row['manifest'],for_update=True)
        if manifest.state!='Received' or not manifest.dispatch_stock_entry:
            frappe.throw('Receive every per-item recovery movement before closing the review')
    return True


def settle(plan, review, rows, count):
    value = active(review)
    if not value:
        frappe.throw('Approve per-item dispositions before using mixed settlement')
    assert_disposition(review,ACTION)
    _unchanged(plan,value)
    service = _recovery()._review_service()
    current = {row['dispatch_allocation']:row for row in rows}
    for group in value['groups']:
        manifest=frappe.get_doc('CFG Kanban Movement Manifest',group['manifest'],for_update=True)
        expected=expected_manifest(plan,review,manifest)
        if expected != json.loads(manifest.recovery_snapshot_json):
            frappe.throw('Saved recovery quantities differ from the frozen per-item decision')
        subset=[dict(current[row['dispatch_allocation']],remaining_qty=row['dispatch_qty']) for row in expected]
        service._movement_evidence(plan,review,subset,manifest.dispatch_stock_entry,manifest.recovery_action,count)
    kept = _recipe(value,keep=True)
    for row in kept:
        if _held(plan,row['dispatch_allocation']):
            frappe.throw('Kept stock acquired a refusal/return hold; investigate before settlement')
    service._at_source(plan,[dict(current[row['dispatch_allocation']],remaining_qty=row['dispatch_qty']) for row in kept],current=True)


def protect_movement_cancellation(doc):
    name = doc.get('cfg_movement_manifest')
    if not name:
        return
    review_name = frappe.db.get_value('CFG Kanban Movement Manifest',name,'dispatch_recovery_review')
    if review_name:
        review=frappe.get_doc('CFG Kanban Dispatch Review',review_name,for_update=True)
        if review.state=='Completed' and active(review):
            frappe.throw('This movement settled a per-item Dispatch Review; use an audited follow-on movement')

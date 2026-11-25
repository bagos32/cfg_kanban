"""E4B: Open Route customer visits and controlled stock selection over the delivery engine."""
import json

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

class RouteReplayConflictError(Exception):
    """An original action exists; re-read its result instead of replacing it."""


class RouteActionVoidedError(Exception):
    """A persisted no-record cancellation prevents late execution of this action."""


STOP = 'CFG Kanban Route Stop'
ACTIVE_STOCK = ('Reserved', 'Delivery Pending', 'Exception', 'Delivered')
STOP_FIELDS = ['name', 'state', 'dispatch_plan', 'planned_sequence', 'actual_sequence',
               'customer_scan_point', 'site_name', 'customer', 'customer_address',
               'delivery_session', 'delivery_note', 'delivery_proof', 'started_on',
               'completed_on', 'started_by_operator', 'office_delivery_trip', 'office_stop_key', 'override_reason', 'override_approved_by', 'skip_reason']


def _engine():
    from cfg_kanban.services import customer_delivery
    return customer_delivery


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _fulfilment():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _locked_plan(name, operator):
    # Frappe 15 supports current locking reads for the document and its children.
    plan = frappe.get_doc('CFG Kanban Dispatch Plan', name, for_update=True)
    _planning()._assert_plan_authorized(plan, operator)
    return plan


def _exists_current(doctype, filters):
    return frappe.db.get_value(doctype, filters, 'name', for_update=True)


def _supervisor(operator):
    if operator.kanban_role not in ('Supervisor', 'Development Proxy') or not cint(operator.get('can_override')):
        frappe.throw('A Supervisor with Override permission must authorize this Route Stop action')


def _assert_route_plan(plan, loaded=True, allow_review=False):
    if not allow_review and (plan.get('dispatch_review_state') or plan.state=='Reconciled'):
        frappe.throw('Resolve the frozen Dispatch Review before changing this route')
    if plan.plan_type != 'Open Route Stock' or plan.fulfilment_mode != 'Vehicle Delivery':
        frappe.throw('Select an Open Route Stock / Vehicle Delivery Dispatch Plan')
    if plan.state in ('Cancelled', 'Exception') or (loaded and not _route_ready(plan)):
        frappe.throw('Open Route delivery requires a Loaded Plan; resolve preparation or its Exception first')
    if plan.get('sales_order'):
        frappe.throw('An Open Route Plan cannot bind one Customer Sales Order')


def _route_ready(plan):
    if plan.get('existing_lorry_stock_only'):
        from cfg_kanban.services.trip_dispatch import route_ready
        return route_ready(plan)
    return plan.state=='Loaded'


def _sequence_policy(plan):
    value = plan.get('stop_sequence_policy') or 'Flexible Order'
    if value not in ('Flexible Order', 'Planned Order'):
        frappe.throw('Invalid Customer Stop Sequence policy on this Plan')
    return value


def _assert_site_scope(plan, site):
    if site.selling_company != plan.company:
        frappe.throw('Customer Site belongs to another selling Company')
    if plan.get('customer_site') and plan.customer_site != site.name:
        frappe.throw('This Plan is restricted to another Customer Site')
    reference = plan.get('delivery_route_reference')
    if reference and (site.route_reference or '') != reference:
        frappe.throw('Customer Site is outside the configured Customer Delivery Route Reference')
    if plan.get('territory') and site.territory != plan.territory:
        parent = frappe.db.get_value('Territory', plan.territory, ['lft', 'rgt'], as_dict=True)
        child = frappe.db.get_value('Territory', site.territory, ['lft', 'rgt'], as_dict=True) if site.territory else None
        if not parent or not child or not (parent.lft <= child.lft and child.rgt <= parent.rgt):
            frappe.throw('Customer Site is outside the configured delivery Territory')


def _stops(plan, current=False):
    rows = (frappe.db.get_values(STOP, {'dispatch_plan': plan.name}, STOP_FIELDS,
                               as_dict=True, for_update=True) if current else
            frappe.get_all(STOP, filters={'dispatch_plan': plan.name}, fields=STOP_FIELDS,
                           limit_page_length=0))
    return sorted(rows, key=lambda r: (cint(r.planned_sequence) or 1000000,
                                      cint(r.actual_sequence), str(r.name)))


def plan_context(plan, operator):
    _planning()._assert_plan_authorized(plan, operator)
    _assert_route_plan(plan, loaded=False, allow_review=True)
    stops = _stops(plan)
    active = next((row for row in stops if row.name == plan.get('active_route_stop')), None)
    can_resume = not active or not active.delivery_session or _engine()._can_view_delivery(
        operator, frappe.get_doc('CFG Kanban Delivery Session',active.delivery_session))
    customer_role = _engine()._customer_delivery_allowed(operator) and not plan.get('dispatch_review_state') and plan.state!='Reconciled'
    return {'name': plan.name, 'business_label': plan.business_label, 'company': plan.company,
            'state': plan.state, 'vehicle_warehouse': plan.vehicle_warehouse,
            'vehicle_reference': plan.vehicle_reference, 'stop_sequence_policy': _sequence_policy(plan),
            'delivery_route_reference': plan.get('delivery_route_reference'),
            'territory': plan.territory, 'stops': stops, 'can_resume_stop': bool(can_resume and not plan.get('dispatch_review_state')), 'dispatch_review_state':plan.get('dispatch_review_state'),
            'can_approve_order': bool(customer_role and cint(plan.get('allow_supervisor_override')) and
                                      operator.kanban_role in ('Supervisor','Development Proxy') and cint(operator.get('can_override'))),
            'can_plan_stops': bool(customer_role and operator.kanban_role in ('Supervisor', 'Development Proxy') and
                                   cint(operator.get('can_override'))),
            'active_route_stop': plan.get('active_route_stop')}


@frappe.whitelist()
def route_context(scan_value, operator_session_token, dispatch_plan=None):
    operator, _session = require_operator(operator_session_token)
    engine = _engine()
    engine._require_customer_delivery(operator)
    value = str(scan_value or '').strip()
    if value.upper().startswith('DPL-') or frappe.db.exists('CFG Kanban Dispatch Plan', value):
        plan = frappe.get_doc('CFG Kanban Dispatch Plan', value)
        return {'plans': [plan_context(plan, operator)], 'customer_scan': None}
    site = engine._resolve_customer_site(value)
    if dispatch_plan:
        plan = frappe.get_doc('CFG Kanban Dispatch Plan',dispatch_plan)
        _planning()._assert_plan_authorized(plan,operator)
        _assert_route_plan(plan,loaded=False)
        _assert_site_scope(plan,site)
        return {'plans':[plan_context(plan,operator)],'customer_scan':value,'customer_site':site.name}
    return {'plans': eligible_route_plans(site, operator), 'customer_scan': value, 'customer_site': site.name}


def eligible_route_plans(site, operator):
    if not _engine()._customer_delivery_allowed(operator):
        return []
    names = frappe.get_all('CFG Kanban Dispatch Plan', filters={
        'plan_type': 'Open Route Stock', 'fulfilment_mode': 'Vehicle Delivery',
        'state': ['in',['Loaded','Ready for Fulfilment']], 'company': site.selling_company}, pluck='name',
        order_by='loaded_on asc, name asc', limit_page_length=200)
    plans = []
    for name in names:
        plan = frappe.get_doc('CFG Kanban Dispatch Plan', name)
        if not _route_ready(plan) or plan.get('dispatch_review_state'):
            continue
        if not (_planning()._view_all(operator) or plan.dispatch_responsibility in _planning()._responsibilities(operator)):
            continue
        # Queue filtering is read-only. A specific Plan/scan still gets an exact rejection.
        if plan.get('customer_site') and plan.customer_site != site.name:
            continue
        if plan.get('delivery_route_reference') and plan.delivery_route_reference != site.route_reference:
            continue
        if plan.get('territory') and site.territory != plan.territory:
            parent = frappe.db.get_value('Territory', plan.territory, ['lft','rgt'], as_dict=True)
            child = frappe.db.get_value('Territory', site.territory, ['lft','rgt'], as_dict=True) if site.territory else None
            if not parent or not child or not (parent.lft <= child.lft and child.rgt <= parent.rgt):
                continue
        plans.append(plan_context(plan, operator))
    return plans


def _new_stop(plan, site, operator, key, planned_sequence=0, retry_of=None):
    return frappe.get_doc({'doctype': STOP, 'state': 'Planned', 'dispatch_plan': plan.name,
        'company': plan.company, 'customer_scan_point': site.name, 'site_name': site.site_name,
        'customer': site.customer, 'customer_address': site.customer_address,
        'planned_sequence': planned_sequence, 'created_by_operator': operator.employee,
        'created_on': now_datetime(), 'idempotency_key': key, 'retry_of_stop': retry_of,
    }).insert(ignore_permissions=True)


def _scan_matches_site(scan, site_name):
    identity = _engine().resolve_logistics_scan(scan)
    if not identity or identity.get('identity_type') != 'Customer Scan Point' or identity['name'] != site_name:
        frappe.throw('Scan the Customer Site assigned to this Route Stop')


@frappe.whitelist()
def add_route_stop(dispatch_plan, customer_scan, event_token, operator_session_token):
    _planning()._require_event_token(event_token)
    operator, session = require_operator(operator_session_token, 'start')
    _engine()._require_customer_delivery(operator)
    _supervisor(operator)
    plan = _locked_plan(dispatch_plan, operator)
    _assert_route_plan(plan, loaded=False)
    key = canonical_key('route-stop-plan', plan.name, event_token)
    existing = frappe.db.get_value(STOP, {'idempotency_key': key}, 'name', for_update=True)
    if existing:
        stop = frappe.get_doc(STOP, existing)
        _scan_matches_site(customer_scan, stop.customer_scan_point)
        return stop.as_dict()
    _assert_not_voided('plan', key)
    site = _engine()._resolve_customer_site(customer_scan)
    _assert_site_scope(plan, site)
    sequence = max([cint(row.planned_sequence) for row in _stops(plan, current=True)] or [0]) + 1
    stop = _new_stop(plan, site, operator, key, sequence)
    record('Customer Route Stop Planned', reference_doctype=STOP, reference_name=stop.name,
           operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
           device_id=key, notes=f'{plan.name}; planned stop {sequence}; {site.site_code}')
    return stop.as_dict()


@frappe.whitelist()
def approve_route_stop_order(route_stop, reason, event_token, operator_session_token):
    return _stop_supervisor_action(route_stop, reason, event_token, operator_session_token, 'approve')


@frappe.whitelist()
def skip_route_stop(route_stop, reason, event_token, operator_session_token):
    return _stop_supervisor_action(route_stop, reason, event_token, operator_session_token, 'skip')


def _stop_supervisor_action(name, reason, event_token, token, action):
    _planning()._require_event_token(event_token)
    operator, session = require_operator(token, 'complete')
    _engine()._require_customer_delivery(operator)
    _supervisor(operator)
    reason = str(reason or '').strip()
    if not reason:
        frappe.throw('A Supervisor reason is required')
    stop = frappe.get_doc(STOP, name)
    plan = _locked_plan(stop.dispatch_plan, operator)
    _assert_route_plan(plan, loaded=False)
    stop = frappe.get_doc(STOP, name, for_update=True)
    key = canonical_key('route-stop-' + action, stop.name, event_token)
    field, reason_field = ('override_key', 'override_reason') if action == 'approve' else ('skip_key', 'skip_reason')
    if stop.get(field) == key:
        if stop.get(reason_field) != reason:
            frappe.throw('This Route Stop action token belongs to another reason', RouteReplayConflictError)
        return stop.as_dict()
    previous = frappe.db.get_value('CFG Kanban Event', {'device_id':key,
        'reference_doctype':STOP,'reference_name':stop.name}, ['notes'], as_dict=True, for_update=True)
    if previous:
        if previous.notes != f'{plan.name}; {reason}':
            frappe.throw('This Route Stop action token belongs to another reason', RouteReplayConflictError)
        return stop.as_dict()
    _assert_not_voided('approve' if action=='approve' else 'skip', key)
    if stop.state != 'Planned' or stop.delivery_session:
        frappe.throw('Only an unstarted Planned Route Stop can be approved or skipped')
    if action == 'approve':
        if not cint(plan.get('allow_supervisor_override')):
            frappe.throw('This Dispatch Plan does not permit a controlled Supervisor override')
        values = {'override_reason': reason, 'override_approved_by': operator.employee,
                  'override_approved_on': now_datetime(), 'override_key': key}
    else:
        values = {'state': 'Skipped', 'skip_reason': reason, 'skipped_by': operator.employee,
                  'skipped_on': now_datetime(), 'skip_key': key}
    stop.db_set(values, update_modified=True)
    record('Customer Route Stop Order Approved' if action == 'approve' else 'Customer Route Stop Skipped',
           reference_doctype=STOP, reference_name=stop.name, operator=operator.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           device_id=key, notes=f'{plan.name}; {reason}')
    return stop.as_dict()


def _route_sources(plan):
    return _fulfilment()._loaded_allocations(plan, for_update=True)


def _source_used(source_name, delivered_only=False):
    states = ['Delivered'] if delivered_only else list(ACTIVE_STOCK)
    rows = frappe.db.get_values('CFG Kanban Delivery Allocation',
        {'dispatch_allocation': source_name, 'state': ['in', states]}, ['allocated_qty'],
        as_dict=True, for_update=True)
    return sum(flt(row.allocated_qty) for row in rows)


def _remaining(source):
    return max(flt(source.allocated_qty) - _source_used(source.name), 0)


def _validate_loaded_route(plan):
    if plan.get('existing_lorry_stock_only'):
        from cfg_kanban.services.trip_dispatch import existing_pool
        if not existing_pool(plan) or not _route_ready(plan):frappe.throw('Existing lorry stock pool is not ready')
        _engine()._vehicle_warehouse(plan.vehicle_warehouse,plan.company)
        return
    if plan.get('follow_on_trip'):
        from cfg_kanban.services.trip_carry_in import validate_loading
        validate_loading(plan)
    else:
        manifest = frappe.get_doc('CFG Kanban Movement Manifest', plan.movement_manifest)
        if (manifest.dispatch_plan != plan.name or manifest.state != 'Received' or
                manifest.source_company != plan.company or manifest.source_warehouse != plan.source_warehouse or
                manifest.destination_company != plan.company or manifest.destination_warehouse != plan.vehicle_warehouse):
            frappe.throw('Open Route requires the completed loading Manifest for this lorry')
        posted = frappe.db.get_value('Stock Entry', manifest.dispatch_stock_entry,
                                    ['docstatus','company'], as_dict=True) if manifest.dispatch_stock_entry else None
        if not posted or posted.docstatus != 1 or posted.company != plan.company:
            frappe.throw('Open Route lorry loading must have a submitted Stock Entry')
    _engine()._vehicle_warehouse(plan.vehicle_warehouse, plan.company)
    sources = _route_sources(plan)
    for item in sorted({row.item_code for row in sources}):
        _planning()._lock_erp_bin(item, plan.vehicle_warehouse)
    groups = {}
    for source in sources:
        remaining = _remaining(source)
        if remaining <= 0.000001:
            continue
        if source.handling_unit:
            frappe.db.sql('select name from `tabCFG Kanban Handling Unit` where name=%s for update', source.handling_unit)
            unit = frappe.get_doc('CFG Kanban Handling Unit', source.handling_unit, for_update=True)
            expected = flt(source.allocated_qty) - _source_used(source.name, delivered_only=True)
            if (unit.inventory_company != plan.company or unit.current_warehouse != plan.vehicle_warehouse or
                    unit.item_code != source.item_code or (unit.batch_no or '') != (source.batch_no or '') or
                    unit.stock_uom != source.stock_uom or abs(flt(unit.current_qty)-expected)>0.000001):
                frappe.throw('Prepared route Stock Tag moved or its quantity changed; reconcile before another visit')
        else:
            key = (source.item_code, source.batch_no or '')
            groups[key] = groups.get(key, 0) + remaining
    for (item, batch), qty in groups.items():
        available = _planning()._untagged_available(plan.company, plan.vehicle_warehouse, item, batch or None,
                                                    exclude_prepared_plan=plan.name)
        if qty > available + 0.000001:
            frappe.throw('Prepared loose route stock is missing or committed elsewhere; reconcile before another visit')


@frappe.whitelist()
def start_route_stop(dispatch_plan, customer_scan, event_token, operator_session_token, route_stop=None):
    _planning()._require_event_token(event_token)
    operator, session = require_operator(operator_session_token, 'start')
    engine = _engine()
    engine._require_customer_delivery(operator)
    candidate=frappe.get_doc('CFG Kanban Dispatch Plan',dispatch_plan)
    from cfg_kanban.services.trip_sequence_scope import sequence_trip
    sequence_name=sequence_trip(frappe,candidate)
    if sequence_name:
        from cfg_kanban.services.trip_sequence import lock_plan, native_target, native_order_permitted
        lock_plan(candidate)
    elif candidate.get('office_delivery_trip'):
        from cfg_kanban.services.trip_sales import lock_scope
        lock_scope(candidate)
    route_scope_lock=None
    if candidate.get('route_approval_required') or candidate.get('route_sequence_scope')=='Combined Lorry Trip' or candidate.get('active_route_sheet'):
        from cfg_kanban.services.route_sheets import lock_plan_route_scope, check_plan_route_scope
        route_scope_lock=lock_plan_route_scope(candidate,operator)
    plan = _locked_plan(dispatch_plan, operator)
    if sequence_trip(frappe,plan)!=sequence_name:frappe.throw('Trip assignment changed; refresh before starting this route stop')
    if route_scope_lock:check_plan_route_scope(plan,route_scope_lock)
    key = canonical_key('route-stop-start', plan.name, event_token)
    identity = engine.resolve_logistics_scan(customer_scan)
    if not identity or identity.get('identity_type') != 'Customer Scan Point':
        frappe.throw('Scan an active Customer Site')
    request_hash = canonical_key('route-stop-start-payload', identity['name'], route_stop or '')
    replay = frappe.db.get_value(STOP, {'start_key': key}, 'name', for_update=True)
    if replay:
        stop = frappe.get_doc(STOP, replay)
        if stop.start_payload_hash != request_hash:
            frappe.throw('This visit token belongs to another Customer Site or Route Stop', RouteReplayConflictError)
        if not stop.delivery_session:
            frappe.throw('Recorded Route Stop has no Delivery Session; Supervisor recovery is required')
        return engine.get_delivery_session(stop.delivery_session, operator_session_token)
    _assert_not_voided('visit', key)
    if plan.get('office_delivery_trip'):
        from cfg_kanban.services.trip_sales import authorize
        authorize(plan,operator,identity['name'],route_stop)
    _assert_route_plan(plan)
    if plan.get('active_route_stop'):
        stop = frappe.get_doc(STOP, plan.active_route_stop)
        if stop.customer_scan_point != identity['name'] or (route_stop and route_stop != stop.name):
            frappe.throw('Complete or cancel the active Route Stop before visiting another Customer Site')
        return engine.get_delivery_session(stop.delivery_session, operator_session_token)
    site = engine._resolve_customer_site(customer_scan)
    _assert_site_scope(plan, site)
    planned = [row for row in _stops(plan, current=True) if row.state == 'Planned']
    matches = [row for row in planned if row.customer_scan_point == site.name]
    if not route_stop and len(matches)>1:
        frappe.throw('Several planned visits match this Customer Site; select the exact numbered Stop')
    stop = frappe.get_doc(STOP, route_stop or matches[0].name, for_update=True) if (route_stop or matches) else None
    if stop and (stop.dispatch_plan != plan.name or stop.customer_scan_point != site.name or stop.state != 'Planned'):
        frappe.throw('Select a Planned Stop for this exact Plan and Customer Site')
    if stop and (stop.customer != site.customer or stop.customer_address != site.customer_address):
        frappe.throw('Planned Customer Site details changed; Supervisor must skip/replan this Stop')
    sequence_target=native_target(plan,site.name,stop.name if stop else None,operator,operator_session_token) if sequence_name else None
    if _sequence_policy(plan) == 'Planned Order':
        if not stop or not cint(stop.planned_sequence):
            frappe.throw('Planned Order requires a Supervisor-planned Customer Stop')
        next_stop = next((row for row in planned if cint(row.planned_sequence)>0), None)
        approved=bool(stop.override_approved_by and stop.override_reason) or bool(sequence_name and native_order_permitted(plan,site.name,stop.name))
        if next_stop and next_stop.name != stop.name and not approved:
            frappe.throw('Visit the next planned Customer Stop or obtain a reasoned Supervisor sequence approval')
    if plan.get('route_approval_required') or plan.get('route_sequence_scope')=='Combined Lorry Trip' or plan.get('active_route_sheet'):
        from cfg_kanban.services.route_sheets import assert_visit_allowed
        assert_visit_allowed(plan,site.name,stop.name if stop else None)
    _validate_loaded_route(plan)
    if not stop:
        stop = _new_stop(plan, site, operator, canonical_key('route-stop-unplanned', key))
    policy = plan.proof_policy
    if not policy or policy == 'Inherit Customer Site':
        policy = site.proof_policy
    if policy not in ('Required','Optional','Unattended Delivery Allowed','No Proof Required'):
        frappe.throw('Unsupported route proof policy')
    snapshot = json.loads(plan.profile_snapshot_json)
    delivery = engine._start_delivery_session(site, plan.vehicle_warehouse, key, operator, session,
        snapshots={'dispatch_plan': plan.name, 'route_stop': stop.name, 'proof_policy': policy,
                   'auto_submit_delivery_note': cint(snapshot.get('auto_submit_delivery_note'))})
    actual = cint(plan.get('actual_stop_count')) + 1
    stop.db_set({'state':'In Progress','actual_sequence':actual,
        'actual_sequence_key':f'{plan.name}:{actual}', 'active_stop_key':plan.name,
        'source_warehouse':plan.vehicle_warehouse,'vehicle_reference':plan.vehicle_reference,
        'started_by_operator':operator.employee,'started_on':now_datetime(),
        'start_key':key,'start_payload_hash':request_hash,'delivery_session':delivery.name}, update_modified=True)
    plan.db_set({'active_route_stop':stop.name,'actual_stop_count':actual,
                 'route_stock_commitment':1,'fulfilment_status':'In Progress'}, update_modified=True)
    record('Customer Route Stop Started', reference_doctype=STOP, reference_name=stop.name,
           delivery_session=delivery.name, operator=operator.employee, operator_session=session.name,
           terminal_user=session.terminal_user, device_id=key,
           notes=f'{plan.name}; planned {stop.planned_sequence or 0}; actual {actual}; {site.site_code}')
    if sequence_target:
        sequence_target[0].db_set('driver_active_stop_key',sequence_target[1].stop_key,update_modified=True)
    elif plan.get('office_delivery_trip'):
        frappe.db.set_value('CFG Kanban Delivery Trip',plan.office_delivery_trip,'driver_active_stop_key',stop.office_stop_key,update_modified=True)
    return engine.get_delivery_session(delivery.name, operator_session_token)


def _delivery_context(name, operator):
    engine = _engine()
    engine._require_customer_delivery(operator)
    candidate=frappe.get_doc('CFG Kanban Delivery Session',name)
    if candidate.get('dispatch_plan'):
        source=frappe.get_doc('CFG Kanban Dispatch Plan',candidate.dispatch_plan)
        if source.get('office_delivery_trip'):
            from cfg_kanban.services.trip_sales import lock_scope
            lock_scope(source)
    delivery = frappe.get_doc('CFG Kanban Delivery Session', name, for_update=True)
    if not engine._can_view_delivery(operator, delivery):
        frappe.throw('Operator cannot access this Delivery Session')
    if not delivery.get('route_stop') or not delivery.dispatch_plan:
        frappe.throw('Select an Open Route Delivery Session')
    plan = _locked_plan(delivery.dispatch_plan, operator)
    _assert_route_plan(plan)
    stop = frappe.get_doc(STOP, delivery.route_stop, for_update=True)
    if (stop.dispatch_plan != plan.name or stop.delivery_session != delivery.name or
            stop.customer_scan_point != delivery.customer_scan_point or
            stop.customer != delivery.customer or stop.customer_address != delivery.customer_address or
            delivery.source_warehouse != plan.vehicle_warehouse or delivery.selling_company != plan.company):
        frappe.throw('Route Stop, Delivery Session and lorry context do not match')
    return delivery, plan


def _unit_choice(unit, delivery, plan, container=None, container_code=None):
    engine = _engine()
    engine._validate_allocation_unit(unit, delivery, expected_container=container)
    _fulfilment().assert_delivery_tag_expiry(unit)
    source = next((row for row in _route_sources(plan) if row.handling_unit == unit.name and _remaining(row)>0.000001), None)
    maximum = min(flt(unit.available_qty), _remaining(source)) if source else flt(unit.available_qty)
    if maximum <= 0.000001:
        frappe.throw('No unallocated route quantity remains for this Stock Tag')
    return {'source_key': source.name if source else 'unassigned',
            'source_kind': 'Prepared Route Stock' if source else 'Unassigned Lorry Stock',
            'allocation_kind': 'Tagged Stock', 'handling_unit': unit.name,
            'visible_code': unit.handling_unit_id, 'item_code': unit.item_code,
            'batch_no': unit.batch_no, 'stock_uom': unit.stock_uom, 'available_qty': maximum,
            'physical_qty': flt(unit.available_qty), 'full_quantity_only': bool(unit.serial_count),
            'container': container, 'container_visible_code': container_code}


def _stock_context(delivery, plan, scan_value=None, item_code=None, batch_no=None):
    engine, planning = _engine(), _planning()
    if scan_value:
        identity = engine.resolve_logistics_scan(scan_value)
        if identity and identity.get('identity_type') == 'Handling Unit':
            unit = frappe.get_doc('CFG Kanban Handling Unit', identity['name'], for_update=True)
            if unit.tag_kind != 'Reusable Container' and ((item_code and item_code != unit.item_code) or
                    (batch_no and batch_no != unit.batch_no)):
                frappe.throw('Scanned Stock Tag does not match the selected Item or Batch')
            if unit.tag_kind == 'Reusable Container':
                engine._validate_container(unit, delivery)
                contents = engine.active_container_contents(unit.name)
                if not contents:
                    frappe.throw('Reusable container is empty')
                rows = [_unit_choice(frappe.get_doc('CFG Kanban Handling Unit', row.content_handling_unit, for_update=True),
                        delivery, plan, unit.name, unit.handling_unit_id) for row in contents]
                if len(rows)==1 and unit.get('reusable_container_role') in ('Production Output Container','Logistics Quantity Bin'):
                    return {'mode':'stock_tag','choices':rows}
                if any(abs(row['available_qty']-row['physical_qty'])>0.000001 for row in rows):
                    frappe.throw('A full-container delivery must fit every current tag quantity; split/repack first')
                return {'mode':'container','choices':[{'source_key':'container','source_kind':'Full Container',
                        'container':unit.name,'container_visible_code':unit.handling_unit_id,
                        'contents':rows,'full_quantity_only':True}]}
            return {'mode':'stock_tag','choices':[_unit_choice(unit,delivery,plan)]}
        if not identity and frappe.db.exists('Item', scan_value):
            item_code = scan_value
        else:
            frappe.throw('Scan an active Stock Tag, reusable container, or select the exact ERP Item')
    if not item_code:
        return {'mode':'item','choices':[]}
    inventory = frappe.db.get_value('Item', item_code,
        ['name','is_stock_item','has_serial_no','has_batch_no','stock_uom','disabled'], as_dict=True)
    if not inventory or inventory.disabled or not inventory.is_stock_item or inventory.has_serial_no:
        frappe.throw('Untagged route delivery requires an enabled non-serialized ERP stock Item')
    if inventory.has_batch_no and not batch_no:
        return {'mode':'item','item_code':item_code,'requires_batch':True,'choices':[]}
    planning._validate_batch(item_code, batch_no)
    _fulfilment()._assert_untagged_batch_expiry(batch_no)
    planning._lock_erp_bin(item_code, plan.vehicle_warehouse)
    available_prepared = planning._untagged_available(plan.company, plan.vehicle_warehouse,
        item_code,batch_no,exclude_prepared_plan=plan.name)
    choices=[]
    for source in _route_sources(plan):
        if source.handling_unit or source.item_code != item_code or (source.batch_no or '') != (batch_no or ''):
            continue
        qty=min(_remaining(source),available_prepared)
        if qty>0.000001:
            choices.append({'source_key':source.name,'source_kind':'Prepared Route Stock',
                'allocation_kind':'Untagged ERP Stock','handling_unit':None,'item_code':item_code,
                'batch_no':batch_no,'stock_uom':inventory.stock_uom,'available_qty':qty})
    free = planning._untagged_available(plan.company, plan.vehicle_warehouse, item_code,batch_no)
    if free>0.000001:
        choices.append({'source_key':'unassigned','source_kind':'Unassigned Lorry Stock',
            'allocation_kind':'Untagged ERP Stock','handling_unit':None,'item_code':item_code,
            'batch_no':batch_no,'stock_uom':inventory.stock_uom,'available_qty':free})
    return {'mode':'item','item_code':item_code,'batch_no':batch_no,'choices':choices}


@frappe.whitelist()
def route_stock_context(delivery_session, operator_session_token, scan_value=None, item_code=None, batch_no=None):
    operator, _session = require_operator(operator_session_token, 'start')
    delivery, plan = _delivery_context(delivery_session, operator)
    if plan.get('office_delivery_trip'):
        from cfg_kanban.services.trip_sales import authorize
        authorize(plan,operator,delivery.customer_scan_point,delivery.route_stop)
    _engine()._assert_allocation_session(delivery)
    return _stock_context(delivery, plan, scan_value, item_code, batch_no)


def _reserve_choice(delivery, plan, choice, qty, event_token, operator, session, request_key, request_hash):
    engine = _engine()
    qty=flt(qty)
    if qty<=0 or qty>flt(choice['available_qty'])+0.000001:
        frappe.throw('Route allocation quantity must be positive and within the displayed source balance')
    if choice.get('full_quantity_only') and abs(qty-flt(choice['physical_qty']))>0.000001:
        frappe.throw('Serialized stock must be delivered as one complete physical unit')
    if frappe.db.get_value('UOM', choice['stock_uom'], 'must_be_whole_number') and qty%1:
        frappe.throw('Route allocation must respect the stock UOM whole-number requirement')
    prepared = choice['source_kind']=='Prepared Route Stock'
    snapshots={'route_stop':delivery.route_stop,'route_source_kind':choice['source_kind'],
        'dispatch_allocation':choice['source_key'] if prepared else None,
        'route_request_key':request_key,'route_request_hash':request_hash}
    if choice.get('handling_unit'):
        return engine._reserve_unit(delivery,frappe.get_doc('CFG Kanban Handling Unit',choice['handling_unit']),
            qty,event_token,operator,session,choice.get('container'),choice.get('container_visible_code'),snapshots=snapshots)
    source=frappe._dict(name=choice['source_key'] if prepared else f"unassigned:{choice['item_code']}:{choice.get('batch_no') or ''}",
        item_code=choice['item_code'],batch_no=choice.get('batch_no'),stock_uom=choice['stock_uom'],allocated_qty=qty)
    return _fulfilment()._reserve_untagged(delivery,source,event_token,operator,session,snapshots,prepared=prepared)


@frappe.whitelist()
def allocate_route_stock(delivery_session, source_key, qty, event_token, operator_session_token,
                         scan_value=None, item_code=None, batch_no=None):
    _planning()._require_event_token(event_token)
    operator, session = require_operator(operator_session_token,'start')
    delivery, plan = _delivery_context(delivery_session,operator)
    request_key=canonical_key('route-stock-request',delivery.name,event_token)
    request_hash=canonical_key('route-stock-payload',str(scan_value or '').strip(),item_code or '',
                               batch_no or '',source_key,flt(qty))
    previous=frappe.db.get_values('CFG Kanban Delivery Allocation',
        {'delivery_session':delivery.name,'route_request_key':request_key},
        ['name','route_request_hash'],as_dict=True,for_update=True)
    if previous:
        if any(row.route_request_hash != request_hash for row in previous):
            frappe.throw('This route stock token belongs to another source or quantity', RouteReplayConflictError)
        return _engine().get_delivery_session(delivery.name,operator_session_token)
    _assert_not_voided('stock', request_key)
    if plan.get('office_delivery_trip'):
        from cfg_kanban.services.trip_sales import authorize
        authorize(plan,operator,delivery.customer_scan_point,delivery.route_stop)
    _engine()._assert_allocation_session(delivery)
    context=_stock_context(delivery,plan,scan_value,item_code,batch_no)
    selected=next((row for row in context['choices'] if row['source_key']==source_key),None)
    if not selected:
        frappe.throw('Select the exact current numbered stock source')
    allocations=[]
    if context['mode']=='container':
        if flt(qty)!=0:
            frappe.throw('Mixed logistics containers require full-content confirmation, without a partial quantity')
        for choice in selected['contents']:
            allocations.append(_reserve_choice(delivery,plan,choice,choice['physical_qty'],event_token,
                                               operator,session,request_key,request_hash))
    else:
        allocations.append(_reserve_choice(delivery,plan,selected,qty,event_token,operator,session,request_key,request_hash))
    delivery.db_set({'state':'Allocating Stock','confirmed_on':None},update_modified=True)
    validate_route_allocations(delivery)
    record('Customer Route Stock Allocated',delivery_session=delivery.name,reference_doctype=STOP,
           reference_name=delivery.route_stop,qty=sum(flt(row.allocated_qty) for row in allocations),
           operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
           device_id=request_key,notes=f'{plan.name}; explicit prepared/unassigned stock selection')
    return _engine().get_delivery_session(delivery.name,operator_session_token)


def validate_route_allocations(delivery, allocations=None):
    if delivery.get('dispatch_plan') and frappe.db.get_value('CFG Kanban Dispatch Plan',delivery.dispatch_plan,'office_delivery_trip'):
        from cfg_kanban.services.trip_sales import assert_delivery_scope
        assert_delivery_scope(delivery)
    if not delivery.get('route_stop'):
        return
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',delivery.dispatch_plan,for_update=True)
    _assert_route_plan(plan)
    stop=frappe.get_doc(STOP,delivery.route_stop,for_update=True)
    if (stop.dispatch_plan!=plan.name or stop.delivery_session!=delivery.name or
            stop.customer_scan_point!=delivery.customer_scan_point or stop.customer!=delivery.customer or
            stop.customer_address!=delivery.customer_address or plan.company!=delivery.selling_company or
            plan.vehicle_warehouse!=delivery.source_warehouse):
        frappe.throw('Route delivery no longer matches its Site, Company or lorry snapshots')
    if allocations is None:
        allocations=frappe.get_all('CFG Kanban Delivery Allocation',filters={
            'delivery_session':delivery.name,'state':['in',['Reserved','Delivery Pending']]},
            fields=['name','route_stop','route_source_kind','dispatch_allocation','handling_unit',
                    'item_code','batch_no','stock_uom','allocated_qty'],limit_page_length=0)
    sources={row.name:row for row in _route_sources(plan)}
    for row in allocations:
        if row.route_stop!=stop.name or flt(row.allocated_qty)<=0:
            frappe.throw('Route allocation is outside this visit or has an invalid quantity')
        if row.route_source_kind=='Prepared Route Stock':
            source=sources.get(row.dispatch_allocation)
            if not source or any((row.get(field) or '')!=(source.get(field) or '')
                                 for field in ('handling_unit','item_code','batch_no','stock_uom')):
                frappe.throw('Prepared route stock identity differs from its loading allocation')
            if _source_used(source.name)>flt(source.allocated_qty)+0.000001:
                frappe.throw('Route deliveries exceed the prepared stock quantity')
        elif row.route_source_kind=='Unassigned Lorry Stock':
            if row.dispatch_allocation:
                frappe.throw('Unassigned route stock cannot consume a prepared allocation budget')
        else:
            frappe.throw('Route allocation requires an explicit prepared or unassigned stock source')


def sync_route_delivery(delivery):
    if not delivery.get('route_stop'):
        return
    frappe.db.sql('select name from `tabCFG Kanban Dispatch Plan` where name=%s for update',delivery.dispatch_plan)
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',delivery.dispatch_plan,for_update=True)
    stop=frappe.get_doc(STOP,delivery.route_stop,for_update=True)
    if stop.dispatch_plan!=plan.name or stop.delivery_session!=delivery.name:
        frappe.throw('Route Stop does not identify this Delivery Session')
    state=('Completed' if delivery.state=='Closed' else 'Delivered' if delivery.state in ('Delivered','Invoiced')
           else 'Delivery Note Pending' if delivery.state=='ERP Document Pending' else
           'Cancelled' if delivery.state=='Cancelled' else 'Exception' if delivery.state=='Exception' else 'In Progress')
    active=state not in ('Completed','Cancelled')
    if active and plan.get('active_route_stop') not in (None,'',stop.name):
        frappe.throw('Complete the current Route Stop before reopening this earlier delivery')
    stop.db_set({'state':state,'delivery_note':delivery.delivery_note,'delivery_proof':delivery.delivery_proof,
                 'completed_on':delivery.completed_on if state=='Completed' else None,
                 'active_stop_key':plan.name if active else None},update_modified=True)
    values={'fulfilment_status':'In Progress'}
    if active:
        values['active_route_stop']=stop.name
    elif plan.get('active_route_stop')==stop.name:
        values['active_route_stop']=None
    rows=frappe.db.sql('''select allocation.route_source_kind, coalesce(sum(allocation.delivered_qty),0) as qty
        from `tabCFG Kanban Delivery Allocation` allocation
        inner join `tabCFG Kanban Delivery Session` delivery on delivery.name=allocation.delivery_session
        where delivery.dispatch_plan=%s and allocation.state='Delivered'
        group by allocation.route_source_kind''',plan.name,as_dict=True)
    values['total_delivered_qty']=sum(flt(row.qty) for row in rows)
    values['unassigned_delivered_qty']=sum(flt(row.qty) for row in rows if row.route_source_kind=='Unassigned Lorry Stock')
    values['completed_stop_count']=frappe.db.count(STOP,{'dispatch_plan':plan.name,'state':'Completed'})
    plan.db_set(values,update_modified=True)
    if state=='Cancelled' and cint(stop.planned_sequence):
        retry=canonical_key('route-stop-cancelled-retry',stop.name)
        if not frappe.db.exists(STOP,{'idempotency_key':retry}):
            # Preserve the cancelled actual visit; its replacement keeps the planned position.
            site=frappe._dict(name=stop.customer_scan_point,site_name=stop.site_name,
                             customer=stop.customer,customer_address=stop.customer_address)
            _new_stop(plan,site,frappe._dict(employee=delivery.started_by_operator),retry,
                      cint(stop.planned_sequence),retry_of=stop.name)



def _void_key(action, key):
    return canonical_key('route-action-void', action, key)


def _assert_not_voided(action, key):
    if _exists_current('CFG Kanban Event', {'event_type':'Open Route Action Voided',
                                          'device_id':_void_key(action,key)}):
        frappe.throw('This route action was cancelled before recording; start a new action if needed', RouteActionVoidedError)


def _locked_action_result(action, event_token, operator, token,
                          delivery_session=None, dispatch_plan=None, route_stop=None):
    engine, planning = _engine(), _planning()
    engine._require_customer_delivery(operator)
    if action=='stock':
        delivery=frappe.get_doc('CFG Kanban Delivery Session',delivery_session,for_update=True)
        if not engine._can_view_delivery(operator,delivery):
            frappe.throw('Operator cannot access this Delivery Session')
        if not delivery.get('route_stop'):
            frappe.throw('Select the original Route Delivery Session')
        plan=_locked_plan(delivery.dispatch_plan,operator)
        key=canonical_key('route-stock-request',delivery.name,event_token)
        recorded=_exists_current('CFG Kanban Delivery Allocation',{'delivery_session':delivery.name,'route_request_key':key})
        result=engine.get_delivery_session(delivery.name,token) if recorded else None
    elif action in ('visit','plan'):
        plan=_locked_plan(dispatch_plan,operator)
        key=canonical_key('route-stop-start' if action=='visit' else 'route-stop-plan',plan.name,event_token)
        name=frappe.db.get_value(STOP,{'start_key' if action=='visit' else 'idempotency_key':key},'name',for_update=True)
        recorded=bool(name)
        stop=frappe.get_doc(STOP,name) if name else None
        result=(engine.get_delivery_session(stop.delivery_session,token) if action=='visit' else stop.as_dict()) if stop else None
    elif action in ('approve','skip'):
        stop=frappe.get_doc(STOP,route_stop)
        plan=_locked_plan(stop.dispatch_plan,operator)
        stop=frappe.get_doc(STOP,route_stop,for_update=True)
        key=canonical_key('route-stop-'+action,stop.name,event_token)
        recorded=_exists_current('CFG Kanban Event',{'device_id':key,'reference_doctype':STOP,'reference_name':stop.name})
        result=stop.as_dict() if recorded else None
    else:
        frappe.throw('Unsupported pending Route action')
    return plan,key,bool(recorded),result


@frappe.whitelist()
def reconcile_route_action(action, event_token, operator_session_token,
                           delivery_session=None, dispatch_plan=None, route_stop=None):
    _planning()._require_event_token(event_token)
    operator,_session=require_operator(operator_session_token)
    plan,key,recorded,result=_locked_action_result(action,event_token,operator,operator_session_token,
        delivery_session,dispatch_plan,route_stop)
    voided=_exists_current('CFG Kanban Event',{'event_type':'Open Route Action Voided','device_id':_void_key(action,key)})
    return {'recorded':int(recorded),'voided':int(bool(voided)),'dispatch_plan':plan.name,'result':result}


@frappe.whitelist()
def void_unrecorded_route_action(action, event_token, reason, operator_session_token,
                                 delivery_session=None, dispatch_plan=None, route_stop=None):
    _planning()._require_event_token(event_token)
    operator,session=require_operator(operator_session_token,'complete')
    reason=str(reason or '').strip()
    if not reason:
        frappe.throw('A cancellation reason is required')
    if action in ('plan','approve','skip'):
        _supervisor(operator)
    plan,key,recorded,result=_locked_action_result(action,event_token,operator,operator_session_token,
        delivery_session,dispatch_plan,route_stop)
    if recorded:
        return {'recorded':1,'voided':0,'dispatch_plan':plan.name,'result':result}
    void_key=_void_key(action,key)
    if not _exists_current('CFG Kanban Event',{'event_type':'Open Route Action Voided','device_id':void_key}):
        record('Open Route Action Voided',reference_doctype='CFG Kanban Dispatch Plan',reference_name=plan.name,
               delivery_session=delivery_session,operator=operator.employee,operator_session=session.name,
               terminal_user=session.terminal_user,device_id=void_key,
               notes=f'{action}; original event {event_token}; {reason}')
    return {'recorded':0,'voided':1,'dispatch_plan':plan.name,'result':None}

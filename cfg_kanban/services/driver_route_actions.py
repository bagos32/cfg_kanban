"""Audited driver steps over the existing prepared delivery, ERP gateway and proof services."""
import json

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

TRIP = 'CFG Kanban Delivery Trip'
MOBILE_ACTIONS = ('Create Sales Invoice', 'Create Custody Label', 'Prepare Mobile Print', 'Record Print Segment', 'Close Mobile Print')
ACTIONS = MOBILE_ACTIONS + ('Request Stop Cancellation','Cancel Customer Stop','Release GPS','Start GPS', 'Start Route', 'Begin Delivery', 'Confirm Allocations', 'Create Delivery Note',
           'Open Proof', 'Submit Proof', 'Complete Stop', 'Collect Old Return', 'Release Refused Stock', 'Begin Open Sale', 'Add Assistant', 'Change Route Order', 'Request Route Change', 'Cancel Route Change', 'Decide Route Change')
PAYLOAD_FIELDS = {
    'Create Sales Invoice': {'delivery_note', 'required_erp_inputs', 'profile_version', 'invoice_mode'},
    'Create Custody Label': {'return_case', 'return_line', 'qty'},
    'Prepare Mobile Print': {'doctype', 'name', 'print_format', 'copies', 'reason', 'no_letterhead', 'printer_settings'},
    'Record Print Segment': {'print_job', 'page', 'frame_hashes', 'outcome', 'reason'},
    'Close Mobile Print': {'print_job', 'reason'},
    'Request Stop Cancellation': {'reason'},
    'Cancel Customer Stop': {'reason','goods_hash','stock_disposition'},
    'Release GPS': {'lease_id','reason'},
    'Start GPS': {'device_id','publish_token'},
    'Change Route Order': {'order','reason'}, 'Request Route Change': {'order','reason'},
    'Cancel Route Change': {'request_name','reason'},
    'Decide Route Change': {'request_name','decision','approval_mode','reason','goods_hash','stock_disposition'},
    'Add Assistant': {'employee'},
    'Begin Open Sale': {'customer_scan'},
    'Start Route': set(), 'Begin Delivery': {'customer_scan', 'quantities'}, 'Confirm Allocations': set(),
    'Create Delivery Note': {'required_erp_inputs'}, 'Open Proof': set(),
    'Submit Proof': {'proof_name', 'disposition', 'recipient_name', 'unattended_reason',
                     'latitude', 'longitude', 'location_accuracy', 'notes'},
    'Complete Stop': {'notes'},
    'Collect Old Return': {'inspection_location','customer_return_reason','lines','customer_acknowledgement_name','reported_source_reference','existing_return_case'},
    'Release Refused Stock': {'outcome','line_names','reason'},
}

class DriverActionConflict(frappe.ValidationError):
    """An action identity already describes a different or voided request."""


def _views():
    from cfg_kanban.services import driver_routes
    return driver_routes


def _delivery():
    from cfg_kanban.services import customer_delivery
    return customer_delivery


def _prepared():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _sheets():
    from cfg_kanban.services import route_sheets
    return route_sheets


def _proof():
    from cfg_kanban.services import delivery_proof
    return delivery_proof


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _core(doc):
    from cfg_kanban.services.delivery_trips import _business
    return _scope_hash(doc, _business(doc))


def _scope_hash(doc, business):
    current=canonical_key('driver-trip-scope',business)
    # Older departures froze an empty planning header while recording the real
    # lorry in their snapshot. Filling that exact lorry must not rewrite the snapshot
    # or invalidate pending delivery/GPS/route-order actions. All other facts still match.
    if doc.get('driver_route_state') in ('In Progress','Completed','Closed Incomplete') and doc.get('vehicle_warehouse'):
        try:saved=json.loads(doc.driver_route_snapshot_json or '{}')
        except (TypeError,ValueError):return current
        if isinstance(saved,dict) and saved.get('vehicle')==doc.vehicle_warehouse:
            for empty in (None,''):
                prior=canonical_key('driver-trip-scope',dict(business,vehicle_warehouse=empty))
                if prior==saved.get('scope_hash'):return prior
    return current


@frappe.whitelist()
def sync_trip_lorry(trip_name,expected_modified):
    """Repair an older blank header from its frozen departure, without moving stock."""
    frappe.only_for(('Stock Manager','Sales Manager','System Manager','CFG Kanban System Maintenance'))
    doc=_root(trip_name);doc.check_permission('write')
    if not expected_modified or get_datetime(doc.modified)!=get_datetime(expected_modified):
        frappe.throw('Trip changed; reload before syncing its departure lorry')
    if doc.get('driver_route_state') not in ('In Progress','Completed','Closed Incomplete'):
        frappe.throw('Start the route before syncing its departure lorry')
    try:saved=json.loads(doc.driver_route_snapshot_json or '{}')
    except (TypeError,ValueError):frappe.throw('The departure snapshot needs Supervisor reconciliation')
    if not isinstance(saved,dict) or not saved.get('vehicle') or saved.get('scope_hash')!=_core(doc):
        frappe.throw('The departure snapshot needs Supervisor reconciliation')
    vehicle=_views().trip_vehicle_warehouse(doc)
    _read('Warehouse',vehicle)
    _planning()._vehicle_warehouse(vehicle,doc.company)
    if doc.vehicle_warehouse:return dict(trip=doc.name,vehicle_warehouse=vehicle,changed=False)
    key=canonical_key('trip-departure-lorry-linked',doc.name,vehicle,saved['scope_hash'])
    doc.db_set('vehicle_warehouse',vehicle,update_modified=True)
    record('Delivery Trip Departure Lorry Linked',reference_doctype=TRIP,reference_name=doc.name,
        terminal_user=frappe.session.user,idempotency_key=key,
        payload=dict(vehicle_warehouse=vehicle,departure_scope_hash=saved['scope_hash']),
        notes='Restored the blank header from the frozen departure; no stock movement')
    return dict(trip=doc.name,vehicle_warehouse=vehicle,changed=True)


def _read(doctype, name, current=False):
    doc = frappe.get_doc(doctype, name, **({'for_update': True} if current else {}))
    doc.check_permission('read')
    return doc


def _root(name):
    # Trip is always first. Native delivery mutations retain their Session -> Plan lock order.
    doc = _read(TRIP, name, current=True)
    _read('Company', doc.company)
    return doc


def _owned(doc, operator):
    if not (_views()._all(operator) or doc.driver==operator.employee or any(r.employee==operator.employee for r in doc.get('assistant_drivers') or [])):
        frappe.throw('This Delivery Trip is not assigned to this driver', frappe.PermissionError)
    _delivery()._require_customer_delivery(operator)


def _request(trip_name, action, stop_key, dispatch_plan, payload, expected_revision, scope_hash):
    if action not in ACTIONS:
        frappe.throw('Select a supported driver route action')
    values = json.loads(payload or '{}') if isinstance(payload, str) else (payload or {})
    if not isinstance(values, dict) or set(values) - PAYLOAD_FIELDS[action]:
        frappe.throw('Unexpected driver action fields; quantities and stock sources come from the saved trip')
    if expected_revision is None or cint(expected_revision) < 0 or not scope_hash:
        frappe.throw('Refresh the route before confirming its current revision')
    return dict(trip_name=trip_name, action=action, stop_key=stop_key or None,
        dispatch_plan=dispatch_plan or None, payload=values,
        expected_revision=cint(expected_revision), scope_hash=str(scope_hash))


def _key(doc, actor, event_token):
    if not str(event_token or '').strip() or len(str(event_token)) > 200:
        frappe.throw('A stable driver action token is required')
    return canonical_key('driver-route-action', doc.name, actor, str(event_token))


def _receipt(key, request):
    rows = frappe.db.sql('SELECT payload_json FROM `tabCFG Kanban Event` WHERE idempotency_key=%s FOR UPDATE',
                         (key,), as_dict=True)
    if not rows:
        return None
    data = json.loads(rows[0].payload_json or '{}')
    if data.get('request_hash') != canonical_key('driver-route-request', request):
        frappe.throw('This driver action token belongs to different original details', DriverActionConflict)
    return data


def _record(doc, operator, session, key, request, result=None, void_reason=None, actor=None):
    receipt = dict(request_hash=canonical_key('driver-route-request', request),
        status='Voided' if void_reason else 'Recorded', action=request['action'],
        trip_name=doc.name, stop_key=request['stop_key'], dispatch_plan=request['dispatch_plan'],
        request_actor=actor or operator.employee, result=result or {}, void_reason=void_reason)
    record('Driver Route Action Voided' if void_reason else 'Driver Route ' + request['action'],
        reference_doctype=TRIP, reference_name=doc.name, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        idempotency_key=key, payload=receipt, notes=void_reason)
    return receipt


def _build_snapshot(doc, context, operator):
    """Validate exact execution links; do not publish or approve an operational Route Sheet."""
    return_only=False
    if doc.get('follow_on_of') and not doc.stops:
        from cfg_kanban.services.return_custody import cases,pending
        return_only=any(pending(case) for case in cases(doc,history=False,native=False))
    if not return_only and not any(not r.get('cancellation_request') for r in doc.stops):
        frappe.throw('Add at least one saved customer stop before departure')
    by_stop = {row.stop_key: row for row in doc.stops}
    cancelled={r.stop_key for r in doc.stops if r.get('cancellation_request')}
    saved=json.loads(doc.driver_route_snapshot_json or '{}') if cancelled else {}
    plans = {row.dispatch_plan: _read('CFG Kanban Dispatch Plan', row.dispatch_plan) for row in doc.dispatch_plans}
    if len(plans) != len(doc.dispatch_plans):
        frappe.throw('Duplicate Dispatch Plan links require office review')
    linked = {row.dispatch_plan: row.stop_key for row in doc.dispatch_plans}
    vehicles = {plan.vehicle_warehouse for name,plan in plans.items() if plan.vehicle_warehouse and linked[name] not in cancelled}
    if doc.get('open_route_plan'):
        shared=_read('CFG Kanban Dispatch Plan',doc.open_route_plan)
        if shared.vehicle_warehouse:vehicles.add(shared.vehicle_warehouse)
    if doc.vehicle_warehouse:
        vehicles.add(doc.vehicle_warehouse)
    for vehicle in sorted(vehicles):
        _planning()._vehicle_warehouse(vehicle, doc.company)
    deliveries = [row for row in doc.stops if row.stop_purpose != 'Visit Only' and row.stop_key not in cancelled]
    if deliveries and (not plans or len(vehicles) != 1):
        frappe.throw('Assign one actual lorry and prepare every delivery before starting the route')
    if len(vehicles) > 1:
        frappe.throw('Trip sources belong to different lorries')
    for row in deliveries:
        if not any(link.stop_key == row.stop_key for link in doc.dispatch_plans):
            frappe.throw('Prepare every Delivery stop, or configure an information-only stop as Visit Only')
    for stop in context['stops']:
        if stop['purpose'] == 'Delivery':
            physical = [row for row in stop['items'] if row['is_stock_item']]
            if not physical or any(row['loaded_qty'] + 0.000001 < row['planned_qty'] for row in physical):
                frappe.throw('Every planned physical quantity must have completed lorry loading')
    signatures = {}; policies = {}; cancelled_sheets={}
    for name, plan in plans.items():
        if linked[name] in cancelled:
            policy=saved.get('policies',{}).get(name)
            if policy:
                policies[name]=policy
                if policy.get('sheet'):cancelled_sheets[policy['sheet']]=saved['sheets'][policy['sheet']]
            continue
        _planning()._assert_plan_authorized(plan, operator)
        if plan.state != 'Loaded' or plan.get('dispatch_review_state') not in (None, '', 'Settled'):
            frappe.throw('Resolve Dispatch Review and use Loaded Customer Order Plans')
        _prepared().validate_prepared_loading(plan)
        need = bool(plan.route_approval_required or plan.route_sequence_scope == 'Combined Lorry Trip' or plan.active_route_sheet)
        if need:
            if not plan.active_route_sheet:
                frappe.throw('Supervisor must approve the existing operational Route Sheet before departure')
        if plan.active_route_sheet:
            sheet = _read('CFG Kanban Route Sheet', plan.active_route_sheet)
            if (sheet.company != doc.company or sheet.vehicle_warehouse != plan.vehicle_warehouse
                    or sheet.state not in ('Approved', 'In Progress', 'Ready to Close')):
                frappe.throw('The operational Route Sheet must be approved for this Company and lorry')
            if sheet.name not in signatures:
                seen = set(); keys = []; rows = []
                for source in sheet.stops:
                    target = linked.get(source.dispatch_plan)
                    identity=source.dispatch_plan
                    if source.dispatch_plan==doc.get('open_route_plan'):
                        from cfg_kanban.services.trip_sales import sheet_target
                        target=sheet_target(doc,source);identity=source.source_route_stop
                    if not target or identity in seen or source.customer_scan_point != by_stop[target].customer_scan_point:
                        frappe.throw('The approved route must map exactly to this trip; reconcile ambiguous or outside stops')
                    seen.add(identity); keys.append(target)
                    rows.append((source.row_key, source.dispatch_plan, source.customer_scan_point))
                distinct = []
                for value in keys:
                    if not distinct or distinct[-1] != value:
                        distinct.append(value)
                if len(distinct) != len(set(distinct)):
                    frappe.throw('Separate interleaved visits before starting this driver route')
                signatures[sheet.name] = dict(revision=cint(sheet.revision), rows=rows,
                    sequence_policy=sheet.sequence_policy, verification_policy=sheet.verification_policy)
            matches = [row for row in sheet.stops if row.dispatch_plan == name]
            if len(matches) != 1:
                frappe.throw('Each loaded Plan needs one exact approved route stop')
            policies[name] = dict(sheet=sheet.name, row_key=matches[0].row_key,
                require_scan=sheet.verification_policy == _sheets().QR)
        else:
            policies[name] = dict(sheet=None, row_key=None, require_scan=_sheets().verification(plan) != _sheets().SELECT)
    for name,signature in cancelled_sheets.items():signatures.setdefault(name,signature)
    order = context.get('source_stop_order') or [row['stop_key'] for row in context['stops']]
    # Visits absent from an operational Sheet retain office position. Delivery order must agree.
    if context['sequence_source'] != 'Approved Route Sheet':
        for signature in signatures.values():
            subset = []
            for _row, name, _site in signature['rows']:
                target = linked.get(name)
                if name==doc.get('open_route_plan'):
                    from cfg_kanban.services.trip_sales import sheet_target
                    sheet=_read('CFG Kanban Route Sheet',next(k for k,v in signatures.items() if v is signature))
                    target=sheet_target(doc,next(r for r in sheet.stops if r.row_key==_row))
                if not subset or subset[-1] != target:
                    subset.append(target)
            if signature['sequence_policy'] == 'Planned Order' and [key for key in order if key in subset] != subset:
                frappe.throw('Office delivery order conflicts with the approved route; Supervisor must reconcile it')
    allocations = sorted([(row['dispatch_plan'], row['dispatch_allocation'], row['item_code'], row['stock_uom'],
                           row['batch_no'], row['tag_code'], row['assigned_qty'])
                          for stop in context['stops'] for row in stop['sources']])
    if cancelled and saved:
        cancelled_plans={name for name,key in linked.items() if key in cancelled}
        allocations=sorted([tuple(r) for r in allocations]+[tuple(r) for r in saved.get('allocations',[]) if r[0] in cancelled_plans])
    extra={}
    if doc.get('open_route_plan'):
        from cfg_kanban.services.trip_sales import snapshot
        shared=snapshot(doc,operator,next(iter(vehicles)) if vehicles else None)
        extra['open_pool']=shared
    return dict(scope_hash=_core(doc), stop_order=order, policies=policies, sheets=signatures, allocations=allocations,**extra,
        strict=bool(doc.sequence_policy == 'Planned Order' or any(s['sequence_policy'] == 'Planned Order' for s in signatures.values())
                    or bool(extra.get('open_pool',{}).get('sheet') and extra['open_pool']['sheet']['sequence_policy']=='Planned Order')),
        vehicle=next(iter(vehicles)) if vehicles else None)


def _execution(doc, operator, context):
    # Pass the operator explicitly through this wrapper; no module-global actor is retained.
    return _build_snapshot(doc, context, operator)


def _session(plan, operator, stop=None):
    if plan.get('office_delivery_trip') and plan.plan_type=='Open Route Stock':
        from cfg_kanban.services.trip_sales import session
        trip=_read(TRIP,plan.office_delivery_trip)
        result=session(trip,stop,operator,current=True) if stop else None
        if not result or not _delivery()._can_view_delivery(operator,result):frappe.throw('Open this exact Trip customer sale first')
        return result
    if not plan.delivery_session:
        frappe.throw('Start the exact prepared delivery for this stop first')
    session = _read('CFG Kanban Delivery Session', plan.delivery_session, current=True)
    if session.dispatch_plan != plan.name or not _delivery()._can_view_delivery(operator, session):
        frappe.throw('This Delivery Session belongs to another Plan or operator', frappe.PermissionError)
    return session


def _is_ready(doc, stop, operator, token):
    if stop.stop_purpose == 'Visit Only':
        if doc.get('open_route_plan'):
            from cfg_kanban.services.trip_sales import finish_visit
            return finish_visit(doc,stop,operator)
        return True
    links = [row for row in doc.dispatch_plans if row.stop_key == stop.stop_key]
    if not links:
        return False
    for link in links:
        plan = _read('CFG Kanban Dispatch Plan', link.dispatch_plan)
        if not plan.delivery_session:
            return False
        delivery = _session(plan, operator)
        if delivery.state != 'Closed' or plan.fulfilment_status != 'Completed':
            return False
        if delivery.get('driver_delivery_outcome'):
            from cfg_kanban.services.driver_delivery_outcomes import full_refusal
            if full_refusal(delivery):
                continue
        note = _read('Delivery Note', delivery.delivery_note)
        if note.docstatus != 1 or note.is_return or note.company != doc.company or note.customer != stop.customer:
            return False
        if delivery.proof_policy != 'No Proof Required':
            if not delivery.delivery_proof:
                return False
            proof = _read('CFG Kanban Delivery Proof', delivery.delivery_proof)
            if proof.state != 'Submitted' or proof.delivery_session != delivery.name or proof.delivery_note != note.name:
                return False
    context = _views().get_driver_trip(doc.name, token)
    target = next(row for row in context['stops'] if row['stop_key'] == stop.stop_key)
    return all(not row['is_stock_item'] or row['delivered_qty'] + row.get('refused_qty',0) + 0.000001 >= row['planned_qty'] for row in target['items'])


def _finish(doc, stop, operator, token, notes=None):
    if stop.get('driver_completed_on'):
        return True
    if not _is_ready(doc, stop, operator, token):
        return False
    if stop.stop_purpose=='Visit Only' and doc.get('open_route_plan'):
        from cfg_kanban.services.trip_sales import finish_visit
        finish_visit(doc,stop,operator,record_no_sale=True)
    stop.db_set(dict(driver_completed_on=now_datetime(), driver_completed_by=operator.employee,
                     driver_visit_notes=(notes or '').strip() or None), update_modified=False)
    values = dict(driver_active_stop_key=None)
    if all(row.get('driver_completed_on') or row.get('cancellation_request') for row in doc.stops):
        values.update(driver_route_state='Completed', driver_route_completed_on=now_datetime(),
                      driver_active_vehicle_key=None)
    doc.db_set(values, update_modified=True)
    return True


def _target(doc, request, snapshot):
    if doc.driver_route_state != 'In Progress':
        frappe.throw('Start Route before completing a customer stop')
    stop = next((row for row in doc.stops if row.stop_key == request['stop_key']), None)
    if not stop:
        frappe.throw('Select the exact saved trip stop')
    if stop.get('cancellation_request'):
        frappe.throw('This customer stop was cancelled; use another active stop')
    if doc.get('route_change_request'):
        from cfg_kanban.services.trip_sequence import assert_target_not_pending_cancellation
        assert_target_not_pending_cancellation(doc,stop)
    if stop.get('driver_completed_on'):
        frappe.throw('This stop is already completed; refresh its recorded outcome')
    active = doc.get('driver_active_stop_key')
    if active and active != stop.stop_key:
        frappe.throw('Complete the current customer stop and proof first')
    keys=snapshot['stop_order']
    if doc.get('driver_stop_order_json'):
        from cfg_kanban.services.trip_sequence import order
        keys=order(doc,snapshot)
    pending = [key for key in keys if not (next(row for row in doc.stops if row.stop_key == key).get('driver_completed_on') or next(row for row in doc.stops if row.stop_key == key).get('cancellation_request'))]
    enforced=snapshot['strict']
    if doc.get('route_sequence_revision') is not None:
        from cfg_kanban.services.trip_sequence import strict
        enforced=strict(doc,snapshot)
    if enforced and pending and pending[0] != stop.stop_key:
        frappe.throw('Complete the next stop in the enforced trip sequence')
    return stop


@frappe.whitelist()
def driver_action_context(trip_name, operator_session_token, stop_key=None, operation=None, outcome_name=None):
    operator, _session = require_operator(operator_session_token)
    doc = _views()._trip(trip_name, operator)
    result = dict(trip_name=doc.name, route_state=doc.get('driver_route_state') or 'Not Started',
        revision=cint(doc.driver_route_revision), scope_hash=_core(doc),
        can_start=bool(operator.can_start), can_complete=bool(operator.can_complete),
        planning_state=doc.state, next_step='Start Route', stop_key=stop_key, dispatch_plan=None)
    if operation=='Cancel Customer Stop':
        from cfg_kanban.services.trip_stop_cancellation import context
        setup=context(doc,stop_key,operator)
        return dict(result,next_step='Cancel Customer Stop' if setup['supervisor'] else 'Request Stop Cancellation',setup=setup)
    if operation in ('Start GPS','Release GPS'):
        return dict(result,next_step=operation,stop_key=None)
    if operation=='Review Route Change':
        from cfg_kanban.services.trip_sequence import review_context
        return dict(result,next_step='Decide Route Change',stop_key=None,setup=review_context(doc,outcome_name,operator))
    context = _views().get_driver_trip(trip_name, operator_session_token)
    if operation=='Change Route Order':
        from cfg_kanban.services.trip_sequence import edit_context
        return dict(result,next_step='Edit Route Order',stop_key=None,setup=edit_context(doc,operator,operator_session_token))
    if operation=='Cancel Route Change':
        return dict(result,next_step='Cancel Route Change',stop_key=None,setup=dict(request_name=doc.route_change_request,request_type=_read('CFG Kanban Route Change Request',doc.route_change_request).get('request_type')))
    if operation == 'Add Assistant':
        from cfg_kanban.services.trip_team import assert_lead
        assert_lead(doc, operator)
        return dict(result,next_step='Add Assistant',stop_key=None,setup=dict(team=[r.employee for r in doc.get('assistant_drivers') or []]))
    if operation == 'Collect Old Return':
        stop=next((r for r in doc.stops if r.stop_key==stop_key),None)
        if not stop:frappe.throw('Select the exact saved customer stop')
        from cfg_kanban.services import driver_collections
        return dict(result,next_step='Collect Old Return',setup=driver_collections.context(doc,stop,operator),purpose='Old Return')
    if operation == 'Release Refused Stock':
        if not (_views()._all(operator) and operator.can_override):frappe.throw('Supervisor with Override is required',frappe.PermissionError)
        from cfg_kanban.services.driver_delivery_outcomes import OUTCOME
        outcome=_read(OUTCOME,outcome_name)
        if outcome.delivery_trip!=doc.name or outcome.stop_key!=stop_key:frappe.throw('Select refused stock at this exact customer stop')
        return dict(result,next_step='Release Refused Stock',setup=dict(outcome=outcome.name,rows=[dict(line_name=r.name,item_code=r.item_code,stock_uom=r.stock_uom,refused_qty=r.refused_qty,stock_state=r.stock_state,selected=0) for r in outcome.lines if r.stock_state in ('Held','Transferred Hold')]))
    if doc.state != 'Planned':
        return dict(result, next_step='Blocked', message='Office must mark this trip Planned before driver execution')
    if result['route_state'] == 'Completed':
        return dict(result, next_step='Done')
    if result['route_state'] == 'Not Started':
        return dict(result, stop_key=None)
    snapshot = json.loads(doc.driver_route_snapshot_json or '{}')
    effective=snapshot.get('stop_order',[])
    if doc.get('driver_stop_order_json'):
        from cfg_kanban.services.trip_sequence import order
        effective=order(doc,snapshot)
    key = stop_key or doc.driver_active_stop_key or next((key for key in effective
        if not (next(row for row in doc.stops if row.stop_key == key).get('driver_completed_on') or next(row for row in doc.stops if row.stop_key == key).get('cancellation_request'))), None)
    stop = next((row for row in doc.stops if row.stop_key == key), None)
    if not stop or stop.get('driver_completed_on'):
        return dict(result, next_step='Done')
    request = dict(stop_key=key)
    _target(doc, request, snapshot)
    result.update(stop_key=key, site_name=stop.site_name or stop.customer, purpose=stop.stop_purpose)
    if stop.stop_purpose == 'Visit Only':
        if doc.get('open_route_plan'):
            from cfg_kanban.services.trip_sales import action_context
            sale=action_context(doc,stop,operator,result,operator_session_token,force=operation=='Sell from Lorry')
            if sale:return sale
        return dict(result, next_step='Complete Stop')
    rows = [row for row in doc.dispatch_plans if row.stop_key == key]
    for row in rows:
        plan = _read('CFG Kanban Dispatch Plan', row.dispatch_plan)
        _planning()._assert_plan_authorized(plan, operator)
        if not plan.delivery_session:
            return dict(result, next_step='Begin Delivery', dispatch_plan=plan.name,
                require_scan=snapshot['policies'][plan.name]['require_scan'],
                quantities=[dict(dispatch_allocation=r.name,item_code=r.item_code,source_label=' · '.join(filter(None,[r.item_code,frappe.db.get_value('CFG Kanban Handling Unit',r.handling_unit,'handling_unit_id') if r.handling_unit else 'Untagged ERP stock',r.batch_no])),batch_no=r.batch_no,stock_uom=r.stock_uom,prepared_qty=r.allocated_qty,accepted_qty=r.allocated_qty,refusal_reason='',condition='Good / Unwanted') for r in _prepared()._loaded_allocations(plan)])
        delivery = _delivery().get_delivery_session(plan.delivery_session, operator_session_token)
        state = delivery['state']
        if state == 'Closed':
            continue
        result.update(dispatch_plan=plan.name, delivery_session=delivery['name'], session_state=state,
            auto_submit_delivery_note=delivery['auto_submit_delivery_note'])
        if state == 'Allocating Stock':
            return dict(result, next_step='Confirm Allocations')
        if state in ('Awaiting Confirmation', 'ERP Document Pending'):
            requirements = _delivery().get_customer_delivery_requirements(delivery['name'], operator_session_token)
            return dict(result, next_step='Await ERP' if requirements.get('existing_draft') else 'Create Delivery Note',
                        requirements=requirements, delivery_note=delivery.get('delivery_note'))
        if state == 'Delivered':
            proof_name = delivery.get('delivery_proof')
            return dict(result, next_step='Submit Proof' if proof_name else 'Open Proof',
                        proof=_proof().get_delivery_proof(proof_name, operator_session_token) if proof_name else None)
        return dict(result, next_step='Blocked', message='Use the existing supervised recovery for this Delivery Session')
    return dict(result, next_step='Complete Stop')


@frappe.whitelist()
def perform_driver_action(trip_name, action, event_token, operator_session_token, expected_revision=None,
                          scope_hash=None, stop_key=None, dispatch_plan=None, payload=None):
    operator, session = require_operator(operator_session_token)
    doc = _root(trip_name)
    request = _request(trip_name, action, stop_key, dispatch_plan, payload, expected_revision, scope_hash)
    key = _key(doc, operator.employee, event_token)
    receipt = _receipt(key, request)
    if receipt:
        if receipt['status'] == 'Voided':
            frappe.throw('This driver request was explicitly voided', DriverActionConflict)
        return receipt
    _owned(doc, operator)
    if action in MOBILE_ACTIONS:
        from cfg_kanban.services import mobile_printing
        result = mobile_printing.action(doc, request, operator, session, operator_session_token, key)
        return _record(doc, operator, session, key, request, result)
    if action in ('Request Stop Cancellation','Cancel Customer Stop'):
        require_operator(operator_session_token,'start' if action=='Request Stop Cancellation' else 'complete')
        if not stop_key or dispatch_plan or request['scope_hash']!=_core(doc) or request['expected_revision']!=cint(doc.driver_route_revision):
            frappe.throw('Trip changed; refresh before confirming this exact customer cancellation')
        from cfg_kanban.services import trip_stop_cancellation
        result=(trip_stop_cancellation.request_cancel(doc,stop_key,request['payload'],operator,session,key)
            if action=='Request Stop Cancellation' else trip_stop_cancellation.direct(doc,stop_key,request['payload'],operator,session,operator_session_token,key))
        doc.db_set('driver_route_revision',cint(doc.driver_route_revision)+1,update_modified=True)
        return _record(doc,operator,session,key,request,result)
    if action=='Release GPS':
        require_operator(operator_session_token,'override')
        if stop_key or dispatch_plan or request['scope_hash']!=_core(doc) or request['expected_revision']!=cint(doc.driver_route_revision):
            frappe.throw('Trip changed; refresh before releasing this GPS source')
        from cfg_kanban.services.trip_gps import release
        result=release(doc,request['payload'],operator,session)
        return _record(doc,operator,session,key,request,result)
    if action=='Start GPS':
        require_operator(operator_session_token,'start')
        if stop_key or dispatch_plan or request['scope_hash']!=_core(doc) or request['expected_revision']!=cint(doc.driver_route_revision):
            frappe.throw('Trip changed; refresh before starting GPS sharing')
        from cfg_kanban.services.trip_gps import start
        result=start(doc,request['payload'],operator,session)
        return _record(doc,operator,session,key,request,result)
    if action=='Decide Route Change':
        require_operator(operator_session_token,'complete')
        if stop_key or dispatch_plan or request['scope_hash']!=_core(doc) or request['expected_revision']!=cint(doc.driver_route_revision):
            frappe.throw('Trip changed; refresh this Supervisor decision')
        from cfg_kanban.services.trip_sequence import decide
        result=decide(doc,request['payload'],operator,session,operator_session_token)
        doc.db_set('driver_route_revision',cint(doc.driver_route_revision)+1,update_modified=True)
        return _record(doc,operator,session,key,request,result)
    if action in ('Collect Old Return','Release Refused Stock'):
        return _special_action(doc,request,operator,session,operator_session_token,key)
    require_operator(operator_session_token, 'start' if action in ('Start Route', 'Begin Delivery', 'Begin Open Sale', 'Add Assistant', 'Change Route Order', 'Request Route Change', 'Cancel Route Change') else 'complete')
    draft_withdrawal=bool(action=='Cancel Route Change' and doc.state=='Draft' and
        _read('CFG Kanban Route Change Request',request['payload'].get('request_name')).get('request_type')=='Cancel Customer Stop')
    if (doc.state != 'Planned' and not draft_withdrawal) or request['scope_hash'] != _core(doc) or request['expected_revision'] != cint(doc.driver_route_revision):
        frappe.throw('Trip planning or execution changed; refresh before submitting new details')
    if action in ('Change Route Order','Request Route Change','Cancel Route Change'):
        if stop_key or dispatch_plan:frappe.throw('Route order changes apply to the Trip, not a Delivery Note')
        from cfg_kanban.services import trip_sequence
        if action=='Change Route Order':result=trip_sequence.change(doc,request['payload'],operator,session,operator_session_token,key)
        elif action=='Request Route Change':result=trip_sequence.request_change(doc,request['payload'],operator,session,operator_session_token,key)
        else:result=trip_sequence.cancel(doc,request['payload'],operator,session)
        doc.db_set('driver_route_revision',cint(doc.driver_route_revision)+1,update_modified=True)
        return _record(doc,operator,session,key,request,result)
    if action=='Add Assistant':
        if stop_key or dispatch_plan:frappe.throw('Assistant assignment applies to this Trip, not a customer or Plan')
        from cfg_kanban.services.trip_team import add_assistant
        result=add_assistant(doc,request['payload'].get('employee'),operator,session)
        doc.db_set('driver_route_revision',cint(doc.driver_route_revision)+1,update_modified=True)
        return _record(doc,operator,session,key,request,result)
    if action=='Start Route' and doc.get('open_route_plan'):
        from cfg_kanban.services.trip_sales import prepare_pool
        prepare_pool(doc,operator)
    context = _views().get_driver_trip(doc.name, operator_session_token)
    snapshot = _execution(doc, operator, context)
    values = request['payload']; result = {}
    if action in ('Start Route', 'Complete Stop') and dispatch_plan:
        frappe.throw('This action applies to the trip or stop, not a separate Dispatch Plan')
    if action == 'Start Route':
        if doc.get('driver_route_state') not in (None, '', 'Not Started'):
            frappe.throw('This route has already started')
        active_key = canonical_key('driver-active-lorry', doc.company, snapshot['vehicle']) if snapshot['vehicle'] else None
        if active_key and frappe.db.exists(TRIP, {'driver_active_vehicle_key': active_key}):
            frappe.throw('This lorry already has an active driver route')
        binding={}
        if snapshot['vehicle']:
            # Hash the final header before persisting the departure in one update.
            previous=doc.vehicle_warehouse
            try:
                doc.vehicle_warehouse=snapshot['vehicle'];snapshot['scope_hash']=_core(doc)
            finally:doc.vehicle_warehouse=previous
            binding['vehicle_warehouse']=snapshot['vehicle']
        try:
            doc.db_set(dict(driver_route_state='In Progress', driver_route_started_on=now_datetime(),
                driver_route_started_by=operator.employee, driver_route_snapshot_json=frappe.as_json(snapshot),
                driver_active_vehicle_key=active_key,**binding), update_modified=True)
        except frappe.UniqueValidationError:
            frappe.throw('This lorry already has an active driver route')
        result['route_started'] = True
        result['gps_auto_start']=bool(cint(doc.get('gps_auto_start')))
    else:
        saved = json.loads(doc.driver_route_snapshot_json or '{}')
        if canonical_key('driver-snapshot', snapshot) != canonical_key('driver-snapshot', saved):
            frappe.throw('The saved execution route changed; Supervisor must reconcile it before continuing')
        stop = _target(doc, request, snapshot)
        links = {row.dispatch_plan for row in doc.dispatch_plans if row.stop_key == stop.stop_key}
        if stop.stop_purpose=='Visit Only' and doc.get('open_route_plan'):links.add(doc.open_route_plan)
        plan = _read('CFG Kanban Dispatch Plan', dispatch_plan) if dispatch_plan else None
        if action != 'Complete Stop' and (not plan or plan.name not in links):
            frappe.throw('Select an exact prepared Plan belonging to this trip stop')
        if action == 'Begin Open Sale':
            if plan.name!=doc.get('open_route_plan') or stop.stop_purpose!='Visit Only':frappe.throw('Select this Trip optional-sale customer stop')
            from cfg_kanban.services.trip_sales import begin
            delivery=begin(doc,stop,values.get('customer_scan'),key,operator,operator_session_token)
            result['delivery_session']=delivery['name']
        elif action == 'Begin Delivery':
            for link in doc.dispatch_plans:
                if link.dispatch_plan == plan.name:
                    continue
                other = _read('CFG Kanban Dispatch Plan', link.dispatch_plan)
                if other.delivery_session:
                    active = _read('CFG Kanban Delivery Session', other.delivery_session)
                    if active.state not in ('Closed', 'Cancelled'):
                        frappe.throw('Complete the existing customer Delivery Note and proof before starting another delivery')
            policy = snapshot['policies'][plan.name]
            scan = str(values.get('customer_scan') or '').strip()
            if policy['require_scan'] and not scan:
                frappe.throw('Scan the assigned Customer Site QR before confirming this stop')
            if values.get('quantities') is not None:
                from cfg_kanban.services.driver_delivery_outcomes import declare
                declare(doc,stop,plan,values['quantities'],operator,session,key)
            if policy['sheet']:
                delivery = _sheets().start_route_sheet_stop(policy['sheet'], policy['row_key'], key, operator_session_token, scan or None)
            else:
                site = _delivery()._resolve_customer_site(scan or stop.customer_scan_point)
                delivery = _prepared().start_prepared_delivery(plan.name, site.site_code, key, operator_session_token)
            doc.db_set('driver_active_stop_key', stop.stop_key, update_modified=True)
            result['delivery_session'] = delivery['name']
        elif action == 'Complete Stop':
            if not _finish(doc, stop, operator, operator_session_token, values.get('notes')):
                frappe.throw('Complete every Delivery Note and required proof before closing this stop')
            result['stop_completed'] = True
        else:
            delivery = _session(plan, operator, stop)
            if action == 'Confirm Allocations':
                _delivery().confirm_delivery_allocations(delivery.name, key, operator_session_token)
            elif action == 'Create Delivery Note':
                _delivery().create_customer_delivery_document(delivery.name, key, operator_session_token,
                    frappe.as_json(values.get('required_erp_inputs') or {'parent': {}, 'tables': {}}))
            elif action == 'Open Proof':
                result['proof_name'] = _proof().get_or_create_delivery_proof(delivery.name, operator_session_token)['name']
            elif action == 'Submit Proof':
                if values.get('proof_name') != delivery.delivery_proof:
                    frappe.throw('Proof record does not belong to this exact Delivery Session')
                _proof().submit_delivery_proof(event_token=key, operator_session_token=operator_session_token, **values)
            result['delivery_session'] = delivery.name
            # Closure is always based on native submitted DN/proof feedback, never a button click alone.
            result['stop_completed'] = _finish(doc, stop, operator, operator_session_token)
    doc.db_set('driver_route_revision', cint(doc.driver_route_revision) + 1, update_modified=True)
    return _record(doc, operator, session, key, request, result)


@frappe.whitelist()
def reconcile_driver_action(trip_name, action, event_token, operator_session_token, expected_revision=None,
                            scope_hash=None, stop_key=None, dispatch_plan=None, payload=None,
                            request_actor=None, void_reason=None):
    operator, session = require_operator(operator_session_token)
    doc = _root(trip_name)
    actor = request_actor or operator.employee
    if actor != operator.employee and not (_views()._all(operator) and operator.can_override):
        frappe.throw('Only an authorized Supervisor may reconcile another operator request', frappe.PermissionError)
    _delivery()._require_customer_delivery(operator)
    request = _request(trip_name, action, stop_key, dispatch_plan, payload, expected_revision, scope_hash)
    key = _key(doc, actor, event_token); receipt = _receipt(key, request)
    if receipt:
        return receipt
    if not void_reason:
        return dict(status='Not Recorded')
    if not str(void_reason).strip() or not (_views()._all(operator) and operator.can_override):
        frappe.throw('Supervisor authority and a reason are required to void an unrecorded driver request')
    return _record(doc, operator, session, key, request, void_reason=str(void_reason).strip(), actor=actor)


def _special_action(doc,request,operator,session,token,key):
    require_operator(token,'start' if request['action']=='Collect Old Return' else 'override')
    if request['scope_hash']!=_core(doc) or request['expected_revision']!=cint(doc.driver_route_revision):
        frappe.throw('Trip changed; refresh before confirming new details')
    if request['dispatch_plan']:
        frappe.throw('Select the trip stop instead of substituting a Dispatch Plan')
    stop=next((r for r in doc.stops if r.stop_key==request['stop_key']),None)
    if not stop:frappe.throw('Select the exact saved customer stop')
    if request['action']=='Collect Old Return':
        from cfg_kanban.services.driver_collections import collect
        result=collect(doc,stop,request['payload'],operator,session,token,key)
    else:
        if not (_views()._all(operator) and operator.can_override):frappe.throw('Supervisor with Override is required',frappe.PermissionError)
        from cfg_kanban.services.driver_delivery_outcomes import OUTCOME, release
        outcome=_read(OUTCOME,request['payload'].get('outcome'))
        if outcome.delivery_trip!=doc.name or outcome.stop_key!=stop.stop_key:frappe.throw('Refused stock belongs to another trip or customer')
        release(outcome,request['payload'].get('line_names'),request['payload'].get('reason'),operator,session)
        result=dict(outcome=outcome.name)
    doc.db_set('driver_route_revision',cint(doc.driver_route_revision)+1,update_modified=True)
    return _record(doc,operator,session,key,request,result)


@frappe.whitelist()
def preview_driver_collection(trip_name,stop_key,payload,operator_session_token):
    operator,_session=require_operator(operator_session_token,'start')
    doc=_views()._trip(trip_name,operator)
    stop=next((r for r in doc.stops if r.stop_key==stop_key),None)
    if not stop:frappe.throw('Select the exact saved customer stop')
    from cfg_kanban.services.driver_collections import preview
    return preview(doc,stop,frappe.parse_json(payload) if isinstance(payload,str) else payload,operator,operator_session_token)


@frappe.whitelist()
def preview_driver_quantities(trip_name,stop_key,dispatch_plan,quantities,operator_session_token):
    operator,_session=require_operator(operator_session_token,'start')
    doc=_views()._trip(trip_name,operator)
    saved=json.loads(doc.driver_route_snapshot_json or '{}')
    _target(doc,dict(stop_key=stop_key),saved)
    if dispatch_plan not in {r.dispatch_plan for r in doc.dispatch_plans if r.stop_key==stop_key}:
        frappe.throw('Select the exact prepared Plan for this stop')
    plan=_read('CFG Kanban Dispatch Plan',dispatch_plan)
    _planning()._assert_plan_authorized(plan,operator)
    from cfg_kanban.services.driver_delivery_outcomes import quantities as validate_quantities
    return validate_quantities(plan,quantities)

"""Approved customer itineraries over existing prepared/open-route delivery services.

Sheets authorize visit order and preserve template/route snapshots; ERP stock,
customer allocations, Delivery Notes, proof and E5 settlement stay on their owners.
"""
import json
import frappe
from frappe.utils import cint, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

SHEET='CFG Kanban Route Sheet'
TEMPLATE='CFG Kanban Route Template'
PER_PLAN='Per Dispatch Plan'
COMBINED='Combined Lorry Trip'
QR='Require Customer Site QR'
SELECT='Allow Assigned Stop Selection'
TERMINAL={'Completed','Skipped','Cancelled','Closed Incomplete'}

class RouteSheetReplayError(Exception):
    """A route action has a different recorded payload or was explicitly voided."""


def _plans():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning

def _routes():
    from cfg_kanban.services import route_delivery
    return route_delivery

def _delivery():
    from cfg_kanban.services import customer_delivery
    return customer_delivery

def _fulfilment():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _closure():
    from cfg_kanban.services import dispatch_closure
    return dispatch_closure


def scope(plan):
    return plan.get('route_sequence_scope') or PER_PLAN


def verification(plan):
    # Legacy profile snapshots predate the Check field: preserve mandatory Site scanning.
    snapshot=json.loads(plan.profile_snapshot_json or '{}')
    return SELECT if snapshot.get('customer_verification')==SELECT else QR


def template_snapshot(name,company):
    if not name:return None
    doc=frappe.get_doc(TEMPLATE,name)
    doc.check_permission('read')
    if not doc.active or doc.company!=company:
        frappe.throw('Select an active Route Template for this Company')
    stops=[dict(customer_scan_point=row.customer_scan_point,instructions=row.instructions or '')
           for row in doc.stops if (row.get('stop_purpose') or 'Delivery') == 'Delivery']
    if not stops:
        frappe.throw('This template has only Visit Only stops; select Delivery stops for dispatch execution')
    return dict(name=doc.name,revision=cint(doc.revision),company=doc.company,stops=stops)


def _supervisor(operator):
    _routes()._supervisor(operator)


def _plan(name,operator):
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',name,for_update=True)
    _plans()._assert_plan_authorized(plan,operator)
    if plan.fulfilment_mode!='Vehicle Delivery' or plan.state in ('Cancelled','Reconciled','Fulfilled'):
        frappe.throw('Select active Vehicle Delivery work for route planning')
    if plan.get('dispatch_review_state'):
        frappe.throw('Resolve Dispatch Review before changing or starting the route')
    return plan


def _lock(key):
    if not isinstance(key,str) or ':' not in key or key.split(':',1)[0] not in ('P','V'):
        frappe.throw('Select a valid Plan or lorry route scope')
    kind,name=key.split(':',1)
    if kind not in ('P','V') or not name:frappe.throw('Select a valid route scope')
    table='Warehouse' if kind=='V' else 'CFG Kanban Dispatch Plan'
    frappe.db.sql(f'select name from `tab{table}` where name=%s for update',name)


def _scope_key(plan=None,warehouse=None):
    return 'V:'+warehouse if warehouse else 'P:'+plan


def plan_scope_key(plan):
    if scope(plan)==COMBINED:
        if not plan.vehicle_warehouse:frappe.throw('Claim the lorry before starting its route')
        return _scope_key(warehouse=plan.vehicle_warehouse)
    return _scope_key(plan=plan.name)


def lock_plan_route_scope(plan,operator):
    _plans()._assert_plan_authorized(plan,operator)
    key=plan_scope_key(plan)
    _lock(key)
    return key


def check_plan_route_scope(plan,key):
    if plan_scope_key(plan)!=key:
        frappe.throw('Lorry assignment changed; refresh the route before starting a visit')


def _current_sheet(key):
    name=frappe.db.get_value(SHEET,{'active_scope_key':key},'name',for_update=True)
    return frappe.get_doc(SHEET,name,for_update=True) if name else None


def _sheet_scope(sheet):
    return _scope_key(plan=sheet.dispatch_plan) if sheet.scope==PER_PLAN else _scope_key(warehouse=sheet.vehicle_warehouse)


def _sheet_members(sheet,operator):
    # Teardown belongs to the frozen itinerary, never today's candidate lorry loads.
    names=sorted({row.dispatch_plan for row in sheet.stops})
    if not names:frappe.throw('This Route Sheet has no member Plans; review its audit history')
    # P: scopes already hold their Plan. Feedback locks Session -> Plan -> Route Stop,
    # so never take Session locks from here. Current Plan mirrors detect prior starts;
    # Closure additionally verifies the locked Plan mirrors and all posted evidence.
    plans=[frappe.get_doc('CFG Kanban Dispatch Plan',name,for_update=True) for name in names]
    for plan in plans:
        _plans()._assert_plan_authorized(plan,operator)
        plan.check_permission('read')
        if plan.company!=sheet.company:frappe.throw('Route Sheet member Plan belongs to another Company')
        if plan.get('active_route_sheet') and plan.active_route_sheet!=sheet.name:
            frappe.throw('A member Plan belongs to a newer Route Sheet; resolve that route first')
    sessions=frappe.db.get_values('CFG Kanban Delivery Session',{'dispatch_plan':['in',names]},
        ['name','dispatch_plan','state'],as_dict=True,order_by='name asc')
    return plans,sessions


def _closure_context(plans,sessions):
    members=[]
    for plan in plans:
        opened=[dict(name=row.name,state=row.state) for row in sessions
                if row.dispatch_plan==plan.name and row.state not in ('Closed','Cancelled')]
        members.append(dict(name=plan.name,state=plan.state,review_state=plan.get('dispatch_review_state') or '',
            settled=plan.state=='Reconciled' and plan.get('dispatch_review_state')=='Settled',
            active_route_stop=plan.get('active_route_stop'),open_deliveries=opened,
            office_delivery_trip=plan.get('office_delivery_trip')))
    return dict(plans=members,ready=all(row['settled'] and not row['open_deliveries'] and not row['active_route_stop'] for row in members))


def _assert_legacy_cancellation(plans):
    # A live office Trip owns its frozen driver itinerary. Stop cancellation there must
    # use its existing Supervisor workflow; changing its Sheet independently strands it.
    for name in sorted({plan.get('office_delivery_trip') for plan in plans if plan.get('office_delivery_trip')}):
        state=frappe.db.get_value('CFG Kanban Delivery Trip',name,'state')
        if state not in ('Closed','Cancelled'):
            frappe.throw('This route belongs to active Delivery Trip '+name+
                '; use its customer-stop cancellation and E5 closure workflow first')


def _members(key,operator,allow_unloaded=True):
    kind,name=key.split(':',1)
    if kind=='P':
        plan=_plan(name,operator)
        if not plan.vehicle_warehouse:frappe.throw('Claim the lorry before creating its trip Route Sheet')
        if scope(plan)!=PER_PLAN:frappe.throw('This Plan uses its combined lorry trip Route Sheet')
        return [plan]
    vehicle=_plans()._vehicle_warehouse(name)
    frappe.get_doc('Warehouse',name).check_permission('read')
    candidates=frappe.get_all('CFG Kanban Dispatch Plan',filters={'company':vehicle.company,
        'vehicle_warehouse':name,'fulfilment_mode':'Vehicle Delivery',
        'state':['in',['Vehicle Claimed','Loading','Ready to Dispatch','Dispatch Pending','Loaded','Ready for Fulfilment']]},
        fields=['name','route_sequence_scope'],order_by='name asc',limit_page_length=0)
    plans=[_plan(row.name,operator) for row in candidates if row.route_sequence_scope==COMBINED]
    if not plans:frappe.throw('No active combined-trip Dispatch Plans are assigned to this lorry')
    return plans


def _site(name,plan):
    site=frappe.get_doc('CFG Kanban Customer Scan Point',name)
    site.check_permission('read')
    if not site.active or site.selling_company!=plan.company:
        frappe.throw('Every route stop must use an active Customer Site in this Company')
    if frappe.db.get_value('Customer',site.customer,'disabled'):
        frappe.throw('Route stop Customer is disabled')
    if plan.get('consolidated_customer_orders'):
        matches=[r for r in _routes()._stops(plan) if r.customer_scan_point==site.name and r.state not in ('Cancelled','Skipped')]
        if not matches:frappe.throw('Customer Site is outside this consolidated customer demand')
    elif plan.plan_type=='Customer Order':
        if plan.customer_site!=site.name or plan.customer!=site.customer or plan.customer_address!=site.customer_address:
            frappe.throw('Customer Order stop must match its assigned Customer and address')
    else:_routes()._assert_site_scope(plan,site)
    return site


def _address(name):
    if not name:return ''
    address=frappe.get_doc('Address',name)
    address.check_permission('read')
    return ', '.join(str(address.get(key) or '').strip() for key in
        ('address_line1','address_line2','city','state','pincode','country') if address.get(key))


def _status(row):
    # Delivery feedback holds Session -> Plan -> Route Stop. Never lock an existing
    # Session from a route read; use the completion status mirrored under its Plan lock.
    plan=frappe.db.get_value('CFG Kanban Dispatch Plan',row.dispatch_plan,
        ['state','dispatch_review_state','delivery_session','fulfilment_status'],as_dict=True,for_update=True)
    if row.source_route_stop:
        source=_live_source_stop(row)
        result=dict(state=source.state if source else 'Exception',
            delivery_session=source.delivery_session if source else None,
            actual_sequence=row.actual_sequence or (source.actual_sequence if source else None))
    elif plan and plan.delivery_session:
        states={'Not Started':'Planned','In Progress':'In Progress','Delivery Note Pending':'Delivery Note Pending',
                'Delivered':'Delivered','Completed':'Completed','Exception':'Exception','Closed Incomplete':'Closed Incomplete'}
        result=dict(state=states.get(plan.fulfilment_status,'Exception'),delivery_session=plan.delivery_session,actual_sequence=row.actual_sequence)
    else:
        result=dict(state=row.state or 'Planned',delivery_session=None,actual_sequence=row.actual_sequence)
    if result['state']=='Planned' and plan and plan.state=='Reconciled' and plan.dispatch_review_state=='Settled':
        result['state']='Closed Incomplete'
    return result


def sheet_context(sheet,operator):
    sheet.check_permission('read')
    frappe.get_doc('Company',sheet.company).check_permission('read')
    if sheet.vehicle_warehouse:frappe.get_doc('Warehouse',sheet.vehicle_warehouse).check_permission('read')
    members=sorted({row.dispatch_plan for row in sheet.stops})
    plans=[frappe.get_doc('CFG Kanban Dispatch Plan',name) for name in members]
    for plan in plans:
        _plans()._assert_plan_authorized(plan,operator)
        plan.check_permission('read')
    result=sheet.as_dict()
    result['stops']=[dict(row.as_dict(),**_status(row)) for row in sheet.stops]
    if sheet.state in ('Approved','In Progress','Ready to Close') and all(row['state'] in TERMINAL for row in result['stops']):result['state']='Ready to Close'
    result['can_edit']=bool(sheet.state=='Draft' and operator.kanban_role in ('Supervisor','Development Proxy') and operator.get('can_override'))
    result['can_start']=bool(result['state'] in ('Approved','In Progress') and operator.get('can_start') and _delivery()._customer_delivery_allowed(operator))
    result['can_close']=bool(result['state']=='Ready to Close' and operator.get('can_start') and operator.get('can_override') and operator.kanban_role in ('Supervisor','Development Proxy'))
    result['can_cancel']=bool(sheet.state not in ('Completed','Cancelled') and operator.get('can_start') and operator.get('can_override') and operator.kanban_role in ('Supervisor','Development Proxy'))
    if sheet.state not in ('Completed','Cancelled'):
        sessions=frappe.db.get_values('CFG Kanban Delivery Session',{'dispatch_plan':['in',members]},
            ['name','dispatch_plan','state'],as_dict=True,order_by='name asc')
        result['cancellation']=_closure_context(plans,sessions)
    return result


@frappe.whitelist()
def get_route_context(operator_session_token,dispatch_plan=None,warehouse=None,route_sheet=None,template=None):
    operator,_session=require_operator(operator_session_token)
    if route_sheet:
        sheet=frappe.get_doc(SHEET,route_sheet)
        if sheet.state!='Draft' or any(frappe.db.get_value('CFG Kanban Dispatch Plan',row.dispatch_plan,'state') in ('Cancelled','Reconciled') for row in sheet.stops):return dict(sheet=sheet_context(sheet,operator),scope_key=_sheet_scope(sheet))
        dispatch_plan=sheet.dispatch_plan if sheet.scope==PER_PLAN else None
        warehouse=sheet.vehicle_warehouse if sheet.scope==COMBINED else None
    if dispatch_plan:
        plan=_plan(dispatch_plan,operator)
        if scope(plan)==COMBINED:
            if not plan.vehicle_warehouse:frappe.throw('Claim the actual lorry before opening its combined trip route')
            warehouse=plan.vehicle_warehouse;dispatch_plan=None
    if not warehouse and not dispatch_plan:frappe.throw('Scan a lorry card or select its Dispatch Plan')
    key=_scope_key(dispatch_plan,warehouse)
    _lock(key)
    sheet=_current_sheet(key)
    if sheet and sheet.state!='Draft':return dict(sheet=sheet_context(sheet,operator),scope_key=key)
    plans=_members(key,operator)
    company=plans[0].company
    templates=frappe.get_list(TEMPLATE,filters={'active':1,'company':company},
        fields=['name','revision'],order_by='name asc',limit_page_length=0)
    frappe.get_doc('Company',company).check_permission('read')
    selected=template_snapshot(template,company) if template else (json.loads(sheet.template_snapshot_json) if sheet and sheet.template_snapshot_json else None)
    if not selected and sheet and sheet.template_snapshot_json:selected=json.loads(sheet.template_snapshot_json)
    if not selected:
        snapshots={row.get('route_template_snapshot_json') for row in plans if row.get('route_template_snapshot_json')}
        if len(snapshots)==1:selected=json.loads(next(iter(snapshots)))
    seeds=[]
    if selected:
        for source in selected['stops']:
            matches=[row for row in plans if row.plan_type=='Customer Order' and row.customer_site==source['customer_scan_point']]
            if not matches:
                matches=[row for row in plans if row.plan_type=='Open Route Stock']
            # Keep ambiguous sources unassigned; the Supervisor must select the Plan.
            seeds.append(dict(source,dispatch_plan=matches[0].name if len(matches)==1 else None))
    else:
        seeds=[dict(customer_scan_point=row.customer_site,dispatch_plan=row.name,instructions='') for row in plans if row.plan_type=='Customer Order']
        for plan in plans:
            if plan.plan_type=='Open Route Stock':
                seeds.extend(dict(customer_scan_point=row.customer_scan_point,dispatch_plan=plan.name,instructions='',source_route_stop=row.name)
                             for row in _routes()._stops(plan) if row.state=='Planned')
    sites=frappe.get_list('CFG Kanban Customer Scan Point',filters={'active':1,'selling_company':company},
        fields=['name','site_code','site_name','customer','customer_address'],order_by='site_name asc, name asc',limit_page_length=0)
    for site in sites:site['address_display']=_address(site.customer_address)
    if sheet and not template:seeds=[row.as_dict() for row in sheet.stops]
    office_seeds=_office_trip_seeds(plans)
    if office_seeds is not None and not sheet:seeds=office_seeds
    return dict(sheet=sheet_context(sheet,operator) if sheet else None,scope_key=key,company=company,scope=COMBINED if warehouse else PER_PLAN,
        warehouse=warehouse or plans[0].vehicle_warehouse,template=selected,template_hash=canonical_key('route-template',selected) if selected else None,templates=templates,stops=seeds,sites=sites,
        plans=[dict(name=row.name,customer=row.customer,customer_site=row.customer_site,plan_type=row.plan_type,state=row.state) for row in plans],
        can_edit=bool(operator.kanban_role in ('Supervisor','Development Proxy') and operator.get('can_override')))


def _action_key(key,operator,event_token):
    _plans()._require_event_token(event_token)
    return canonical_key('route-sheet-action',key,operator.employee,event_token)


def _receipt(key,fingerprint=None):
    value=frappe.db.get_value('CFG Kanban Event',{'idempotency_key':key},['payload_json'],as_dict=True,for_update=True)
    if not value:return None
    payload=json.loads(value.payload_json or '{}')
    if fingerprint and payload.get('request_hash')!=fingerprint:
        frappe.throw('This route action belongs to different details; reconcile its original request',RouteSheetReplayError)
    return payload


def _normal_rows(rows,plans):
    submitted=frappe.parse_json(rows) if isinstance(rows,str) else rows
    if not isinstance(submitted,list) or not submitted:frappe.throw('Add at least one assigned Customer stop')
    by_name={row.name:row for row in plans};seen=set();result=[];covered=set()
    for raw in submitted:
        if not isinstance(raw,dict):frappe.throw('Invalid route stop')
        plan=by_name.get(raw.get('dispatch_plan'))
        if not plan:frappe.throw('Select an eligible Dispatch Plan for every stop; stock sources cannot be guessed')
        identity=str(raw.get('row_key') or '').strip()
        if not identity or identity in seen:frappe.throw('Every stop needs a distinct stable row identity')
        seen.add(identity);site=_site(raw.get('customer_scan_point'),plan)
        if plan.plan_type=='Customer Order' and not plan.get('consolidated_customer_orders') and plan.name in covered:
            frappe.throw('A Customer Order Plan has one prepared customer delivery; include it once')
        covered.add(plan.name)
        result.append(dict(row_key=identity,dispatch_plan=plan.name,customer_scan_point=site.name,
            site_name=site.site_name,customer=site.customer,customer_address=site.customer_address,
            address_display=_address(site.customer_address),instructions=str(raw.get('instructions') or '').strip(),state='Planned'))
        if raw.get('source_route_stop'):
            source=frappe.get_doc('CFG Kanban Route Stop',raw['source_route_stop'])
            if source.dispatch_plan!=plan.name or source.customer_scan_point!=site.name or source.state!='Planned':frappe.throw('Select an exact Planned native visit for this route row')
            result[-1]['source_route_stop']=source.name
    if covered!=set(by_name):frappe.throw('The route must include every active Plan in this route scope')
    office=_office_trip_seeds(plans)
    if office is not None:
        identity=lambda row:(row['dispatch_plan'],row['customer_scan_point'],row.get('source_route_stop') or '')
        if len(result)!=len(office) or {identity(r) for r in result}!={identity(r) for r in office}:
            frappe.throw('Retain every exact office Trip visit; edit its stop list before generating dispatch work')
    return result


def _approve(sheet,plans,operator):
    _supervisor(operator)
    if sheet.scope==COMBINED and any(not _route_ready(row) for row in plans):
        frappe.throw('Complete physical loading for every combined-trip Plan before approving the route')
    # Existing E4B visits are reused; approval projects the order within each Plan.
    by_plan={row.name:row for row in plans}
    assigned={};used=set()
    for row in sheet.stops:
        plan=by_plan[row.dispatch_plan]
        if plan.plan_type!='Open Route Stock' and not plan.get('consolidated_customer_orders'):continue
        existing=[stop for stop in _routes()._stops(plan,current=True) if stop.state=='Planned'
                  and stop.customer_scan_point==row.customer_scan_point and stop.name not in used
                  and (not row.source_route_stop or row.source_route_stop==stop.name)]
        if len(existing)>1:frappe.throw('Several existing visits match this Site; skip unwanted old visits before route approval')
        if existing:
            stop=frappe.get_doc('CFG Kanban Route Stop',existing[0].name,for_update=True)
        else:
            if plan.get('consolidated_customer_orders'):frappe.throw('Retain the exact saved consolidated customer scope')
            site=_site(row.customer_scan_point,plan)
            stop=_routes()._new_stop(plan,site,operator,canonical_key('route-sheet-stop',sheet.name,row.row_key))
        used.add(stop.name);assigned.setdefault(plan.name,[]).append(stop)
        row.source_route_stop=stop.name
    for plan in plans:
        if plan.plan_type!='Open Route Stock' and not plan.get('consolidated_customer_orders'):continue
        old=[row for row in _routes()._stops(plan,current=True) if row.state=='Planned']
        if any(row.name not in used for row in old):
            frappe.throw('Existing planned visits are outside this route; explicitly skip them before approving a replacement')
        for index,stop in enumerate(assigned.get(plan.name,[]),1):
            stop.db_set('planned_sequence',index,update_modified=True)
    sheet.state='Approved';sheet.approved_by_operator=operator.employee;sheet.approved_on=now_datetime()


@frappe.whitelist()
def save_route_sheet(scope_key,stops,expected_revision,event_token,operator_session_token,
                     action='Save Draft',template=None,reason=None,template_hash=None,route_sheet=None):
    args=(scope_key,stops,expected_revision,event_token,operator_session_token,action,template,reason,template_hash,route_sheet)
    if action!='Close':return _save_route_sheet(*args)
    frappe.db.savepoint('cfg_close_route')
    try:
        return _save_route_sheet(*args)
    except Exception as error:
        frappe.db.rollback(save_point='cfg_close_route')
        _closure().report_blocker(error)
        raise


def _save_route_sheet(scope_key,stops,expected_revision,event_token,operator_session_token,
                      action='Save Draft',template=None,reason=None,template_hash=None,route_sheet=None):
    operator,session=require_operator(operator_session_token,'start')
    if action not in ('Save Draft','Approve','Cancel','Close'):frappe.throw('Select a valid route action')
    _lock(scope_key)
    key=_action_key(scope_key,operator,event_token)
    request=dict(scope_key=scope_key,stops=frappe.parse_json(stops) if isinstance(stops,str) else stops,
        expected_revision=cint(expected_revision),action=action,template=template or None,template_hash=template_hash or None,reason=(reason or '').strip())
    # Old browser receipts have no parent ID. Keep their hash stable for read-back/retry.
    if route_sheet:request['route_sheet']=route_sheet
    fingerprint=canonical_key('route-sheet-request',request)
    receipt=_receipt(key,fingerprint)
    if receipt:
        if receipt.get('voided'):frappe.throw('This unrecorded route action was voided',RouteSheetReplayError)
        return dict(sheet=sheet_context(frappe.get_doc(SHEET,receipt['route_sheet']),operator),scope_key=scope_key)
    current=_current_sheet(scope_key)
    sheet=frappe.get_doc(SHEET,route_sheet,for_update=True) if route_sheet else current
    if sheet and _sheet_scope(sheet)!=scope_key:frappe.throw('Route Sheet does not belong to this route scope')
    if sheet:
        sheet.check_permission('read')
        frappe.get_doc('Company',sheet.company).check_permission('read')
        if sheet.vehicle_warehouse:frappe.get_doc('Warehouse',sheet.vehicle_warehouse).check_permission('read')
    teardown=action in ('Close','Cancel')
    if not teardown and route_sheet and (not current or current.name!=sheet.name):
        frappe.throw('Route changed; refresh before saving this revision')
    plans,sessions=(_sheet_members(sheet,operator) if sheet else ([],[])) if teardown else (_members(scope_key,operator),[])
    for plan in plans:_plans()._assert_plan_authorized(plan,operator)
    if action=='Close' and sheet and sheet.state=='Completed':
        _supervisor(operator)
        if not request['reason']:frappe.throw('An existing route and decision reason are required')
        return dict(sheet=sheet_context(sheet,operator),scope_key=scope_key)
    settlements=[]
    if (cint(sheet.revision) if sheet else 0)!=cint(expected_revision):
        frappe.throw('Route changed; refresh before saving this revision')
    if teardown:
        _supervisor(operator)
        if not sheet or not request['reason']:frappe.throw('An existing route and decision reason are required')
        if sheet.state in ('Completed','Cancelled'):frappe.throw('This Route Sheet is already closed; its history is retained')
        if not isinstance(request['stops'],list) or any(not isinstance(row,dict) for row in request['stops']):
            frappe.throw('Refresh the Route Sheet stops before cancelling or closing')
        identities=lambda values:[(row.get('row_key'),row.get('dispatch_plan'),row.get('customer_scan_point')) for row in values]
        if identities(request['stops'] or [])!=identities(sheet.stops):
            frappe.throw('Route changed; refresh the exact Route Sheet before cancelling or closing')
        states=[_status(row)['state'] for row in sheet.stops]
        if action=='Cancel':
            _assert_legacy_cancellation(plans)
            started=bool(sessions or sheet.get('cancellation_requested_on') or sheet.state in ('In Progress','Cancellation Pending') or
                any(plan.get('delivery_session') or plan.get('active_route_stop') or plan.get('dispatch_review_state') for plan in plans) or
                any(row.get('delivery_session') or row.get('actual_sequence') for row in sheet.stops) or
                any(state not in ('Planned','Skipped','Cancelled','Closed Incomplete') for state in states))
            closure=_closure_context(plans,sessions)
            if started and not closure['ready']:
                if not current or current.name!=sheet.name:
                    frappe.throw('This historical route is no longer active; settle its original Plans through E5 before cancelling it')
                if not sheet.get('cancellation_requested_on'):
                    sheet.cancellation_requested_on=now_datetime()
                    sheet.cancellation_requested_by=operator.employee
                    sheet.cancellation_reason=request['reason']
                    sheet.cancellation_snapshot_json=frappe.as_json(closure)
                sheet.state='Cancellation Pending'
            else:
                for row in sheet.stops:
                    if row.source_route_stop:
                        stop=_live_source_stop(row)
                        if stop and stop.state=='Planned':stop.db_set({'state':'Skipped','skip_reason':request['reason'],'skipped_by':operator.employee,'skipped_on':now_datetime()},update_modified=True)
                sheet.state='Cancelled'
        else:
            if sheet.state=='Cancellation Pending':frappe.throw('Finish the pending Route Sheet cancellation after E5 settlement')
            if any(state not in TERMINAL for state in states):
                frappe.throw('Complete or skip every Route Sheet stop before closing the route')
            # Preflight every member before the first write. The outer savepoint also
            # rolls back all settlements if a later audit/save/response fails.
            checked=[_closure().inspect_plan(plan) for plan in plans]
            _closure().validate_group(checked)
            settlements=[_closure().settle(value,operator,session,request['reason'],key,fingerprint,sheet.name)
                         for value in checked]
            sheet.state='Completed'
        if sheet.state in ('Cancelled','Completed'):
            sheet.active_scope_key=None;sheet.closed_on=now_datetime();sheet.decision_notes=request['reason']
    else:
        if sheet and sheet.state!='Draft':frappe.throw('Approved route order is frozen; finish its visits or stop/cancel the route with a reason')
        _supervisor(operator)
        if any(not _route_ready(plan) for plan in plans):frappe.throw('Load every assigned Plan before saving its trip route')
        if any(plan.get('active_route_sheet') and (not sheet or plan.active_route_sheet!=sheet.name) for plan in plans):frappe.throw('Close or cancel the previous Route Sheet before planning another trip')
        rows=_normal_rows(request['stops'],plans)
        snapshot=None
        if template:
            frozen=[json.loads(plan.route_template_snapshot_json) for plan in plans if plan.get('route_template_snapshot_json')]
            if sheet and sheet.template_snapshot_json:frozen.append(json.loads(sheet.template_snapshot_json))
            snapshot=next((value for value in frozen if value['name']==template and canonical_key('route-template',value)==template_hash),None)
            if not snapshot:snapshot=template_snapshot(template,plans[0].company)
            if canonical_key('route-template',snapshot)!=template_hash:frappe.throw('Route Template changed; refresh its revision before saving')
        if not sheet:
            vehicle=plans[0].vehicle_warehouse
            sheet=frappe.get_doc(dict(doctype=SHEET,state='Draft',scope=COMBINED if scope_key.startswith('V:') else PER_PLAN,
                company=plans[0].company,dispatch_plan=plans[0].name if scope_key.startswith('P:') else None,
                vehicle_warehouse=vehicle,vehicle_reference=plans[0].vehicle_reference,trip_date=plans[0].trip_date or plans[0].required_date,
                created_by_operator=operator.employee,created_on=now_datetime(),active_scope_key=scope_key,revision=0))
        sheet.sequence_policy='Planned Order' if any(row.stop_sequence_policy=='Planned Order' for row in plans) else 'Flexible Order'
        sheet.verification_policy=QR if any(verification(row)==QR for row in plans) else SELECT
        if snapshot:
            sheet.route_template=snapshot['name'];sheet.template_revision=snapshot['revision'];sheet.template_snapshot_json=frappe.as_json(snapshot)
        sheet.set('stops',rows)
        if sheet.is_new():sheet.insert(ignore_permissions=True)
        if action=='Approve':
            if any(not _route_ready(plan) for plan in plans):frappe.throw('Load every assigned Plan before route approval')
            _approve(sheet,plans,operator)
    sheet.revision=cint(sheet.revision)+1
    sheet.save(ignore_permissions=True)
    for plan in plans:
        if not teardown:plan.db_set('active_route_sheet',sheet.name,update_modified=False)
        elif sheet.state in ('Cancelled','Completed') and plan.get('active_route_sheet')==sheet.name:
            plan.db_set('active_route_sheet',None,update_modified=False)
    record('Customer Route Sheet '+action,reference_doctype=SHEET,reference_name=sheet.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        notes=request['reason'],idempotency_key=key,
        payload=dict(request_hash=fingerprint,route_sheet=sheet.name,revision=sheet.revision,
            action=action,state=sheet.state,settlements=settlements,sequence=[dict(plan=row.dispatch_plan,site=row.customer_scan_point,row_key=row.row_key) for row in sheet.stops]))
    return dict(sheet=sheet_context(sheet,operator),scope_key=scope_key)






@frappe.whitelist()
def reconcile_route_sheet_action(scope_key,event_token,operator_session_token,void_reason=None):
    operator,session=require_operator(operator_session_token)
    _lock(scope_key)
    key=_action_key(scope_key,operator,event_token)
    payload=_receipt(key)
    if payload:
        if payload.get('voided'):return dict(status='Voided')
        return dict(status='Recorded',sheet=sheet_context(frappe.get_doc(SHEET,payload['route_sheet']),operator))
    if not void_reason:return dict(status='Not Recorded')
    require_operator(operator_session_token,'start')
    record('Unrecorded Route Sheet Action Voided',reference_doctype='Employee',reference_name=operator.employee,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        idempotency_key=key,notes=str(void_reason).strip(),payload=dict(voided=True))
    return dict(status='Voided')


def _live_source_stop(row):
    name=row.source_route_stop
    for _ in range(30):
        if not name:return None
        source=frappe.get_doc('CFG Kanban Route Stop',name,for_update=True)
        if source.state!='Cancelled':return source
        replacement=frappe.db.get_value('CFG Kanban Route Stop',{'retry_of_stop':name},'name',for_update=True)
        if not replacement:return source
        name=replacement
    frappe.throw('Route cancellation history needs Supervisor reconciliation')


def assert_visit_allowed(plan,site_name,route_stop=None):
    """Called by both delivery entry points, so direct API calls cannot skip approval/order."""
    required=bool(plan.get('route_approval_required') or scope(plan)==COMBINED)
    linked=plan.get('active_route_sheet')
    key=_scope_key(warehouse=plan.vehicle_warehouse) if scope(plan)==COMBINED else _scope_key(plan=plan.name)
    _lock(key)
    sheet=frappe.get_doc(SHEET,linked,for_update=True) if linked else _current_sheet(key)
    if not sheet:
        if required:frappe.throw('Prepare and obtain Supervisor approval for this customer route before delivery')
        return None
    if sheet.company!=plan.company or sheet.vehicle_warehouse!=plan.vehicle_warehouse:
        frappe.throw('Route Sheet Company/lorry no longer matches this loaded Plan')
    if sheet.state=='Cancellation Pending':
        frappe.throw('Route cancellation is pending; resolve existing deliveries and settle its Plans through E5')
    if sheet.state not in ('Approved','In Progress','Ready to Close'):
        frappe.throw('Supervisor must approve this route before customer delivery can start')
    matches=[];pending=[];active=[]
    for row in sheet.stops:
        status=_status(row)['state']
        if status not in TERMINAL:pending.append(row)
        if status not in TERMINAL|{'Planned'}:active.append(row)
        source=_live_source_stop(row)
        if (row.dispatch_plan==plan.name and row.customer_scan_point==site_name
                and (not route_stop or (source and source.name==route_stop)) and status not in TERMINAL):matches.append(row)
    if len(matches)!=1:frappe.throw('Select the exact assigned stop on the approved Route Sheet')
    target=matches[0]
    if any(row.name!=target.name for row in active):frappe.throw('Complete the active lorry customer visit and proof before starting another stop')
    if sheet.sequence_policy=='Planned Order' and pending and pending[0].name!=target.name:
        source=_live_source_stop(target)
        approved=bool(source and plan.get('allow_supervisor_override') and source.get('override_approved_by') and source.get('override_reason'))
        if not approved:
            from cfg_kanban.services.trip_sequence_scope import sequence_trip
            if sequence_trip(frappe,plan):
                from cfg_kanban.services.trip_sequence import native_order_permitted
                approved=native_order_permitted(plan,site_name,route_stop)
        if not approved:frappe.throw('Visit the next customer in the approved lorry route sequence')
    return sheet,target


@frappe.whitelist()
def start_route_sheet_stop(route_sheet,row_key,event_token,operator_session_token,customer_scan=None):
    operator,_session=require_operator(operator_session_token,'start')
    _delivery()._require_customer_delivery(operator)
    reference=frappe.get_doc(SHEET,route_sheet)
    selected=next((row for row in reference.stops if row.row_key==row_key),None)
    if selected:
        source_plan=frappe.get_doc('CFG Kanban Dispatch Plan',selected.dispatch_plan)
        from cfg_kanban.services.trip_sequence_scope import sequence_trip
        if sequence_trip(frappe,source_plan):
            from cfg_kanban.services.trip_sequence import lock_plan
            lock_plan(source_plan)
        elif source_plan.get('office_delivery_trip'):
            from cfg_kanban.services.trip_sales import lock_scope
            lock_scope(source_plan)
    _lock(_scope_key(plan=reference.dispatch_plan) if reference.scope==PER_PLAN else _scope_key(warehouse=reference.vehicle_warehouse))
    sheet=frappe.get_doc(SHEET,route_sheet,for_update=True)
    row=next((row for row in sheet.stops if row.row_key==row_key),None)
    if not row:frappe.throw('Select a customer stop on this Route Sheet')
    if not selected or row.dispatch_plan!=selected.dispatch_plan:frappe.throw('Route Sheet changed; refresh before starting this customer visit')
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',row.dispatch_plan)
    sheet_context(sheet,operator)
    _plans()._assert_plan_authorized(plan,operator)
    _plans()._require_event_token(event_token)
    key=canonical_key('route-sheet-visit',sheet.name,row.row_key,operator.employee,event_token)
    fingerprint=canonical_key('route-sheet-visit-request',row.row_key,str(customer_scan or '').strip())
    receipt=_receipt(key,fingerprint)
    if receipt:
        if receipt.get('voided'):frappe.throw('This unrecorded visit was voided',RouteSheetReplayError)
        return _delivery().get_delivery_session(receipt['delivery_session'],operator_session_token)
    plan=_plan(row.dispatch_plan,operator)
    site=_site(row.customer_scan_point,plan)
    if customer_scan:
        scanned=_delivery()._resolve_customer_site(customer_scan)
        if scanned.name!=site.name:frappe.throw('Customer Site scan does not match the selected route stop')
    elif sheet.verification_policy==QR:
        frappe.throw('Supervisor requires a Customer Site QR scan at this stop')
    if (row.customer!=site.customer or row.customer_address!=site.customer_address):
        frappe.throw('Customer Site details changed; Supervisor must reconcile this route snapshot')
    source=_live_source_stop(row)
    assert_visit_allowed(plan,site.name,source.name if source else None)
    if not _route_ready(plan):frappe.throw('The assigned Plan must be Loaded before a customer visit starts')
    if plan.plan_type=='Customer Order':
        delivery=_fulfilment().start_prepared_delivery(plan.name,site.site_code,key,operator_session_token,**({'customer_dispatch_stop':source.name} if plan.get('consolidated_customer_orders') and source else {}))
    else:
        if not source or source.state not in ('Planned','In Progress','Delivery Note Pending','Delivered'):
            frappe.throw('This route visit needs Supervisor recovery before starting')
        delivery=_routes().start_route_stop(plan.name,site.site_code,key,operator_session_token,route_stop=source.name)
    actual=cint(row.actual_sequence) or (max([cint(stop.actual_sequence) for stop in sheet.stops] or [0])+1)
    row.db_set({'delivery_session':delivery['name'],'actual_sequence':actual},update_modified=False)
    sheet.db_set('state','In Progress',update_modified=True)
    record('Approved Route Customer Visit Started',reference_doctype=SHEET,reference_name=sheet.name,
        delivery_session=delivery['name'],operator=operator.employee,idempotency_key=key,
        payload=dict(delivery_session=delivery['name'],row_key=row.row_key,request_hash=fingerprint))
    return delivery


def vehicle_sheets(warehouse,operator):
    result=[]
    names=frappe.get_all(SHEET,filters={'vehicle_warehouse':warehouse,'state':['not in',['Cancelled','Completed']]},
        fields=['name'],order_by='created_on desc',limit_page_length=0)
    for row in names:
        sheet=frappe.get_doc(SHEET,row.name)
        try:result.append(sheet_context(sheet,operator))
        except frappe.PermissionError:continue
    return result


@frappe.whitelist()
def get_route_launch_context(operator_session_token,scan_value=None,warehouse=None):
    operator,_session=require_operator(operator_session_token)
    value=str(scan_value or '').strip()
    if frappe.db.exists('CFG Kanban Dispatch Plan',value):
        return dict(choices=[dict(label=value,args=dict(dispatch_plan=value))])
    if frappe.db.exists(SHEET,value):return dict(choices=[dict(label=value,args=dict(route_sheet=value))])
    if warehouse:
        vehicle=_plans()._vehicle_warehouse(warehouse)
    else:
        from cfg_kanban.api.logistics import _resolve_kanban_card_scan
        card_name=_resolve_kanban_card_scan(value)
        if not card_name:frappe.throw('Scan a lorry Warehouse card, Dispatch Plan or Route Sheet')
        card=frappe.get_doc('CFG Kanban Card',card_name)
        vehicle=_plans()._vehicle_warehouse_from_scan(value,card.company)
    from cfg_kanban.services.vehicle_overview import vehicle_context
    view=vehicle_context(vehicle.name,operator)
    existing=vehicle_sheets(vehicle.name,operator)
    choices=[dict(label=sheet['name']+' · '+sheet['state'],args=dict(route_sheet=sheet['name'])) for sheet in existing]
    bound={row['dispatch_plan'] for sheet in existing for row in sheet['stops']}
    combined=False
    for row in view['assigned_plans']:
        if row.name in bound:continue
        plan=frappe.get_doc('CFG Kanban Dispatch Plan',row.name)
        if scope(plan)==COMBINED:combined=True
        else:choices.append(dict(label=row.name+' · '+(row.customer or row.business_label),args=dict(dispatch_plan=row.name)))
    if combined:choices.insert(0,dict(label=vehicle.cfg_vehicle_reference+' · Combined Lorry Trip',args=dict(warehouse=vehicle.name)))
    return dict(choices=choices,warehouse=vehicle.name)


@frappe.whitelist()
def reconcile_route_sheet_visit(route_sheet,row_key,event_token,operator_session_token,void_reason=None):
    operator,session=require_operator(operator_session_token)
    reference=frappe.get_doc(SHEET,route_sheet)
    _lock(_scope_key(plan=reference.dispatch_plan) if reference.scope==PER_PLAN else _scope_key(warehouse=reference.vehicle_warehouse))
    sheet=frappe.get_doc(SHEET,route_sheet,for_update=True)
    sheet_context(sheet,operator)
    row=next((value for value in sheet.stops if value.row_key==row_key),None)
    if not row:frappe.throw('Select a route stop')
    key=canonical_key('route-sheet-visit',sheet.name,row.row_key,operator.employee,event_token)
    receipt=_receipt(key)
    if receipt:
        if receipt.get('voided'):return dict(status='Voided')
        return dict(status='Recorded',result=_delivery().get_delivery_session(receipt['delivery_session'],operator_session_token))
    if not void_reason:return dict(status='Not Recorded')
    require_operator(operator_session_token,'start')
    record('Unrecorded Route Visit Voided',reference_doctype=SHEET,reference_name=sheet.name,
        operator=operator.employee,operator_session=session.name,idempotency_key=key,
        notes=str(void_reason).strip(),payload=dict(voided=True))
    return dict(status='Voided')


def _route_ready(plan):
    if plan.get('existing_lorry_stock_only'):
        from cfg_kanban.services.trip_dispatch import route_ready
        return route_ready(plan)
    return plan.state=='Loaded'


def _office_trip_seeds(plans):
    keys={r.get('office_delivery_trip') for r in plans}
    if len(keys)!=1 or not next(iter(keys)):return None
    trip=frappe.get_doc('CFG Kanban Delivery Trip',next(iter(keys)));trip.check_permission('read')
    names={r.name for r in plans};seeds=[]
    by_stop={}
    for link in trip.dispatch_plans:
        if link.dispatch_plan in names and not next(p for p in plans if p.name==link.dispatch_plan).get('consolidated_customer_orders'):by_stop.setdefault(link.stop_key,[]).append(link.dispatch_plan)
    native={}
    for plan in plans:
        if plan.get('consolidated_customer_orders'):
            native.update({r.office_stop_key:r for r in _routes()._stops(plan) if r.state=='Planned'})
    if trip.get('open_route_plan') in names:
        pool=next(r for r in plans if r.name==trip.open_route_plan)
        native.update({r.office_stop_key:r for r in _routes()._stops(pool) if r.state=='Planned'})
    for stop in trip.stops:
        for name in by_stop.get(stop.stop_key,[]):
            seeds.append(dict(dispatch_plan=name,customer_scan_point=stop.customer_scan_point,instructions=stop.instructions or ''))
        row=native.get(stop.stop_key)
        if row:seeds.append(dict(dispatch_plan=row.dispatch_plan,customer_scan_point=row.customer_scan_point,
            source_route_stop=row.name,instructions=stop.instructions or ''))
    return seeds

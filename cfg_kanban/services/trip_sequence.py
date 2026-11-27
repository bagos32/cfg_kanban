"""Runtime Trip order and bounded Supervisor decisions over native delivery controls."""
import json

import frappe
from frappe.utils import cint, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

TRIP = 'CFG Kanban Delivery Trip'
REQUEST = 'CFG Kanban Route Change Request'
NEXT = 'Next Customer Only'
FULL = 'Entire Proposed Order'
ACTIONS = ('Change Route Order','Request Route Change','Cancel Route Change','Decide Route Change')


def _actions():
    from cfg_kanban.services import driver_route_actions
    return driver_route_actions


def _views():
    from cfg_kanban.services import driver_routes
    return driver_routes


def _read(dt,name,current=False):
    doc=frappe.get_doc(dt,name,**({'for_update':True} if current else {}))
    doc.check_permission('read')
    return doc


def _saved(doc):
    return json.loads(doc.driver_route_snapshot_json or '{}')


def order(doc,snapshot=None):
    snapshot=snapshot or _saved(doc)
    values=json.loads(doc.get('driver_stop_order_json') or 'null') or snapshot.get('stop_order') or []
    keys=[r.stop_key for r in doc.stops]
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values) or len(values)!=len(keys) or set(values)!=set(keys):
        frappe.throw('Trip execution order needs Supervisor reconciliation')
    return values


def pending(doc,snapshot=None):
    done={r.stop_key for r in doc.stops if r.driver_completed_on or r.get('cancellation_request')}
    return [key for key in order(doc,snapshot) if key not in done]


def _plans(doc):
    names=[r.dispatch_plan for r in doc.dispatch_plans]+([doc.open_route_plan] if doc.get('open_route_plan') else [])
    return [_read('CFG Kanban Dispatch Plan',name) for name in sorted(set(names))]


def strict(doc,snapshot=None):
    return bool((snapshot or _saved(doc)).get('strict') or any(p.stop_sequence_policy=='Planned Order' for p in _plans(doc)))


def _supervisor(operator):
    if not (_views()._all(operator) and operator.can_override and operator.can_complete):
        frappe.throw('A Supervisor with View All, Override and Complete is required for route decisions',frappe.PermissionError)


def _between_stops(doc):
    if doc.state!='Planned' or doc.driver_route_state!='In Progress':frappe.throw('Start an active Planned Trip before changing its delivery order')
    if doc.driver_active_stop_key:frappe.throw('Complete the current customer stop and required proof before changing route order')
    for plan in _plans(doc):
        if plan.get('dispatch_review_state') not in (None,'','Settled'):frappe.throw('Resolve Dispatch Review before changing route order')
        if plan.get('active_route_stop'):frappe.throw('Complete the active route sale and proof before changing order')
        if frappe.db.exists('CFG Kanban Delivery Session',{'dispatch_plan':plan.name,'state':['not in',['Closed','Cancelled']]}):
            frappe.throw('Complete every active Delivery Note and proof before changing route order')
        if plan.get('active_route_sheet'):
            from cfg_kanban.services import route_sheets
            sheet=_read('CFG Kanban Route Sheet',plan.active_route_sheet)
            if any(route_sheets._status(r)['state'] not in route_sheets.TERMINAL|{'Planned'} for r in sheet.stops):
                frappe.throw('Complete the active approved-route visit and proof before changing order')


def _live(doc,operator,token):
    _between_stops(doc)
    context=_views().get_driver_trip(doc.name,token)
    snapshot=_actions()._execution(doc,operator,context)
    if canonical_key('driver-snapshot',snapshot)!=canonical_key('driver-snapshot',_saved(doc)):
        frappe.throw('Trip sources or approved route changed; reconcile them before changing the order')
    return snapshot


def _stamp(doc):
    return canonical_key('trip-order-source',_actions()._core(doc),_saved(doc),order(doc),
        [(r.stop_key,str(r.driver_completed_on or '')) for r in doc.stops],cint(doc.get('route_sequence_revision')))


def _proposal(doc,values):
    values=json.loads(values) if isinstance(values,str) else values
    expected=pending(doc)
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values) or len(values)!=len(expected) or set(values)!=set(expected):
        frappe.throw('Include every unfinished Trip stop exactly once; completed stops cannot be moved or removed')
    if len(values)<2 or values==expected:frappe.throw('Move an unfinished customer to a different position first')
    return values


def _target_plans(doc,key):
    stop=next(r for r in doc.stops if r.stop_key==key)
    names={r.dispatch_plan for r in doc.dispatch_plans if r.stop_key==key}
    if doc.get('consolidated_customer_orders'):
        from cfg_kanban.services.consolidated_dispatch import linked
        names.update(r.dispatch_plan for r in linked(doc,key))
    if stop.stop_purpose=='Visit Only' and stop.customer_scan_point and doc.get('open_route_plan'):names.add(doc.open_route_plan)
    return [_read('CFG Kanban Dispatch Plan',name) for name in sorted(names)]


def _allow_override(doc,keys):
    for key in keys:
        if any(not cint(p.allow_supervisor_override) for p in _target_plans(doc,key)):
            frappe.throw('The captured Dispatch Profile does not allow a Supervisor sequence override for every affected customer')


def _install(doc,proposal,label):
    iterator=iter(proposal);done={r.stop_key for r in doc.stops if r.driver_completed_on or r.get('cancellation_request')}
    revised=[key if key in done else next(iterator) for key in order(doc)]
    doc.db_set(dict(driver_stop_order_json=frappe.as_json(revised),route_order_source=label,
        route_sequence_revision=cint(doc.get('route_sequence_revision'))+1),update_modified=True)
    return revised


def _request(doc,current=False):
    return _read(REQUEST,doc.route_change_request,current) if doc.get('route_change_request') else None


def _close_request(row,state,operator,session,reason,**extra):
    row.db_set(dict(state=state,pending_trip_key=None,decided_by=operator.employee,deciding_session=session.name,
        decided_on=now_datetime(),decision_reason=reason,**extra),update_modified=True)


def _labels(doc,keys):
    stops={r.stop_key:r for r in doc.stops}
    return [dict(stop_key=key,label=(stops[key].site_name or stops[key].customer) if key in stops else key,
        customer=stops[key].customer if key in stops else '') for key in keys]


def edit_context(doc,operator,token):
    _live(doc,operator,token)
    row=_request(doc)
    return dict(enforced=strict(doc),stops=_labels(doc,pending(doc)),
        request=dict(name=row.name,state=row.state,reason=row.reason,requested_by=row.requested_by) if row else None)


def review_context(doc,name,operator):
    _supervisor(operator)
    row=_read(REQUEST,name)
    if row.get('request_type')=='Cancel Customer Stop':
        from cfg_kanban.services.trip_stop_cancellation import review_context as cancellation_context
        if row.delivery_trip!=doc.name or row.company!=doc.company:frappe.throw('Cancellation request belongs to another Trip/Company')
        return cancellation_context(doc,row,operator)
    if row.delivery_trip!=doc.name or row.company!=doc.company:frappe.throw('Route request belongs to another Trip or Company')
    fresh=bool(row.state=='Pending' and doc.state=='Planned' and doc.driver_route_state=='In Progress'
        and not doc.driver_active_stop_key and row.source_fingerprint==_stamp(doc))
    return dict(request_name=row.name,state=row.state,requested_by=row.requested_by,reason=row.reason,
        current=_labels(doc,json.loads(row.base_order_json)),proposed=_labels(doc,json.loads(row.proposed_order_json)),
        approvable=fresh,modes=[NEXT,FULL],approval_mode=row.approval_mode,decision_reason=row.decision_reason)


def change(doc,values,operator,session,token,key):
    snapshot=_live(doc,operator,token)
    proposal=_proposal(doc,values.get('order'))
    if strict(doc,snapshot):frappe.throw('This Trip enforces its stop sequence; request Supervisor approval instead')
    old=_request(doc,current=True)
    if old and old.state=='Pending':frappe.throw('Cancel or resolve the pending route request before changing the order')
    applied=_install(doc,proposal,'Driver order')
    record('Driver Trip Order Changed',reference_doctype=TRIP,reference_name=doc.name,operator=operator.employee,
        operator_session=session.name,idempotency_key=key+':order',payload=dict(order=applied,reason=values.get('reason') or ''))
    return dict(route_order_changed=True)


def request_change(doc,values,operator,session,token,key):
    snapshot=_live(doc,operator,token)
    if not strict(doc,snapshot):frappe.throw('This route is flexible; save the driver order directly')
    proposal=_proposal(doc,values.get('order'));reason=str(values.get('reason') or '').strip()
    if not reason:frappe.throw('Enter a reason for the Supervisor route request')
    if proposal[0]==pending(doc)[0]:frappe.throw('Put the requested next customer first in the proposed order')
    _allow_override(doc,[proposal[0]])
    old=_request(doc,current=True)
    if old and old.state=='Pending':
        if old.get('request_type')=='Cancel Customer Stop':frappe.throw('Resolve or withdraw the pending customer cancellation before requesting a different route order')
        if old.source_fingerprint==_stamp(doc):frappe.throw('A route request is already waiting; cancel or resolve it before replacing its details')
        _close_request(old,'Superseded',operator,session,'Trip progressed before a new request')
    stop=next(r for r in doc.stops if r.stop_key==proposal[0])
    row=frappe.get_doc(dict(doctype=REQUEST,state='Pending',delivery_trip=doc.name,company=doc.company,
        vehicle_warehouse=snapshot['vehicle'],requested_by=operator.employee,operator_session=session.name,requested_on=now_datetime(),
        reason=reason,target_stop_key=stop.stop_key,target_customer=stop.customer,target_customer_site=stop.customer_scan_point,
        base_order_json=frappe.as_json(pending(doc)),proposed_order_json=frappe.as_json(proposal),
        source_fingerprint=_stamp(doc),idempotency_key=key,pending_trip_key=doc.name))
    row.flags.cfg_trip_route_change=True;row.insert(ignore_permissions=True)
    doc.db_set('route_change_request',row.name,update_modified=True)
    record('Driver Route Change Requested',reference_doctype=REQUEST,reference_name=row.name,operator=operator.employee,
        operator_session=session.name,idempotency_key=key+':request',payload=dict(order=proposal,reason=reason))
    return dict(route_change_request=row.name)


def cancel(doc,values,operator,session):
    row=_read(REQUEST,values.get('request_name'),current=True)
    if row.delivery_trip!=doc.name or row.company!=doc.company or row.state!='Pending':frappe.throw('Select this Trip pending request')
    if operator.employee not in (doc.driver,row.requested_by):frappe.throw('Only the requester or lead driver may cancel this route request',frappe.PermissionError)
    reason=str(values.get('reason') or '').strip()
    if not reason:frappe.throw('Enter a route request cancellation reason')
    _close_request(row,'Cancelled',operator,session,reason)
    return dict(route_change_request=row.name,state='Cancelled')


def decide(doc,values,operator,session,token):
    _supervisor(operator)
    row=_read(REQUEST,values.get('request_name'),current=True)
    if row.delivery_trip!=doc.name or row.company!=doc.company or row.state!='Pending':frappe.throw('Select this Trip pending request')
    if row.get('request_type')=='Cancel Customer Stop':
        from cfg_kanban.services.trip_stop_cancellation import decide as decide_cancellation
        return decide_cancellation(doc,row,values,operator,session,token)
    reason=str(values.get('reason') or '').strip();decision=values.get('decision')
    if not reason or decision not in ('Approve','Reject'):frappe.throw('Select Approve or Reject and enter the Supervisor reason')
    if decision=='Reject':
        _close_request(row,'Rejected',operator,session,reason)
        return dict(route_change_request=row.name,state='Rejected')
    _live(doc,operator,token)
    if row.source_fingerprint!=_stamp(doc):frappe.throw('Trip progressed after this request; reject it and ask the driver to submit the current order')
    proposal=_proposal(doc,json.loads(row.proposed_order_json));mode=values.get('approval_mode')
    if mode==NEXT:
        selected=proposal[0];proposal=[selected]+[k for k in pending(doc) if k!=selected]
        _allow_override(doc,[selected])
    elif mode==FULL:_allow_override(doc,proposal)
    else:frappe.throw('Choose Next Customer Only or Entire Proposed Order')
    applied=_install(doc,proposal,'Supervisor approved next customer' if mode==NEXT else 'Supervisor approved order')
    _close_request(row,'Approved',operator,session,reason,approval_mode=mode,applied_order_json=frappe.as_json(applied))
    return dict(route_change_request=row.name,state='Approved',approval_mode=mode)


def _request_summary(doc,row,operator):
    if not row:return None
    return dict(name=row.name,state=row.state,request_type=row.get('request_type') or 'Sequence Change',
        target_stop_key=row.target_stop_key,requested_by=row.requested_by,reason=row.reason,
        approval_mode=row.approval_mode,decision_reason=row.decision_reason,
        can_cancel=bool(row.state=='Pending' and doc.state in ('Draft','Planned') and operator.can_start
            and operator.employee in (doc.driver,row.requested_by)))


def project(doc,ordered,operator):
    if doc.get('route_sequence_revision') is None:return ordered,None
    row=_request(doc)
    if doc.driver_route_state not in ('In Progress','Completed','Closed Incomplete'):
        if not row or row.get('request_type')!='Cancel Customer Stop':return ordered,None
        return ordered,dict(enforced=doc.sequence_policy=='Planned Order',can_change=False,
            source=None,revision=cint(doc.get('route_sequence_revision')),request=_request_summary(doc,row,operator))
    saved=_saved(doc);keys=order(doc,saved);by_key={r['stop_key']:r for r in ordered}
    ordered=[by_key[k] for k in keys]
    for n,stop in enumerate(ordered,1):stop['sequence']=n
    waiting=bool(row and row.state=='Pending' and (row.get('request_type')=='Cancel Customer Stop' or row.source_fingerprint==_stamp(doc)))
    info=dict(enforced=strict(doc,saved),can_change=bool(not waiting and operator.can_start and doc.state=='Planned'
        and doc.driver_route_state=='In Progress' and not doc.driver_active_stop_key and len(pending(doc))>1),
        source=doc.get('route_order_source'),revision=cint(doc.get('route_sequence_revision')),
        request=_request_summary(doc,row,operator))
    return ordered,info


def _trip_name(plan):
    if plan.get('office_delivery_trip'):return plan.office_delivery_trip
    names=frappe.get_all('CFG Kanban Delivery Trip Plan',filters={'dispatch_plan':plan.name,
        'parenttype':TRIP,'parentfield':'dispatch_plans'},pluck='parent',limit_page_length=0)
    if len(set(names))>1:frappe.throw('Dispatch Plan belongs to several Trips; reconcile its route scope')
    return names[0] if names else None


def lock_plan(plan):
    name=_trip_name(plan)
    return _actions()._root(name) if name else None


def native_target(plan,site_name,route_stop=None,operator=None,token=None):
    name=_trip_name(plan)
    if not name:return None
    doc=_read(TRIP,name)
    if doc.driver_route_state!='In Progress':frappe.throw('Start this exact Delivery Trip before customer delivery')
    if doc.state!='Planned':frappe.throw('This runtime route is no longer active office planning')
    if operator:_actions()._owned(doc,operator)
    saved=_saved(doc)
    if saved.get('scope_hash')!=_actions()._core(doc):frappe.throw('Trip source scope changed after departure')
    if operator and token:
        live=_actions()._execution(doc,operator,_views().get_driver_trip(doc.name,token))
        if canonical_key('driver-snapshot',live)!=canonical_key('driver-snapshot',saved):
            frappe.throw('Saved Trip sources or approved route changed; reconcile before visiting this customer')
    if plan.name==doc.get('open_route_plan') or plan.get('consolidated_customer_orders'):
        if not route_stop:frappe.throw('Select the exact saved Trip visit')
        native=_read('CFG Kanban Route Stop',route_stop)
        keys=[native.office_stop_key] if native.dispatch_plan==plan.name else []
    else:keys=[r.stop_key for r in doc.dispatch_plans if r.dispatch_plan==plan.name]
    stops=[r for r in doc.stops if r.stop_key in keys and r.customer_scan_point==site_name]
    if len(stops)!=1:frappe.throw('Select the exact runtime Trip customer stop')
    stop=stops[0]
    _actions()._target(doc,dict(stop_key=stop.stop_key),saved)
    if strict(doc,saved) and pending(doc)[0]!=stop.stop_key:frappe.throw('Visit the next customer in the approved Trip order')
    return doc,stop


def native_order_permitted(plan,site_name,route_stop=None):
    target=native_target(plan,site_name,route_stop)
    if not target:return False
    doc,stop=target
    if not strict(doc):return False
    return bool(cint(plan.allow_supervisor_override) and pending(doc)[0]==stop.stop_key
        and str(doc.route_order_source or '').startswith('Supervisor approved'))


def supervisor_requests(limit=100):
    if not frappe.has_permission(REQUEST,'read'):return []
    fields=['name','state','request_type','delivery_trip','company','target_customer','target_customer_site',
        'reason','requested_by','requested_on','approval_mode','decision_reason']
    rows=frappe.get_list(REQUEST,filters={'state':'Pending'},fields=fields,order_by='requested_on asc',limit_page_length=limit)
    rows+=frappe.get_list(REQUEST,filters={'state':['not in',['Pending']]},fields=fields,order_by='modified desc',limit_page_length=20)
    result=[]
    for row in rows:
        try:_read(TRIP,row.delivery_trip);_read('Company',row.company)
        except frappe.PermissionError:continue
        result.append(dict(row))
    return result


def assert_target_not_pending_cancellation(doc,stop):
    row=_request(doc)
    if row and row.state=='Pending' and row.get('request_type')=='Cancel Customer Stop' and row.target_stop_key==stop.stop_key:
        frappe.throw('This stop awaits Supervisor cancellation approval; resolve or withdraw its request before delivery')

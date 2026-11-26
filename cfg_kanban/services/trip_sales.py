"""Trip/visit authorization over native Open Route delivery; no alternate stock or DN engine."""
import json

import frappe
from frappe.utils import cint, flt
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.events import record


def _office():
    from cfg_kanban.services import delivery_trips
    return delivery_trips


def _routes():
    from cfg_kanban.services import route_delivery
    return route_delivery


def _actions():
    from cfg_kanban.services import driver_route_actions
    return driver_route_actions


def _sheets():
    from cfg_kanban.services import route_sheets
    return route_sheets


def _read(doctype,name,current=False):
    return _office()._read(doctype,name,current)


def pool(trip,current=False):
    if not trip.get('open_route_plan'):return None
    doc=_read('CFG Kanban Dispatch Plan',trip.open_route_plan,current)
    if doc.office_delivery_trip!=trip.name or doc.company!=trip.company or doc.plan_type!='Open Route Stock':
        frappe.throw('Shared route pool no longer belongs to this Trip/Company')
    return doc


def visit(trip,stop,current=False):
    doc=pool(trip,current)
    if not doc:return None
    names=frappe.db.get_values('CFG Kanban Route Stop',{'dispatch_plan':doc.name,'office_delivery_trip':trip.name,
        'office_stop_key':stop.stop_key},['name'],as_dict=True,for_update=current)
    if len(names)>1:frappe.throw('Multiple shared visits match this office stop; Supervisor must reconcile them')
    if not names:return None
    row=_read('CFG Kanban Route Stop',names[0].name,current)
    if row.customer_scan_point!=stop.customer_scan_point or row.customer!=stop.customer or row.customer_address!=stop.customer_address:
        frappe.throw('Shared visit no longer matches the saved customer stop')
    return row


def session(trip,stop,operator,current=False):
    row=visit(trip,stop,current)
    if not row or not row.delivery_session:return None
    doc=_read('CFG Kanban Delivery Session',row.delivery_session,current)
    if (doc.dispatch_plan!=trip.open_route_plan or doc.route_stop!=row.name or doc.customer!=stop.customer
            or doc.customer_scan_point!=stop.customer_scan_point or doc.selling_company!=trip.company
            or not _routes()._engine()._can_view_delivery(operator,doc)):
        frappe.throw('Open Route Session belongs to another stop, Company or operator',frappe.PermissionError)
    return doc


def snapshot(trip,operator,vehicle):
    doc=pool(trip)
    if not doc:return None
    from cfg_kanban.services.trip_dispatch import route_ready,existing_pool
    _routes()._planning()._assert_plan_authorized(doc,operator)
    if not route_ready(doc) or doc.get('dispatch_review_state') not in (None,''):
        frappe.throw('Prepare/approve the shared Open Route stock pool before departure')
    if not vehicle or doc.vehicle_warehouse!=vehicle:frappe.throw('Shared route stock and ordered deliveries must use one lorry')
    sources=[] if existing_pool(doc) else _routes()._route_sources(doc)
    rows=[r for r in trip.stops if r.stop_purpose=='Visit Only' and r.customer_scan_point]
    visits=[]
    for stop in rows:
        source=visit(trip,stop)
        if not source:frappe.throw('Generate the shared Open Route visit for every optional-sale customer stop')
        visits.append((source.name,stop.stop_key,source.customer_scan_point))
    sheet=None
    if doc.get('route_approval_required') or doc.get('route_sequence_scope')=='Combined Lorry Trip' or doc.get('active_route_sheet'):
        if not doc.active_route_sheet:frappe.throw('Approve the shared Open Route customer sequence before departure')
        sheet=_read('CFG Kanban Route Sheet',doc.active_route_sheet)
        if (sheet.company!=trip.company or sheet.vehicle_warehouse!=vehicle or sheet.state not in ('Approved','In Progress','Ready to Close')):
            frappe.throw('Shared Open Route Sheet must be approved for this Trip lorry')
        # Every shared visit is the exact native visit referenced by its approved sheet row.
        for name,key,site in visits:
            matches=[r for r in sheet.stops if r.dispatch_plan==doc.name and r.source_route_stop==name and r.customer_scan_point==site]
            if len(matches)!=1:frappe.throw('Approved route must include every exact shared-pool customer visit')
    if sheet:
        order=[]
        known={r.dispatch_plan:r.stop_key for r in trip.dispatch_plans}
        for source in sheet.stops:
            key=sheet_target(trip,source) if source.dispatch_plan==doc.name else known.get(source.dispatch_plan)
            target=next((r for r in trip.stops if r.stop_key==key),None)
            if not target or source.customer_scan_point!=target.customer_scan_point:frappe.throw('Approved Sheet includes a visit outside this exact Trip')
            if not order or order[-1]!=key:order.append(key)
        if len(order)!=len(set(order)):frappe.throw('Approved Sheet interleaves repeated office stops')
        if sheet.sequence_policy=='Planned Order' and order!=[r.stop_key for r in trip.stops if r.stop_key in order]:frappe.throw('Office stop sequence conflicts with the enforced approved Sheet')
    _routes()._planning()._assert_plan_authorized(doc,operator)
    if doc.vehicle_warehouse!=vehicle or not _routes()._route_ready(doc):frappe.throw('Prepare or approve the shared route pool for this exact lorry')
    _routes()._assert_route_plan(doc)
    _routes()._validate_loaded_route(doc)
    return dict(name=doc.name,profile_hash=doc.profile_snapshot_hash,source_hash=doc.office_source_hash,
        vehicle=vehicle,existing_stock_only=bool(existing_pool(doc)),visits=visits,
        sources=[(r.name,r.item_code,r.batch_no,r.stock_uom,flt(r.allocated_qty)) for r in sources],
        sheet=dict(name=sheet.name,revision=sheet.revision,rows=[(r.row_key,r.dispatch_plan,r.source_route_stop,r.customer_scan_point) for r in sheet.stops],
            sequence_policy=sheet.sequence_policy,verification_policy=sheet.verification_policy) if sheet else None,
        require_scan=(sheet.verification_policy if sheet else _sheets().verification(doc))!=_sheets().SELECT)


def authorize(plan,operator,site_name=None,route_stop=None):
    """Acquire the Trip before native Plan/Session locks, including direct Logistics entry."""
    if not plan.get('office_delivery_trip'):return None
    from cfg_kanban.services import driver_routes
    trip=_actions()._root(plan.office_delivery_trip)
    _actions()._owned(trip,operator)
    if trip.open_route_plan!=plan.name or trip.state!='Planned' or trip.driver_route_state!='In Progress':
        frappe.throw('Start this exact Delivery Trip before an Open Route sale')
    saved=json.loads(trip.driver_route_snapshot_json or '{}')
    if saved.get('scope_hash')!=_actions()._core(trip):frappe.throw('Trip planning changed after departure; reconcile its scope')
    matches=[s for s in trip.stops if s.stop_purpose=='Visit Only' and s.customer_scan_point==site_name]
    if route_stop:
        native=_read('CFG Kanban Route Stop',route_stop)
        matches=[s for s in matches if s.stop_key==native.office_stop_key and native.dispatch_plan==plan.name]
    if len(matches)!=1:frappe.throw('Select the exact saved office visit for this optional sale')
    stop=matches[0];_actions()._target(trip,dict(stop_key=stop.stop_key),saved)
    native=visit(trip,stop)
    if not native or (route_stop and native.name!=route_stop):frappe.throw('Select the generated shared-pool visit')
    return trip,stop,native


def finish_visit(trip,stop,operator,record_no_sale=False):
    if not trip.get('open_route_plan') or not stop.customer_scan_point:return True
    row=visit(trip,stop,current=True)
    if not row:return True
    delivery=session(trip,stop,operator,current=True)
    if not delivery:
        if record_no_sale and row.state=='Planned':
            row.db_set(dict(state='Skipped',skip_reason='Office visit completed without a sale',skipped_by=operator.employee),update_modified=True)
            record('Trip Visit Completed Without Sale',reference_doctype='CFG Kanban Route Stop',reference_name=row.name,operator=operator.employee)
        return True
    if delivery.state=='Cancelled':return True
    if delivery.state != 'Closed':return False
    if not delivery.delivery_note:
        from cfg_kanban.services.driver_delivery_outcomes import full_refusal
        return full_refusal(delivery) if delivery.get('driver_delivery_outcome') else False
    note=_read('Delivery Note',delivery.delivery_note)
    if note.docstatus!=1 or note.is_return or note.company!=trip.company or note.customer!=stop.customer:return False
    if delivery.proof_policy!='No Proof Required':
        if not delivery.delivery_proof:return False
        proof=_read('CFG Kanban Delivery Proof',delivery.delivery_proof)
        if proof.state!='Submitted' or proof.delivery_session!=delivery.name or proof.delivery_note!=note.name:return False
    return True


def projection(trip,stops,operator):
    doc=pool(trip)
    if not doc:return None
    _routes()._planning()._assert_plan_authorized(doc,operator)
    for stop in trip.stops:
        if stop.stop_purpose!='Visit Only':continue
        row=visit(trip,stop)
        target=stops[stop.stop_key]
        target['can_open_sale']=bool(row and not stop.get('cancellation_request') and not stop.driver_completed_on and trip.driver_route_state=='In Progress')
        if not row:continue
        delivery=session(trip,stop,operator)
        if doc.get('has_loose_tags'):
            from cfg_kanban.services.loose_tags import driver_context, project_open_sources
            target['loose_tags'] = driver_context(doc, stop.stop_key)
            target['sources'].extend(project_open_sources(doc,stop.stop_key,delivery))
        target['open_sale']=dict(dispatch_plan=doc.name,route_stop=row.name,state=row.state,
            delivery_session=delivery.name if delivery else None,session_state=delivery.state if delivery else None,
            delivery_note=delivery.delivery_note if delivery else None,allocations=[])
        if delivery:
            allocations=frappe.get_list('CFG Kanban Delivery Allocation',filters={'delivery_session':delivery.name},
                fields=['name','item_code','visible_code','batch_no','stock_uom','allocated_qty','delivered_qty','state'],
                order_by='reserved_on asc, name asc',limit_page_length=0)
            for allocation in allocations:_read('Item',allocation.item_code)
            target['open_sale']['allocations']=[dict(r) for r in allocations]
        if delivery and delivery.state not in ('Closed','Cancelled'):
            if stop.get('cancellation_request'):frappe.throw('Cancelled visit unexpectedly has active delivery feedback')
            target['state']='Awaiting proof' if delivery.state=='Delivered' else 'Delivery Note pending' if delivery.state=='ERP Document Pending' else 'In Progress'
    return dict(name=doc.name,state=doc.state,vehicle_warehouse=doc.vehicle_warehouse,
        existing_stock_only=bool(doc.existing_lorry_stock_only),total_delivered_qty=flt(doc.total_delivered_qty))


def lock_scope(plan):
    if plan.get('office_delivery_trip'):
        return _actions()._root(plan.office_delivery_trip)


def assert_delivery_scope(delivery):
    plan=_read('CFG Kanban Dispatch Plan',delivery.dispatch_plan)
    trip=lock_scope(plan)
    stop=next((r for r in trip.stops if r.stop_key==frappe.db.get_value('CFG Kanban Route Stop',delivery.route_stop,'office_stop_key')),None)
    if (trip.open_route_plan!=plan.name or trip.state!='Planned' or trip.driver_route_state!='In Progress'
            or not stop or stop.get('cancellation_request') or stop.driver_completed_on or trip.driver_active_stop_key!=stop.stop_key):
        frappe.throw('This Open Route delivery no longer belongs to the active Trip customer stop')


def sheet_target(trip,source):
    if source.dispatch_plan==trip.get('open_route_plan'):
        if not source.source_route_stop:return None
        row=_read('CFG Kanban Route Stop',source.source_route_stop)
        if row.dispatch_plan==source.dispatch_plan and row.office_delivery_trip==trip.name:
            return row.office_stop_key
        return None
    return next((r.stop_key for r in trip.dispatch_plans if r.dispatch_plan==source.dispatch_plan),None)


def prepare_pool(trip,operator):
    doc=pool(trip,current=True)
    if not doc:return
    from cfg_kanban.services.trip_dispatch import bind_existing_pool, existing_pool
    if not existing_pool(doc):return
    _routes()._planning()._assert_plan_authorized(doc,operator)
    vehicles={_read('CFG Kanban Dispatch Plan',r.dispatch_plan).vehicle_warehouse for r in trip.dispatch_plans}
    vehicles.discard(None);vehicles.discard('')
    if trip.vehicle_warehouse:vehicles.add(trip.vehicle_warehouse)
    if len(vehicles)!=1:frappe.throw('Assign one actual lorry before opening this Trip existing-stock pool')
    bind_existing_pool(trip,doc,next(iter(vehicles)))


def action_context(trip,stop,operator,result,token,force=False):
    row=visit(trip,stop)
    if not row:return None
    delivery=session(trip,stop,operator)
    if not delivery:
        packed = {}
        if trip.get('open_route_plan'):
            source = pool(trip)
            if source.get('has_loose_tags'):
                from cfg_kanban.services.loose_tags import open_context
                packed = open_context(source, stop.stop_key)
        if force or packed:
            saved=json.loads(trip.driver_route_snapshot_json or '{}')
            return dict(result,next_step='Begin Open Sale',dispatch_plan=trip.open_route_plan,
                require_scan=saved['open_pool']['require_scan'], **packed)
        return None
    if delivery.state in ('Closed','Cancelled'):return None
    engine=_routes()._engine();view=engine.get_delivery_session(delivery.name,token)
    base=dict(result,dispatch_plan=trip.open_route_plan,delivery_session=delivery.name,session_state=delivery.state,
        auto_submit_delivery_note=view['auto_submit_delivery_note'],open_sale=True)
    if delivery.state=='Allocating Stock':
        if pool(trip).get('has_loose_tags'):
            from cfg_kanban.services.loose_tags import is_pack_delivery
            if is_pack_delivery(delivery):
                return dict(base,next_step='Confirm Allocations')
        return dict(base,next_step='Select Route Stock' ,selected_stock=view.get('allocations') or [])
    if delivery.state in ('Awaiting Confirmation','ERP Document Pending'):
        req=engine.get_customer_delivery_requirements(delivery.name,token)
        return dict(base,next_step='Await ERP' if req.get('existing_draft') else 'Create Delivery Note',requirements=req,delivery_note=delivery.delivery_note)
    if delivery.state=='Delivered':
        from cfg_kanban.services import delivery_proof
        return dict(base,next_step='Submit Proof' if delivery.delivery_proof else 'Open Proof',
            proof=delivery_proof.get_delivery_proof(delivery.delivery_proof,token) if delivery.delivery_proof else None)
    return dict(base,next_step='Blocked',message='Use controlled recovery for this Open Route Session')


def begin(trip,stop,scan,key,operator,token):
    row=visit(trip,stop,current=True)
    if not row:frappe.throw('This customer visit has no generated shared Open Route context')
    saved=json.loads(trip.driver_route_snapshot_json or '{}');policy=saved['open_pool']
    if policy['require_scan'] and not str(scan or '').strip():frappe.throw('Scan the assigned Customer Site before starting this sale')
    site=_read('CFG Kanban Customer Scan Point',stop.customer_scan_point)
    if scan:
        scanned=_routes()._engine()._resolve_customer_site(scan)
        if scanned.name!=site.name:frappe.throw('Customer Site scan does not match this Trip stop')
    if policy['sheet']:
        sheet=_read('CFG Kanban Route Sheet',policy['sheet']['name'])
        target=next(r for r in sheet.stops if r.source_route_stop==row.name and r.dispatch_plan==trip.open_route_plan)
        result=_sheets().start_route_sheet_stop(sheet.name,target.row_key,key,token,scan or None)
    else:
        result=_routes().start_route_stop(trip.open_route_plan,scan or site.site_code,key,token,route_stop=row.name)
    trip.db_set('driver_active_stop_key',stop.stop_key,update_modified=True)
    return result

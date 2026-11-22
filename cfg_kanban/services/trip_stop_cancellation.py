"""Reasoned stop cancellation reuses driver receipts, Supervisor decisions, E2/E3 and E5."""
import json
import frappe
from frappe.utils import cint,flt,now_datetime
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.events import record

REQUEST='CFG Kanban Route Change Request'
TRIP='CFG Kanban Delivery Trip'
KIND='Cancel Customer Stop'
HOLD='Keep Reserved for Return'
RELEASE='Release for Same-trip Sale'
EPS=0.000001


def _actions():
    from cfg_kanban.services import driver_route_actions
    return driver_route_actions


def _sequence():
    from cfg_kanban.services import trip_sequence
    return trip_sequence


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _prepared():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _custody():
    from cfg_kanban.services import cancelled_stop_stock
    return cancelled_stop_stock


def _read(dt,name,current=False):
    doc=frappe.get_doc(dt,name,**({'for_update':True} if current else {}));doc.check_permission('read');return doc


def _stop(doc,key):
    if doc.state not in ('Draft','Planned') or doc.driver_route_state not in (None,'','Not Started','In Progress'):
        frappe.throw('Cancel an unstarted stop on an active office/driver Trip')
    stop=next((row for row in doc.stops if row.stop_key==key),None)
    if not stop:frappe.throw('Select the exact saved customer stop')
    if stop.get('cancellation_request') or stop.get('driver_completed_on'):
        frappe.throw('This customer stop is already completed or cancelled')
    if doc.get('driver_active_stop_key')==key:frappe.throw('This customer delivery has started; complete or recover its delivery/proof first')
    return stop


def _stamp(doc,stop):
    # Warehouse preparation and progress at other customers do not invalidate the driver's intent.
    return canonical_key('cancel-trip-stop-intent',doc.name,doc.company,stop.stop_key,
        stop.customer,stop.customer_scan_point,stop.customer_address,stop.stop_purpose,
        [(r.sales_order,r.sales_order_item,flt(r.planned_qty)) for r in doc.orders if r.stop_key==stop.stop_key])


def _plans(doc,stop,operator,current=False):
    names=sorted({r.dispatch_plan for r in doc.dispatch_plans if r.stop_key==stop.stop_key})
    candidates=[_read('CFG Kanban Dispatch Plan',name) for name in names]
    # Match the existing Route Sheet -> Plan lock order after the parent Trip.
    if current:
        from cfg_kanban.services import route_sheets
        for plan in candidates:
            if plan.get('active_route_sheet'):route_sheets.lock_plan_route_scope(plan,operator)
        candidates=[_read('CFG Kanban Dispatch Plan',name,True) for name in names]
    orders={r.sales_order for r in doc.orders if r.stop_key==stop.stop_key}
    for plan in candidates:
        if (plan.company!=doc.company or plan.plan_type!='Customer Order' or plan.fulfilment_mode!='Vehicle Delivery'
                or plan.customer!=stop.customer or plan.customer_site!=stop.customer_scan_point or plan.customer_address!=stop.customer_address or plan.sales_order not in orders):
            frappe.throw('Customer cancellation must retain the exact Trip Company, customer, Sales Order and Plan')
        if plan.get('office_delivery_trip') and (plan.office_delivery_trip!=doc.name or plan.office_stop_key!=stop.stop_key):
            frappe.throw('Generated dispatch belongs to another Trip/customer stop')
        if current:_planning()._assert_plan_authorized(plan,operator)
        if plan.get('stop_cancellation'):frappe.throw('Dispatch Plan already belongs to a cancellation decision')
    return candidates


def _unstarted(plan):
    if plan.get('delivery_session') or plan.get('driver_delivery_outcome') or plan.get('active_route_stop'):
        frappe.throw('Customer delivery/quantity reporting has started; use existing delivery, proof or refusal recovery before cancelling this stop')
    if frappe.db.exists('CFG Kanban Delivery Session',{'dispatch_plan':plan.name}):
        frappe.throw('This Plan has delivery history; retain it and use the existing delivery/return recovery')
    if plan.get('dispatch_review_state') and plan.state!='Reconciled':frappe.throw('Resolve this Plan Dispatch Review before cancelling the stop')


def _shared_visit(doc,stop,operator,current=False):
    if stop.stop_purpose!='Visit Only' or not doc.get('open_route_plan') or not stop.customer_scan_point:return None
    if current:
        from cfg_kanban.services.route_sheets import lock_plan_route_scope
        candidate=_read('CFG Kanban Dispatch Plan',doc.open_route_plan)
        if candidate.get('active_route_sheet'):lock_plan_route_scope(candidate,operator)
        _read('CFG Kanban Dispatch Plan',doc.open_route_plan,True)
    from cfg_kanban.services.trip_sales import visit
    row=visit(doc,stop,current)
    if row and (row.delivery_session or row.state not in ('Planned','Skipped')):
        frappe.throw('This shared-pool customer sale has started; complete/recover its delivery and proof first')
    return row


def _manifest(plan,current=False):
    if not plan.movement_manifest:return None
    row=_read('CFG Kanban Movement Manifest',plan.movement_manifest,current)
    if (row.dispatch_plan!=plan.name or row.source_company!=plan.company or
            row.source_warehouse!=plan.source_warehouse or row.destination_warehouse!=plan.vehicle_warehouse):
        frappe.throw('Loading Manifest no longer matches the cancelled customer Plan')
    return row


def _preview(doc,stop,operator,current=False):
    # Explicit actor parameters stay out of module globals and out of background jobs.
    plans=_plans(doc,stop,operator,current)
    from cfg_kanban.services import route_sheets
    shared=_shared_visit(doc,stop,operator,current)
    result=[];stock=[]
    for plan in plans:
        _unstarted(plan);manifest=_manifest(plan,current)
        for name in {plan.source_warehouse,plan.vehicle_warehouse}-{None,''}:
            warehouse=_read('Warehouse',name)
            if warehouse.company!=doc.company:frappe.throw('Cancellation stock Warehouse belongs to another Company')
        if plan.state not in {'Draft','Awaiting Approval',*_planning().RESERVABLE_STATES,
                              'Vehicle Claimed','Loading','Ready to Dispatch','Loaded','Cancelled','Reconciled'}:
            frappe.throw('This loading/ERP state needs controlled recovery before stop cancellation')
        if plan.state not in ('Loaded','Reconciled') and manifest:
            if (manifest.state not in ('Draft','Prepared') or any(manifest.get(f) for f in
                    ('dispatch_stock_entry','receipt_stock_entry','dispatch_delivery_note','receipt_purchase_receipt','dispatch_command','receipt_command'))):
                frappe.throw('Loading has ERP work; resolve it through existing recovery before cancelling the customer')
        if current:
            for item in sorted({r.item_code for r in plan.lines}):_planning()._lock_erp_bin(item,plan.vehicle_warehouse or plan.source_warehouse)
        allocations=(_prepared()._loaded_allocations(plan,for_update=current) if plan.state=='Loaded' else
            [_read('CFG Kanban Dispatch Allocation',name,current) for name in frappe.get_all('CFG Kanban Dispatch Allocation',
                filters={'dispatch_plan':plan.name,'state':'Reserved'},pluck='name',order_by='name',limit_page_length=0)])
        if plan.state=='Loaded':_prepared().validate_prepared_loading(plan)
        sources=[]
        for source in allocations:
            unit=_read('CFG Kanban Handling Unit',source.handling_unit,current) if source.handling_unit else None
            qty=flt(source.allocated_qty)
            if not EPS<qty<float('inf'):frappe.throw('Cancellation source quantities must remain positive')
            if unit and plan.state=='Loaded' and (unit.inventory_company!=doc.company or unit.current_warehouse!=plan.vehicle_warehouse
                    or unit.item_code!=source.item_code or (unit.batch_no or '')!=(source.batch_no or '') or unit.stock_uom!=source.stock_uom
                    or abs(flt(unit.current_qty)-qty)>EPS or flt(unit.reserved_qty)>EPS):
                frappe.throw('Loaded Stock Tag moved, changed or is already reserved; reconcile it before cancelling this stop')
            identity=dict(dispatch_plan=plan.name,dispatch_allocation=source.name,handling_unit=source.handling_unit,
                visible_code=unit.handling_unit_id if unit else None,item_code=source.item_code,batch_no=source.batch_no,
                stock_uom=source.stock_uom,qty=qty,company=doc.company,original_warehouse=plan.vehicle_warehouse)
            sources.append(dict(identity,expiry_date=unit.expiry_date if unit else None,
                process_certificate_set=unit.process_certificate_set if unit else None))
            if plan.state=='Loaded':stock.append(identity)
        if plan.state=='Loaded' and doc.driver_route_state=='In Progress':
            saved=json.loads(doc.driver_route_snapshot_json or '{}')
            expected=sorted(tuple(r) for r in saved.get('allocations',[]) if r[0]==plan.name)
            actual=sorted((plan.name,r['dispatch_allocation'],r['item_code'],r['stock_uom'],r['batch_no'],r['visible_code'],r['qty']) for r in sources)
            if expected!=actual:frappe.throw('Loaded sources differ from the frozen departure record; reconcile them before cancellation')
        if plan.state=='Loaded':
            from cfg_kanban.services.dispatch_reconciliation import _balances,_at_source
            _at_source(plan,_balances(plan,current=current),current=current)
        if plan.get('active_route_sheet'):
            sheet=_read('CFG Kanban Route Sheet',plan.active_route_sheet,current)
            matches=[r for r in sheet.stops if r.dispatch_plan==plan.name]
            if (sheet.company!=doc.company or sheet.vehicle_warehouse!=plan.vehicle_warehouse or len(matches)!=1
                    or route_sheets._status(matches[0])['state']!='Planned'):
                frappe.throw('The approved customer visit has progressed or changed; reconcile it before cancellation')
        result.append(dict(name=plan.name,state=plan.state,source_warehouse=plan.source_warehouse,
            vehicle_warehouse=plan.vehicle_warehouse,movement_manifest=plan.movement_manifest,
            dispatch_stock_entry=manifest.dispatch_stock_entry if manifest else None,sales_order=plan.sales_order,sources=sources))
    if shared and doc.get('open_route_plan'):
        pool=_read('CFG Kanban Dispatch Plan',doc.open_route_plan,current)
        if current:_planning()._assert_plan_authorized(pool,operator)
        if pool.get('active_route_sheet'):
            sheet=_read('CFG Kanban Route Sheet',pool.active_route_sheet,current)
            matches=[r for r in sheet.stops if r.source_route_stop==shared.name]
            if len(matches)!=1 or route_sheets._status(matches[0])['state'] not in ('Planned','Skipped'):
                frappe.throw('Shared customer visit has progressed or changed')
    data=dict(stop_key=stop.stop_key,sequence=cint(stop.delivery_sequence),customer=stop.customer,site_name=stop.site_name or stop.customer,
        customer_site=stop.customer_scan_point,address=stop.address_display or '',purpose=stop.stop_purpose,
        orders=[dict(sales_order=r.sales_order,customer_po=r.customer_po,item_code=r.item_code,
            stock_uom=r.stock_uom,planned_qty=flt(r.planned_qty)) for r in doc.orders if r.stop_key==stop.stop_key],
        plans=result,shared_visit=shared.name if shared else None)
    return data,canonical_key('cancel-stop-goods',data),plans,stock,shared


def context(doc,key,operator):
    stop=_stop(doc,key);data,digest,_plans_,stock,_visit=_preview(doc,stop,operator)
    return dict(target=data,goods_hash=digest,has_loaded_goods=bool(stock),dispositions=[HOLD,RELEASE],
        supervisor=bool(_actions()._views()._all(operator) and operator.can_override and operator.can_complete))


def _new_request(doc,stop,operator,session,reason,key):
    reason=str(reason or '').strip()
    if not reason:frappe.throw('Enter the customer-stop cancellation reason')
    old=_sequence()._request(doc,True)
    if old and old.state=='Pending':frappe.throw('Resolve or withdraw the pending Trip request before requesting another cancellation')
    data,_digest,_plans_,_stock,_visit=_preview(doc,stop,operator)
    pending=[r.stop_key for r in doc.stops if not r.driver_completed_on and not r.get('cancellation_request')]
    row=frappe.get_doc(dict(doctype=REQUEST,state='Pending',request_type=KIND,delivery_trip=doc.name,
        company=doc.company,vehicle_warehouse=doc.vehicle_warehouse,requested_by=operator.employee,
        operator_session=session.name,requested_on=now_datetime(),reason=reason,target_stop_key=stop.stop_key,
        target_customer=stop.customer,target_customer_site=stop.customer_scan_point,
        base_order_json=frappe.as_json(pending),proposed_order_json=frappe.as_json([k for k in pending if k!=stop.stop_key]),
        cancellation_preview_json=frappe.as_json(data),source_fingerprint=_stamp(doc,stop),idempotency_key=key,pending_trip_key=doc.name))
    row.flags.cfg_trip_route_change=True;row.insert(ignore_permissions=True)
    doc.db_set('route_change_request',row.name,update_modified=True)
    return row


def request_cancel(doc,key,values,operator,session,identity):
    stop=_stop(doc,key);row=_new_request(doc,stop,operator,session,values.get('reason'),identity)
    record('Customer Stop Cancellation Requested',reference_doctype=REQUEST,reference_name=row.name,
        operator=operator.employee,operator_session=session.name,idempotency_key=identity+':request',notes=row.reason)
    return dict(route_change_request=row.name,state='Pending')


def review_context(doc,row,operator):
    _sequence()._supervisor(operator)
    target=None;digest=None;loaded=False;blocked=None
    try:
        stop=_stop(doc,row.target_stop_key)
        if row.source_fingerprint!=_stamp(doc,stop):frappe.throw('Customer/order assignment changed; reject this request and submit the current stop')
        target,digest,_plans_,stock,_visit=_preview(doc,stop,operator)
        loaded=bool(stock)
        if doc.get('driver_active_stop_key'):frappe.throw('Complete the active customer delivery and proof before approving cancellation')
    except frappe.ValidationError as exc:blocked=str(exc)
    return dict(request_name=row.name,request_type=KIND,state=row.state,requested_by=row.requested_by,reason=row.reason,
        approvable=bool(row.state=='Pending' and not blocked),message=blocked,target=target or json.loads(row.cancellation_preview_json or '{}'),
        goods_hash=digest,has_loaded_goods=loaded,dispositions=[HOLD,RELEASE],stock_disposition=row.stock_disposition,
        decision_reason=row.decision_reason,current=[],proposed=[],modes=[])


def _apply(doc,row,values,operator,session,token):
    stop=_stop(doc,row.target_stop_key)
    if row.source_fingerprint!=_stamp(doc,stop):frappe.throw('Customer/order assignment changed; reject this request and submit the current stop')
    if doc.get('driver_active_stop_key'):frappe.throw('Complete the active customer delivery and required proof before cancelling another stop')
    for name in sorted({r.dispatch_plan for r in doc.dispatch_plans}|({doc.open_route_plan} if doc.get('open_route_plan') else set())):
        if frappe.db.exists('CFG Kanban Delivery Session',{'dispatch_plan':name,'state':['not in',['Closed','Cancelled']]}):
            frappe.throw('Complete every active customer delivery and proof before approving cancellation')
    if doc.driver_route_state=='In Progress':
        saved=json.loads(doc.driver_route_snapshot_json or '{}')
        if saved.get('scope_hash')!=_actions()._core(doc):frappe.throw('Trip source scope changed after departure; reconcile it before cancellation')
    data,digest,plans,stock,visit=_preview(doc,stop,operator,True)
    if not values.get('goods_hash') or values['goods_hash']!=digest:
        frappe.throw('Customer loading/stock changed; refresh and review the exact current goods before cancellation')
    disposition=values.get('stock_disposition') or HOLD
    if disposition not in (HOLD,RELEASE):frappe.throw('Choose Keep Reserved for Return or Release for Same-trip Sale')
    if disposition==RELEASE:
        from cfg_kanban.services.driver_delivery_outcomes import _assert_resalable
        for source in stock:_assert_resalable(frappe._dict(source))
    # Preserve posted loading evidence. Only an entirely unused E3 claim can be released here.
    for plan in plans:
        if plan.state not in ('Loaded','Reconciled','Cancelled'):
            if plan.movement_manifest:
                _planning().release_vehicle_claim(_read('CFG Kanban Movement Manifest',plan.movement_manifest,True),
                    operator,session,values['reason'],row.name+':claim')
            _planning()._cancel_unposted_plan(plan,operator,session,values['reason'],row.name+':unloaded',supervisor_cancel=True)
        plan.db_set(dict(stop_cancellation=row.name,**({'prepared_stock_commitment':int(disposition==HOLD)} if plan.state=='Loaded' else {})),update_modified=True)
        if plan.get('active_route_sheet'):
            sheet=_read('CFG Kanban Route Sheet',plan.active_route_sheet,True)
            for native in sheet.stops:
                if native.dispatch_plan==plan.name:native.db_set('state','Cancelled',update_modified=False)
    if visit:
        visit.db_set(dict(state='Skipped',skip_reason=values['reason'],skipped_by=operator.employee,
            skipped_on=now_datetime()),update_modified=True)
    _custody().install(row,stock,disposition,operator,session)
    stop.db_set(dict(cancellation_request=row.name,stop_cancelled_on=now_datetime(),stop_cancelled_by=operator.employee,
        stop_cancellation_reason=values['reason']),update_modified=False)
    row.db_set(dict(stock_disposition=disposition,cancellation_preview_json=frappe.as_json(data)),update_modified=False)
    doc.db_set('route_sequence_revision',cint(doc.get('route_sequence_revision'))+1,update_modified=True)
    if doc.driver_route_state=='In Progress' and all(r.driver_completed_on or r.get('cancellation_request') for r in doc.stops):
        doc.db_set(dict(driver_route_state='Completed',driver_route_completed_on=now_datetime(),driver_active_vehicle_key=None,
            driver_active_stop_key=None),update_modified=True)
    record('Customer Stop Cancelled',reference_doctype=REQUEST,reference_name=row.name,operator=operator.employee,
        operator_session=session.name,idempotency_key=row.name+':applied',payload=dict(stop_key=stop.stop_key,
        stock_disposition=disposition,loaded_sources=stock),notes=values['reason'])
    return dict(stop_cancelled=True,stop_key=stop.stop_key,route_change_request=row.name,stock_disposition=disposition)


def decide(doc,row,values,operator,session,token):
    _sequence()._supervisor(operator)
    if row.state!='Pending' or row.delivery_trip!=doc.name or row.company!=doc.company:frappe.throw('Select this Trip pending cancellation request')
    reason=str(values.get('reason') or '').strip();decision=values.get('decision')
    if not reason or decision not in ('Approve','Reject'):frappe.throw('Choose Approve or Reject and enter the Supervisor reason')
    if decision=='Reject':
        _sequence()._close_request(row,'Rejected',operator,session,reason)
        return dict(route_change_request=row.name,state='Rejected')
    result=_apply(doc,row,dict(values,reason=reason),operator,session,token)
    _sequence()._close_request(row,'Approved',operator,session,reason)
    return result


def direct(doc,key,values,operator,session,token,identity):
    _sequence()._supervisor(operator)
    stop=_stop(doc,key)
    _data,digest,_plans_,_stock,_visit=_preview(doc,stop,operator,True)
    if digest!=values.get('goods_hash'):frappe.throw('Customer loading/stock changed; refresh and review its current goods')
    if not str(values.get('reason') or '').strip():frappe.throw('Enter the customer-stop cancellation reason')
    disposition=values.get('stock_disposition') or HOLD
    if disposition not in (HOLD,RELEASE):frappe.throw('Choose the loaded goods disposition')
    if doc.get('driver_active_stop_key'):frappe.throw('Complete the active customer delivery and proof before cancellation')
    if disposition==RELEASE:
        from cfg_kanban.services.driver_delivery_outcomes import _assert_resalable
        for source in _stock:_assert_resalable(frappe._dict(source))
    row=_new_request(doc,stop,operator,session,values.get('reason'),identity)
    return decide(doc,row,dict(values,decision='Approve'),operator,session,token)


def history_stop(doc,stop):
    row=_read(REQUEST,stop.cancellation_request)
    if row.delivery_trip!=doc.name or row.company!=doc.company or row.request_type!=KIND or row.state!='Approved' or row.target_stop_key!=stop.stop_key:
        frappe.throw('Cancelled customer stop does not match its approved decision')
    data=json.loads(row.cancellation_preview_json or '{}')
    return dict(stop_key=stop.stop_key,office_sequence=cint(stop.delivery_sequence),sequence=cint(stop.delivery_sequence),
        purpose=stop.stop_purpose,customer=stop.customer,customer_name=data.get('site_name') or stop.customer,
        site_name=data.get('site_name') or stop.customer,customer_site=stop.customer_scan_point,customer_address=stop.customer_address,
        address=data.get('address') or '',state='Cancelled',cancelled=True,cancellation_request=row.name,
        cancelled_on=stop.stop_cancelled_on,cancelled_by=stop.stop_cancelled_by,cancellation_reason=stop.stop_cancellation_reason,
        stock_disposition=row.stock_disposition,items=[],sources=[],plans=[],route_sheets=[],warnings=[],driver_completed_on=None,
        loaded_stock=[dict(r.as_dict()) for r in row.cancelled_stock],orders=data.get('orders') or [],delivery_pin=None)

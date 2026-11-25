"""E5B3: a reviewed follow-on Trip, using existing E5 recovery and delivery engines.

The source Plans settle first. This confirms stock already on the chosen lorry;
it never rewrites the original load, invents a loading Stock Entry or repeats a DN.
"""
import json
import math

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, today

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

TRIP='CFG Kanban Delivery Trip'
PLAN='CFG Kanban Dispatch Plan'
EPS=0.000001


class FollowOnReplayError(Exception):
    """The original follow-on request was changed or explicitly voided."""


def _office():
    from cfg_kanban.services import delivery_trips
    return delivery_trips


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _read(dt,name,current=False):
    doc=frappe.get_doc(dt,name,**({'for_update':True} if current else {}))
    doc.check_permission('read')
    return doc


def _auth(token):
    frappe.only_for(_office().EDITORS)
    operator,session=require_operator(token,'override')
    from cfg_kanban.services.trip_handover import _supervisor
    if not _supervisor(operator) or not operator.get('can_start') or not operator.get('can_complete'):
        frappe.throw('A Supervisor with Start, Complete, Override and Logistics Reconciliation is required',frappe.PermissionError)
    return operator,session


def _source(name,operator,current=False):
    hint=_read(TRIP,name)
    if current:_office()._locks('CFG Kanban Route Template',[hint.route_template])
    doc=_read(TRIP,name,current)
    doc.check_permission('write')
    _read('Company',doc.company)
    return doc


def _vehicle(name,company,current=False):
    doc=_read('Warehouse',name,current)
    if doc.company!=company or doc.disabled or doc.is_group or not doc.get('cfg_is_vehicle_warehouse') or not doc.get('cfg_vehicle_reference'):
        frappe.throw('Select an active Company-specific lorry Warehouse')
    _planning()._vehicle_warehouse(name,company)
    return doc


def _profile(source,kind,current=False):
    name=source.get('dispatch_profile' if kind=='Customer Order' else 'open_route_profile')
    if not name:
        # Older manually planned Trips may obtain the policy from their original Plan.
        plans=[_read(PLAN,row.dispatch_plan) for row in source.dispatch_plans]
        if source.get('open_route_plan'):plans.append(_read(PLAN,source.open_route_plan))
        options={p.dispatch_profile for p in plans if p.plan_type==kind}
        if len(options)==1:name=next(iter(options))
    if not name:frappe.throw('Set the appropriate Dispatch Profile before creating this follow-on Trip')
    policy=_read('CFG Kanban Dispatch Profile',name,current)
    if not policy.active or policy.company!=source.company or policy.fulfilment_mode!='Vehicle Delivery' or policy.plan_type!=kind:
        frappe.throw('Follow-on stock requires an active matching Company / Vehicle Delivery Profile')
    _read('Warehouse',policy.source_warehouse)
    _read('CFG Kanban Card',policy.dispatch_point)
    _planning()._validate_profile_card(policy,current=current)
    return policy


def _context(source,operator,warehouse=None,current=False):
    from cfg_kanban.services.return_custody import cases,pending
    template=_office()._template(source.route_template,source.company,current)
    plan_names=sorted(set([r.dispatch_plan for r in source.dispatch_plans]+([source.open_route_plan] if source.get('open_route_plan') else [])))
    plans=[];blockers=[];sheets={}
    unused_follow_on=False
    if not source.get('driver_route_started_on'):
        if source.get('follow_on_of'):
            from cfg_kanban.services.trip_carry_in import validate_origin
            validate_origin(source,current=current)
            unused_follow_on=True
        else:blockers.append('Use normal office planning until the original route has started')
    for name in plan_names:
        plan=_read(PLAN,name,current);_planning()._assert_plan_authorized(plan,operator)
        if plan.company!=source.company:frappe.throw('A source Plan belongs to another Company')
        plans.append(dict(name=name,state=plan.state,review_state=plan.get('dispatch_review_state'),review=plan.get('active_dispatch_review')))
        if plan.state not in ('Reconciled','Cancelled') or (plan.state=='Reconciled' and plan.get('dispatch_review_state')!='Settled'):blockers.append('Settle Plan '+name+' through E5 before takeover')
        if plan.get('active_route_sheet'):
            sheet=_read('CFG Kanban Route Sheet',plan.active_route_sheet,current)
            if {r.dispatch_plan for r in sheet.stops}-set(plan_names):
                blockers.append('Route Sheet '+sheet.name+' includes work outside this Trip')
            sheets[sheet.name]=dict(name=sheet.name,state=sheet.state,revision=cint(sheet.revision))
    sessions=frappe.db.get_values('CFG Kanban Delivery Session',{'dispatch_plan':['in',plan_names],
        'state':['not in',['Closed','Cancelled']]},['name'],as_dict=True,for_update=current) if plan_names else []
    if sessions:blockers.append('Complete or cancel all source Delivery Sessions and proof first')
    if source.get('follow_on_trip'):blockers.append('This source already has follow-on Trip '+source.follow_on_trip)
    if source.get('route_change_request'):
        request=_read('CFG Kanban Route Change Request',source.route_change_request,current)
        if request.state=='Pending':blockers.append('Resolve the pending route-change/cancellation request first')
    orders=sorted({r.sales_order for r in source.orders})
    delivered=_office()._delivered_assignments(orders,current=current)
    elsewhere=_office()._assignments(orders,source.name,current=current)
    stops={r.stop_key:r for r in source.stops};lines=[];native_orders={}
    for row in source.orders:
        stop=stops[row.stop_key]
        if stop.get('cancellation_request'):continue
        order=native_orders.setdefault(row.sales_order,_read('Sales Order',row.sales_order,current))
        if order.company!=source.company or order.customer!=stop.customer:
            frappe.throw('Original order/stop Company or customer changed')
        item,remaining=_office()._line(order,row.sales_order_item)
        _read('Item',item.item_code)
        outstanding=max(0,flt(row.planned_qty)-delivered.get((source.name,row.sales_order,row.sales_order_item),0))
        available=min(outstanding,max(0,remaining-elsewhere.get((row.sales_order,row.sales_order_item),0)))
        if order.docstatus!=1 or order.status in ('Closed','Cancelled','Completed','On Hold') or order.get('cfg_delivery_route')!=source.route_template:
            available=0
        if available>EPS:
            lines.append(dict(source_row=row.name,stop_key=row.stop_key,customer=stop.customer,
                sales_order=row.sales_order,sales_order_item=row.sales_order_item,customer_po=order.get('po_no'),
                item_code=item.item_code,item_name=item.item_name,stock_uom=item.stock_uom,
                max_qty=available,already_completed=bool(stop.get('driver_completed_on')),
                is_stock_item=cint(row.is_stock_item),order_modified=str(order.modified or '')))
    visits=[dict(stop_key=r.stop_key,customer=r.customer,site_name=r.site_name)
        for r in source.stops if r.stop_purpose=='Visit Only' and not r.get('driver_completed_on') and not r.get('cancellation_request')]
    returns=[]
    for case in cases(source,history=False,current=current,native=False):
        if not pending(case):continue
        case.check_permission('read')
        returns.append(dict(name=case.name,customer=case.customer,state=case.state,modified=str(case.modified or ''),
            items=[dict(item_code=r.item_code,batch_no=r.batch_no,stock_uom=r.stock_uom,qty=flt(r.claimed_qty)) for r in case.lines]))
    vehicle=_vehicle(warehouse,source.company,current=current) if warehouse else None
    policies={}
    for kind in ('Customer Order','Open Route Stock'):
        if (kind=='Customer Order' and lines) or (kind=='Open Route Stock' and visits):
            policy=_profile(source,kind,current=current)
            policies[kind]=dict(name=policy.name,revision=policy.revision,modified=str(policy.modified or ''))
    stamp=dict(source=source.name,modified=str(source.modified or ''),state=source.state,plans=plans,
        sheets=sorted(sheets.values(),key=lambda r:r['name']),lines=lines,visits=visits,returns=returns,
        template_revision=template.revision,template_modified=str(template.modified or ''),
        policies=policies,warehouse=vehicle.name if vehicle else None)
    return dict(source_trip=source.name,company=source.company,source_state=source.state,unused_follow_on=unused_follow_on,
        warehouse=vehicle.name if vehicle else None,lines=lines,visits=visits,returns=returns,blockers=blockers,
        context_hash=canonical_key('follow-on-context',stamp),policies=policies,
        notice=('This confirmed follow-on never departed. After E5 settlement, reviewed takeover can close it and transfer its pending return custody without inventing a route start. ' if unused_follow_on else '')+'Choose only still-required deliveries. Completed/refused stops are never automatically redelivered. Existing stock must be physically confirmed on the receiving lorry.')


@frappe.whitelist()
def get_follow_on_context(source_trip,operator_session_token,warehouse=None,reconciliation_only=0):
    operator,_session=_auth(operator_session_token)
    source=_source(source_trip,operator)
    # Pending requests must remain reconcilable after policies or stock change.
    result=(dict(source_trip=source.name,lines=[],visits=[],returns=[],blockers=[],
        notice='Original request retained; Read Back before changing it.') if cint(reconciliation_only) else _context(source,operator,warehouse))
    result['operator']=dict(employee=operator.employee,employee_name=operator.get('employee_name'))
    return result


def _stock_info(source,warehouse,row,kind,scan_value=None,item_code=None,batch_no=None,current=False):
    from cfg_kanban.services import dispatch_fulfilment as prepared
    planning=_planning();unit=None
    if kind=='Tagged Stock':
        identity=planning.resolve_logistics_scan(scan_value)
        if not identity or identity.get('identity_type')!='Handling Unit':frappe.throw('Scan the exact physical Stock Tag')
        unit=_read('CFG Kanban Handling Unit',identity['name'],current)
        item_code=unit.item_code;batch_no=unit.batch_no
    elif kind!='Untagged ERP Stock':frappe.throw('Select Tagged Stock or Untagged ERP Stock')
    if row and item_code!=row['item_code']:frappe.throw('Scanned stock does not match the selected order Item')
    item=_read('Item',item_code,current)
    if item.disabled or not item.is_stock_item:frappe.throw('Choose an enabled stock Item')
    if batch_no:_read('Batch',batch_no,current)
    planning._validate_batch(item_code,batch_no)
    if unit:
        line=frappe._dict(item_code=item_code,stock_uom=item.stock_uom,batch_no=batch_no)
        plan=frappe._dict(company=source.company,source_warehouse=warehouse)
        planning._validate_tag_for_plan(unit,plan,line)
        if unit.tag_kind!='Stock Tag':frappe.throw('Scan the content Stock Tag, or release/repack the container stock before takeover')
        prepared.assert_prepared_tag_scope(unit.name,frappe._dict(dispatch_plan=None),current=current)
        prepared.assert_delivery_tag_expiry(unit)
        planning._assert_not_in_open_manifest(unit.name)
        planning.assert_erp_stock(unit,warehouse,unit.current_qty)
        from cfg_kanban.services.logistics_stock_identity import identity_snapshot
        detail=identity_snapshot(unit)
        from cfg_kanban.services.trip_stock_revision import revision
        detail['source_revision']=revision(unit,current=current)
        qty=flt(unit.available_qty)
        detail.update(qty=flt(unit.current_qty),reserved=flt(unit.reserved_qty),warehouse=unit.current_warehouse,
            company=unit.inventory_company,quality=unit.quality_state)
    else:
        if item.has_serial_no:frappe.throw('Serialized stock requires its exact Stock Tag')
        if bool(item.has_batch_no)!=bool(batch_no):frappe.throw('Confirm the exact Batch for this stock Item')
        prepared._assert_untagged_batch_expiry(batch_no,current=current)
        planning._lock_erp_bin(item_code,warehouse)
        from cfg_kanban.services.logistics_stock_identity import _line_identity
        _line_identity(frappe._dict(handling_unit=None,item_code=item_code,batch_no=batch_no,
            source_company=source.company,source_warehouse=warehouse))
        qty=planning._untagged_available(source.company,warehouse,item_code,batch_no,current=True)
        detail=dict(item_code=item_code,batch_no=batch_no,stock_uom=item.stock_uom,warehouse=warehouse,available=qty)
    return dict(kind=kind,scan_value=unit.handling_unit_id if unit else item_code,handling_unit=unit.name if unit else None,
        item_code=item_code,item_name=item.item_name,batch_no=batch_no or None,stock_uom=item.stock_uom,
        available_qty=qty,source_hash=canonical_key('follow-on-stock',detail))


@frappe.whitelist(methods=['POST'])
def preview_follow_on_stock(source_trip,warehouse,source_row,kind,operator_session_token,
                            scan_value=None,item_code=None,batch_no=None):
    operator,_session=_auth(operator_session_token);source=_source(source_trip,operator)
    _vehicle(warehouse,source.company)
    context=_context(source,operator,warehouse)
    row=next((r for r in context['lines'] if r['source_row']==source_row),None)
    if source_row!='ROUTE' and not row:frappe.throw('Select a current follow-on order line')
    return _stock_info(source,warehouse,row,kind,scan_value,item_code,batch_no)


def _payload(raw):
    if isinstance(raw,str):
        if len(raw)>250000:frappe.throw('Follow-on request is too large')
        try:raw=json.loads(raw)
        except ValueError:frappe.throw('Invalid follow-on request')
    allowed={'warehouse','lorry_scan','driver','assistants','trip_date','expected_return_date','orders','visits','stock','returns','confirmed_returns','reason','context_hash'}
    if not isinstance(raw,dict) or set(raw)!=allowed:frappe.throw('Review all follow-on settings before confirming')
    values=dict(raw)
    for key in ('warehouse','lorry_scan','driver','reason','context_hash'):
        if not isinstance(values[key],str) or not values[key].strip():frappe.throw('Receiving lorry, physical scan, driver and Supervisor reason are required')
        values[key]=values[key].strip()
    for key in ('trip_date','expected_return_date'):
        if not isinstance(values[key],str) or not values[key].strip():frappe.throw('Enter departure and expected return dates')
        values[key]=str(getdate(values[key]))
    if values['expected_return_date']<values['trip_date']:frappe.throw('Return date cannot precede departure')
    for key in ('assistants','visits','returns','confirmed_returns'):
        rows=values[key]
        if not isinstance(rows,list) or len(rows)>200 or any(not isinstance(v,str) or not 1<=len(v)<=140 for v in rows) or len(set(rows))!=len(rows):
            frappe.throw('Choose distinct displayed follow-on identities')
        values[key]=sorted(rows)
    if not isinstance(values['orders'],list) or len(values['orders'])>500 or not isinstance(values['stock'],list) or len(values['stock'])>1000:
        frappe.throw('Choose valid follow-on quantities and physical sources')
    for rows,fields in ((values['orders'],{'source_row','qty'}),(values['stock'],{'source_row','kind','scan_value','item_code','batch_no','qty','source_hash'})):
        for row in rows:
            if not isinstance(row,dict) or set(row)!=fields or not isinstance(row['source_row'],str):frappe.throw('Invalid follow-on row')
            try:
                if isinstance(row['qty'],bool):raise ValueError()
                qty=float(row['qty'])
            except (ValueError,TypeError,OverflowError):frappe.throw('Follow-on quantities must be positive finite numbers')
            if not math.isfinite(qty) or qty<=EPS:frappe.throw('Follow-on quantities must be positive finite numbers')
            row['qty']=qty
            if fields!={'source_row','qty'}:
                for field in fields-{'qty','batch_no'}:
                    if not isinstance(row[field],str) or not row[field].strip():frappe.throw('Invalid stock identity')
                if row['batch_no'] is not None and not isinstance(row['batch_no'],str):frappe.throw('Invalid Batch')
    values['orders']=sorted(values['orders'],key=lambda r:r['source_row'])
    values['stock']=sorted(values['stock'],key=lambda r:(r['source_row'],str(r['scan_value']),str(r['batch_no'])))
    return values


def _request_key(source,event):return canonical_key('follow-on-trip',source,event)


def _receipt(source,event,values,operator):
    key=_request_key(source.name,event)
    name=frappe.db.get_value(TRIP,{'follow_on_request_key':key},'name',for_update=True)
    if not name:return None
    child=_read(TRIP,name,current=True)
    saved=json.loads(child.follow_on_snapshot_json or '{}')
    if (child.follow_on_of!=source.name or saved.get('request_hash')!=canonical_key('follow-on-request',values)
            or saved.get('operator')!=operator.employee or saved.get('terminal_user')!=frappe.session.user):
        frappe.throw('This follow-on token belongs to different details or another actor',FollowOnReplayError)
    return dict(trip=child.name,source_trip=source.name,recorded=True)


def _void_key(source,event):return canonical_key('follow-on-void',source,event)


def _void_receipt(source,event,values,operator):
    row=frappe.db.get_value('CFG Kanban Event',{'idempotency_key':_void_key(source.name,event)},
        ['name','operator','user','payload_json'],as_dict=True,for_update=True)
    if not row:return None
    saved=json.loads(row.payload_json or '{}')
    if (saved.get('request_hash')!=canonical_key('follow-on-request',values)
            or row.operator!=operator.employee or row.user!=frappe.session.user):
        frappe.throw('This voided token belongs to different details or another actor',FollowOnReplayError)
    return row



@frappe.whitelist(methods=['POST'])
def reconcile_follow_on(source_trip,payload,event_token,operator_session_token,void_reason=None):
    operator,session=_auth(operator_session_token);_planning()._require_event_token(event_token)
    values=_payload(payload);source=_source(source_trip,operator,True)
    receipt=_receipt(source,event_token,values,operator)
    if receipt:return receipt
    key=_void_key(source.name,event_token)
    voided=_void_receipt(source,event_token,values,operator)
    if void_reason and not voided:
        if not isinstance(void_reason,str) or not void_reason.strip() or len(void_reason)>2000:frappe.throw('Enter a valid reason for voiding this unrecorded request')
        record('Unrecorded Follow-on Request Voided',reference_doctype=TRIP,reference_name=source.name,
            operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
            idempotency_key=key,notes=str(void_reason).strip(),payload=dict(request_hash=canonical_key('follow-on-request',values)))
        voided=True
    return dict(recorded=False,voided=bool(voided),source_trip=source.name)


def _select(source,context,values,operator):
    choices={row['source_row']:row for row in context['lines']};orders=[];used=set()
    for row in values['orders']:
        prior=choices.get(row['source_row'])
        if not prior or prior['source_row'] in used or row['qty']>prior['max_qty']+EPS:
            frappe.throw('Selected order quantity exceeds its exact still-required, unassigned balance')
        if not prior['is_stock_item']:frappe.throw('Follow-on delivery supports physical stock Items; keep service-only orders in their native workflow')
        _office()._quantity(row['qty'],prior['stock_uom']);used.add(prior['source_row'])
        orders.append(dict(prior,qty=row['qty']))
    visit_keys={r['stop_key'] for r in context['visits']}
    if set(values['visits'])-visit_keys:frappe.throw('Select only unfinished uncancelled visits')
    if set(values['returns'])!={r['name'] for r in context['returns']}:frappe.throw('Confirm QC receipt or include every unreceived customer return before ending the original Trip')
    if set(values['returns'])!=set(values['confirmed_returns']):frappe.throw('Scan/confirm every selected return bundle before custody handover')
    if not orders and not values['visits'] and not values['returns']:frappe.throw('Select an unfinished delivery, visit or pending return')
    if not orders and not values['visits'] and values['stock']:frappe.throw('Extra stock requires an order or optional-sale visit')
    return orders


def _stocks(source,values,orders):
    selected={r['source_row']:r for r in orders};stock=[];used_tags=set();budgets={};loose_totals={}
    planning=_planning()
    for item in sorted({r['item_code'] for r in values['stock']}):planning._lock_erp_bin(item,values['warehouse'])
    tag_names=set()
    for row in values['stock']:
        if row['kind']=='Tagged Stock':
            identity=planning.resolve_logistics_scan(row['scan_value'])
            if not identity or identity.get('identity_type')!='Handling Unit':frappe.throw('Scan the exact physical Stock Tag')
            tag_names.add(identity['name'])
    for name in sorted(tag_names):_read('CFG Kanban Handling Unit',name,True)
    for row in values['stock']:
        order=selected.get(row['source_row'])
        if row['source_row']!='ROUTE' and (not order or not order['is_stock_item']):frappe.throw('Choose an exact physical order line for each stock source')
        if row['source_row']=='ROUTE' and not values['visits']:frappe.throw('Shared route stock requires a selected optional-sale visit')
        found=_stock_info(source,values['warehouse'],order,row['kind'],row['scan_value'],row['item_code'],row['batch_no'],True)
        if found['source_hash']!=row['source_hash'] or found['item_code']!=row['item_code'] or (found['batch_no'] or None)!=(row['batch_no'] or None):
            frappe.throw('Physical source identity/availability changed; scan and review it again')
        _office()._quantity(row['qty'],found['stock_uom'])
        if found['handling_unit']:
            if found['handling_unit'] in used_tags or abs(row['qty']-found['available_qty'])>EPS:
                frappe.throw('Keep each physical tag whole and on one Plan; split/repack before follow-on confirmation')
            used_tags.add(found['handling_unit'])
        else:
            identity=(found['item_code'],found['batch_no'])
            loose_totals[identity]=loose_totals.get(identity,0)+row['qty']
            if loose_totals[identity]>found['available_qty']+EPS:frappe.throw('Selected loose quantity is no longer available')
        budgets[row['source_row']]=budgets.get(row['source_row'],0)+row['qty']
        stock.append(dict(found,qty=row['qty'],source_row=row['source_row'],sales_order_item=order['sales_order_item'] if order else None))
    if any(abs(budgets.get(row['source_row'],0)-row['qty'])>EPS for row in orders if row['is_stock_item']):
        frappe.throw('Physically confirm all selected order quantities on the receiving lorry')
    totals={}
    for row in stock:
        identity=(row['item_code'],row['batch_no'] or '')
        totals[identity]=totals.get(identity,0)+row['qty']
    for (item,batch),qty in sorted(totals.items()):
        _planning()._lock_erp_bin(item,values['warehouse'])
        _planning().assert_erp_stock(frappe._dict(item_code=item,batch_no=batch or None),values['warehouse'],qty)
    return stock


def _new_trip(source,values,orders,key,operator):
    template=_office()._template(source.route_template,source.company,current=True)
    selected={r['stop_key'] for r in orders}|set(values['visits'])
    stops=[dict(stop_key=r.stop_key,stop_purpose=r.stop_purpose,customer_scan_point=r.customer_scan_point,
        customer=r.customer,customer_address=r.customer_address,instructions=r.instructions) for r in source.stops if r.stop_key in selected]
    trip=frappe.get_doc(dict(doctype=TRIP,state='Draft',trip_title=(source.trip_title or source.name)+' / Follow-on',
        company=source.company,route_template=source.route_template,trip_date=values['trip_date'],expected_return_date=values['expected_return_date'],
        driver=values['driver'],assistant_drivers=[dict(employee=name) for name in values['assistants']],
        source_warehouse=values['warehouse'],vehicle_warehouse=values['warehouse'],
        sequence_policy='Planned Order' if 'Planned Order' in (source.sequence_policy,template.sequence_policy) else 'Flexible Order',
        gps_auto_start=source.get('gps_auto_start'),gps_publish_interval_seconds=source.get('gps_publish_interval_seconds') or '15',
        follow_on_of=source.name,follow_on_key=source.name,follow_on_request_key=key,
        follow_on_snapshot_json=json.dumps(dict(source_trip=source.name,preparing=True,return_only=not stops)),
        auto_generate_dispatch=0,stops=stops,orders=[],dispatch_plans=[]))
    trip.flags.cfg_follow_on=True
    trip.insert()
    return trip


def _close_sheets(source,operator,token,reason,key):
    from cfg_kanban.services import route_sheets
    plans=[_read(PLAN,r.dispatch_plan) for r in source.dispatch_plans]
    if source.get('open_route_plan'):plans.append(_read(PLAN,source.open_route_plan))
    for name in sorted({p.active_route_sheet for p in plans if p.get('active_route_sheet')}):
        sheet=_read('CFG Kanban Route Sheet',name,True)
        if sheet.state in ('Completed','Cancelled'):continue
        if {r.dispatch_plan for r in sheet.stops}-{p.name for p in plans}:frappe.throw('The old Route Sheet contains outside work')
        action='Close' if sheet.state!='Cancellation Pending' and all(p.state=='Reconciled' for p in plans if p.name in {r.dispatch_plan for r in sheet.stops}) else 'Cancel'
        result=route_sheets.save_route_sheet(route_sheets._sheet_scope(sheet),
            [dict(row_key=r.row_key,dispatch_plan=r.dispatch_plan,customer_scan_point=r.customer_scan_point) for r in sheet.stops],
            sheet.revision,canonical_key(key,'old-sheet',name),token,action=action,reason=reason,route_sheet=name)
        if result['sheet']['state'] not in ('Completed','Cancelled'):frappe.throw('Finish the old Route Sheet closure before follow-on takeover')


def _make_plans(source,trip,orders,stocks,operator,session,token,key):
    from cfg_kanban.services.trip_carry_in import confirm
    groups={};stops={s.stop_key:s for s in trip.stops};made=[];links=[];pool=None
    for row in orders:
        if not row['is_stock_item']:continue
        group=groups.setdefault(('Customer Order',row['stop_key'],row['sales_order']),[]);group.append(row)
    route_stock=[row for row in stocks if row['source_row']=='ROUTE']
    if values_visits(trip):groups[('Open Route Stock',None,None)]=[]
    for (kind,stop_key,order_name),rows in groups.items():
        selected=[r for r in stocks if (r['source_row']=='ROUTE' if kind=='Open Route Stock' else r['source_row'] in {o['source_row'] for o in rows})]
        policy=_profile(source,kind,current=True)
        if not selected and kind=='Open Route Stock':
            # No duplicate stock draw: use the existing empty shared-pool capability.
            line_values=[]
        elif kind=='Open Route Stock':
            combined={}
            for r in selected:
                identity=(r['item_code'],r['batch_no'],r['stock_uom'])
                combined[identity]=combined.get(identity,0)+r['qty']
            line_values=[dict(item_code=i,batch_no=b,stock_uom=u,requested_qty=q,reserved_qty=0,line_state='Open') for (i,b,u),q in combined.items()]
        else:
            line_values=[dict(item_code=r['item_code'],item_name=r['item_name'],stock_uom=r['stock_uom'],sales_order_item=r['sales_order_item'],
                requested_qty=r['qty'],reserved_qty=0,line_state='Open') for r in rows]
        context=_planning()._business_context(policy,customer_site=stops[stop_key].customer_scan_point if stop_key else None,
            sales_order=order_name,required_date=trip.trip_date,trip_date=trip.trip_date)
        plan=_planning()._build_dispatch_plan(policy,context,line_values,canonical_key(key,kind,stop_key,order_name),
            route_template=trip.route_template,actor=dict(employee=operator.employee,operator_session=session.name,user=session.terminal_user),
            template_data=dict(name=trip.route_template,revision=trip.template_revision,company=trip.company,office_delivery_trip=trip.name,
                stops=[dict(customer_scan_point=r.customer_scan_point,instructions=r.instructions or '') for r in trip.stops if r.customer_scan_point]))
        plan.update(dict(office_delivery_trip=trip.name,office_stop_key=stop_key,office_source_hash=key,
            source_warehouse=trip.vehicle_warehouse,vehicle_warehouse=trip.vehicle_warehouse,
            vehicle_reference=_vehicle(trip.vehicle_warehouse,trip.company).cfg_vehicle_reference,
            follow_on_trip=trip.name,existing_lorry_stock_only=int(kind=='Open Route Stock' and not selected),
            state='Awaiting Approval' if policy.approval_required else 'Approved',submitted_on=now_datetime()))
        plan.flags.cfg_office_dispatch=True;plan.flags.cfg_follow_on=True;plan.insert(ignore_permissions=True)
        if selected:made.append(confirm(plan,selected,operator,session,token,canonical_key(key,'plan',plan.name)))
        else:
            if plan.approval_required:_planning().approve_dispatch_plan(plan.name,canonical_key(key,'approve',plan.name),token)
            plan.db_set(dict(state='Ready for Fulfilment',ready_on=now_datetime()),update_modified=True)
        if kind=='Customer Order':links.append(dict(dispatch_plan=plan.name,stop_key=stop_key))
        else:
            pool=plan
            from cfg_kanban.services.trip_dispatch import _seed_visits
            _seed_visits(trip,pool)
    trip.set('dispatch_plans',links);trip.open_route_plan=pool.name if pool else None
    return made


def values_visits(trip):return [s for s in trip.stops if s.stop_purpose=='Visit Only' and s.customer_scan_point]


@frappe.whitelist(methods=['POST'])
def create_follow_on_trip(source_trip,payload,event_token,operator_session_token):
    operator,session=_auth(operator_session_token);_planning()._require_event_token(event_token)
    values=_payload(payload);source=_source(source_trip,operator,True)
    receipt=_receipt(source,event_token,values,operator)
    if receipt:return receipt
    if _void_receipt(source,event_token,values,operator):
        frappe.throw('This unrecorded follow-on request was voided',FollowOnReplayError)
    if source.get('follow_on_trip') or frappe.db.exists(TRIP,{'follow_on_key':source.name}):
        frappe.throw('This original Trip already has a follow-on; open the recorded Trip instead')
    _vehicle(values['warehouse'],source.company,current=True)
    vehicle=_planning()._vehicle_warehouse_from_scan(values['lorry_scan'],source.company)
    if vehicle.name!=values['warehouse']:frappe.throw('Scan the selected receiving lorry Warehouse card')
    driver=_read('Employee',values['driver'],True)
    if driver.status!='Active':frappe.throw('Select an active receiving driver')
    if values['driver'] in values['assistants']:frappe.throw('The lead driver cannot also be an assistant')
    for name in values['assistants']:
        if _read('Employee',name,True).status!='Active':frappe.throw('Select active assistant Employees')
    orders_names=sorted({r.sales_order for r in source.orders})
    _office()._locks('CFG Kanban Dispatch Plan',sorted({r.dispatch_plan for r in source.dispatch_plans}|({source.open_route_plan} if source.get('open_route_plan') else set())))
    _office()._locks('Sales Order',orders_names)
    context=_context(source,operator,values['warehouse'],True)
    if context['blockers']:frappe.throw('; '.join(context['blockers']))
    if values['context_hash']!=context['context_hash']:frappe.throw('Source Trip/orders/custody changed; refresh and review the follow-on again')
    orders=_select(source,context,values,operator)
    stocks=_stocks(source,values,orders)
    key=_request_key(source.name,event_token)
    savepoint='cfg_follow_on_create'
    frappe.db.savepoint(savepoint)
    try:
        return _persist_follow_on(source,values,orders,stocks,key,operator,session,operator_session_token)
    except Exception:
        try:frappe.db.rollback(save_point=savepoint)
        except Exception:
            # Deadlocks/connection recovery can already have discarded the savepoint.
            # Roll back the whole request rather than leave partial work committable.
            frappe.db.rollback()
        raise


def _persist_follow_on(source,values,orders,stocks,key,operator,session,operator_session_token):
    child=_new_trip(source,values,orders,key,operator)
    from cfg_kanban.services.return_custody import transfer
    transfer(source,child,values['returns'],operator,session,values['reason'])
    source.flags.cfg_follow_on=True;source.follow_on_trip=child.name
    if source.state not in ('Closed','Cancelled'):
        source.state='Closed';source.closure_reason='Follow-on '+child.name+': '+values['reason']
    source.save()
    _close_sheets(source,operator,operator_session_token,values['reason'],key)
    child.set('orders',[dict(stop_key=r['stop_key'],sales_order=r['sales_order'],sales_order_item=r['sales_order_item'],planned_qty=r['qty']) for r in orders])
    child.save()
    plans=_make_plans(source,child,orders,stocks,operator,session,operator_session_token,key)
    snapshot=dict(source_trip=source.name,source_context_hash=values['context_hash'],source_vehicle=source.vehicle_warehouse,
        warehouse=child.vehicle_warehouse,operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        request_hash=canonical_key('follow-on-request',values),orders=orders,stock=stocks,returns=values['returns'],plans=plans,
        confirmed_on=str(now_datetime()),reason=values['reason'],return_only=not child.stops)
    child.follow_on_snapshot_json=json.dumps(snapshot,sort_keys=True,default=str)
    child.flags.cfg_trip_dispatch=True
    child.save()
    record('Follow-on Delivery Trip Created',reference_doctype=TRIP,reference_name=child.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        idempotency_key=canonical_key(key,'created'),payload=snapshot)
    return dict(trip=child.name,source_trip=source.name,recorded=True)


def protect_trip(doc,before):
    if before and doc.get('follow_on_of') and not doc.flags.get('cfg_follow_on') and _office()._business(doc)!=_office()._business(before):
        frappe.throw('Confirmed follow-on stock and custody must retain their Trip snapshot; use Trip Handover for another takeover')
    fields=('follow_on_of','follow_on_trip','follow_on_key','follow_on_request_key','follow_on_snapshot_json')
    if not doc.flags.get('cfg_follow_on') and any((doc.get(f) or None)!=((before.get(f) or None) if before else None) for f in fields):
        frappe.throw('Follow-on links and physical stock/custody receipts are controlled; use the follow-on action')


@frappe.whitelist()
def resolve_follow_on_return(source_trip,scan_value,operator_session_token):
    """A label confirms custody, never a second receipt or a new return claim."""
    operator,_session=_auth(operator_session_token);source=_source(source_trip,operator)
    value=str(scan_value or '').strip()
    if value.startswith('CFG:RETURN-CUSTODY:'):
        label=_read('CFG Kanban Return Custody Label',value.split(':',2)[2])
        name=label.return_case
    else:
        name=value if frappe.db.exists('CFG Kanban Return Case',value) else frappe.db.get_value('CFG Kanban Return Case',{'scan_token':value},'name')
    if not name:frappe.throw('Scan a selected Return Case or its original custody label')
    case=_read('CFG Kanban Return Case',name)
    from cfg_kanban.services.return_custody import current_trip,pending
    if case.selling_company!=source.company or current_trip(case)!=source.name or not pending(case):
        frappe.throw('This Return Case is not pending custody on the selected original Trip')
    return dict(name=case.name)

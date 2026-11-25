"""Office-generated native dispatch requests and one shared Open Route pool per Trip."""
import json

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

PLAN = 'CFG Kanban Dispatch Plan'
TRIP = 'CFG Kanban Delivery Trip'
EDITABLE_REQUEST = ('Draft', 'Awaiting Approval', 'Approved')


def _office():
    from cfg_kanban.services import delivery_trips
    return delivery_trips


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _routes():
    from cfg_kanban.services import route_delivery
    return route_delivery


def existing_pool(plan):
    return bool(plan.get('office_delivery_trip') and plan.get('existing_lorry_stock_only')
                and plan.plan_type == 'Open Route Stock' and plan.fulfilment_mode == 'Vehicle Delivery'
                and not plan.lines and not plan.get('movement_manifest'))


def route_ready(plan):
    return plan.state == 'Loaded' or (existing_pool(plan) and plan.state == 'Ready for Fulfilment')


def _profile(name, trip, kind):
    if not name:
        frappe.throw('Select the %s Dispatch Profile on this Delivery Trip' % kind)
    policy = _office()._read('CFG Kanban Dispatch Profile', name, current=True)
    if (not policy.active or policy.company != trip.company or policy.plan_type != kind
            or policy.fulfilment_mode != 'Vehicle Delivery'):
        frappe.throw('Trip Profile must be an active %s / Vehicle Delivery Profile in this Company' % kind)
    if trip.source_warehouse and policy.source_warehouse != trip.source_warehouse:
        frappe.throw('Dispatch Profile source Warehouse differs from the Trip')
    warehouse=_office()._read('Warehouse',policy.source_warehouse)
    if warehouse.company!=trip.company or warehouse.disabled or warehouse.is_group:frappe.throw('Profile source must be an active leaf Warehouse in this Company')
    _office()._read('CFG Kanban Card', policy.dispatch_point)
    _planning()._validate_profile_card(policy)
    return policy


def validate_setup(doc, before=None):
    if not (getattr(doc,'flags',None) or {}).get('cfg_trip_dispatch'):
        for field in ('open_route_plan', 'dispatch_generated_on'):
            current=doc.get(field) or None
            original=(before.get(field) if before else None) or None
            if field=='dispatch_generated_on':
                # Desk sends JSON text; the saved Doc can contain a native datetime.
                current=get_datetime(current) if current else None
                original=get_datetime(original) if original else None
            if current != original:
                frappe.throw('Generated Dispatch links and audit facts are controlled; use Generate / Refresh Dispatch')
    seen = set()
    for row in doc.get('route_stock') or []:
        item=_office()._read('Item',row.item_code)
        if item.disabled or not item.is_stock_item:frappe.throw('Extra route goods must be enabled stock Items')
        key=(row.item_code,row.batch_no or '')
        if key in seen:frappe.throw('Combine duplicate extra Item/Batch quantities in the shared pool')
        seen.add(key)
        row.stock_uom=item.stock_uom;row.qty=_office()._quantity(row.qty,item.stock_uom)
        _planning()._validate_batch(row.item_code,row.batch_no)
    if doc.get('open_route_plan'):
        pool = _office()._read(PLAN, doc.open_route_plan, current=True)
        if (pool.office_delivery_trip != doc.name or pool.company != doc.company
                or pool.plan_type != 'Open Route Stock' or pool.fulfilment_mode != 'Vehicle Delivery'):
            frappe.throw('Shared Open Route Plan does not belong to this exact Trip and Company')
        if doc.vehicle_warehouse and pool.vehicle_warehouse and pool.vehicle_warehouse != doc.vehicle_warehouse:
            frappe.throw('Shared pool and Trip use different lorries')


def _specs(trip):
    if trip.get('follow_on_of'):
        frappe.throw('Follow-on stock was already confirmed; do not generate another warehouse withdrawal')
    groups = {}
    stops = {r.stop_key: r for r in trip.stops}
    stock = [r for r in trip.orders if cint(r.is_stock_item) and not stops[r.stop_key].get('cancellation_request')]
    if stock:
        profile = _profile(trip.dispatch_profile, trip, 'Customer Order')
        for row in stock:
            stop = stops[row.stop_key]
            key = ('customer', row.stop_key, row.sales_order)
            spec = groups.setdefault(key, dict(kind='customer', key=key, policy=profile,
                stop_key=row.stop_key, site=stop.customer_scan_point, sales_order=row.sales_order, lines=[]))
            spec['lines'].append(dict(item_code=row.item_code, stock_uom=row.stock_uom,
                item_name=row.item_name, requested_qty=flt(row.planned_qty), sales_order_item=row.sales_order_item,
                batch_no=None, reserved_qty=0, loaded_qty=0, line_state='Open'))
    visits = [r for r in trip.stops if r.stop_purpose == 'Visit Only' and r.customer_scan_point and not r.get('cancellation_request')]
    if visits or trip.get('route_stock') or (trip.get('open_route_plan') and any(r.stop_purpose=='Visit Only' and r.get('cancellation_request') for r in trip.stops)):
        policy = _profile(trip.open_route_profile, trip, 'Open Route Stock')
        key = ('open', '', '')
        groups[key] = dict(kind='open', key=key, policy=policy, stop_key=None, site=None, sales_order=None,
            lines=[dict(item_code=r.item_code, item_name=frappe.db.get_value('Item',r.item_code,'item_name'),
                stock_uom=r.stock_uom, requested_qty=flt(r.qty),batch_no=r.batch_no or None,
                reserved_qty=0,loaded_qty=0,line_state='Open') for r in trip.get('route_stock') or []])
    return groups


def _hash(trip, spec):
    return canonical_key('office-dispatch-source',trip.name,trip.company,str(trip.trip_date),
        spec['key'],spec['policy'].name,spec['policy'].revision,spec['lines'],
        trip.template_snapshot_json,[(r.stop_key,r.customer_scan_point,r.customer,r.customer_address) for r in trip.stops], trip.vehicle_warehouse if not spec['lines'] else None)


def _can_replace(plan):
    if ((plan.state not in EDITABLE_REQUEST and not (existing_pool(plan) and plan.state=='Ready for Fulfilment')) or plan.get('movement_manifest') or plan.get('delivery_session')
            or plan.get('active_route_sheet') or plan.get('dispatch_review_state')
            or frappe.db.exists('CFG Kanban Dispatch Allocation',{'dispatch_plan':plan.name,
                'state':['not in',['Released','Cancelled']]})
            or frappe.db.exists('CFG Kanban Route Stop',{'dispatch_plan':plan.name,
                'state':['not in',['Planned','Cancelled','Skipped']]})):
        frappe.throw('Generated dispatch work has started. Release/cancel it through its controlled workflow before changing the Trip request')


def _retire(plan, trip):
    _can_replace(plan)
    for row in frappe.db.get_values('CFG Kanban Route Stop',{'dispatch_plan':plan.name,'state':'Planned'},['name'],as_dict=True,for_update=True):
        frappe.db.set_value('CFG Kanban Route Stop',row.name,dict(state='Skipped',skip_reason='Office Trip request replaced before execution'),update_modified=True)
    plan.db_set(dict(state='Cancelled',cancelled_on=now_datetime(),cancellation_reason='Office Trip request updated before execution'),update_modified=True)
    record('Office Trip Dispatch Request Replaced',reference_doctype=PLAN,reference_name=plan.name,
        terminal_user=frappe.session.user,notes=trip.name)


def _create(trip,spec,digest):
    policy=spec['policy']
    context=_planning()._business_context(policy,customer_site=spec['site'],sales_order=spec['sales_order'],
        required_date=trip.trip_date,trip_date=trip.trip_date)
    key=canonical_key('office-dispatch-create',trip.name,spec['key'],digest)
    while True:
        existing=frappe.db.get_value(PLAN,{'idempotency_key':key},'name',for_update=True)
        if not existing:break
        plan=_office()._read(PLAN,existing,current=True)
        if plan.state!='Cancelled':return plan
        if plan.get('cancellation_reason')!='Office Trip request updated before execution':
            frappe.throw('This exact Trip request was cancelled. Revise the office request before generating a replacement')
        # An unused office quantity may be corrected back to an earlier value. Keep
        # every cancelled request and derive one new identity under the parent lock.
        key=canonical_key('office-dispatch-replaced',key,plan.name)
    plan=_planning()._build_dispatch_plan(policy,context,spec['lines'],key,
        route_template=trip.route_template,actor=dict(user=frappe.session.user),
        template_data=dict(name=trip.route_template,revision=trip.template_revision,company=trip.company,
            office_delivery_trip=trip.name,stops=[dict(customer_scan_point=r.customer_scan_point,instructions=r.instructions or '') for r in trip.stops if r.customer_scan_point]))
    stop=next((r for r in trip.stops if r.stop_key==spec['stop_key']),None)
    plan.business_label=(trip.name+' / '+(str(stop.delivery_sequence)+'. '+stop.customer if stop else 'Shared Open Route Stock'))[:140]
    plan.office_delivery_trip=trip.name;plan.office_stop_key=spec['stop_key'];plan.office_source_hash=digest
    plan.existing_lorry_stock_only=int(spec['kind']=='open' and not spec['lines'])
    plan.state='Awaiting Approval' if cint(policy.approval_required) else 'Approved'
    plan.submitted_on=now_datetime()
    plan.flags.cfg_office_dispatch=True
    plan.insert(ignore_permissions=True)
    record('Office Trip Dispatch Request Created',reference_doctype=PLAN,reference_name=plan.name,
        previous_state=None,new_state=plan.state,terminal_user=frappe.session.user,
        idempotency_key=canonical_key('office-dispatch-created',plan.name),notes=trip.name+'; no stock reserved or posted')
    return plan


def _seed_visits(trip,pool):
    desired={r.stop_key:r for r in trip.stops if r.stop_purpose=='Visit Only' and r.customer_scan_point and not r.get('cancellation_request')}
    existing={r.office_stop_key:r for r in frappe.db.get_values('CFG Kanban Route Stop',
        {'dispatch_plan':pool.name,'state':'Planned'},['name','office_stop_key','customer_scan_point'],as_dict=True,for_update=True)}
    for key,row in existing.items():
        if key not in desired:
            frappe.db.set_value('CFG Kanban Route Stop',row.name,dict(state='Skipped',skip_reason='Office visit removed before execution'),update_modified=True)
    for key,stop in desired.items():
        if key in existing:
            if existing[key].customer_scan_point!=stop.customer_scan_point:
                frappe.throw('Customer Site changed on a generated visit; replace the unused shared request first')
            frappe.db.set_value('CFG Kanban Route Stop',existing[key].name,'planned_sequence',stop.delivery_sequence,update_modified=False)
            continue
        site=_office()._read('CFG Kanban Customer Scan Point',stop.customer_scan_point)
        _routes()._assert_site_scope(pool,site)
        doc=frappe.get_doc(dict(doctype='CFG Kanban Route Stop',state='Planned',dispatch_plan=pool.name,
            company=trip.company,customer_scan_point=site.name,site_name=site.site_name,customer=site.customer,
            customer_address=site.customer_address,planned_sequence=stop.delivery_sequence,
            office_delivery_trip=trip.name,office_stop_key=key,created_on=now_datetime(),
            idempotency_key=canonical_key('office-route-visit',pool.name,key)))
        doc.flags.cfg_office_dispatch=True;doc.insert(ignore_permissions=True)


def bind_existing_pool(trip,pool,vehicle):
    if not existing_pool(pool) or not vehicle:
        return
    _planning()._vehicle_warehouse(vehicle,trip.company)
    if pool.state=='Awaiting Approval':return
    if pool.state not in ('Approved','Ready for Fulfilment'):
        frappe.throw('Approve the shared existing-stock request before starting the route')
    if pool.vehicle_warehouse and pool.vehicle_warehouse!=vehicle:
        frappe.throw('Shared existing-stock pool belongs to another lorry')
    warehouse=_office()._read('Warehouse',vehicle)
    pool.db_set(dict(vehicle_warehouse=vehicle,vehicle_reference=warehouse.cfg_vehicle_reference,
        state='Ready for Fulfilment',ready_on=pool.get('ready_on') or now_datetime()),update_modified=True)


def generate(doc, explicit=False, save=True):
    if doc.flags.get('cfg_generating_trip_dispatch'):return
    if not explicit and (not cint(doc.get('auto_generate_dispatch')) or doc.state!='Planned'):return
    if doc.state not in ('Draft','Planned') or doc.get('driver_route_state') not in (None,'','Not Started'):
        if explicit:frappe.throw('Generate dispatch requests before driver execution starts')
        return
    _office()._locks('CFG Kanban Route Template',[doc.route_template])
    frappe.db.sql('select name from `tabCFG Kanban Delivery Trip` where name=%s for update',doc.name)
    doc.check_permission('write');frappe.only_for(_office().EDITORS)
    existing=[_office()._read(PLAN,r.dispatch_plan,current=True) for r in doc.dispatch_plans]
    if doc.get('open_route_plan'):existing.append(_office()._read(PLAN,doc.open_route_plan,current=True))
    if any(p.office_delivery_trip!=doc.name for p in existing):
        frappe.throw('Keep manually linked Plans in manual mode, or remove unused manual links before generating Trip dispatch')
    if existing and any(p.state not in EDITABLE_REQUEST+('Ready for Fulfilment','Cancelled') for p in existing):
        if explicit:frappe.throw('Dispatch execution has started; retain the generated requests and use existing operational controls')
        return
    specs=_specs(doc)
    if not specs and (any(not next((s.get('cancellation_request') for s in doc.stops if s.stop_key==r.stop_key),False) for r in doc.orders) or doc.get('route_stock')):frappe.throw('No physical stock quantities are available for dispatch generation')
    by_key={('open','','') if p.plan_type=='Open Route Stock' else ('customer',p.office_stop_key,p.sales_order):p for p in existing if p.state!='Cancelled'}
    cancelled_keys={r.stop_key for r in doc.stops if r.get('cancellation_request')}
    retained=[dict(dispatch_plan=r.dispatch_plan,stop_key=r.stop_key) for r in doc.dispatch_plans if r.stop_key in cancelled_keys]
    made=[];known=[];pool=None
    for key,spec in specs.items():
        digest=_hash(doc,spec);plan=by_key.get(key)
        if plan and plan.office_source_hash!=digest:
            _retire(plan,doc);plan=None
        if not plan:plan=_create(doc,spec,digest)
        made.append(plan)
        if spec['kind']=='open':pool=plan;_seed_visits(doc,pool)
        else:known.append(dict(dispatch_plan=plan.name,stop_key=spec['stop_key']))
    for key,plan in by_key.items():
        if key not in specs and plan.get('office_stop_key') not in cancelled_keys:_retire(plan,doc)
    doc.flags.cfg_generating_trip_dispatch=True;doc.flags.cfg_trip_dispatch=True
    try:
        doc.set('dispatch_plans',retained+known);doc.open_route_plan=pool.name if pool else None
        if pool:bind_existing_pool(doc,pool,doc.vehicle_warehouse)
        if not doc.get('source_warehouse') and made:doc.source_warehouse=made[0].source_warehouse
        if any(p.source_warehouse!=doc.source_warehouse for p in made):frappe.throw('Generated requests must share this Trip loading source Warehouse')
        if not doc.get('dispatch_generated_on') or any(p.name not in {x.name for x in existing} for p in made):doc.dispatch_generated_on=now_datetime()
        if save:doc.save()
    finally:
        doc.flags.cfg_generating_trip_dispatch=False;doc.flags.cfg_trip_dispatch=False


@frappe.whitelist()
def generate_dispatch_for_trip(trip_name,expected_modified):
    frappe.only_for(_office().EDITORS)
    row=_office()._read(TRIP,trip_name)
    _office()._locks('CFG Kanban Route Template',[row.route_template])
    doc=_office()._read(TRIP,trip_name,current=True);doc.check_permission('write')
    if get_datetime(doc.modified)!=get_datetime(expected_modified):frappe.throw('Trip changed. Reload before generating dispatch work')
    generate(doc,explicit=True)
    return dict(trip=doc.name,plans=[r.dispatch_plan for r in doc.dispatch_plans],open_route_plan=doc.open_route_plan)


def open_loading_rows(trip):
    if not trip.get('open_route_plan'):return []
    pool=_office()._read(PLAN,trip.open_route_plan)
    if existing_pool(pool):return []
    allocations=frappe.get_list('CFG Kanban Dispatch Allocation',filters={'dispatch_plan':pool.name,'state':['not in',['Released','Cancelled']]},
        fields=['name','dispatch_plan_line','item_code','batch_no','stock_uom','allocated_qty','state','handling_unit','visible_code','allocation_kind'],order_by='name',limit_page_length=0)
    rows=[];used={}
    for a in allocations:
        used[a.dispatch_plan_line]=used.get(a.dispatch_plan_line,0)+flt(a.allocated_qty)
        rows.append(dict(dispatch_plan=pool.name,dispatch_allocation=a.name,item_code=a.item_code,batch_no=a.batch_no,
            stock_uom=a.stock_uom,qty=flt(a.allocated_qty),handling_unit=a.handling_unit,tag_code=a.visible_code,
            allocation_kind=a.allocation_kind,source_state=a.state,loaded_qty=flt(a.allocated_qty) if a.state=='Loaded' else 0))
    for line in pool.lines:
        if flt(line.requested_qty)>used.get(line.name,0):rows.append(dict(dispatch_plan=pool.name,item_code=line.item_code,
            batch_no=line.batch_no,stock_uom=line.stock_uom,qty=flt(line.requested_qty)-used.get(line.name,0),loaded_qty=0,
            allocation_kind='Not Prepared',source_state=pool.state))
    for r in rows:r.update(delivery_sequence=0,instruction='Shared Open Route pool; keep accessible across customer visits')
    return rows

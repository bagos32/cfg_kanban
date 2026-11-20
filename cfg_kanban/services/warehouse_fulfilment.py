"""E4C: hand prepared warehouse reservations to the existing customer-delivery engine."""
import json

import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key


MODES = ('Direct Warehouse Delivery', 'Customer Pickup')
ACTIVE_STATES = ('Ready for Fulfilment', 'Fulfilment In Progress')


def _bridge():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _planning():
    return _bridge()._planning_services()


def _engine():
    return _bridge()._delivery_services()


def source_warehouse(name, company):
    warehouse = frappe.db.get_value('Warehouse', name,
        ['name', 'company', 'disabled', 'is_group'], as_dict=True)
    if not warehouse or warehouse.company != company or warehouse.disabled or warehouse.is_group:
        frappe.throw('Warehouse fulfilment requires an active stock Warehouse in the selling Company')
    return warehouse


def _assert_plan(plan, starting=False):
    if plan.plan_type != 'Customer Order' or plan.fulfilment_mode not in MODES:
        frappe.throw('Select a Customer Order Plan for Direct Warehouse Delivery or Customer Pickup')
    if plan.vehicle_warehouse or plan.movement_manifest:
        frappe.throw('Warehouse fulfilment cannot use a vehicle claim or loading Manifest')
    allowed = ('Ready for Fulfilment',) if starting else (*ACTIVE_STATES, 'Fulfilled')
    if plan.state not in allowed:
        frappe.throw('Fully prepare and reserve the warehouse Plan before starting customer fulfilment')
    source_warehouse(plan.source_warehouse, plan.company)


def warehouse_plans(site_name, operator):
    engine, planning = _engine(), _planning()
    if not engine._customer_delivery_allowed(operator):
        return []
    rows = frappe.get_all('CFG Kanban Dispatch Plan', filters={
        'plan_type': 'Customer Order', 'fulfilment_mode': ['in', list(MODES)],
        'state': ['in', list(ACTIVE_STATES)], 'customer_site': site_name},
        fields=['name', 'company', 'customer', 'customer_site', 'source_warehouse', 'fulfilment_mode',
                'business_label', 'dispatch_responsibility', 'delivery_session', 'fulfilment_status'],
        order_by='ready_on asc, name asc', limit_page_length=200)
    result = []
    for row in rows:
        if not (planning._view_all(operator) or row.dispatch_responsibility in planning._responsibilities(operator)):
            continue
        if row.delivery_session and not engine._can_view_delivery(operator,
                frappe.get_doc('CFG Kanban Delivery Session', row.delivery_session)):
            continue
        quantities = {}
        for line in frappe.get_all('CFG Kanban Dispatch Plan Line', filters={'parent':row.name},
                                  fields=['stock_uom','requested_qty'], limit_page_length=0):
            quantities[line.stock_uom] = quantities.get(line.stock_uom,0) + flt(line.requested_qty)
        row['quantity_summary'] = ' / '.join(f'{qty:g} {uom}' for uom,qty in sorted(quantities.items()))
        result.append(row)
    return result


def _sources(plan, states):
    return frappe.db.get_values('CFG Kanban Dispatch Allocation',
        {'dispatch_plan':plan.name, 'state':['in',list(states)]},
        ['name','state','dispatch_plan_line','allocation_kind','handling_unit','item_code','batch_no',
         'stock_uom','allocated_qty','source_company','source_warehouse'],
        as_dict=True, for_update=True, order_by='name asc')


def _assert_complete(plan, sources):
    totals = {}
    lines = {row.name:row for row in plan.lines}
    for source in sources:
        line = lines.get(source.dispatch_plan_line)
        if (not line or source.source_company != plan.company or source.source_warehouse != plan.source_warehouse
                or source.item_code != line.item_code or source.stock_uom != line.stock_uom
                or (line.batch_no and source.batch_no != line.batch_no) or flt(source.allocated_qty)<=0):
            frappe.throw('Prepared reservation no longer matches its warehouse Plan line')
        totals[line.name] = totals.get(line.name,0) + flt(source.allocated_qty)
    if not lines or any(abs(totals.get(name,0)-flt(line.requested_qty))>0.000001 for name,line in lines.items()):
        frappe.throw('Every warehouse Plan line must be fully and exactly reserved')


def start_warehouse_delivery(plan, customer_scan, event_token, operator, session, token):
    """Caller holds the current Plan lock and has checked both operational responsibilities."""
    engine, planning, bridge = _engine(), _planning(), _bridge()
    request_key = canonical_key('warehouse-customer-delivery', plan.name, event_token)
    key = canonical_key('customer-delivery-session', plan.customer_site, plan.source_warehouse, request_key)
    replay = frappe.db.get_value('CFG Kanban Delivery Session', {'idempotency_key':key}, 'name')
    existing = replay or plan.get('delivery_session')
    if existing:
        # Replay reads immutable snapshots; never wait for an existing Session while holding Plan.
        delivery = frappe.get_doc('CFG Kanban Delivery Session', existing)
        identity = engine.resolve_logistics_scan(customer_scan)
        if not identity or identity.get('identity_type')!='Customer Scan Point' or identity['name']!=delivery.customer_scan_point:
            frappe.throw('Scan the Customer Site assigned to this warehouse delivery')
        if delivery.dispatch_plan!=plan.name or not engine._can_view_delivery(operator, delivery):
            frappe.throw('Warehouse Delivery Session belongs to another Plan or operator')
        return engine.get_delivery_session(delivery.name,token)
    _assert_plan(plan, starting=True)
    card = frappe.db.get_value('CFG Kanban Card',plan.dispatch_point,['active','blocked'],as_dict=True)
    if not card or not card.active or card.blocked:
        frappe.throw('Dispatch Operations Card is inactive or blocked')
    site = engine._resolve_customer_site(customer_scan)
    if (site.name!=plan.customer_site or site.selling_company!=plan.company or
            site.customer!=plan.customer or site.customer_address!=plan.customer_address):
        frappe.throw('Scanned Customer Site differs from the Plan Company, Customer or address')
    sources = _sources(plan, ('Reserved',))
    _assert_complete(plan,sources)
    for item in sorted({row.item_code for row in sources}):
        planning._lock_erp_bin(item, plan.source_warehouse)
    for name in sorted({row.handling_unit for row in sources if row.handling_unit}):
        frappe.get_doc('CFG Kanban Handling Unit',name,for_update=True)
    for source in sources:
        if source.handling_unit:
            unit=frappe.get_doc('CFG Kanban Handling Unit',source.handling_unit,for_update=True)
            if (unit.inventory_company!=plan.company or unit.current_warehouse!=plan.source_warehouse or
                    unit.item_code!=source.item_code or (unit.batch_no or '')!=(source.batch_no or '') or
                    unit.stock_uom!=source.stock_uom or flt(unit.current_qty)+0.000001<flt(source.allocated_qty) or
                    abs(flt(unit.reserved_qty)-flt(source.allocated_qty))>0.000001):
                frappe.throw('Prepared Stock Tag identity or reservation changed; release and prepare it again')
            bridge.assert_delivery_tag_expiry(unit)
            membership=engine.active_container_membership(unit.name)
            if membership:
                holder=frappe.get_doc('CFG Kanban Handling Unit',membership.container_handling_unit,for_update=True)
                quantity_bin=holder.get('reusable_container_role') in ('Production Output Container','Logistics Quantity Bin')
                if not quantity_bin and abs(flt(unit.current_qty)-flt(source.allocated_qty))>0.000001:
                    frappe.throw('Ordinary logistics containers require every tag in full; split/repack before fulfilment')
        else:
            planning._assert_untagged_allocation_available(source)
    order, order_rows = bridge._order_assignments(plan,sources)
    snapshot=json.loads(plan.profile_snapshot_json)
    policy=plan.proof_policy
    if not policy or policy=='Inherit Customer Site':
        policy=site.proof_policy
    if policy not in ('Required','Optional','Unattended Delivery Allowed','No Proof Required'):
        frappe.throw('Unsupported warehouse delivery proof policy')
    extra={'dispatch_plan':plan.name,'active_dispatch_plan_key':plan.name,
           'fulfilment_mode':plan.fulfilment_mode,'sales_order':plan.sales_order,'proof_policy':policy,
           'auto_submit_delivery_note':cint(snapshot.get('auto_submit_delivery_note'))}
    if plan.fulfilment_mode=='Customer Pickup':
        acknowledgement=snapshot.get('pickup_acknowledgement') or 'Recipient Name'
        if acknowledgement not in ('Recipient Name','Signature','Recipient Name and Signature'):
            frappe.throw('Unsupported Pickup Acknowledgement requirement')
        extra.update(proof_policy='Required',pickup_acknowledgement=acknowledgement,
            require_recipient_name=int(bool(cint(site.require_recipient_name) or 'Recipient Name' in acknowledgement)),
            require_signature=int(bool(cint(site.require_signature) or 'Signature' in acknowledgement)))
    if order:
        price_list=order.selling_price_list or site.default_price_list
        if price_list:
            extra['price_list']=price_list
        extra['sales_order_context_json']=json.dumps({key:order.get(key) for key in
            ('currency','conversion_rate','price_list_currency','plc_conversion_rate','project')},sort_keys=True)
    created=engine._start_delivery_session(site,plan.source_warehouse,request_key,operator,session,snapshots=extra)
    # Releasing and re-reserving happen in this transaction under Plan/Bin/HU locks.
    # No stock movement occurs, and failure rolls back both halves of the handoff.
    for source in sources:
        allocation=frappe.get_doc('CFG Kanban Dispatch Allocation',source.name,for_update=True)
        planning._release_allocation(allocation,plan,operator,session,
            f'Reservation handed to Delivery Session {created.name}',canonical_key(request_key,source.name),
            final_state='In Fulfilment')
    for source in sources:
        link={'dispatch_allocation':source.name,'sales_order_item':order_rows.get(source.name)}
        if source.handling_unit:
            unit=frappe.get_doc('CFG Kanban Handling Unit',source.handling_unit,for_update=True)
            membership=engine.active_container_membership(unit.name)
            container=membership.container_handling_unit if membership else None
            if container:
                engine._validate_container(frappe.get_doc('CFG Kanban Handling Unit',container,for_update=True),created)
            engine._reserve_unit(created,unit,source.allocated_qty,request_key,operator,session,
                container,membership.container_visible_code if membership else None,snapshots=link)
        else:
            bridge._reserve_untagged(created,source,request_key,operator,session,link)
    created.db_set('state','Allocating Stock',update_modified=True)
    plan.db_set({'state':'Fulfilment In Progress','delivery_session':created.name,
                 'total_reserved_qty':0,'fulfilment_status':'In Progress'},update_modified=True)
    for line in plan.lines:
        frappe.db.set_value('CFG Kanban Dispatch Plan Line',line.name,
            {'reserved_qty':0,'line_state':'In Fulfilment'},update_modified=False)
    validate_warehouse_allocations(created)
    engine._validate_confirmed_container_groups(frappe.db.get_values('CFG Kanban Delivery Allocation',
        {'delivery_session':created.name,'state':'Reserved'},['name','handling_unit','container_handling_unit'],
        as_dict=True,for_update=True))
    record('Warehouse Customer Fulfilment Started',delivery_session=created.name,
        reference_doctype='CFG Kanban Dispatch Plan',reference_name=plan.name,
        device_id=request_key,operator=operator.employee,operator_session=session.name,
        terminal_user=session.terminal_user,notes=f'{plan.fulfilment_mode}; {plan.source_warehouse}; existing reservations handed over')
    return engine.get_delivery_session(created.name,token)


def validate_warehouse_allocations(delivery, allocations=None):
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',delivery.dispatch_plan,for_update=True)
    _assert_plan(plan)
    if (plan.state!='Fulfilment In Progress' or plan.delivery_session!=delivery.name or
            plan.company!=delivery.selling_company or plan.source_warehouse!=delivery.source_warehouse or
            plan.customer_site!=delivery.customer_scan_point or plan.customer!=delivery.customer or
            plan.customer_address!=delivery.customer_address or plan.fulfilment_mode!=delivery.fulfilment_mode):
        frappe.throw('Warehouse Delivery Session differs from its immutable Plan context')
    sources=_sources(plan,('In Fulfilment',))
    _assert_complete(plan,sources)
    by_name={row.name:row for row in sources}
    if allocations is None:
        allocations=frappe.db.get_values('CFG Kanban Delivery Allocation',
            {'delivery_session':delivery.name,'state':['in',['Reserved','Delivery Pending']]},
            ['name','dispatch_allocation','handling_unit','item_code','batch_no','stock_uom','allocated_qty'],
            as_dict=True,for_update=True)
    seen=set()
    for row in allocations:
        source=by_name.get(row.dispatch_allocation)
        if (not source or source.name in seen or any((row.get(field) or '')!=(source.get(field) or '')
                for field in ('handling_unit','item_code','batch_no','stock_uom')) or
                abs(flt(row.allocated_qty)-flt(source.allocated_qty))>0.000001):
            frappe.throw('Warehouse delivery must retain every exact prepared allocation; release all and reset to change it')
        seen.add(source.name)
    if seen!=set(by_name):
        frappe.throw('Every prepared warehouse allocation is required before delivery confirmation')


def sync_warehouse_delivery(delivery):
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',delivery.dispatch_plan,for_update=True)
    if plan.delivery_session!=delivery.name:
        frappe.throw('Warehouse Plan is linked to a different Delivery Session')
    sources=_sources(plan,('In Fulfilment','Fulfilled'))
    if delivery.state=='Cancelled':
        for source in sources:
            frappe.db.set_value('CFG Kanban Dispatch Allocation',source.name,'state','Released',update_modified=False)
        for line in plan.lines:
            frappe.db.set_value('CFG Kanban Dispatch Plan Line',line.name,
                {'reserved_qty':0,'line_state':'Open'},update_modified=False)
        plan.db_set({'state':'Approved','delivery_session':None,'fulfilment_status':'Not Started',
            'total_reserved_qty':0,'total_delivered_qty':0,'delivery_note':None,'delivery_proof':None,
            'fulfilment_completed_on':None,'ready_on':None},update_modified=True)
        delivery.db_set('active_dispatch_plan_key',None,update_modified=False)
        return
    posted=delivery.state in ('Delivered','Invoiced','Closed')
    for source in sources:
        frappe.db.set_value('CFG Kanban Dispatch Allocation',source.name,
                           'state','Fulfilled' if posted else 'In Fulfilment',update_modified=False)
    amounts=frappe.db.get_values('CFG Kanban Delivery Allocation',
        {'delivery_session':delivery.name,'state':'Delivered'},['delivered_qty'],as_dict=True,for_update=True)
    status=('Completed' if delivery.state=='Closed' else 'Delivered' if posted else
            'Delivery Note Pending' if delivery.state=='ERP Document Pending' else
            'Exception' if delivery.state=='Exception' else 'In Progress')
    plan.db_set({'state':'Fulfilled' if delivery.state=='Closed' else 'Fulfilment In Progress',
        'fulfilment_status':status,'delivery_note':delivery.delivery_note,'delivery_proof':delivery.delivery_proof,
        'total_delivered_qty':sum(flt(row.delivered_qty) for row in amounts),
        'fulfilment_completed_on':delivery.completed_on if delivery.state=='Closed' else None},update_modified=True)
    for line in plan.lines:
        frappe.db.set_value('CFG Kanban Dispatch Plan Line',line.name,
            'line_state','Fulfilled' if posted else 'In Fulfilment',update_modified=False)

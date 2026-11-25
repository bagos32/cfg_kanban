"""Confirmed existing lorry stock uses normal Dispatch allocations, without a new ERP load."""
import json
import frappe
from frappe.utils import flt, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def confirm(plan,source_rows,operator,session,token,key):
    """Reserve through E2, then exchange those reservations for the normal loaded commitment."""
    planning=_planning()
    if plan.approval_required:
        planning.approve_dispatch_plan(plan.name,canonical_key(key,'approve'),token)
    for index,source in enumerate(source_rows):
        line=next(row for row in plan.lines if (row.get('sales_order_item') or None)==(source.get('sales_order_item') or None)
            and row.item_code==source['item_code'] and (not row.batch_no or row.batch_no==source.get('batch_no')))
        event=canonical_key(key,'reserve',index)
        if source.get('handling_unit'):
            planning.reserve_dispatch_tag(plan.name,line.name,source['scan_value'],source['qty'],event,token)
        else:
            planning.reserve_dispatch_untagged(plan.name,line.name,source['qty'],source.get('batch_no'),event,token)
    plan.reload()
    names=frappe.db.get_values('CFG Kanban Dispatch Allocation',{'dispatch_plan':plan.name,'state':'Reserved'},
        ['name'],as_dict=True,for_update=True,order_by='name')
    allocations=[frappe.get_doc('CFG Kanban Dispatch Allocation',r.name,for_update=True) for r in names]
    by_line={}
    for allocation in allocations:
        by_line[allocation.dispatch_plan_line]=by_line.get(allocation.dispatch_plan_line,0)+flt(allocation.allocated_qty)
    if set(by_line)!={line.name for line in plan.lines} or any(abs(by_line[line.name]-flt(line.requested_qty))>0.000001 for line in plan.lines):
        frappe.throw('Confirm exact existing stock for every follow-on Plan line')
    for allocation in allocations:
        if allocation.handling_unit:
            unit=frappe.get_doc('CFG Kanban Handling Unit',allocation.handling_unit,for_update=True)
            planning.post_quantity_event(event_type='Unreserve',qty=allocation.allocated_qty,stock_uom=allocation.stock_uom,
                source_handling_unit=unit.name,item_code=unit.item_code,batch_no=unit.batch_no,
                source_company=plan.company,source_warehouse=plan.source_warehouse,
                reference_doctype=allocation.doctype,reference_name=allocation.name,
                operator=operator.employee,operator_session=session.name,
                idempotency_key=canonical_key(key,'carry-in-unreserve',allocation.name),
                reason='Existing lorry stock confirmed; normal prepared delivery commitment now applies')
            unit.db_set('movement_state',allocation.movement_state_before_reservation or 'Received',update_modified=False)
        allocation.db_set(dict(state='Loaded',active_handling_unit_key=None,load_confirmed=1,
            loaded_by_operator=operator.employee,loaded_operator_session=session.name,loaded_on=now_datetime(),
            load_key=canonical_key(key,'physical-confirmation',allocation.name)),update_modified=True)
    for line in plan.lines:
        line.db_set(dict(loaded_qty=by_line[line.name],reserved_qty=0,line_state='Loaded'),update_modified=False)
    plan.db_set(dict(state='Loaded',total_reserved_qty=0,total_loaded_qty=sum(by_line.values()),loaded_on=now_datetime(),
        prepared_stock_commitment=int(plan.plan_type=='Customer Order'),route_stock_commitment=int(plan.plan_type=='Open Route Stock')),
        update_modified=True)
    recipe=[_allocation_receipt(row) for row in allocations]
    record('Follow-on Existing Lorry Stock Confirmed',reference_doctype=plan.doctype,reference_name=plan.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        idempotency_key=canonical_key(key,'confirmed'),payload=dict(allocations=recipe,
            notice='Confirmed existing ERP stock; no new loading Stock Entry or warehouse withdrawal'))
    return dict(plan=plan.name,allocations=recipe)


def validate_origin(trip,current=False):
    try:saved=json.loads(trip.follow_on_snapshot_json or '{}')
    except (TypeError,ValueError):frappe.throw('Reconcile the confirmed follow-on receipt before recovery')
    if (not isinstance(saved,dict) or saved.get('preparing') or not saved.get('confirmed_on') or
            not saved.get('request_hash') or saved.get('source_trip')!=trip.follow_on_of or
            saved.get('warehouse')!=trip.vehicle_warehouse or trip.follow_on_key!=trip.follow_on_of or
            not trip.follow_on_request_key):
        frappe.throw('This Trip has no completed immutable follow-on receipt')
    source=frappe.get_doc('CFG Kanban Delivery Trip',trip.follow_on_of,**({'for_update':True} if current else {}))
    source.check_permission('read')
    if (source.company!=trip.company or source.state not in ('Closed','Cancelled')
            or source.get('follow_on_trip')!=trip.name):
        frappe.throw('The original Trip must be closed through its controlled follow-on handover')
    return saved


def _allocation_receipt(row):
    return dict(name=row.name,line=row.dispatch_plan_line,item_code=row.item_code,batch_no=row.batch_no or None,
        handling_unit=row.handling_unit or None,stock_uom=row.stock_uom,qty=flt(row.allocated_qty),
        allocation_kind=row.allocation_kind,source_company=row.source_company,source_warehouse=row.source_warehouse,
        load_key=row.load_key)


def validate_loading(plan):
    trip=frappe.get_doc('CFG Kanban Delivery Trip',plan.follow_on_trip)
    trip.check_permission('read')
    saved=validate_origin(trip)
    if (plan.office_delivery_trip!=trip.name or plan.company!=trip.company or
            plan.vehicle_warehouse!=trip.vehicle_warehouse or plan.source_warehouse!=trip.vehicle_warehouse or
            plan.movement_manifest):
        frappe.throw('Follow-on existing-stock provenance does not match this Trip and lorry')
    approved=next((row for row in saved.get('plans',[]) if row['plan']==plan.name),None)
    if not approved:frappe.throw('This Plan is absent from the confirmed existing-stock receipt')
    rows=frappe.db.get_values('CFG Kanban Dispatch Allocation',{'dispatch_plan':plan.name},
        ['name','dispatch_plan_line','item_code','batch_no','handling_unit','stock_uom','allocated_qty',
         'load_confirmed','movement_manifest','allocation_kind','source_company','source_warehouse','load_key'],
        as_dict=True,order_by='name')
    if [_allocation_receipt(row) for row in rows]!=approved['allocations'] or any(not r.load_confirmed or r.movement_manifest for r in rows):
        frappe.throw('Follow-on loading allocations differ from their immutable physical confirmation')
    return trip


def validate_allocation(allocation):
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',allocation.dispatch_plan)
    if not plan.get('follow_on_trip'):frappe.throw('Loading confirmation requires a Movement Manifest')
    trip=validate_loading(plan)
    receipt=json.loads(trip.follow_on_snapshot_json)
    approved=next(r for p in receipt['plans'] if p['plan']==plan.name for r in p['allocations'] if r['name']==allocation.name)
    if allocation.is_new() or _allocation_receipt(allocation)!=approved or not allocation.load_confirmed or allocation.movement_manifest:
        frappe.throw('Follow-on allocation must retain its exact confirmed stock receipt')

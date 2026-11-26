"""Trip-end visibility over existing Plans, native stock and return/QC custody."""
import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.operator_auth import require_operator, public_operator

TRIP = 'CFG Kanban Delivery Trip'
PLAN = 'CFG Kanban Dispatch Plan'
CASE = 'CFG Kanban Return Case'


def _read(dt,name):
    doc=frappe.get_doc(dt,name)
    doc.check_permission('read')
    return doc


def _supervisor(operator):
    from cfg_kanban.services.route_reconciliation import _authorized
    return bool(operator.kanban_role in ('Supervisor','Development Proxy') and
                cint(operator.get('can_override')) and _authorized(operator))


def _trip(name,operator):
    from cfg_kanban.services.driver_routes import assigned
    doc=_read(TRIP,name)
    if not (_supervisor(operator) or assigned(doc,operator)):
        frappe.throw('This trip is not assigned to this operator',frappe.PermissionError)
    _read('Company',doc.company)
    return doc


def _plans(trip):
    return sorted(set([row.dispatch_plan for row in trip.dispatch_plans if row.dispatch_plan]
        + ([trip.open_route_plan] if trip.get('open_route_plan') else [])))


def _returns(trip,start=0):
    # Do not expose hidden Cases through a permissive stock/driver summary.
    if not frappe.has_permission(CASE,ptype='read'):
        return [],False
    names=frappe.get_list(CASE,filters=dict(driver_trip=trip.name,selling_company=trip.company),
        pluck='name',order_by='creation asc, name asc',limit_start=start,limit_page_length=21)
    if trip.get('follow_on_of') or trip.get('follow_on_trip'):
        from cfg_kanban.services.return_custody import cases
        names=[case.name for case in cases(trip)][start:start+21]
    result=[]
    for name in names[:20]:
        case=_read(CASE,name)
        result.append(dict(name=case.name,customer=case.customer,state=case.state,
            origin_trip=case.driver_trip,custody_trip=case.get('custody_trip') or case.driver_trip,current_vehicle=case.get('custody_vehicle_warehouse') or case.collection_vehicle_warehouse,
            received_on=case.received_on,inspection_location=case.inspection_location,
            accounting_status=case.accounting_status,disposition_status=case.disposition_status,
            stock_already_owned=bool(case.get('stock_already_owned')),
            items=[dict(item_code=row.item_code,batch_no=row.batch_no,stock_uom=row.stock_uom,
                claimed_qty=flt(row.claimed_qty),received_qty=flt(row.received_qty)) for row in case.lines]))
    return result,len(names)>20


@frappe.whitelist(methods=['POST'])
def start_handover_count(company,vehicle_warehouse,event_token,operator_session_token):
    """Native source permissions precede the unchanged D3 opening/authorization engine."""
    _read('Company',company)
    _read('Warehouse',vehicle_warehouse)
    from cfg_kanban.services.route_reconciliation import start_route_reconciliation
    return start_route_reconciliation(company,vehicle_warehouse,event_token,operator_session_token)


@frappe.whitelist()
def get_trip_handover(scan_value=None,operator_session_token=None,start=0,return_start=0,interactive=0):
    operator,session=require_operator(operator_session_token,touch_activity=bool(cint(interactive)))
    manage=_supervisor(operator)
    start=max(0,cint(start));return_start=max(0,cint(return_start))
    identity=public_operator(operator,session)
    result=dict(operator={key:identity.get(key) for key in ('employee','employee_name','kanban_role')},
        can_manage=manage,can_start=bool(manage and operator.get('can_start')),
        can_complete=bool(manage and operator.get('can_complete')),trip=None,plans=[],returns=[],
        trips=[],has_more=False,return_has_more=False,start=start,return_start=return_start,refreshed_on=now_datetime())
    if not scan_value:
        filters=dict(state=['in',['Draft','Planned']]);choices={}
        if not manage:
            assistants=frappe.get_all('CFG Kanban Trip Assistant',filters=dict(employee=operator.employee,
                parenttype=TRIP,parentfield='assistant_drivers'),pluck='parent',limit_page_length=0)
            if assistants:choices['or_filters']={'driver':operator.employee,'name':['in',assistants]}
            else:filters['driver']=operator.employee
        names=frappe.get_list(TRIP,filters=filters,pluck='name',order_by='trip_date asc, name asc',
            limit_start=start,limit_page_length=11,**choices)
        for name in names[:10]:
            trip=_trip(name,operator)
            result['trips'].append(dict(name=trip.name,title=trip.trip_title,company=trip.company,state=trip.state))
        result['has_more']=len(names)>10
        return result
    value=str(scan_value).strip()
    if frappe.db.exists('CFG Kanban Dispatch Review',value):
        value=_read('CFG Kanban Dispatch Review',value).dispatch_plan
    standalone=None
    if frappe.db.exists(PLAN,value):
        standalone=_read(PLAN,value)
        if standalone.get('office_delivery_trip'):
            value=standalone.office_delivery_trip
        elif not manage:
            frappe.throw('A standalone Plan handover requires an authorized Supervisor',frappe.PermissionError)
    trip=_trip(value,operator) if not standalone or value!=standalone.name else None
    if trip:
        from cfg_kanban.services.driver_routes import trip_vehicle_warehouse,trip_driver_display
        warehouse=trip_vehicle_warehouse(trip)
        result['trip']=dict(name=trip.name,title=trip.trip_title,company=trip.company,state=trip.state,
            vehicle_warehouse=warehouse,driver=trip_driver_display(trip),driver_route_state=trip.driver_route_state,
            assistants=[dict(employee=row.employee,employee_name=row.employee_name) for row in trip.get('assistant_drivers') or []])
        plan_names=_plans(trip);company=trip.company
        if standalone and standalone.name not in plan_names:
            frappe.throw('The scanned Plan is not a member of this saved Trip')
        result['returns'],result['return_has_more']=_returns(trip,return_start)
    else:
        company=standalone.company;warehouse=standalone.vehicle_warehouse;plan_names=[standalone.name]
        _read('Company',company)
    if warehouse:
        _read('Warehouse',warehouse)
    from cfg_kanban.services import dispatch_reconciliation as review_service
    from cfg_kanban.services.dispatch_recovery_mixed import context as mixed_context
    for name in plan_names:
        plan=_read(PLAN,name)
        if plan.company!=company or (warehouse and plan.vehicle_warehouse and plan.vehicle_warehouse!=warehouse):
            frappe.throw('A linked Plan differs from the Trip Company or lorry; reconcile its assignment')
        balances=review_service._balances(plan) if plan.state in ('Loaded','Reconciled') else []
        balance_hash=review_service._hash(balances)
        for row in balances:
            _read('Item',row['item_code'])
            if row.get('batch_no'):_read('Batch',row['batch_no'])
            if row['handling_unit']:_read('CFG Kanban Handling Unit',row['handling_unit'])
            row['refused_qty']=0
            if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
                from cfg_kanban.services.driver_delivery_outcomes import declared_source_qty
                row['refused_qty']=declared_source_qty(row['dispatch_allocation'])
        review=_read(review_service.REVIEW,plan.active_dispatch_review) if plan.get('active_dispatch_review') else None
        result['plans'].append(dict(name=plan.name,customer=plan.customer,state=plan.state,
            review=review.name if review else None,review_state=review.state if review else None,
            balances=balances,balance_hash=balance_hash,
            mixed_recovery=mixed_context(plan,review) if review else None))
    from cfg_kanban.services.route_reconciliation import _erp_balances
    result['lorry_stock']=[]
    for (item,batch),qty in (_erp_balances(company,warehouse,now_datetime()).items() if warehouse else []):
        source=_read('Item',item)
        if batch:_read('Batch',batch)
        result['lorry_stock'].append(dict(item_code=item,batch_no=batch,qty=qty,stock_uom=source.stock_uom))
    result['boundary']='Remaining prepared quantities include held refusals. Old customer returns are separate non-stock custody. Native stock and QC services confirm physical handover; this screen creates no stock receipt or credit.'
    return result

"""Operational custody of undelivered goods; native E5 owns physical recovery and ERP stock."""
import frappe
from frappe.utils import flt,now_datetime
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event

STOCK='CFG Kanban Cancelled Stop Stock'
REQUEST='CFG Kanban Route Change Request'
HOLD='Keep Reserved for Return'
RELEASE='Release for Same-trip Sale'
HELD='Held for Return'
RELEASED='Released for Sale'
RECOVERY='Recovery Reserved'
RECOVERED='Recovered'
EPS=0.000001


def rows(filters=None,current=False):
    if not frappe.db.table_exists(STOCK):return []
    query=dict(filters or {},parenttype=REQUEST,parentfield='cancelled_stock')
    data=frappe.db.get_values(STOCK,query,['name'],as_dict=True,for_update=current,order_by='name')
    return [frappe.get_doc(STOCK,row.name,**({'for_update':True} if current else {})) for row in data]


def _ledger(row,kind,key,operator=None,session=None,warehouse=None):
    if not row.handling_unit:return None
    result=post_quantity_event(event_type=kind,qty=row.qty,stock_uom=row.stock_uom,
        idempotency_key=canonical_key('cancelled-stop-custody',row.name,kind,key),
        source_handling_unit=row.handling_unit,item_code=row.item_code,batch_no=row.batch_no,
        source_company=row.company,source_warehouse=warehouse or row.current_warehouse,
        reference_doctype=REQUEST,reference_name=row.parent,operator=operator,
        operator_session=session,reason='Undelivered stock from a Supervisor-cancelled customer stop')
    return result.name


def install(request,lines,disposition,operator,session):
    request.set('cancelled_stock',[dict(row,stock_state=HELD if disposition==HOLD else RELEASED,
        current_warehouse=row['original_warehouse']) for row in lines])
    request.flags.cfg_trip_route_change=True;request.save(ignore_permissions=True)
    if disposition==HOLD:
        for row in request.cancelled_stock:
            ledger=_ledger(row,'Reserve',request.name,operator.employee,session.name)
            if ledger:row.db_set('hold_ledger',ledger,update_modified=False)


def released_source_qty(source,current=False):
    return sum(flt(row.qty) for row in rows({'dispatch_allocation':source,'stock_state':RELEASED},current))


def held_tag_qty(unit,current=False,dispatch_plan=None,parent=None):
    filters={'handling_unit':unit,'stock_state':HELD}
    if dispatch_plan:filters['dispatch_plan']=dispatch_plan
    if parent:filters['parent']=parent
    return sum(flt(row.qty) for row in rows(filters,current))


def assert_held_tag_unload(unit,token):
    """A Supervisor may detach a whole physical tag; its return hold stays intact."""
    from cfg_kanban.services.operator_auth import require_operator
    from cfg_kanban.services.trip_sequence import _supervisor
    if not token:frappe.throw('A Supervisor operator session is required to unload cancelled stock')
    operator,_session=require_operator(token,action='start');_supervisor(operator)
    held=rows({'handling_unit':unit.name,'stock_state':HELD},True)
    if (len(held)!=1 or unit.get('virtual_content') or
            abs(flt(held[0].qty)-flt(unit.current_qty))>EPS or
            abs(flt(unit.reserved_qty)-flt(unit.current_qty))>EPS or abs(flt(unit.available_qty))>EPS):
        frappe.throw('Only the whole physical Stock Tag held for an approved cancelled stop can be unloaded')
    row=held[0]
    decision=frappe.get_doc(REQUEST,row.parent);decision.check_permission('read')
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',row.dispatch_plan);plan.check_permission('read')
    for dt,name in (('Company',row.company),('Warehouse',row.current_warehouse)):
        frappe.get_doc(dt,name).check_permission('read')
    if plan.get('consolidated_customer_orders'):
        from cfg_kanban.services.consolidated_dispatch import scoped
        plan=scoped(plan,decision.target_stop_key)
    if (decision.state!='Approved' or decision.request_type!='Cancel Customer Stop' or
            plan.get('stop_cancellation')!=row.parent or plan.state!='Loaded' or
            not plan.prepared_stock_commitment or row.company!=unit.inventory_company or
            row.current_warehouse!=unit.current_warehouse):
        frappe.throw('Cancelled-stock custody changed; use the active controlled recovery')


def assert_review_action(plan,action):
    if not plan.get('stop_cancellation') and not plan.get('consolidated_customer_orders'):return
    outstanding=rows({'dispatch_plan':plan.name,'stock_state':['in',[HELD,RECOVERY]]},True)
    if outstanding and action not in ('Continue Same Plan Overnight','Returned to Warehouse','Transferred to Another Lorry','Mixed Leftover Dispositions'):
        frappe.throw('Cancelled customer goods are reserved for return; complete their controlled recovery or continue the same Plan overnight')


def lock_recovery_rows(manifest):
    from cfg_kanban.services.dispatch_planning import _lock_erp_bin
    for item in sorted({r.item_code for r in manifest.lines}):_lock_erp_bin(item,manifest.source_warehouse)
    for line in sorted(manifest.lines,key=lambda row:row.dispatch_allocation):
        rows({'dispatch_allocation':line.dispatch_allocation,'stock_state':['in',[HELD,RECOVERY]]},True)


def recovery_adopt(manifest):
    for line in manifest.lines:
        for row in rows({'dispatch_allocation':line.dispatch_allocation,'stock_state':HELD},True):
            if (abs(flt(row.qty)-flt(line.dispatch_qty))>EPS or row.company!=manifest.source_company
                    or row.current_warehouse!=manifest.source_warehouse):
                frappe.throw('Cancelled-stock recovery must retain the exact held source and quantity')
            _ledger(row,'Unreserve',manifest.name)
            row.db_set(dict(stock_state=RECOVERY,recovery_manifest=manifest.name),update_modified=False)


def recovery_restore(manifest,received=False):
    for row in rows({'recovery_manifest':manifest.name,'stock_state':RECOVERY},True):
        if received:
            row.db_set(dict(stock_state=RECOVERED,current_warehouse=manifest.destination_warehouse,
                recovered_on=now_datetime()),update_modified=False)
        else:
            _ledger(row,'Reserve',manifest.name+':cancelled')
            row.db_set(dict(stock_state=HELD,current_warehouse=manifest.source_warehouse,
                recovery_manifest=None),update_modified=False)


def assert_loose_movement(item,warehouse,qty,manifest=None):
    """No-tag movements cannot silently use cancelled goods committed for return."""
    if not frappe.db.table_exists(STOCK):return
    from cfg_kanban.services.dispatch_planning import _lock_erp_bin
    _lock_erp_bin(item,warehouse)
    held=rows({'item_code':item,'current_warehouse':warehouse,'stock_state':['in',[HELD,RECOVERY]]},True)
    if not held:return
    excluded=None
    if manifest and manifest.get('dispatch_recovery_review'):
        review=frappe.get_doc('CFG Kanban Dispatch Review',manifest.dispatch_recovery_review)
        allowed=review.recovery_manifest==manifest.name
        if manifest.get('recovery_bundle_key'):
            from cfg_kanban.services.dispatch_recovery_mixed import belongs
            allowed=belongs(review,manifest)
        if not allowed:frappe.throw('Recovery does not match its controlled Dispatch Review')
        excluded=review.dispatch_plan
    protected={}
    for row in held:
        if row.dispatch_plan==excluded:continue
        batch=row.batch_no or ''
        protected[batch]=protected.get(batch,0)+flt(row.qty)
    if not any(qty>EPS for qty in protected.values()):return
    wanted={}
    for line in (manifest.lines if manifest else []):
        if line.item_code!=item:continue
        batch=line.batch_no or ''
        wanted[batch]=wanted.get(batch,0)+flt(line.dispatch_qty)
    if not manifest:wanted['']=flt(qty)
    if any(protected) or any(wanted):
        from cfg_kanban.services.route_reconciliation import _erp_balances
        actual=_erp_balances(held[0].company,warehouse,now_datetime(),current=True)
        available=lambda batch:flt(actual.get((item,batch)))
    else:
        balance=flt(frappe.db.get_value('Bin',{'item_code':item,'warehouse':warehouse},'actual_qty',for_update=True))
        available=lambda batch:balance
    if any(amount+protected.get(batch,0)>available(batch)+EPS for batch,amount in wanted.items()):
        frappe.throw('This movement would use cancelled customer stock reserved for return; use its controlled Dispatch Recovery')

"""E5A: immutable Dispatch Plan reviews over D3 counts and existing ERP movement evidence.

No inventory or ERP posting is performed here. A review freezes new fulfilment while
D3 counts and the existing movement services establish what physically remains.
"""
import json

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator


REVIEW = 'CFG Kanban Dispatch Review'
ACTIONS = ('No Remaining Prepared Stock', 'Close Trip - Stock Stays', 'Continue Same Plan Overnight',
           'Returned to Warehouse', 'Transferred to Another Lorry')
EPSILON = 0.000001


class DispatchReviewReplayError(Exception):
    """Recorded action identity cannot be reused for different review details."""


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _counts():
    from cfg_kanban.services import route_reconciliation
    return route_reconciliation


def _fulfilment():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _authorized(token, permission=None):
    operator, session = require_operator(token, permission) if permission else require_operator(token)
    _counts()._require_authorized(operator)
    return operator, session


def _supervisor(operator):
    if operator.kanban_role not in ('Supervisor', 'Development Proxy') or not cint(operator.get('can_override')):
        frappe.throw('A Supervisor with Override permission must authorize this leftover-stock decision')


def _plan(name, operator, current=False):
    plan = frappe.get_doc('CFG Kanban Dispatch Plan', name, for_update=current)
    _planning()._assert_plan_authorized(plan, operator)
    ready=plan.state in ('Loaded','Reconciled')
    if plan.get('existing_lorry_stock_only'):
        from cfg_kanban.services.trip_dispatch import route_ready
        ready=ready or route_ready(plan)
    if plan.fulfilment_mode != 'Vehicle Delivery' or not ready:
        frappe.throw('Dispatch review requires a loaded Vehicle Delivery Plan')
    return plan


def _no_open_delivery(plan):
    rows = frappe.db.get_values('CFG Kanban Delivery Session',
        {'dispatch_plan': plan.name, 'state': ['not in', ['Closed', 'Cancelled']]}, ['name'],
        as_dict=True, for_update=True)
    if rows or plan.get('active_route_stop'):
        frappe.throw('Complete proof or release/cancel every unfinished Delivery Session before reviewing this Plan')


def _balances(plan, current=False):
    sources = _fulfilment()._loaded_allocations(plan, for_update=current)
    rows = []
    for source in sources:
        allocations = frappe.db.get_values('CFG Kanban Delivery Allocation',
            {'dispatch_allocation': source.name, 'state': 'Delivered'}, ['delivered_qty'],
            as_dict=True, for_update=current)
        delivered = sum(flt(row.delivered_qty) for row in allocations)
        released = 0
        if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
            from cfg_kanban.services.driver_delivery_outcomes import released_source_qty
            released = released_source_qty(source.name, current=current)
        cancelled_released=0
        if plan.get('stop_cancellation'):
            from cfg_kanban.services.cancelled_stop_stock import released_source_qty as cancelled_release
            cancelled_released=cancelled_release(source.name,current)
        remaining = flt(source.allocated_qty) - delivered - released - cancelled_released
        if remaining < -EPSILON or delivered < -EPSILON:
            frappe.throw('Prepared delivery totals exceed their loading allocation; investigate before settlement')
        row = dict(cancelled_released_qty=cancelled_released,refused_released_qty=released, dispatch_allocation=source.name, item_code=source.item_code,
            batch_no=source.batch_no, stock_uom=source.stock_uom, handling_unit=source.handling_unit,
            loaded_qty=flt(source.allocated_qty), delivered_qty=delivered, remaining_qty=max(remaining, 0))
        if source.handling_unit:
            unit = frappe.get_doc('CFG Kanban Handling Unit', source.handling_unit, for_update=current)
            row.update(visible_code=unit.handling_unit_id, current_qty=flt(unit.current_qty),
                reserved_qty=flt(unit.reserved_qty), current_warehouse=unit.current_warehouse,
                current_company=unit.inventory_company, current_item=unit.item_code,
                current_batch=unit.batch_no, current_uom=unit.stock_uom)
        rows.append(row)
    return rows


def _hash(rows):
    return canonical_key('dispatch-review-balances', _json(rows))


def _current_context(plan, review=None):
    balances = _balances(plan)
    quantities = {}
    for row in balances:
        group = quantities.setdefault(row['stock_uom'], dict(loaded=0, delivered=0, remaining=0))
        for total, source in (('loaded','loaded_qty'),('delivered','delivered_qty'),('remaining','remaining_qty')):
            group[total] += row[source]
    sessions=frappe.db.get_values('CFG Kanban Delivery Session',{'dispatch_plan':plan.name},['name'],as_dict=True)
    unassigned=[]
    if sessions:
        for allocation in frappe.db.get_values('CFG Kanban Delivery Allocation',{
                'delivery_session':['in',[row.name for row in sessions]],'state':'Delivered',
                'route_source_kind':'Unassigned Lorry Stock'},
                ['item_code','batch_no','stock_uom','delivered_qty'],as_dict=True):
            unassigned.append(dict(allocation))
    lorry_balances=[]
    for (item,batch),qty in _counts()._erp_balances(plan.company,plan.vehicle_warehouse,now_datetime()).items():
        prepared=sum(row['remaining_qty'] for row in balances if row['item_code']==item and (row['batch_no'] or '')==batch)
        uom=next((row['stock_uom'] for row in balances if row['item_code']==item),None) or frappe.db.get_value('Item',item,'stock_uom')
        lorry_balances.append(dict(item_code=item,batch_no=batch,stock_uom=uom,erp_qty=qty,
            prepared_remaining_budget=prepared))
    recovery = frappe.db.get_value('CFG Kanban Movement Manifest', review.recovery_manifest,
        ['name','state','dispatch_stock_entry','recovery_action'], as_dict=True) if review and review.get('recovery_manifest') else None
    mixed = None
    if review and review.get('mixed_recovery_json'):
        from cfg_kanban.services.dispatch_recovery_mixed import context
        mixed = context(plan, review)
    return dict(plan=plan.as_dict(), review=review.as_dict() if review else None, recovery=recovery,
                mixed_recovery=mixed,
                lorry_balances=lorry_balances,
                unassigned_deliveries=unassigned,
                balances=balances, balance_hash=_hash(balances), quantity_totals=quantities,
                actions=list(ACTIONS) + (['Mixed Leftover Dispositions'] if mixed and mixed['active'] else []),
                boundary='The route stock count covers all lorry stock, including other Plans and unassigned stock. This review settles only this Plan.')


@frappe.whitelist()
def get_dispatch_review_context(scan_value, operator_session_token):
    operator, _session = _authorized(operator_session_token)
    value = str(scan_value or '').strip()
    if frappe.db.exists(REVIEW, value):
        review = frappe.get_doc(REVIEW, value)
        plan = _plan(review.dispatch_plan, operator)
    else:
        plan = _plan(value, operator)
        review = frappe.get_doc(REVIEW, plan.active_dispatch_review) if plan.get('active_dispatch_review') else None
    return _current_context(plan, review)


@frappe.whitelist()
def begin_dispatch_review(dispatch_plan, event_token, operator_session_token):
    _planning()._require_event_token(event_token)
    operator, session = _authorized(operator_session_token, 'start')
    plan = _plan(dispatch_plan, operator, current=True)
    key = canonical_key('dispatch-review-open', plan.name, event_token)
    old = frappe.db.get_value(REVIEW, {'idempotency_key': key}, 'name', for_update=True)
    if old:
        return _current_context(plan, frappe.get_doc(REVIEW, old))
    if plan.get('active_dispatch_review'):
        return _current_context(plan, frappe.get_doc(REVIEW, plan.active_dispatch_review))
    if plan.state == 'Reconciled':
        frappe.throw('This Dispatch Plan is already reconciled')
    _counts()._validate_vehicle_warehouse(plan.company, plan.vehicle_warehouse)
    _no_open_delivery(plan)
    snapshot = _balances(plan, current=True)
    review = frappe.get_doc(dict(doctype=REVIEW, state='Reviewing', dispatch_plan=plan.name,
        company=plan.company, vehicle_warehouse=plan.vehicle_warehouse, vehicle_reference=plan.vehicle_reference,
        opened_on=now_datetime(), opened_by_operator=operator.employee, operator_session=session.name,
        idempotency_key=key, active_plan_key=plan.name, opening_snapshot_json=_json(snapshot),
        opening_snapshot_hash=_hash(snapshot))).insert(ignore_permissions=True)
    plan.db_set(dict(active_dispatch_review=review.name, dispatch_review_state='Reviewing'), update_modified=True)
    record('Dispatch Review Started', reference_doctype=REVIEW, reference_name=review.name,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        device_id=key, notes=f'{plan.name}; new fulfilment frozen; stock unchanged')
    return _current_context(plan, review)


def _locked_review(name, operator):
    link = frappe.db.get_value(REVIEW, name, 'dispatch_plan')
    if not link:
        frappe.throw('Dispatch Review was not found')
    plan = _plan(link, operator, current=True)
    review = frappe.get_doc(REVIEW, name, for_update=True)
    if review.dispatch_plan != plan.name or review.company != plan.company or review.vehicle_warehouse != plan.vehicle_warehouse:
        frappe.throw('Dispatch Review no longer matches its original Plan and lorry')
    return plan, review


def _count_evidence(plan, review, name):
    if not name:
        frappe.throw('Select a closed balanced D3 Route Reconciliation for this lorry')
    doc = frappe.get_doc('CFG Kanban Route Reconciliation', name, for_update=True)
    if (doc.state != 'Closed' or doc.company != plan.company or doc.vehicle_warehouse != plan.vehicle_warehouse
            or not doc.closed_on or get_datetime(doc.closed_on) < get_datetime(review.opened_on)):
        frappe.throw('Route count must be closed for this Company/lorry after the Dispatch Review began')
    if any(abs(flt(row.variance_qty)) > EPSILON for row in doc.lines):
        frappe.throw('Route count contains an unresolved variance')
    _counts()._assert_no_open_vehicle_work(doc)
    # Current locking SLE reads prevent a prior transaction snapshot from certifying old stock.
    frappe.db.sql('select name from `tabBin` where warehouse=%s order by name for update', plan.vehicle_warehouse)
    _counts()._validate_scan_snapshot(doc)
    expected = {(row.item_code, row.batch_no or ''): flt(row.expected_closing_qty)
                for row in doc.lines if abs(flt(row.expected_closing_qty))>EPSILON}
    actual = _counts()._erp_balances(plan.company, plan.vehicle_warehouse, now_datetime(), current=True)
    if set(expected) != set(actual) or any(abs(expected[key]-actual[key])>EPSILON for key in expected):
        frappe.throw('ERP stock changed after the closed count; create and close a fresh D3 count')
    return doc


def _at_source(plan, rows,current=False):
    for row in rows:
        if row['remaining_qty']<=EPSILON or not row['handling_unit']:
            continue
        if (row['current_company']!=plan.company or row['current_warehouse']!=plan.vehicle_warehouse
                or row['current_item']!=row['item_code'] or (row['current_batch'] or '')!=(row['batch_no'] or '')
                or row['current_uom']!=row['stock_uom'] or row['reserved_qty']>_refusal_reserve(plan,row)+EPSILON
                or abs(row['current_qty']-row['remaining_qty'])>EPSILON):
            frappe.throw('Remaining prepared Stock Tag moved, changed or is reserved; reconcile its movement first')
    groups = {}
    for row in rows:
        if not row['handling_unit'] and row['remaining_qty']>EPSILON:
            key=(row['item_code'],row['batch_no'] or '')
            groups[key]=groups.get(key,0)+row['remaining_qty']
    for (item,batch),qty in groups.items():
        available = _planning()._untagged_available(plan.company, plan.vehicle_warehouse, item, batch or None,
                                                    exclude_prepared_plan=plan.name,current=current,
                                                    **({'exclude_refusal_outcome':plan.driver_delivery_outcome} if plan.get('driver_delivery_outcome') else {}))
        if qty>available+EPSILON:
            frappe.throw('Prepared loose stock is missing or committed elsewhere; resolve the variance or movement')


def _movement_evidence(plan, review, rows, name, action, count):
    if not name:
        frappe.throw('A submitted Stock Entry is required for returned or transferred leftovers')
    entry=frappe.get_doc('Stock Entry',name,for_update=True)
    if (entry.docstatus!=1 or entry.company!=plan.company or
            (entry.get('purpose') or entry.get('stock_entry_type'))!='Material Transfer'):
        frappe.throw('Movement evidence must be a submitted same-Company Material Transfer')
    manifest_name=entry.get('cfg_movement_manifest')
    linked_review=frappe.db.get_value('CFG Kanban Movement Manifest',manifest_name,'dispatch_recovery_review') if manifest_name else None
    if linked_review and linked_review!=review.name:
        frappe.throw('This controlled movement belongs to another Dispatch Review and cannot settle this Plan')
    # SLE creation supplies submission chronology. Tags additionally require the completed
    # controlled Manifest, so native stock and the operational tag ledger agree.
    expected={}
    for row in rows:
        if row['remaining_qty']>EPSILON:
            key=(row['handling_unit'] or '',row['item_code'],row['batch_no'] or '',row['stock_uom'])
            expected[key]=expected.get(key,0)+row['remaining_qty']
    actual={};destinations=set()
    for item in entry.items:
        if item.s_warehouse!=plan.vehicle_warehouse:
            continue
        key=(item.get('cfg_handling_unit') or '',item.item_code,item.batch_no or '',item.stock_uom or item.uom)
        if key in expected:
            if not item.t_warehouse or item.t_warehouse==plan.vehicle_warehouse:
                frappe.throw('Recovery movement requires another destination Warehouse')
            destinations.add(item.t_warehouse)
            actual[key]=actual.get(key,0)+flt(item.transfer_qty or item.stock_qty or item.qty)
    if set(actual)!=set(expected) or any(abs(actual[key]-expected[key])>EPSILON for key in expected):
        frappe.throw('Submitted movement must cover every exact remaining prepared tag/Item/Batch/stock-UOM quantity')
    if len(destinations)!=1:
        frappe.throw('Use one exact destination for this review movement')
    destination=next(iter(destinations))
    warehouse=frappe.db.get_value('Warehouse',destination,['company','disabled','is_group','cfg_is_vehicle_warehouse'],as_dict=True)
    if not warehouse or warehouse.company!=plan.company or warehouse.disabled or warehouse.is_group:
        frappe.throw('Recovery destination must be an active leaf Warehouse in this Company')
    if action=='Transferred to Another Lorry':
        _counts()._validate_vehicle_warehouse(plan.company,destination)
    elif warehouse.cfg_is_vehicle_warehouse:
        frappe.throw('Select Transferred to Another Lorry for a vehicle Warehouse')
    # A movement cannot be reused to explain two Plans' loose quantities.
    used=frappe.db.get_value(REVIEW,{'movement_stock_entry':name,'state':'Completed'},'name',for_update=True)
    if used and used!=review.name:
        frappe.throw('This Stock Entry already settled another Dispatch Review')
    entries=frappe.db.get_values('Stock Ledger Entry',
        {'voucher_type':'Stock Entry','voucher_no':entry.name,'warehouse':plan.vehicle_warehouse},
        ['creation'],as_dict=True,for_update=True)
    if not entries or any(get_datetime(row.creation)<get_datetime(review.opened_on) for row in entries):
        frappe.throw('Recovery Stock Entry must post after this Dispatch Review began')
    if any(get_datetime(row.creation)>get_datetime(count.closed_on) for row in entries):
        frappe.throw('Close a fresh route count after the recovery movement is submitted')
    if not entry.get('posting_date'):
        frappe.throw('Recovery Stock Entry posting date is required')
    posted=get_datetime(str(entry.posting_date)+' '+str(entry.get('posting_time') or '00:00:00'))
    if posted>get_datetime(count.closed_on):
        frappe.throw('Recovery posting time is later than the closed count; close a fresh count after posting')
    tagged=[row for row in rows if row['handling_unit'] and row['remaining_qty']>EPSILON]
    if tagged:
        manifest_name=entry.get('cfg_movement_manifest')
        manifest=frappe.get_doc('CFG Kanban Movement Manifest',manifest_name,for_update=True) if manifest_name else None
        if (not manifest or manifest.state!='Received' or manifest.dispatch_stock_entry!=entry.name
                or manifest.source_company!=plan.company or manifest.destination_company!=plan.company
                or manifest.source_warehouse!=plan.vehicle_warehouse or manifest.destination_warehouse!=destination):
            frappe.throw('Tagged recovery requires its completed controlled Movement Manifest and tag ledger')
        for row in tagged:
            if (row['current_company']!=plan.company or row['current_warehouse']!=destination
                    or row['current_item']!=row['item_code'] or (row['current_batch'] or '')!=(row['batch_no'] or '')
                    or row['current_uom']!=row['stock_uom']
                    or abs(row['current_qty']-row['remaining_qty'])>EPSILON or row['reserved_qty']>_refusal_reserve(plan,row)+EPSILON):
                frappe.throw('Transferred tag quantity/location changed; inspect the recovery before settlement')
    return destination


@frappe.whitelist()
def finish_dispatch_review(dispatch_review, action, reconciliation_name, reason, event_token,
                           operator_session_token, movement_stock_entry=None, balance_hash=None):
    _planning()._require_event_token(event_token)
    operator,session=_authorized(operator_session_token,'complete')
    plan,review=_locked_review(dispatch_review,operator)
    reason=str(reason or '').strip()
    key=canonical_key('dispatch-review-finish',review.name,event_token)
    fingerprint=canonical_key('dispatch-review-finish-payload',action,reconciliation_name,reason,
                              movement_stock_entry or '',balance_hash or '')
    if review.get('finish_key')==key:
        if review.finish_payload_hash!=fingerprint:
            frappe.throw('This review token belongs to different closing details',DispatchReviewReplayError)
        return _current_context(plan,review)
    if review.state not in ('Reviewing','Held') or plan.active_dispatch_review!=review.name:
        frappe.throw('Only the active Dispatch Review can be completed')
    if action not in ACTIONS + ('Mixed Leftover Dispositions',) or not reason:
        frappe.throw('Choose a valid leftover-stock action and provide its reason')
    _no_open_delivery(plan)
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import assert_review_action
        assert_review_action(plan,action)
    rows=_balances(plan,current=True)
    if not balance_hash or _hash(rows)!=balance_hash:
        frappe.throw('Dispatch balances changed; refresh and review the current quantities before closing')
    remaining=any(row['remaining_qty']>EPSILON for row in rows)
    if remaining or review.state=='Held':
        _supervisor(operator)
    if action=='No Remaining Prepared Stock' and remaining:
        frappe.throw('Prepared stock remains; select its actual disposition')
    if action!='No Remaining Prepared Stock' and not remaining:
        frappe.throw('No prepared stock remains; use No Remaining Prepared Stock')
    if review.get('recovery_manifest') or review.get('mixed_recovery_json'):
        from cfg_kanban.services.dispatch_recovery import assert_review_disposition
        assert_review_disposition(review, action, movement_stock_entry)
    count=_count_evidence(plan,review,reconciliation_name)
    destination=None
    if action == 'Mixed Leftover Dispositions':
        from cfg_kanban.services.dispatch_recovery_mixed import settle
        settle(plan, review, rows, count)
    elif action in ('Returned to Warehouse','Transferred to Another Lorry'):
        destination=_movement_evidence(plan,review,rows,movement_stock_entry,action,count)
    else:
        if movement_stock_entry:
            frappe.throw('A stock-stays/overnight decision cannot use a transfer as its evidence')
        _at_source(plan,rows)
    overnight=action=='Continue Same Plan Overnight'
    values=dict(state='Overnight' if overnight else 'Completed',action=action,reason=reason,
        route_reconciliation=count.name,movement_stock_entry=movement_stock_entry,
        destination_warehouse=destination,closed_on=now_datetime(),closed_by_operator=operator.employee,
        closing_snapshot_json=_json(rows),closing_snapshot_hash=_hash(rows),active_plan_key=None,
        finish_key=key,finish_payload_hash=fingerprint)
    review.db_set(values,update_modified=True)
    plan_values=dict(dispatch_review_state='Overnight' if overnight else 'Settled',
                     active_dispatch_review=review.name)
    if not overnight:
        plan_values.update(state='Reconciled',route_stock_commitment=0,prepared_stock_commitment=0,
            fulfilment_status='Closed Incomplete' if remaining else 'Completed',
            fulfilment_completed_on=values['closed_on'])
        # Preserve every planned visit as an explicit unvisited/closed-trip audit entry.
        for stop in frappe.db.get_values('CFG Kanban Route Stop',{'dispatch_plan':plan.name,'state':'Planned'},
                ['name'],as_dict=True,for_update=True):
            frappe.db.set_value('CFG Kanban Route Stop',stop.name,dict(state='Skipped',skip_reason=reason,
                skipped_by=operator.employee,skipped_on=values['closed_on']),update_modified=True)
    plan.db_set(plan_values,update_modified=True)
    _resolve_hold(review,reason)
    record('Dispatch Plan Overnight' if overnight else 'Dispatch Plan Reconciled',
        reference_doctype=REVIEW,reference_name=review.name,route_reconciliation=count.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        device_id=key,notes=f'{plan.name}; {action}; {reason}')
    return _current_context(plan,review)


def _resolve_hold(review,reason):
    if review.get('variance_exception'):
        frappe.db.set_value('CFG Kanban Exception',review.variance_exception,
            dict(status='Resolved',resolved_on=now_datetime(),resolved_by=frappe.session.user,resolution=reason),
            update_modified=True)


@frappe.whitelist()
def hold_dispatch_review(dispatch_review, reason, event_token, operator_session_token):
    _planning()._require_event_token(event_token)
    operator,session=_authorized(operator_session_token,'complete');_supervisor(operator)
    plan,review=_locked_review(dispatch_review,operator)
    reason=str(reason or '').strip()
    key=canonical_key('dispatch-review-hold',review.name,event_token)
    if review.get('hold_key')==key:
        if review.reason!=reason:
            frappe.throw('This hold token belongs to another reason',DispatchReviewReplayError)
        return _current_context(plan,review)
    if review.state not in ('Reviewing','Held') or not reason:
        frappe.throw('Only an active review can be held, with a reason')
    if review.state=='Held':
        frappe.throw('This review is already held; retain its original reason or complete its counted recovery')
    exception=frappe.get_doc(dict(doctype='CFG Kanban Exception',exception_type='Dispatch Review Variance',
        severity='Critical',status='Open',reference_doctype=REVIEW,reference_name=review.name,
        message=f'{plan.name}: {reason}',raised_on=now_datetime())).insert(ignore_permissions=True)
    review.db_set(dict(state='Held',reason=reason,hold_key=key,variance_exception=exception.name),update_modified=True)
    plan.db_set('dispatch_review_state','Held',update_modified=True)
    record('Dispatch Review Held',reference_doctype=REVIEW,reference_name=review.name,device_id=key,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,notes=reason)
    return _current_context(plan,review)


@frappe.whitelist()
def resume_dispatch_review(dispatch_review, reason, event_token, operator_session_token):
    _planning()._require_event_token(event_token)
    operator,session=_authorized(operator_session_token,'complete')
    plan,review=_locked_review(dispatch_review,operator)
    reason=str(reason or '').strip()
    key=canonical_key('dispatch-review-resume',review.name,event_token)
    if review.get('resume_key')==key:
        if review.resume_reason!=reason:
            frappe.throw('This resume token belongs to another reason',DispatchReviewReplayError)
        return _current_context(plan,review)
    if review.state not in ('Reviewing','Overnight') or not reason or plan.active_dispatch_review!=review.name:
        frappe.throw('Only an open or overnight review can resume, with a reason; a held review requires counted settlement')
    if review.state=='Reviewing':
        _supervisor(operator)
    if review.get('recovery_manifest') or review.get('mixed_recovery_json'):
        from cfg_kanban.services.dispatch_recovery import assert_review_disposition
        assert_review_disposition(review)
    _counts()._validate_vehicle_warehouse(plan.company, plan.vehicle_warehouse)
    _no_open_delivery(plan)
    rows=_balances(plan,current=True)
    _at_source(plan,rows)
    review.db_set(dict(state='Resumed',resume_key=key,resume_reason=reason,resumed_on=now_datetime(),
        resumed_by_operator=operator.employee,active_plan_key=None),update_modified=True)
    plan.db_set(dict(dispatch_review_state='',active_dispatch_review=None),update_modified=True)
    record('Dispatch Plan Resumed',reference_doctype=REVIEW,reference_name=review.name,
        operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
        device_id=key,notes=f'{plan.name}; {reason}')
    return _current_context(plan,review)



def protect_review_movement_cancellation(doc, method=None):
    """A closing stock-disposition reference cannot disappear behind a reconciled trip."""
    if not frappe.db.table_exists(REVIEW):
        return
    manifest=doc.get('cfg_movement_manifest')
    if manifest and frappe.db.get_value('CFG Kanban Movement Manifest',manifest,'recovery_bundle_key'):
        from cfg_kanban.services.dispatch_recovery_mixed import protect_movement_cancellation
        protect_movement_cancellation(doc)
    review=frappe.db.get_value(REVIEW,{'movement_stock_entry':doc.name,'state':'Completed'},'name',for_update=True)
    if review:
        frappe.throw(f'Stock Entry {doc.name} settled Dispatch Review {review}; use an audited follow-on movement instead of cancelling its evidence')


def _refusal_reserve(plan,row):
    if not row.get('handling_unit'):return 0
    held=0
    if plan.get('driver_delivery_outcome') or plan.get('has_loose_tags'):
        from cfg_kanban.services.driver_delivery_outcomes import held_tag_qty
        held+=held_tag_qty(row['handling_unit'])
    if plan.get('stop_cancellation'):
        from cfg_kanban.services.cancelled_stop_stock import held_tag_qty
        held+=held_tag_qty(row['handling_unit'],dispatch_plan=plan.name,parent=plan.stop_cancellation)
    return held

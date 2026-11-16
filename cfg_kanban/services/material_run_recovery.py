"""Supervisor recovery of unused reservations and untouched historical hopper output."""
import math
import frappe
from frappe.utils import flt, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

RELEASE = 'Release unused'
RECONSTRUCT = 'Reconstruct hopper'
EPSILON = 0.000001


def _context(material_run, token, lock=False):
    if lock:
        # Same execution/Cycle lock order as normal Material Run mutations.
        execution_name = frappe.db.get_value('CFG Kanban Operation Material Run', material_run, 'process_execution')
        from cfg_kanban.services.operation_hoppers import lock_execution
        execution = lock_execution(execution_name, allow_closed=True)
        rows = frappe.db.sql('select * from `tabCFG Kanban Operation Material Run` where name=%s for update', material_run, as_dict=True)
        if not rows:
            frappe.throw('Material Run was not found')
        run = frappe.get_doc('CFG Kanban Operation Material Run', material_run)
        run.update(rows[0])
    else:
        run = frappe.get_doc('CFG Kanban Operation Material Run', material_run)
        execution = frappe.get_doc('CFG Kanban Process Execution', run.process_execution)
    profile, session = require_operator(token, 'override', execution=execution)
    if run.process_execution != execution.name or run.kanban_cycle != execution.kanban_cycle:
        frappe.throw('Material Run execution/Cycle identity requires reconciliation')
    if frappe.db.get_value('Job Card',execution.job_card,'work_order') != run.work_order:
        frappe.throw('Material Run belongs to a different Work Order')
    return run, execution, profile, session


def _draws(run, lock=False):
    return frappe.db.sql('''
        select * from `tabCFG Kanban Operation Material Draw`
        where material_run=%s and remaining_qty > 0.000001
          and status in ('Open','Partially Used','Carry Forward','Used','Bound to ERP')
        order by name
    ''' + (' for update' if lock else ''), run.name, as_dict=True)


@frappe.whitelist()
def recovery_context(material_run, operator_session_token=None):
    run, execution, _profile, _session = _context(material_run, operator_session_token)
    progress = frappe.get_doc('CFG Kanban Operation Progress', run.progress) if run.progress else None
    return {'material_run':run.name, 'work_order':run.work_order, 'operation':execution.operation,
            'unused_qty':sum(flt(row.remaining_qty) for row in _draws(run)),
            'good_qty':flt(progress.good_qty) if progress else 0,
            'hopper_reserved_qty':flt(run.get('hopper_reserved_qty')),
            'note':'Reconstruction requires untouched, fully released output matching one recorded Rinse progress.'}


def _release(run, execution, reason):
    other = [row[0] for row in frappe.db.sql("select name from `tabCFG Kanban Operation Material Run` where process_execution=%s and status='Open' and name!=%s for update", (execution.name,run.name))]
    if other:
        frappe.throw('Cancel the other open Material Run before releasing carry-forward: ' + ', '.join(other))
    draws = _draws(run, lock=True)
    if not draws and run.status != 'Open':
        frappe.throw('This Material Run has no unused reservation to release')
    total = 0
    audit_draws = []
    for draw in draws:
        amount = flt(draw.remaining_qty)
        released = flt(draw.released_qty) + amount
        if abs(flt(draw.drawn_qty) - flt(draw.used_qty) - released) > EPSILON:
            frappe.throw('Material Draw quantities require reconciliation before release')
        status = ('Bound to ERP' if draw.status == 'Bound to ERP' else
                  'Used' if flt(draw.used_qty) > EPSILON else 'Released')
        frappe.db.set_value('CFG Kanban Operation Material Draw', draw.name,
            {'remaining_qty':0,'released_qty':released,'status':status})
        audit_draws.append({'draw':draw.name,'used_qty':flt(draw.used_qty),'remaining_before':amount,'remaining_after':0,'released_before':flt(draw.released_qty),'released_after':released})
        total += amount
    hopper_reserved = flt(run.get('hopper_reserved_qty'))
    if run.status == 'Open':
        if run.progress:
            frappe.throw('An open run with progress needs reconciliation before cancellation')
        from cfg_kanban.services.operation_hoppers import cancel_run_hopper
        cancel_run_hopper(run.name, reason)
        run.db_set({'status':'Cancelled','active_execution_key':None,
            'closed_on':now_datetime(),'cancelled_on':now_datetime(),'cancellation_reason':reason})
        if execution.open_material_run == run.name:
            execution.db_set('open_material_run',None)
    from cfg_kanban.services.operation_material_runs import _refresh_run_totals
    _refresh_run_totals(run)
    return {'released_qty':total,'released_hopper_qty':hopper_reserved if run.status == 'Cancelled' else 0,'material_run':run.name,'draws':audit_draws}


def _reconstruct(run, execution, hopper_scan, physical_qty):
    from cfg_kanban.services.operation_hoppers import _unit, _active_fill, _sync_unit
    if run.status != 'Progress Posted' or not run.progress or run.operation_hopper_fill:
        frappe.throw('Select a posted historical Material Run without an existing Hopper fill')
    order = frappe.get_doc('Work Order',run.work_order)
    current_order = frappe.db.sql('select * from `tabWork Order` where name=%s for update',run.work_order,as_dict=True)
    if not current_order:frappe.throw('Work Order was not found')
    order.update(current_order[0])
    if order.docstatus != 1 or order.status in ('Completed','Closed','Stopped','Cancelled') or flt(order.produced_qty) > EPSILON:
        frappe.throw('Hopper reconstruction requires an active Work Order without posted finished output')
    progress = frappe.get_doc('CFG Kanban Operation Progress',run.progress)
    if (progress.process_execution != execution.name or progress.material_run != run.name
            or flt(progress.good_qty) <= EPSILON):
        frappe.throw('The original progress does not prove this Material Run output')
    if abs(physical_qty - flt(progress.good_qty)) > EPSILON:
        frappe.throw('Physical quantity must match this untouched progress; partial use, loss or mixed loads need separate reconciliation')
    if execution.handoff_mode != 'Digital Quantity Handoff' or flt(execution.released_qty) + EPSILON < flt(execution.good_qty):
        frappe.throw('The original operation output must already be fully released through digital handoff')
    master = frappe.get_doc('CFG Kanban Master',execution.kanban_master)
    source = next((row for row in master.operation_profiles if row.operation == execution.operation),None)
    destination = next((row for row in master.operation_profiles if source and row.operation == source.destination_operation),None)
    if (not source or source.get('material_run_hopper_mode') != 'Fill Hopper' or not destination
            or destination.get('material_run_hopper_mode') != 'Consume Hopper'
            or destination.dependency_operation != execution.operation
            or source.destination_operation != execution.destination_operation):
        frappe.throw('Configure the matching Fill Hopper / Consume Hopper route before recovery')
    jobs = frappe.db.sql('select total_completed_qty from `tabJob Card` where work_order=%s and operation=%s and docstatus < 2 for update',(order.name,destination.operation),as_dict=True)
    if any(flt(job.total_completed_qty) > EPSILON for job in jobs):
        frappe.throw('Packing already has output on this Work Order; historical use needs explicit reconciliation')
    # Use current approved location only for validation; never rewrite the old execution snapshot.
    transient = frappe._dict(execution.as_dict())
    transient.material_run_hopper_warehouse = source.material_run_hopper_warehouse
    unit, _order = _unit(transient,hopper_scan,lock=True)
    native = frappe.db.sql("select name from `tabCFG Kanban Container Content` where container_handling_unit=%s and state='Loaded' for update",unit.name)
    if native:frappe.throw('The Hopper already contains ERP-manufactured stock')
    if _active_fill(unit.name,lock=True):
        frappe.throw('The Hopper already has an active operation fill')
    cycle_uom = frappe.db.get_value('CFG Kanban Cycle',execution.kanban_cycle,'stock_uom')
    if cycle_uom != master.stock_uom:
        frappe.throw('Historical production UOM differs from the current Master')
    fill = frappe.get_doc({'doctype':'CFG Kanban Operation Hopper Fill','status':'Ready',
        'handling_unit':unit.name,'active_hopper_key':unit.name,'work_order':order.name,
        'company':order.company,'warehouse':unit.current_warehouse,'stock_uom':master.stock_uom,
        'source_operation':execution.operation,'destination_operation':destination.operation,
        'source_execution':execution.name,'source_material_run':run.name,'source_progress':progress.name,
        'qty':physical_qty,'used_qty':0,'reserved_qty':0,'opened_on':now_datetime()}).insert(ignore_permissions=True)
    run.db_set({'operation_hopper':unit.name,'operation_hopper_fill':fill.name})
    _sync_unit(fill.name)
    return {'hopper_fill':fill.name,'loaded_qty':physical_qty,'material_run':run.name}


@frappe.whitelist()
def recover_material_run(material_run, action, reason, event_token, hopper_scan=None,
                         physical_qty=0, operator_session_token=None):
    run, execution, profile, session = _context(material_run,operator_session_token,lock=True)
    reason = str(reason or '').strip()
    qty = flt(physical_qty)
    if action not in (RELEASE,RECONSTRUCT) or not reason or not event_token or not math.isfinite(qty):
        frappe.throw('Select a recovery action, reason and stable event token with a finite quantity')
    if action == RECONSTRUCT and (not hopper_scan or qty <= EPSILON):
        frappe.throw('Scan the Hopper and confirm its positive physical quantity')
    fingerprint = canonical_key('material-run-recovery-request',run.name,action,reason,hopper_scan or '',qty)
    key = canonical_key('material-run-recovery',run.name,event_token)
    existing = frappe.db.sql('select payload_json from `tabCFG Kanban Event` where idempotency_key=%s for update',key)
    if existing:
        payload = frappe.parse_json(existing[0][0])
        if payload['request'] != fingerprint:
            frappe.throw('Recovery token was already used for different recovery data')
        return dict(payload['result'],duplicate=True)
    result = (_release(run,execution,reason) if action == RELEASE else
              _reconstruct(run,execution,hopper_scan,qty))
    record('Material Run Recovery',cycle=run.kanban_cycle,execution=execution.name,
        reference_doctype='CFG Kanban Operation Material Run',reference_name=run.name,
        work_order=run.work_order,operation=execution.operation,notes=reason,
        operator=profile.employee,operator_session=session.name,terminal_user=session.terminal_user,
        payload={'request':fingerprint,'action':action,'result':result},idempotency_key=key)
    return result


@frappe.whitelist()
def recovery_runs(execution_name, operator_session_token=None):
    execution = frappe.get_doc('CFG Kanban Process Execution',execution_name)
    require_operator(operator_session_token,'override',execution=execution)
    order = frappe.db.get_value('Job Card',execution.job_card,'work_order')
    return frappe.get_all('CFG Kanban Operation Material Run',filters={
        'work_order':order,'job_card':execution.job_card,'status':['in',['Open','Progress Posted']]},
        fields=['name'],order_by='creation desc',limit_page_length=0)

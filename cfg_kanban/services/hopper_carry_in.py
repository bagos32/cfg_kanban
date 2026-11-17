"""Audited carry-in of already-processed intermediate WIP into a fresh Work Order.

The source load/progress and posted inputs stay with their original order. A native
zero-duration Job Card credit records inherited output without inventing new labor
or raw draws. Only the receiving order's actual additional inputs are consumed.
"""
from types import MethodType

import frappe
from frappe.utils import flt, now_datetime, get_datetime

from cfg_kanban.services.operator_auth import require_operator

EPSILON = 0.000001
TERMINAL = ('Completed', 'Closed', 'Stopped')


def owner(fill):
    return fill.get('current_work_order') or fill.work_order


def owner_execution(fill):
    return fill.get('current_source_execution') or fill.source_execution


def _source_evidence(fill):
    """Require real released output and submitted, still-valid original input evidence."""
    source = frappe.get_doc('CFG Kanban Process Execution', fill.source_execution)
    progress = frappe.get_doc('CFG Kanban Operation Progress', fill.source_progress)
    run = frappe.get_doc('CFG Kanban Operation Material Run', fill.source_material_run)
    if (progress.get('cancelled') or progress.process_execution != source.name or
            progress.material_run != run.name or run.progress != progress.name or
            run.status != 'Progress Posted' or run.work_order != fill.work_order or
            abs(flt(progress.good_qty) - flt(fill.qty)) > EPSILON):
        frappe.throw('Original Hopper output evidence requires reconciliation before carry-in')
    rules = frappe.parse_json(source.material_run_rules_json or '[]') or []
    if not rules:
        frappe.throw('Carry-in requires tracked original raw-material evidence')
    from cfg_kanban.services.material_run_receipts import _validated_draw_posting
    current_order = frappe.db.sql('select docstatus, status from `tabWork Order` where name=%s for update', fill.work_order, as_dict=True)
    if not current_order or current_order[0].docstatus != 1 or current_order[0].status not in TERMINAL:
        frappe.throw('Original Work Order is no longer completed/closed; reconcile carry-in evidence')
    original_order = frappe.get_doc('Work Order', fill.work_order)
    draws = frappe.get_all('CFG Kanban Operation Material Draw', filters={
        'process_execution': source.name, 'used_qty': ['>', EPSILON], 'status': ['!=', 'Cancelled']},
        fields=['name', 'process_execution', 'work_order', 'job_card', 'operation', 'material_flow_rule_row',
                'status', 'item_code', 'source_warehouse', 'stock_uom', 'source_handling_unit',
                'used_qty', 'material_trace', 'material_trace_line'], limit_page_length=0)
    covered = set()
    entries = set()
    for draw in draws:
        if draw.work_order != fill.work_order or draw.status != 'Bound to ERP':
            frappe.throw('Submit all original Hopper raw-material settlements before carry-in')
        native_name = frappe.db.get_value('CFG Kanban Material Trace', draw.material_trace, 'stock_entry')
        native = frappe.db.sql('select docstatus from `tabStock Entry` where name=%s for update', native_name, as_dict=True)
        if not native or native[0].docstatus != 1:
            frappe.throw('Original Hopper input posting was cancelled; reconcile carry-in evidence')
        if not _validated_draw_posting(draw, frappe._dict(name=None), original_order, {}):
            frappe.throw('Original Hopper inputs are not submitted ERP consumption')
        rule = next((r for r in rules if r.get('rule_row') == draw.material_flow_rule_row), None)
        if (not rule or draw.job_card != source.job_card or draw.operation != source.operation or
                (draw.item_code, draw.source_warehouse, draw.stock_uom) !=
                (rule.get('item_code'), rule.get('scan_warehouse'), rule.get('stock_uom'))):
            frappe.throw('Original Hopper raw-material rule evidence does not match')
        covered.add(draw.material_flow_rule_row)
        entries.add(frappe.db.get_value('CFG Kanban Material Trace', draw.material_trace, 'stock_entry'))
    if any(rule.get('rule_row') not in covered for rule in rules):
        frappe.throw('Original Hopper raw-material evidence is incomplete')
    return sorted(entries)


def _assert_receipt_scope(order, job, execution):
    from cfg_kanban.services.material_run_receipts import _receipt_scopes
    jobs = frappe.get_all('Job Card', filters={'work_order': order.name, 'docstatus': ['<', 2]},
                          fields=['name', 'operation', 'for_quantity'], limit_page_length=0)
    executions = frappe.get_all('CFG Kanban Process Execution', filters={
        'job_card': ['in', [row.name for row in jobs]], 'status': ['!=', 'Cancelled']},
        fields=['name', 'job_card', 'operation', 'material_run_control', 'material_run_rules_json'], limit_page_length=0)
    scopes, _rules = _receipt_scopes(order, jobs, executions)
    source_rules = frappe.parse_json(execution.material_run_rules_json or '[]') or []
    keys = {(row.get('item_code'), row.get('scan_warehouse'), row.get('stock_uom')) for row in source_rules}
    if (not keys or execution.material_run_control not in ('Optional', 'Required Before Progress') or
            any(key not in scopes or job.name not in scopes[key] for key in keys) or
            any((row.item_code, row.source_warehouse, row.stock_uom) not in keys
                for row in order.required_items if row.operation == job.operation)):
        frappe.throw('Receiving source material rules must prove the full BOM input scope before carry-in')
    return keys


def _target(fill, work_order, job_card=None, token=None, lock=False):
    source_order = frappe.get_doc('Work Order', owner(fill))
    if source_order.docstatus != 1 or source_order.status not in TERMINAL:
        frappe.throw('Carry-in is for leftovers of a completed or closed Work Order')
    target = frappe.get_doc('Work Order', work_order)
    locked_cycle = None
    if lock:
        if target.get('cfg_kanban_cycle'):
            locked_cycle = frappe.db.sql('select * from `tabCFG Kanban Cycle` where name=%s for update', target.cfg_kanban_cycle, as_dict=True)
            if not locked_cycle:
                frappe.throw('Target Work Order Cycle was not found')
        rows = frappe.db.sql('select * from `tabWork Order` where name=%s for update', target.name, as_dict=True)
        if not rows:
            frappe.throw('Target Work Order was not found')
        target.update(rows[0])
    original = frappe.get_doc('Work Order', fill.work_order)
    if (target.name == source_order.name or target.name == original.name or target.docstatus != 1 or
            target.status in ('Completed', 'Closed', 'Stopped', 'Cancelled') or
            target.company != fill.company or target.production_item != original.production_item or
            target.bom_no != original.bom_no or not target.skip_transfer or
            not target.get('cfg_kanban_controlled') or not target.get('cfg_kanban_cycle') or
            flt(target.produced_qty) > EPSILON):
        frappe.throw('Use a new active Kanban Skip-WIP Work Order with the same Company, Item and BOM')
    from cfg_kanban.services.production_cancellation import assert_cycle_not_under_cancellation
    assert_cycle_not_under_cancellation(target.cfg_kanban_cycle)
    cycle = frappe.get_doc('CFG Kanban Cycle', target.cfg_kanban_cycle)
    if locked_cycle:
        cycle.update(locked_cycle[0])
    if cycle.status in ('Completed', 'Cancelled') or cycle.work_order != target.name:
        frappe.throw('Target Work Order Cycle is closed or mismatched')
    original_execution = frappe.get_doc('CFG Kanban Process Execution', fill.source_execution)
    if cycle.kanban_master != original_execution.kanban_master:
        frappe.throw('Carry-in requires the same Kanban Master')
    master = frappe.get_doc('CFG Kanban Master', cycle.kanban_master)
    profiles = list(master.operation_profiles)
    source = next((row for row in profiles if row.operation == fill.source_operation), None)
    destination = next((row for row in profiles if row.operation == fill.destination_operation), None)
    if (len(profiles) != 2 or not source or not destination or source.get('dependency_operation') or
            source.get('material_run_hopper_mode') != 'Fill Hopper' or
            destination.get('material_run_hopper_mode') != 'Consume Hopper' or
            source.destination_operation != destination.operation or
            destination.dependency_operation != source.operation or
            source.handoff_mode != 'Digital Quantity Handoff' or
            source.material_run_hopper_warehouse != fill.warehouse or
            destination.material_run_hopper_warehouse != fill.warehouse or master.stock_uom != fill.stock_uom):
        frappe.throw('Carry-in requires the matching two-operation Fill Hopper / Consume Hopper route')
    # Source-task/certificate inheritance needs its own explicit revision mapping. Never bypass it.
    if (frappe.db.exists('Sub Operation', {'parent': source.operation}) or
            any(row.operation == source.operation for row in master.certificate_requirements) or
            any(row.operation == source.operation for row in master.certificate_output_rules) or
            frappe.db.exists('CFG Kanban Process Task', {'kanban_cycle': cycle.name, 'operation': source.operation})):
        frappe.throw('Source operation has sub-operations/certificate/task gates; reconcile inherited gate evidence before carry-in')
    if frappe.db.exists('Stock Entry', {'work_order': target.name, 'docstatus': ['<', 2]}):
        frappe.throw('Target Work Order already has a stock draft/posting; reconcile it before carry-in')
    if frappe.db.exists('CFG Kanban Runtime Allocation', {'work_order': target.name, 'status': ['not in', ['Cancelled', 'Completed']]}):
        frappe.throw('Close/cancel active target Card allocations before carry-in')
    target_profile, _session = require_operator(token, 'override', operation=source.operation)
    allowed_stations = {row.workstation for row in (target_profile.get('allowed_workstations') or []) if row.workstation}
    jobs = frappe.get_all('Job Card', filters={'work_order': target.name, 'operation': source.operation, 'docstatus': 0},
                          fields=['name', 'workstation', 'for_quantity', 'total_completed_qty'], limit_page_length=0)
    eligible = []
    for row in jobs:
        if flt(row.for_quantity) - flt(row.total_completed_qty) <= EPSILON:
            continue
        job = frappe.get_doc('Job Card', row.name)
        if allowed_stations and job.workstation and job.workstation not in allowed_stations:
            continue
        if job.get('sub_operations') or job.get('items') or any(not log.get('cfg_hopper_carry_in') for log in job.time_logs):
            continue
        executions = frappe.get_all('CFG Kanban Process Execution', filters={
            'kanban_cycle': cycle.name, 'job_card': job.name, 'status': ['!=', 'Cancelled']},
            fields=['name', 'runtime_allocation'], limit_page_length=0)
        if len(executions) != 1 or executions[0].runtime_allocation:
            continue
        require_operator(token, 'override', operation=source.operation, workstation=job.workstation)
        eligible.append((job, executions[0].name))
    if not job_card:
        return target, eligible
    chosen = next((pair for pair in eligible if pair[0].name == job_card), None)
    if not chosen:
        frappe.throw('Select an eligible untouched source Job Card on the target Work Order')
    job, execution_name = chosen
    if lock:
        rows = frappe.db.sql('select * from `tabJob Card` where name=%s for update', job.name, as_dict=True)
        if not rows:
            frappe.throw('Target Job Card was not found')
        job.reload()
        job.update(rows[0])
        # Reload child rows with current locking reads too; a normal reload alone
        # can retain an older REPEATABLE READ snapshot after a concurrent native save.
        logs = frappe.db.sql('select * from `tabJob Card Time Log` where parent=%s order by idx for update', job.name, as_dict=True)
        job.set('time_logs', logs)
        current_items = frappe.db.sql('select name from `tabJob Card Item` where parent=%s for update', job.name)
        current_suboperations = frappe.db.sql('select name from `tabJob Card Operation` where parent=%s for update', job.name)
        execution_rows = frappe.db.sql('select * from `tabCFG Kanban Process Execution` where name=%s for update', execution_name, as_dict=True)
        if not execution_rows:
            frappe.throw('Target source execution was not found')
        execution = frappe.get_doc('CFG Kanban Process Execution', execution_name)
        execution.update(execution_rows[0])
        require_operator(token, 'override', operation=job.operation, workstation=job.workstation)
        if (job.docstatus != 0 or job.work_order != target.name or job.operation != fill.source_operation or
                job.get('items') or job.get('sub_operations') or current_items or current_suboperations or
                execution.kanban_cycle != target.cfg_kanban_cycle or execution.job_card != job.name or
                execution.kanban_master != master.name or execution.operation != source.operation or
                execution.status in ('Cancelled', 'Completed') or
                any(not log.get('cfg_hopper_carry_in') for log in job.time_logs) or
                execution.get('open_material_run') or execution.get('runtime_allocation') or
                execution.get('material_run_hopper_mode') != 'Fill Hopper' or
                execution.get('material_run_hopper_warehouse') != fill.warehouse or
                execution.destination_operation != fill.destination_operation):
            frappe.throw('Target Job Card or execution changed; reload carry-in')
        _assert_receipt_scope(target, job, execution)
        return target, job, execution, owner(fill)
    return target, chosen


@frappe.whitelist()
def carry_in_targets(hopper_fill, target_work_order, operator_session_token=None):
    fill = frappe.get_doc('CFG Kanban Operation Hopper Fill', hopper_fill)
    execution = frappe.get_doc('CFG Kanban Process Execution', fill.source_execution)
    require_operator(operator_session_token, 'override', execution=execution)
    target, choices = _target(fill, target_work_order, token=operator_session_token)
    return {'work_order': target.name, 'choices': [
        {'name': job.name, 'label': job.name + ' · ' + str(job.workstation or '-') + ' · Remaining ' +
         str(max(0, flt(job.for_quantity) - flt(job.total_completed_qty)))} for job, _execution in choices]}


def lock_target(fill_name, work_order, job_card, token):
    fill = frappe.get_doc('CFG Kanban Operation Hopper Fill', fill_name)
    return _target(fill, work_order, job_card, token, lock=True)


def apply_carry(fill, target_context, qty, reason, profile):
    target, job, execution, expected_owner = target_context
    if owner(fill) != expected_owner:
        frappe.throw('Hopper ownership changed; reload carry-in')
    previous_order = frappe.db.sql('select docstatus,status from `tabWork Order` where name=%s for update', owner(fill), as_dict=True)
    if not previous_order or previous_order[0].docstatus != 1 or previous_order[0].status not in TERMINAL:
        frappe.throw('The current Hopper owner must be completed/closed before carry-in')
    if qty > flt(job.for_quantity) - flt(job.total_completed_qty) + EPSILON:
        frappe.throw('Hopper remainder exceeds the target source Job Card remaining demand')
    settlements = _source_evidence(fill)
    previous_owner = owner(fill)
    previous_execution = owner_execution(fill)
    carry = frappe.get_doc({'doctype': 'CFG Kanban Hopper Carry In', 'hopper_fill': fill.name,
        'source_work_order': previous_owner, 'original_work_order': fill.work_order,
        'source_execution': fill.source_execution, 'source_progress': fill.source_progress,
        'source_material_run': fill.source_material_run, 'target_work_order': target.name,
        'target_job_card': job.name, 'target_execution': execution.name, 'target_cycle': target.cfg_kanban_cycle,
        'source_operation': fill.source_operation, 'destination_operation': fill.destination_operation,
        'company': fill.company, 'item_code': target.production_item, 'stock_uom': fill.stock_uom,
        'qty': qty, 'reason': reason, 'operator': profile.employee, 'carried_on': now_datetime(),
        'material_rules_json': execution.material_run_rules_json,
        'source_settlements_json': frappe.as_json(settlements)}).insert(ignore_permissions=True)
    from cfg_kanban.services.wip import append_entry
    previous_cycle = frappe.db.get_value('Work Order', previous_owner, 'cfg_kanban_cycle')
    if previous_cycle:
        append_entry(previous_cycle, 'Adjusted', -qty, source_execution=previous_execution,
                     source_operation=fill.source_operation, destination_operation=fill.destination_operation,
                     stock_uom=fill.stock_uom, notes='WIP carried to ' + target.name + ': ' + carry.name)
    # Reserve the mirrored release before native Job Card feedback. That feedback must
    # see this credit as already released, rather than release the same quantity twice.
    append_entry(target.cfg_kanban_cycle, 'Released', qty, source_execution=execution.name,
                 source_operation=fill.source_operation, destination_operation=fill.destination_operation,
                 stock_uom=fill.stock_uom, notes='Inherited Hopper WIP: ' + carry.name)
    execution.db_set('released_qty', flt(execution.released_qty) + qty)
    stamp = carry.carried_on
    job.append('time_logs', {'from_time': stamp, 'to_time': stamp, 'completed_qty': qty,
                            'cfg_hopper_carry_in': carry.name})
    job.remarks = (job.get('remarks') or '') + '\nInherited WIP ' + carry.name + ': no new processing time or raw draw. ' + reason
    before = flt(job.total_completed_qty)
    job.save(ignore_permissions=True)
    job.reload()
    if abs(flt(job.total_completed_qty) - before - qty) > EPSILON:
        frappe.throw('ERPNext did not record the exact Hopper carry-in Job Card credit')
    if abs(flt(job.total_completed_qty) - flt(job.for_quantity)) <= EPSILON:
        job.submit()
        job.reload()
        if job.docstatus != 1 or job.status != 'Completed':
            frappe.throw('ERPNext did not complete the fully credited source Job Card')
    frappe.db.set_value('CFG Kanban Operation Hopper Fill', fill.name,
                        {'current_work_order': target.name, 'current_source_execution': execution.name,
                         'carry_in': carry.name})
    from cfg_kanban.services.operation_summary import refresh_destination
    refresh_destination(target.cfg_kanban_cycle, fill.source_operation, fill.destination_operation)
    return carry.name


def receipt_evidence(order, jobs):
    """Validate native credits before allowing a fully inherited component to have zero new use."""
    if not frappe.db.table_exists('CFG Kanban Hopper Carry In'):
        return set()
    rows = frappe.get_all('CFG Kanban Hopper Carry In', filters={'target_work_order': order.name},
                          fields=['name', 'target_job_card', 'target_execution', 'material_rules_json', 'qty', 'hopper_fill'], limit_page_length=0)
    totals = {}
    for row in rows:
        job = frappe.get_doc('Job Card', row.target_job_card)
        logs = [log for log in job.time_logs if log.get('cfg_hopper_carry_in') == row.name]
        fill = frappe.get_doc('CFG Kanban Operation Hopper Fill', row.hopper_fill)
        if (job.docstatus != 1 or job.work_order != order.name or len(logs) != 1 or
                abs(flt(logs[0].completed_qty) - flt(row.qty)) > EPSILON):
            frappe.throw('Hopper carry-in Job Card credit requires reconciliation before Manufacture')
        uses = frappe.get_all('CFG Kanban Operation Hopper Use', filters={
            'hopper_fill': row.hopper_fill, 'work_order': order.name}, fields=['qty'], limit_page_length=0)
        if abs(sum(flt(use.qty) for use in uses) - flt(row.qty)) > EPSILON:
            frappe.throw('Consume the carried Hopper WIP in this Work Order before Manufacture')
        _source_evidence(fill)
        execution = frappe.get_doc('CFG Kanban Process Execution', row.target_execution)
        if execution.material_run_rules_json != row.material_rules_json:
            frappe.throw('Receiving carry-in material rule snapshot was changed; reconcile before Manufacture')
        keys = _assert_receipt_scope(order, job, execution)
        real_logs = [log for log in job.time_logs if not log.get('cfg_hopper_carry_in')]
        if real_logs:
            draws = frappe.get_all('CFG Kanban Operation Material Draw', filters={
                'work_order': order.name, 'job_card': job.name, 'used_qty': ['>', EPSILON], 'status': ['!=', 'Cancelled']},
                fields=['item_code', 'source_warehouse', 'stock_uom'], limit_page_length=0)
            actual_keys = {(draw.item_code, draw.source_warehouse, draw.stock_uom) for draw in draws}
            if any(not log.get('cfg_kanban_progress') for log in real_logs) or not keys.issubset(actual_keys):
                frappe.throw('New source processing needs tracked actual Material Run use before Manufacture')
        totals[job.name] = totals.get(job.name, 0) + flt(row.qty)
    inherited = set()
    for job_row in jobs:
        if totals.get(job_row.name, 0) <= EPSILON:
            continue
        job = frappe.get_doc('Job Card', job_row.name)
        if (all(log.get('cfg_hopper_carry_in') for log in job.time_logs) and
                abs(totals[job.name] - flt(job.total_completed_qty)) <= EPSILON):
            inherited.add(job.name)
    return inherited


def validate_fill_owner(fill, work_order):
    if owner(fill) != work_order:
        frappe.throw('The Hopper fill belongs to another Work Order')
    if fill.get('current_work_order'):
        carry = frappe.get_doc('CFG Kanban Hopper Carry In', fill.carry_in)
        if carry.target_work_order != work_order or carry.hopper_fill != fill.name:
            frappe.throw('Hopper carry-in ownership requires reconciliation')
        job = frappe.get_doc('Job Card', carry.target_job_card)
        logs = [log for log in job.time_logs if log.get('cfg_hopper_carry_in') == carry.name]
        if job.docstatus == 2 or len(logs) != 1 or abs(flt(logs[0].completed_qty) - flt(carry.qty)) > EPSILON:
            frappe.throw('Hopper carry-in native credit was changed; reconcile before use')
        _source_evidence(fill)


def protect_source_cancellation(doc, method=None):
    if doc.doctype not in ('Work Order', 'Job Card', 'Stock Entry') or not frappe.db.table_exists('CFG Kanban Hopper Carry In'):
        return
    if doc.doctype == 'Stock Entry' and not doc.get('work_order'):
        return
    frappe.db.sql('select name from `tab' + doc.doctype + '` where name=%s for update', doc.name)
    conditions = []
    values = []
    if doc.doctype == 'Stock Entry':
        conditions.append('original_work_order=%s'); values.append(doc.work_order)
    elif doc.doctype == 'Work Order':
        conditions.append('original_work_order=%s'); values.append(doc.name)
    elif doc.doctype == 'Job Card':
        conditions.append('source_material_run in (select name from `tabCFG Kanban Operation Material Run` where job_card=%s)'); values.append(doc.name)
    rows = frappe.db.sql('select name,target_work_order,source_settlements_json from `tabCFG Kanban Hopper Carry In`' +
                         (' where ' + ' and '.join(conditions) if conditions else '') + ' for update', tuple(values), as_dict=True)
    for row in rows:
        if doc.doctype == 'Stock Entry' and doc.name not in (frappe.parse_json(row.source_settlements_json or '[]') or []):
            continue
        if frappe.db.get_value('Work Order', row.target_work_order, 'docstatus') != 2:
            frappe.throw('Cancel/reconcile downstream Work Order ' + row.target_work_order +
                         ' before reversing source evidence used by Hopper carry-in ' + row.name)


def prepare_carry_credit_validation(doc, method=None):
    """A proven zero-duration credit occupies no workstation/employee time.

    Keep native time, sequence, quantity, submission and all actual-work overlap
    checks. Only the inherited quantity row is exempt from workstation overlap.
    Validate it on every subsequent native save/submit, not only during recovery.
    """
    references = set()
    for log in doc.get('time_logs') or []:
        if not log.get('cfg_hopper_carry_in'):
            continue
        carry = frappe.get_doc('CFG Kanban Hopper Carry In', log.cfg_hopper_carry_in)
        if (carry.target_job_card != doc.name or carry.target_work_order != doc.work_order or
                carry.source_operation != doc.operation or log.get('employee') or log.get('cfg_kanban_progress') or
                not log.get('from_time') or not log.get('to_time') or
                get_datetime(log.from_time) != get_datetime(carry.carried_on) or
                get_datetime(log.to_time) != get_datetime(carry.carried_on) or
                abs(flt(log.completed_qty) - flt(carry.qty)) > EPSILON or carry.name in references):
            frappe.throw('Inherited Hopper credit identity, quantity or zero-duration evidence was changed')
        references.add(carry.name)
    if not references:
        return
    native = getattr(doc, '_cfg_native_get_overlap_for', None) or doc.get_overlap_for
    def overlap(current, args, open_job_cards=None):
        if args.get('cfg_hopper_carry_in') in references:
            return {}
        return native(args, open_job_cards=open_job_cards)
    object.__setattr__(doc, '_cfg_native_get_overlap_for', native)
    object.__setattr__(doc, 'get_overlap_for', MethodType(overlap, doc))

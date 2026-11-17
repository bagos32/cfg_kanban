"""Audited physical recovery of intermediate WIP, including closed Work Orders.

This never adjusts ERP-posted container contents or deletes production evidence.
"""
import math

import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

TRANSFER = 'Transfer remaining'
EMPTY = 'Confirm physically empty'
DISCARD = 'Discard remaining'
CARRY = 'Carry into Work Order'
ACTIONS = (TRANSFER, EMPTY, DISCARD, CARRY)
EPSILON = 0.000001


def _identity(scan):
    from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
    identity = resolve_logistics_scan(scan)
    if not identity or identity.get('identity_type') != 'Handling Unit':
        frappe.throw('Scan the physical Hopper identity')
    return identity['name']


def _physical_unit(name, lock=False):
    rows = frappe.db.sql('select * from `tabCFG Kanban Handling Unit` where name=%s' +
                         (' for update' if lock else ''), name, as_dict=True)
    if not rows:
        frappe.throw('Hopper was not found')
    unit = frappe.get_doc('CFG Kanban Handling Unit', name)
    unit.update(rows[0])
    if (unit.tag_kind != 'Reusable Container' or unit.handling_unit_type != 'Hopper'
            or unit.reusable_container_role != 'Production Output Container'):
        frappe.throw('Use a reusable Hopper with role Production Output Container')
    if unit.identity_state != 'Active' or unit.movement_state in (
            'Internal Transit', 'Intercompany Transit', 'Delivered', 'Quarantined'):
        frappe.throw('The Hopper must be Active and outside transit or movement restrictions')
    from cfg_kanban.services.container_contents import active_container_contents, assert_container_not_in_open_manifest
    # Current reads under the physical HU lock, including native stock membership.
    native = frappe.db.sql("select name from `tabCFG Kanban Container Content` where container_handling_unit=%s and state='Loaded'" +
                           (' for update' if lock else ''), name)
    if native or active_container_contents(name):
        frappe.throw('This Hopper contains ERP-posted stock; use controlled ERP/container recovery')
    assert_container_not_in_open_manifest(name, 'recovering operation Hopper WIP')
    return unit


def _remaining(fill):
    values = [flt(fill.get(key)) for key in ('qty', 'used_qty', 'cleared_qty', 'reserved_qty')]
    if (not all(math.isfinite(value) and value >= 0 for value in values)
            or sum(values[1:]) > values[0] + EPSILON):
        frappe.throw('Hopper quantities require reconciliation before recovery')
    return max(0, values[0] - values[1] - values[2])


@frappe.whitelist()
def recovery_context(hopper_scan, operator_session_token=None):
    from cfg_kanban.services.operation_hoppers import _active_fill
    require_operator(operator_session_token)
    unit = _physical_unit(_identity(hopper_scan))
    fill = _active_fill(unit.name)
    if not fill:
        frappe.throw('This Hopper has no recorded active operation fill; reconstruct missing historical output from its Material Run first')
    execution = frappe.get_doc('CFG Kanban Process Execution', fill.source_execution)
    require_operator(operator_session_token, 'override', execution=execution)
    if unit.inventory_company != fill.company:
        frappe.throw('Hopper Company differs from its recorded fill')
    return {'hopper_fill': fill.name, 'handling_unit': unit.name,
            'visible_code': unit.handling_unit_id, 'work_order': fill.get('current_work_order') or fill.work_order,
            'original_work_order': fill.work_order,
            'work_order_status': frappe.db.get_value('Work Order', fill.get('current_work_order') or fill.work_order, 'status'),
            'item_code': frappe.db.get_value('Work Order', fill.work_order, 'production_item'),
            'source_operation': fill.source_operation, 'destination_operation': fill.destination_operation,
            'remaining_qty': _remaining(fill), 'reserved_qty': flt(fill.reserved_qty),
            'stock_uom': fill.stock_uom, 'status': fill.status}


@frappe.whitelist()
def recover_hopper(hopper_fill, hopper_scan, action, physical_qty, reason, event_token,
                   destination_scan=None, operator_session_token=None, target_work_order=None, target_job_card=None):
    from cfg_kanban.services.operation_hoppers import lock_execution, _active_fill, _sync_unit
    source_execution = frappe.db.get_value('CFG Kanban Operation Hopper Fill', hopper_fill, 'source_execution')
    execution = lock_execution(source_execution, allow_closed=True)
    profile, session = require_operator(operator_session_token, 'override', execution=execution)
    reason = str(reason or '').strip()
    try:
        qty = float(physical_qty)
    except (TypeError, ValueError):
        frappe.throw("Confirm the physical quantity as a number")
    if action not in ACTIONS or not reason or not event_token or not math.isfinite(qty) or qty < 0:
        frappe.throw('Select a recovery action, reason, finite physical quantity and stable event token')
    fingerprint = canonical_key('hopper-recovery-request', hopper_fill, hopper_scan, action,
                                qty, reason, destination_scan or '', target_work_order or '', target_job_card or '')
    key = canonical_key('hopper-recovery', hopper_fill, event_token)
    existing = frappe.db.sql('select payload_json from `tabCFG Kanban Event` where idempotency_key=%s for update', key)
    if existing:
        payload = frappe.parse_json(existing[0][0])
        if payload['request'] != fingerprint:
            frappe.throw('Recovery token was already used for different recovery data')
        if action == CARRY:
            job = frappe.get_doc('Job Card', target_job_card)
            require_operator(operator_session_token, 'override', operation=job.operation, workstation=job.workstation)
        return dict(payload['result'], duplicate=True)
    target_context = None
    if action == CARRY:
        if not target_work_order or not target_job_card:
            frappe.throw('Select the receiving Work Order and its exact source Job Card')
        from cfg_kanban.services.hopper_carry_in import lock_target
        target_context = lock_target(hopper_fill, target_work_order, target_job_card, operator_session_token)
    source_name = _identity(hopper_scan)
    destination_name = _identity(destination_scan) if action == TRANSFER else None
    if destination_name == source_name:
        frappe.throw('Scan a different empty destination Hopper')
    units = {name: _physical_unit(name, lock=True) for name in sorted({source_name, destination_name} - {None})}
    fill = _active_fill(source_name, lock=True)
    if not fill or fill.name != hopper_fill:
        frappe.throw('The Hopper fill changed; reload recovery before confirming')
    if fill.source_execution != execution.name or fill.company != units[source_name].inventory_company:
        frappe.throw('Hopper source identity or Company requires reconciliation')
    remaining = _remaining(fill)
    # A reservation is not physical consumption. Return it through Material Run recovery first.
    open_runs = frappe.db.sql("""select name from `tabCFG Kanban Operation Material Run`
        where operation_hopper_fill=%s and status='Open' for update""", fill.name)
    if fill.status != 'Ready' or remaining <= EPSILON:
        frappe.throw('Only released, positive remaining Hopper WIP can be recovered')
    if flt(fill.reserved_qty) > EPSILON or open_runs:
        frappe.throw('Release or cancel the open Material Run reservations before physical Hopper recovery')
    if action == EMPTY:
        if qty > EPSILON:
            frappe.throw('Confirm physically empty requires a physical count of zero')
    elif abs(qty - remaining) > EPSILON:
        frappe.throw('Physical quantity must match the full recorded remainder; reconcile discrepancies before transfer or discard')
    carry_name = None
    if action in (EMPTY, DISCARD) and fill.get('current_work_order'):
        current_order = frappe.get_doc('Work Order', fill.current_work_order)
        if current_order.docstatus != 2 and current_order.status not in ('Completed', 'Closed', 'Stopped'):
            frappe.throw('This Hopper credits an active Work Order; reconcile/cancel that Work Order before clearing its inherited WIP')
    if action == CARRY:
        if units[source_name].quality_state != 'Released' or units[source_name].current_warehouse != fill.warehouse:
            frappe.throw('Carry-in requires Released WIP in its original Hopper Warehouse')
        from cfg_kanban.services.hopper_carry_in import apply_carry
        carry_name = apply_carry(fill, target_context, remaining, reason, profile)
    elif action == TRANSFER:
        destination = units[destination_name]
        if (destination.inventory_company != fill.company or
                destination.current_warehouse != units[source_name].current_warehouse or
                destination.current_warehouse != fill.warehouse or destination.quality_state != 'Released' or
                units[source_name].quality_state != 'Released'):
            frappe.throw('Transfer requires Released Hoppers in the fill Company and original Hopper Warehouse')
        if _active_fill(destination_name, lock=True):
            frappe.throw('Destination Hopper already has operation WIP; mixing fills is not allowed')
        frappe.db.set_value('CFG Kanban Operation Hopper Fill', fill.name,
                            {'current_handling_unit': destination_name, 'active_hopper_key': destination_name})
        frappe.db.set_value('CFG Kanban Handling Unit', source_name,
                            {'operation_hopper_fill': None, 'operation_wip_qty': 0,
                             'operation_wip_reserved_qty': 0, 'operation_wip_available_qty': 0,
                             'operation_wip_uom': None, 'movement_state': 'Empty'}, update_modified=False)
    else:
        frappe.db.set_value('CFG Kanban Operation Hopper Fill', fill.name,
                            {'cleared_qty': flt(fill.get('cleared_qty')) + remaining,
                             'status': 'Empty', 'active_hopper_key': None})
        cycle = frappe.db.get_value('Work Order', fill.get('current_work_order') or fill.work_order, 'cfg_kanban_cycle')
        if cycle:
            from cfg_kanban.services.wip import append_entry
            append_entry(cycle, 'Rejected', remaining, source_execution=(fill.get("current_source_execution") or fill.source_execution),
                         source_operation=fill.source_operation, destination_operation=fill.destination_operation,
                         stock_uom=fill.stock_uom, notes=action + ': ' + reason + ' (fill ' + fill.name + ')')
    _sync_unit(fill.name)
    result = {'hopper_fill': fill.name, 'action': action, 'source_hopper': source_name,
              'destination_hopper': destination_name, 'recovered_qty': remaining,
              'remaining_qty': remaining if action in (TRANSFER, CARRY) else 0, 'stock_uom': fill.stock_uom,
              'carry_in': carry_name, 'target_work_order': target_work_order if action == CARRY else None}
    record('Operation Hopper Recovery', cycle=execution.kanban_cycle, execution=execution.name,
           handling_unit=source_name, work_order=fill.work_order, qty=remaining,
           reference_doctype='CFG Kanban Operation Hopper Fill', reference_name=fill.name,
           notes=reason, operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user,
           payload={'request': fingerprint, 'action': action, 'before': dict(fill), 'result': result},
           idempotency_key=key)
    return result

"""Accepted/refused quantities over native prepared deliveries; refused stock stays company-owned."""
import json
import math

import frappe
from frappe.utils import flt, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event

OUTCOME = 'CFG Kanban Delivery Outcome'
LINE = 'CFG Kanban Delivery Outcome Line'
HOLD_STATES = ('Held', 'Transferred Hold', 'Recovery Reserved')
SOUND = 'Good / Unwanted'
RELEASE = 'Allow Resale After Delivery'
HOLD = 'Require Supervisor Release'
EPS = 0.000001


def _prepared():
    from cfg_kanban.services import dispatch_fulfilment
    return dispatch_fulfilment


def _returns():
    from cfg_kanban.services import customer_returns
    return customer_returns


def _read(doctype, name, current=False):
    doc = frappe.get_doc(doctype, name, **({'for_update': True} if current else {}))
    doc.check_permission('read')
    return doc


def outcome_for(delivery, current=False):
    name = delivery.get('driver_delivery_outcome')
    if not name:
        return None
    doc = _read(OUTCOME, name, current)
    if (doc.delivery_session != delivery.name or doc.dispatch_plan != delivery.dispatch_plan
            or doc.company != delivery.selling_company or doc.customer != delivery.customer
            or doc.vehicle_warehouse != delivery.source_warehouse or doc.state != 'Recorded'):
        frappe.throw('Delivery outcome no longer matches its immutable Session/Plan scope')
    return doc


def quantities(plan, submitted):
    """Only stock UOM, finite numbers and the exact prepared physical sources are accepted."""
    sources = _prepared()._loaded_allocations(plan)
    submitted = frappe.parse_json(submitted) if isinstance(submitted, str) else submitted
    if submitted is None:
        return None
    if not isinstance(submitted, list):
        frappe.throw('Review the prepared quantity rows before confirming delivery')
    by_name = {}; rows = []
    for raw in submitted:
        if not isinstance(raw, dict) or set(raw) - {'dispatch_allocation', 'accepted_qty', 'refusal_reason', 'condition'}:
            frappe.throw('Unexpected delivery quantity fields')
        name = raw.get('dispatch_allocation')
        if not name or name in by_name:
            frappe.throw('Review every prepared source exactly once')
        by_name[name] = raw
    if set(by_name) != {row.name for row in sources}:
        frappe.throw('Quantity review must retain every exact prepared source')
    for source in sources:
        raw = by_name[source.name]
        try:
            accepted = float(raw.get('accepted_qty'))
        except (TypeError, ValueError):
            frappe.throw('Accepted quantity must be finite and non-negative')
        loaded = flt(source.allocated_qty); refused = loaded - accepted
        if not math.isfinite(accepted) or accepted < 0 or refused < -EPS:
            frappe.throw('Accepted quantity must be between zero and its loaded stock quantity')
        if abs(refused) <= EPS:
            accepted = loaded; refused = 0
        if frappe.db.get_value('UOM', source.stock_uom, 'must_be_whole_number') and abs(accepted - round(accepted)) > EPS:
            frappe.throw('Accepted quantity must follow the whole-number stock UOM')
        condition = raw.get('condition') or SOUND; reason = str(raw.get('refusal_reason') or '').strip()
        if refused and (not reason or condition not in _returns().CONDITIONS):
            frappe.throw('Every refused quantity needs its reason and reported condition')
        unit = _read('CFG Kanban Handling Unit', source.handling_unit) if source.handling_unit else None
        if unit and flt(unit.serial_count) and EPS < accepted < loaded - EPS:
            frappe.throw('Accept or refuse the whole serialized Stock Tag; split it through the controlled stock workflow first')
        membership = None
        if unit:
            from cfg_kanban.services.container_contents import active_container_membership
            membership = active_container_membership(unit.name)
        rows.append(dict(dispatch_allocation=source.name, handling_unit=source.handling_unit,
            visible_code=unit.handling_unit_id if unit else None,
            container_handling_unit=membership.container_handling_unit if membership else None,
            item_code=source.item_code, batch_no=source.batch_no, stock_uom=source.stock_uom,
            prepared_qty=loaded, accepted_qty=accepted, refused_qty=max(refused, 0),
            refusal_reason=reason or None, condition=condition,
            current_warehouse=plan.vehicle_warehouse, stock_state='Held' if refused > EPS else 'Not Refused'))
    return rows


def declare(trip, stop, plan, submitted, operator, session, event_token):
    rows = quantities(plan, submitted)
    if not rows or not any(row['refused_qty'] > EPS for row in rows):
        return None
    planning=_prepared()._planning_services()
    if plan.get('route_approval_required') or plan.get('route_sequence_scope')=='Combined Lorry Trip' or plan.get('active_route_sheet'):
        from cfg_kanban.services.route_sheets import lock_plan_route_scope, check_plan_route_scope
        scope=lock_plan_route_scope(plan,operator)
        plan=planning._locked_authorized_plan(plan.name,operator)
        check_plan_route_scope(plan,scope)
    else:
        plan=planning._locked_authorized_plan(plan.name,operator)
    rows=quantities(plan,submitted)
    for item in sorted({r['item_code'] for r in rows}):planning._lock_erp_bin(item,plan.vehicle_warehouse)
    if plan.get('driver_delivery_outcome'):
        frappe.throw('This prepared delivery already has a recorded quantity decision; use supervised correction')
    if plan.delivery_session:
        frappe.throw('Record refusals before starting the prepared delivery; an existing Session needs supervised reconciliation')
    site = _read('CFG Kanban Customer Scan Point', plan.customer_site)
    if any(row['refused_qty'] > EPS and row['condition'] != SOUND for row in rows):
        _returns()._assert_enabled(); _returns()._require_intake(operator)
        if not site.enable_customer_return_qc or not site.return_inspection_location:
            frappe.throw('Configure Customer Return QC and Inspection Custody Location for quality refusals')
    policy = json.loads(plan.profile_snapshot_json or '{}').get('sound_refusal_policy') or HOLD
    if policy not in (HOLD, RELEASE):
        frappe.throw('Unsupported sound-refusal release policy')
    doc = frappe.get_doc(dict(doctype=OUTCOME, state='Declared', delivery_trip=trip.name,
        stop_key=stop.stop_key, dispatch_plan=plan.name, active_plan_key=plan.name,
        company=plan.company, customer=plan.customer, customer_site=plan.customer_site,
        vehicle_warehouse=plan.vehicle_warehouse, sound_refusal_policy=policy,
        declared_on=now_datetime(), declared_by=operator.employee, operator_session=session.name,
        request_key=event_token, lines=rows))
    doc.flags.cfg_controlled_outcome = True
    doc.insert(ignore_permissions=True)
    plan.db_set('driver_delivery_outcome', doc.name, update_modified=True)
    return doc


def pending_for(plan, operator):
    name = plan.get('driver_delivery_outcome')
    if not name:
        return None
    doc = _read(OUTCOME, name, current=True)
    if (doc.state != 'Declared' or doc.delivery_session or doc.dispatch_plan != plan.name
            or doc.company != plan.company or doc.customer != plan.customer
            or doc.vehicle_warehouse != plan.vehicle_warehouse or doc.declared_by != operator.employee):
        frappe.throw('The prepared quantity decision is already bound or belongs to another operator')
    sources = {row.name: row for row in _prepared()._loaded_allocations(plan)}
    if set(sources) != {row.dispatch_allocation for row in doc.lines}:
        frappe.throw('Prepared sources changed after quantity review')
    for row in doc.lines:
        source = sources[row.dispatch_allocation]
        if (any((row.get(f) or '') != (source.get(f) or '') for f in ('handling_unit', 'item_code', 'batch_no', 'stock_uom'))
                or abs(flt(row.prepared_qty) - flt(source.allocated_qty)) > EPS
                or abs(flt(row.accepted_qty) + flt(row.refused_qty) - flt(row.prepared_qty)) > EPS):
            frappe.throw('Prepared source identity or accepted/refused quantities changed')
    return doc


def bind(doc, delivery):
    doc.db_set('delivery_session', delivery.name, update_modified=False)
    delivery.db_set('driver_delivery_outcome', doc.name, update_modified=False)


def _ledger(row, parent, kind, key, operator=None, operator_session=None, warehouse=None):
    if not row.handling_unit or flt(row.refused_qty) <= EPS:
        return None
    return post_quantity_event(event_type=kind, qty=row.refused_qty, stock_uom=row.stock_uom,
        idempotency_key=canonical_key('refused-stock', row.name, kind, key),
        source_handling_unit=row.handling_unit, item_code=row.item_code, batch_no=row.batch_no,
        source_company=parent.company, source_warehouse=warehouse or row.current_warehouse,
        reference_doctype=OUTCOME, reference_name=parent.name, operator=operator,
        operator_session=operator_session, reason='Company-owned refused stock custody')


def activate(doc, delivery, operator, session):
    for row in doc.lines:
        if flt(row.refused_qty) <= EPS:
            continue
        if row.handling_unit:
            unit = _read('CFG Kanban Handling Unit', row.handling_unit, current=True)
            if (unit.inventory_company != doc.company or unit.current_warehouse != doc.vehicle_warehouse
                    or unit.item_code != row.item_code or (unit.batch_no or '') != (row.batch_no or '')
                    or unit.stock_uom != row.stock_uom or abs(flt(unit.current_qty) - flt(row.prepared_qty)) > EPS):
                frappe.throw('Refused Stock Tag identity or quantity changed before custody was recorded')
        ledger = _ledger(row, doc, 'Reserve', doc.request_key, operator.employee, session.name)
        if ledger:
            row.db_set('hold_ledger', ledger.name, update_modified=False)
    doc.db_set('state', 'Recorded', update_modified=True)
    bad = [row for row in doc.lines if flt(row.refused_qty) > EPS and row.condition != SOUND]
    if bad:
        _quality_case(doc, bad, operator, session)
    if not any(flt(row.accepted_qty) > EPS for row in doc.lines):
        delivery.db_set(dict(state='Closed', completed_on=now_datetime(), proof_disposition='No goods accepted'), update_modified=True)
    record('Driver Accepted and Refused Quantities Recorded', delivery_session=delivery.name,
        reference_doctype=OUTCOME, reference_name=doc.name, qty=sum(flt(r.refused_qty) for r in doc.lines),
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
        idempotency_key=canonical_key('delivery-outcome-recorded', doc.name))


def _quality_case(doc, lines, operator, session):
    service = _returns(); service._assert_enabled(); service._require_intake(operator)
    site = _read('CFG Kanban Customer Scan Point', doc.customer_site)
    source = [dict(item_code=r.item_code, batch_no=r.batch_no, claimed_qty=r.refused_qty,
        condition=r.condition, original_visible_code=r.visible_code or '',
        details=r.refusal_reason, driver_outcome_line=r.name) for r in lines]
    validated = service._validate_free_intake_lines(source)
    case = frappe.get_doc(dict(doctype='CFG Kanban Return Case', intake_method='Customer Site',
        return_flow='Customer Return for QC', state='Awaiting QC Receipt',
        selling_company=doc.company, customer=doc.customer, customer_scan_point=site.name,
        customer_address=site.customer_address, site_code=site.site_code, site_name=site.site_name,
        inspection_location=site.return_inspection_location, claimed_on=now_datetime(),
        customer_return_reason='Refused before delivery: ' + '; '.join(r.refusal_reason for r in lines),
        lines=validated, claimed_total_qty=sum(flt(r.refused_qty) for r in lines),
        accounting_status='Not Required', stock_already_owned=1, driver_delivery_outcome=doc.name,
        driver_trip=doc.delivery_trip, driver_stop_key=doc.stop_key,
        collection_vehicle_warehouse=doc.vehicle_warehouse,
        created_by_operator=operator.employee, created_operator_session=session.name,
        idempotency_key=canonical_key('owned-refusal-qc', doc.name)))
    case.flags.cfg_driver_return = True
    case.insert(ignore_permissions=True)
    for row, result in zip(lines, case.lines):
        result.db_set('driver_outcome_line', row.name, update_modified=False)
        row.db_set('qc_return_case', case.name, update_modified=False)
    record('Owned Refusal Sent to Customer Return QC', return_case=case.name,
        reference_doctype=OUTCOME, reference_name=doc.name, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes='Company stock remains on hand. No customer credit or Material Receipt is allowed.')


def validate_allocations(delivery, allocations):
    doc = outcome_for(delivery)
    expected = {r.dispatch_allocation: r for r in doc.lines if flt(r.accepted_qty) > EPS}
    seen = set()
    for row in allocations:
        source = expected.get(row.dispatch_allocation)
        if (not source or row.dispatch_allocation in seen
                or any((row.get(f) or '') != (source.get(f) or '') for f in ('handling_unit','item_code','batch_no','stock_uom'))
                or abs(flt(row.allocated_qty)-flt(source.accepted_qty)) > EPS):
            frappe.throw('Delivery allocations must match the recorded accepted quantities exactly')
        seen.add(row.dispatch_allocation)
    if seen != set(expected):
        frappe.throw('Every accepted source is required for this Delivery Note')


def full_refusal(delivery):
    doc = outcome_for(delivery)
    return bool(doc and doc.lines and all(flt(r.accepted_qty) <= EPS and
        abs(flt(r.refused_qty)-flt(r.prepared_qty)) <= EPS for r in doc.lines) and not delivery.delivery_note)


def container_units(delivery, container):
    doc = outcome_for(delivery)
    return {r.handling_unit for r in doc.lines if r.container_handling_unit == container and r.handling_unit}


def refused_by_source(delivery):
    doc = outcome_for(delivery)
    return {r.dispatch_allocation: dict(refused_qty=flt(r.refused_qty), stock_state=r.stock_state,
        current_warehouse=r.current_warehouse, qc_return_case=r.qc_return_case, outcome=doc.name)
        for r in doc.lines} if doc else {}


def _release_line(row, doc, operator, session, reason):
    if row.stock_state not in ('Held', 'Transferred Hold'):
        frappe.throw('Only stock still held for this refusal may be released')
    if row.qc_return_case:
        case = _read('CFG Kanban Return Case', row.qc_return_case, current=True)
        result = next((r for r in case.lines if r.driver_outcome_line == row.name), None)
        if (not case.qc_completed_on or not result or result.qc_disposition != 'Release Own Stock'
                or abs(flt(result.accepted_qty)-flt(row.refused_qty)) > EPS or flt(result.rejected_qty) > EPS):
            frappe.throw('QC must approve all of this refused stock for resale first')
    warehouse=_read('Warehouse',row.current_warehouse)
    if warehouse.company!=doc.company:frappe.throw('Refused stock custody belongs to another Company')
    if row.handling_unit:
        unit=_read('CFG Kanban Handling Unit',row.handling_unit,current=True)
        if (unit.inventory_company!=doc.company or unit.current_warehouse!=row.current_warehouse
                or unit.item_code!=row.item_code or (unit.batch_no or '')!=(row.batch_no or '')
                or unit.stock_uom!=row.stock_uom or flt(unit.current_qty)+EPS<flt(row.refused_qty)
                or abs(flt(unit.reserved_qty)-held_tag_qty(unit.name))>EPS):
            frappe.throw('Refused Stock Tag custody or reservation changed; reconcile it before release')
    _assert_resalable(row)
    _ledger(row, doc, 'Unreserve', 'release', operator.employee, session.name)
    row.db_set(dict(stock_state='Available for Resale', released_on=now_datetime(),
        released_by=operator.employee, release_reason=reason), update_modified=False)
    if row.qc_return_case:
        _close_released_case(row.qc_return_case)
    record('Refused Company Stock Released for Resale', reference_doctype=OUTCOME,
        reference_name=doc.name, handling_unit=row.handling_unit, qty=row.refused_qty,
        operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user, notes=reason,
        idempotency_key=canonical_key('refusal-release', row.name))


def release(doc, line_names, reason, operator, session):
    if operator.kanban_role not in ('Supervisor','Development Proxy') or not operator.can_override:
        frappe.throw('A Supervisor with Override permission must release refused stock', frappe.PermissionError)
    if not str(reason or '').strip():
        frappe.throw('A Supervisor release reason is required')
    delivery = _read('CFG Kanban Delivery Session', doc.delivery_session, current=True)
    if delivery.state != 'Closed':
        frappe.throw('Complete accepted delivery and proof before releasing refused stock')
    for name in sorted({r.qc_return_case for r in doc.lines if r.qc_return_case}):
        _read('CFG Kanban Return Case', name, current=True)
    doc = _read(OUTCOME, doc.name, current=True)
    # Fetch the child values with current reads; a row lock alone must not retain an older snapshot.
    rows = [frappe.get_doc(LINE, row.name, for_update=True) for row in sorted(doc.lines,key=lambda r:r.name)]
    names = set(line_names or [])
    if not names or len(names) != len(line_names) or names - {r.name for r in rows}:
        frappe.throw('Select the exact refused stock rows')
    for row in rows:
        if row.name in names:
            _release_line(row, doc, operator, session, str(reason).strip())


def auto_release(delivery):
    if not delivery.get('driver_delivery_outcome') or delivery.state != 'Closed':
        return
    doc = outcome_for(delivery, current=True)
    # Fetch the child values with current reads; a row lock alone must not retain an older snapshot.
    rows = [frappe.get_doc(LINE, row.name, for_update=True) for row in sorted(doc.lines,key=lambda r:r.name)]
    if doc.sound_refusal_policy != RELEASE:
        return
    operator = frappe._dict(employee=doc.declared_by)
    session = frappe.get_doc('CFG Kanban Operator Session', doc.operator_session)
    for row in rows:
        if flt(row.refused_qty) > EPS and row.condition == SOUND and not row.qc_return_case and row.stock_state == 'Held':
            try:
                _assert_resalable(row)
            except frappe.ValidationError:
                continue
            _release_line(row, doc, operator, session, 'Released by captured Dispatch Profile after accepted delivery/proof completion')


def held_rows(filters=None, current=False):
    base = {'stock_state':['in',list(HOLD_STATES)], **(filters or {})}
    if current:
        names = [r.name for r in frappe.db.get_values(LINE, base, ['name'], as_dict=True, for_update=True, order_by='name')]
    else:
        names = frappe.get_all(LINE, filters=base, pluck='name', order_by='name', limit_page_length=0)
    return [frappe.get_doc(LINE, name, **({'for_update':True} if current else {})) for name in names]


def held_tag_qty(name):
    return sum(flt(row.refused_qty) for row in held_rows({'handling_unit':name}))


def held_untagged(company, warehouse, item, batch, current=False, exclude_outcome=None):
    return sum(flt(row.refused_qty) for row in held_rows({'handling_unit':['is','not set'],
        'current_warehouse':warehouse, 'item_code':item, 'batch_no':batch or ['is','not set']}, current=current)
        if row.parent!=exclude_outcome and frappe.db.get_value(OUTCOME, row.parent, 'company', for_update=current) == company)


def declared_source_qty(name, current=False):
    rows = frappe.db.get_values(LINE, {'dispatch_allocation':name}, ['refused_qty'], as_dict=True, for_update=current)
    return sum(flt(r.refused_qty) for r in rows)


def released_source_qty(name, current=False):
    rows = frappe.db.get_values(LINE, {'dispatch_allocation':name,
        'stock_state':['in',['Available for Resale','Disposed']]}, ['refused_qty'], as_dict=True, for_update=current)
    return sum(flt(r.refused_qty) for r in rows)


def recovery_adopt(manifest):
    for line in manifest.lines:
        for row in held_rows({'dispatch_allocation':line.dispatch_allocation}, current=True):
            if row.stock_state == 'Recovery Reserved':
                continue
            parent = frappe.get_doc(OUTCOME, row.parent)
            _ledger(row, parent, 'Unreserve', manifest.name)
            row.db_set(dict(stock_state='Recovery Reserved', recovery_manifest=manifest.name), update_modified=False)


def recovery_restore(manifest, received=False):
    for row in held_rows({'recovery_manifest':manifest.name}, current=True):
        if row.stock_state != 'Recovery Reserved':
            continue
        warehouse = manifest.destination_warehouse if received else manifest.source_warehouse
        parent = frappe.get_doc(OUTCOME, row.parent)
        _ledger(row, parent, 'Reserve', manifest.name + (':received' if received else ':cancelled'), warehouse=warehouse)
        row.db_set(dict(stock_state='Transferred Hold' if received else 'Held',
            current_warehouse=warehouse, recovery_manifest=manifest.name if received else None), update_modified=False)


def _assert_resalable(row):
    if row.handling_unit:
        unit=_read('CFG Kanban Handling Unit',row.handling_unit,current=True)
        if unit.identity_state!='Active' or unit.quality_state!='Released':
            frappe.throw('Refused Stock Tag must still be Active and Released for resale')
        _prepared().assert_delivery_tag_expiry(unit)
    elif row.batch_no:
        _prepared()._assert_untagged_batch_expiry(row.batch_no)


def _close_released_case(name):
    case=frappe.get_doc('CFG Kanban Return Case',name,for_update=True)
    if case.get('stock_already_owned') and case.qc_completed_on and all(
            r.driver_outcome_line and frappe.db.get_value(LINE,r.driver_outcome_line,'stock_state')=='Available for Resale' for r in case.lines):
        case.db_set(dict(state='Closed',disposition_status='Completed',stock_disposition_entry_status='Not Required'),update_modified=True)


def lock_recovery_rows(manifest):
    for line in sorted(manifest.lines,key=lambda r:r.dispatch_allocation):
        held_rows({'dispatch_allocation':line.dispatch_allocation},current=True)

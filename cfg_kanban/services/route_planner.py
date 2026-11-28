"""Office-only mock proposals. Acceptance edits Draft stop order through normal Trip validation."""
import copy
import datetime as dt
import json
import time

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from cfg_kanban.services import delivery_trips as office
from cfg_kanban.services import route_planner_model as model
from cfg_kanban.services.customer_locations import delivery_pin
from cfg_kanban.services.events import record

SETTINGS = 'CFG Kanban Route Planner Settings'
RUN = 'CFG Kanban Route Planning Run'
WORKER_SECONDS = 30


def run_has_permission(doc, user=None, ptype=None, **kwargs):
    """Only deny: native role/Company permissions still decide the final permission."""
    if ptype not in (None, 'read', 'select', 'print', 'export'):
        return None
    user = user or frappe.session.user
    try:
        trip = frappe.get_doc(office.TRIP, doc.delivery_trip)
        if trip.company != doc.company:
            return False
        snapshot = json.loads(doc.snapshot_json or '{}')
        refs = {(office.TRIP, doc.delivery_trip), ('Company', doc.company)}
        refs.update(('Sales Order', row['sales_order']) for row in snapshot.get('lines') or [])
        refs.update(('CFG Kanban Customer Scan Point', row['customer_scan_point']) for row in snapshot.get('stops') or [] if row.get('customer_scan_point'))
        # Only permission results are cached, only for this HTTP request, never between users.
        local = getattr(frappe, 'local', None)
        cache = getattr(local, 'cfg_route_planner_permissions', None) if local is not None else None
        if cache is None:
            cache = {}
            if local is not None:
                local.cfg_route_planner_permissions = cache
        for doctype, name in sorted(refs):
            key = (user, doctype, name)
            if key not in cache:
                source = trip if doctype == office.TRIP else frappe.get_doc(doctype, name)
                cache[key] = bool(frappe.has_permission(doctype, 'read', doc=source, user=user, raise_exception=False))
            if not cache[key]:
                return False
    except Exception:
        return False
    return None


def run_query_conditions(user=None):
    """Native list filtering; internal JSON fields have no ordinary-role field access."""
    user = user or frappe.session.user
    try:
        trips = frappe.get_list(office.TRIP, user=user, pluck='name', limit_page_length=0)
    except frappe.PermissionError:
        return '1=0'
    if not trips:
        return '1=0'
    names = ','.join(frappe.db.escape(name) for name in trips)
    return '`tabCFG Kanban Route Planning Run`.`delivery_trip` in (' + names + ')'


def _stamp(value):
    return str(get_datetime(value)) if value else ''


def _flag(doc, value):
    doc.flags.cfg_route_planner = value
    return doc


def _save(run):
    return _flag(run, True).save(ignore_permissions=True)


def verify_site_pin(doc, before):
    """Pin edits invalidate verification; a second reviewed save can verify the new entrance."""
    current = delivery_pin(doc.get('delivery_location'))
    try:
        previous = delivery_pin(before.get('delivery_location')) if before else None
    except ValueError:
        previous = None  # A repaired legacy pin can still be saved normally.
    identity_changed = bool(before and any(doc.get(f) != before.get(f) for f in
                            ('selling_company', 'customer', 'customer_address')))
    if before and (current != previous or identity_changed) and before.get('planner_pin_verified'):
        doc.planner_pin_verified = 0
    verified = cint(doc.get('planner_pin_verified'))
    if verified and current is None:
        frappe.throw('Save a Customer Site entrance pin before verifying it for route planning')
    if verified and not (before and before.get('planner_pin_verified')):
        frappe.only_for(office.EDITORS)
        doc.planner_pin_verified_by, doc.planner_pin_verified_on = frappe.session.user, now_datetime()
    else:
        doc.planner_pin_verified_by = before.get('planner_pin_verified_by') if verified and before else None
        doc.planner_pin_verified_on = before.get('planner_pin_verified_on') if verified and before else None


def validate_settings(doc):
    frappe.only_for(('Stock Manager', 'System Manager', 'CFG Kanban System Maintenance'))
    office._company(doc.company)
    if doc.provider != model.PROVIDER:
        frappe.throw('This package supports only Mock (test only); no Google connection is enabled')
    for field, maximum in [('max_stops', model.MAX_STOPS), ('max_attempts_per_trip', 100)]:
        try:
            model.number(doc.get(field), field.replace('_', ' '), integer=True, maximum=maximum)
        except ValueError as exc:
            frappe.throw(str(exc))
    pins = []
    for field in ('start_location', 'end_location'):
        try:
            pins.append(delivery_pin(doc.get(field)))
        except ValueError as exc:
            frappe.throw(f'{field}: {exc}')
    before = None if doc.is_new() else doc.get_doc_before_save()
    if before and before.company != doc.company and frappe.db.exists(RUN, {'company': before.company}):
        frappe.throw('Company cannot change after this pilot has planning history; create separate company settings')
    changed = before and (any(delivery_pin(before.get(f)) != pins[i] for i, f in
                enumerate(('start_location', 'end_location'))) or any(doc.get(f) != before.get(f)
                for f in ('company', 'source_warehouse', 'vehicle_warehouse')))
    if changed and before.get('gates_verified'):
        doc.gates_verified = 0
    if doc.get('gates_verified') and not all(pins):
        frappe.throw('Save both the start and return gate pins before verifying them')
    if doc.get('gates_verified'):
        doc.verified_by = before.get('verified_by') if before and before.get('gates_verified') else frappe.session.user
        doc.verified_on = before.get('verified_on') if before and before.get('gates_verified') else now_datetime()
    else:
        doc.verified_by = doc.verified_on = None
    if not doc.enabled:
        return
    for field in ('source_warehouse', 'vehicle_warehouse'):
        warehouse = office._read('Warehouse', doc.get(field))
        if warehouse.company != doc.company or warehouse.disabled or warehouse.is_group:
            frappe.throw('Planner Warehouses must be active leaf Warehouses in this Company')
        if field == 'vehicle_warehouse' and not (warehouse.get('cfg_is_vehicle_warehouse') and warehouse.get('cfg_vehicle_reference')):
            frappe.throw('Select a configured company lorry Warehouse')
    if doc.source_warehouse == doc.vehicle_warehouse:
        frappe.throw('Depot source and lorry Warehouse must differ')
    try:
        model.number(doc.capacity_grams, 'Usable payload (grams)', integer=True)
        date = dt.date(2026, 1, 1)
        if model.clock(doc.shift_end, date) <= model.clock(doc.shift_start, date):
            raise ValueError('Return deadline must follow departure on the same day')
    except ValueError as exc:
        frappe.throw(str(exc))


def _authorize(trip_name, current=False):
    frappe.only_for(office.EDITORS)
    doc = office._read(office.TRIP, trip_name, current=current)
    doc.check_permission('write')
    office._company(doc.company)
    return doc


def _locked(trip_name):
    initial = _authorize(trip_name)
    # Same template -> Trip -> Sales Order order as the normal office save path.
    office._locks(office.TEMPLATE, [initial.route_template])
    office._locks(office.TRIP, [initial.name])
    doc = _authorize(trip_name, current=True)
    if doc.route_template != initial.route_template:
        frappe.throw('The Trip template changed; reload before planning')
    office._locks('CFG Kanban Dispatch Plan', [row.dispatch_plan for row in doc.dispatch_plans]
                  + ([doc.open_route_plan] if doc.get('open_route_plan') else []))
    # Current dispatch reads belong before SO locks, matching normal office validation.
    doc.flags.cfg_route_planner_dispatch_guard = _dispatch_guard(doc, True)
    office._locks('Sales Order', [row.sales_order for row in doc.orders])
    return doc


def _current_rows(doctype, filters, fields, current=False):
    return frappe.db.get_values(doctype, filters, fields, as_dict=True, for_update=current, order_by='name asc')


def _dispatch_guard(doc, current=False):
    return dict(linked=_current_rows('CFG Kanban Dispatch Plan', {'office_delivery_trip': doc.name}, ['name'], current),
        vehicle=_current_rows('CFG Kanban Dispatch Plan', {'vehicle_warehouse': doc.get('vehicle_warehouse'),
            'state': ['in', sorted(office.EXECUTING)]}, ['name'], current) if doc.get('vehicle_warehouse') else [])


def _eligible(doc, current=False):
    errors = []
    guard = doc.flags.get('cfg_route_planner_dispatch_guard') if current else None
    guard = guard if guard is not None else _dispatch_guard(doc, current)
    if doc.state != 'Draft' or doc.get('driver_route_state') not in (None, '', 'Not Started'):
        errors.append('Use a saved, unstarted Draft Delivery Trip')
    if (doc.dispatch_plans or doc.get('open_route_plan') or doc.get('dispatch_generated_on')
            or guard['linked']):
        errors.append('Dispatch work has been generated; use existing preparation/recovery controls or a new Draft Trip')
    if doc.get('follow_on_of') or doc.get('follow_on_trip'):
        errors.append('Follow-on Trips remain in their controlled handover workflow')
    if doc.get('route_stock') or doc.get('allow_existing_lorry_sales'):
        errors.append('This pilot supports assigned customer orders only; shared/open-route stock is not modelled')
    if guard['vehicle']:
        errors.append(f'Lorry is already in dispatch execution ({guard["vehicle"][0].name}); resolve its existing work first')
    return errors


def _capture(doc, current=False):
    if len(doc.stops) > model.MAX_STOPS or len(doc.orders) > 250:
        frappe.throw('The mock pilot supports at most 50 stops and 250 exact Sales Order Item rows')
    errors = _eligible(doc, current)
    template = office._template(doc.route_template, doc.company, current=current)
    settings = _current_rows(SETTINGS, {'company': doc.company}, ['name'], current)
    setup = office._read(SETTINGS, settings[0].name, current=current) if len(settings) == 1 else None
    values = {f: setup.get(f) for f in ('enabled', 'provider', 'source_warehouse', 'vehicle_warehouse',
        'gates_verified', 'capacity_grams', 'max_stops', 'max_attempts_per_trip', 'shift_start', 'shift_end')} if setup else {}
    values.update(name=setup.name if setup else None, modified=_stamp(setup.modified) if setup else '')
    for field, target in [('start_location', 'start_pin'), ('end_location', 'end_pin')]:
        try:
            values[target] = delivery_pin(setup.get(field)) if setup else None
        except ValueError as exc:
            errors.append(f'{field}: {exc}')
    warehouses = []
    for field in ('source_warehouse', 'vehicle_warehouse'):
        if not doc.get(field):
            errors.append(f'Select the {field.replace("_", " ")}')
            continue
        wh = office._read('Warehouse', doc.get(field), current=current)
        if wh.company != doc.company or wh.is_group or wh.disabled:
            errors.append(f'{wh.name}: Warehouse is not an active leaf of this Company')
        if field == 'vehicle_warehouse' and not (wh.get('cfg_is_vehicle_warehouse') and wh.get('cfg_vehicle_reference')):
            errors.append(f'{wh.name}: configure the lorry Warehouse/vehicle reference')
        if doc.get(field) != values.get(field):
            errors.append(f'{field.replace("_", " ")} must match the company pilot settings')
        warehouses.append(dict(name=wh.name, company=wh.company, modified=_stamp(wh.modified), vehicle=wh.get('cfg_vehicle_reference')))
    # Do not pretend spare lorry stock has zero weight; this first pilot models only this load.
    lorry_stock = _current_rows('Bin', {'warehouse': doc.get('vehicle_warehouse'), 'actual_qty': ['!=', 0]},
        ['item_code', 'actual_qty'], current) if doc.get('vehicle_warehouse') else []
    if lorry_stock:
        errors.append(f'Lorry has existing ERP stock ({lorry_stock[0].item_code}); this pilot requires an empty lorry')
    stops = []
    for row in doc.stops:
        site = office._read('CFG Kanban Customer Scan Point', row.customer_scan_point, current=current) if row.customer_scan_point else None
        if not site or not site.active or site.selling_company != doc.company or site.customer != row.customer or (site.get('customer_address') or '') != (row.get('customer_address') or ''):
            errors.append(f'Stop {row.delivery_sequence}: Customer Site identity or Company changed')
        customer = office._read('Customer', row.customer, current=current)
        if customer.get('disabled'):
            errors.append(f'{row.customer}: Customer is disabled')
        address = office._address(row.get('customer_address'), row.customer)
        try:
            pin = delivery_pin(site.get('delivery_location')) if site else None
        except ValueError as exc:
            pin = None; errors.append(f'Stop {row.delivery_sequence}: {exc}')
        stops.append(dict(stop_key=row.stop_key, site_name=row.get('site_name'),
            customer=row.customer, customer_scan_point=row.customer_scan_point, customer_address=row.get('customer_address'),
            address=address, site_modified=_stamp(site.modified) if site else '',
            stop_purpose=row.stop_purpose, cancelled=bool(row.get('cancellation_request')),
            pin=pin, pin_verified=cint(site.get('planner_pin_verified')) if site else 0,
            **{f: str(row.get(f) or '') for f in ('planner_service_minutes', 'planner_window_start', 'planner_window_end')},
            planner_finish_by_close=cint(row.get('planner_finish_by_close'))))
    other = office._assignments([row.sales_order for row in doc.orders], doc.name, current=current)
    source_orders = {}; lines = []; seen = set()
    for row in doc.orders:
        identity = (row.sales_order, row.sales_order_item)
        if identity in seen:
            errors.append(f'Duplicate Sales Order Item: {row.sales_order} / {row.sales_order_item}')
        seen.add(identity)
        if row.sales_order not in source_orders:
            source_orders[row.sales_order] = office._order(row.sales_order, doc.company, doc.route_template, current=current, allow_unrouted=True)
        order = source_orders[row.sales_order]
        source, remaining = office._line(order, row.sales_order_item)
        stop = next((stop for stop in doc.stops if stop.stop_key == row.stop_key), None)
        if not stop or not office._matches_stop(order, stop):
            errors.append(f'{row.sales_order}: assignment does not match its exact Customer Site/address')
        item = office._read('Item', source.item_code, current=current)
        qty = office._quantity(row.planned_qty, source.stock_uom)
        if item.disabled or source.item_code != row.item_code or source.stock_uom != row.stock_uom:
            errors.append(f'{row.sales_order} / {source.item_code}: source Item/UOM changed or is disabled')
        if qty + other.get(identity, 0) > remaining + office.EPSILON:
            errors.append(f'{row.sales_order} / {source.item_code}: assigned quantity exceeds the current unassigned SO balance')
        due = source.get('delivery_date') or order.get('delivery_date')
        if due and str(due) > str(doc.trip_date):
            errors.append(f'{row.sales_order} / {source.item_code}: delivery is dated after this Trip')
        lines.append(dict(sales_order=row.sales_order, sales_order_item=row.sales_order_item,
            stop_key=row.stop_key, item_code=source.item_code, stock_uom=source.stock_uom,
            planned_qty=str(qty), planner_grams_per_stock_uom=str(row.get('planner_grams_per_stock_uom') or ''),
            is_stock_item=cint(item.is_stock_item), item_modified=_stamp(item.modified),
            source_modified=_stamp(order.modified), remaining=str(remaining), assigned_elsewhere=str(other.get(identity, 0)),
            conversion_factor=str(source.conversion_factor), delivery_date=str(due or '')))
    return dict(trip=dict(name=doc.name, company=doc.company, modified=_stamp(doc.modified),
        revision=cint(doc.planning_revision), trip_date=str(doc.trip_date), expected_return_date=str(doc.get('expected_return_date') or ''),
        sequence_policy=doc.sequence_policy, planner_enabled=cint(doc.get('planner_enabled')),
        planner_load_verified=cint(doc.get('planner_load_verified')), business=office._business(doc),
        template_modified=_stamp(template.modified)), settings=values, warehouses=warehouses,
        lorry_stock=[dict(row) for row in lorry_stock], stops=stops, lines=lines, errors=errors)


def _ready(doc, current=False):
    snapshot = _capture(doc, current)
    result = model.readiness(snapshot)
    return snapshot, result


def _require_ready(snapshot, result):
    if not result['ready']:
        frappe.throw('Route planning is blocked:\n' + '\n'.join(result['errors']))
    return model.fingerprint(snapshot)


def _attempts(trip, limit):
    rows = _current_rows(RUN, {'delivery_trip': trip.name, 'company': trip.company}, ['attempt_count'], True)
    if sum(cint(row.attempt_count) for row in rows) >= limit:
        frappe.throw('Mock planning attempt limit reached for this Trip; review the company pilot limit')


def _enqueue(run):
    frappe.enqueue('cfg_kanban.services.route_planner.solve_mock_run', queue='short', timeout=WORKER_SECONDS + 15,
        enqueue_after_commit=True, run_name=run.name, attempt=cint(run.attempt_count))


def _view(run, snapshot=None):
    saved = json.loads(run.snapshot_json)
    response = json.loads(run.response_json) if run.response_json else None
    captured_model = json.loads(run.model_json)
    labels = {f'S{i + 1:04d}': row for i, row in enumerate(saved['stops'])}
    rows = []
    for index, visit in enumerate((response or {}).get('visits') or []):
        stop = labels.get(visit.get('shipment_label'))
        if stop:
            rows.append(dict(stop_key=stop['stop_key'], site_name=stop['site_name'], customer=stop['customer'],
                original_sequence=list(labels).index(visit['shipment_label']) + 1,
                proposed_sequence=index + 1, start_time=visit.get('start_time')))
    stale = snapshot is not None and model.fingerprint(snapshot) != run.input_key
    return dict(name=run.name, status=run.status, provider=run.provider, source_revision=run.source_revision,
        requested_by=run.requested_by, requested_on=run.requested_on, attempt_count=run.attempt_count,
        original=[dict(stop_key=row['stop_key'], site_name=row['site_name'], customer=row['customer']) for row in saved['stops']],
        proposed=rows, stale=stale, failure=run.failure_message, decision_reason=run.decision_reason,
        accepted_by=run.accepted_by, accepted_on=run.accepted_on, resulting_revision=run.resulting_revision,
        preserve_order=captured_model['preserve_order'], end_time=(response or {}).get('end_time'))


@frappe.whitelist()
def get_planning_panel(trip_name):
    doc = _authorize(trip_name)
    snapshot, result = _ready(doc)
    names = frappe.get_list(RUN, filters={'delivery_trip': doc.name, 'company': doc.company}, pluck='name',
        order_by='creation desc', limit_page_length=10)
    runs = [_view(office._read(RUN, name), snapshot) for name in names]
    return dict(**result, settings=snapshot['settings'].get('name'), runs=runs,
                current_modified=doc.modified, provider=model.PROVIDER)


@frappe.whitelist()
def request_mock_proposal(trip_name, expected_modified):
    doc = _locked(trip_name)
    if _stamp(expected_modified) != _stamp(doc.modified):
        frappe.throw('The Trip changed; save/reload before requesting a proposal')
    snapshot, result = _ready(doc, current=True)
    key = _require_ready(snapshot, result)
    existing = _current_rows(RUN, {'input_key': key}, ['name'], True)
    if existing:
        return _view(office._read(RUN, existing[0].name, current=True), snapshot)
    _attempts(doc, cint(snapshot['settings']['max_attempts_per_trip']))
    run = _flag(frappe.get_doc(dict(doctype=RUN, delivery_trip=doc.name, company=doc.company,
        input_key=key, provider=model.PROVIDER, status='Queued', source_modified=_stamp(doc.modified),
        source_revision=doc.planning_revision, attempt_count=1, requested_by=frappe.session.user,
        requested_on=now_datetime(), snapshot_json=model.encode(snapshot), model_json=model.encode(result['model']))), True)
    run.insert(ignore_permissions=True)
    _enqueue(run)
    return _view(run, snapshot)


def _provider(payload):
    # Intentionally no user-selectable adapter, credentials, HTTP or arbitrary import path.
    return model.mock_solve(payload)


def solve_mock_run(run_name, attempt):
    """Worker phase: claim -> release locks -> bounded mock -> guarded result save."""
    run = frappe.get_doc(RUN, run_name, for_update=True)
    if run.status != 'Queued' or cint(run.attempt_count) != cint(attempt):
        return
    run.status, run.started_on = 'Running', now_datetime()
    _save(run)
    frappe.db.commit()  # Worker only. No provider call holds a document lock.
    started = time.monotonic()
    state, failure, response = 'Ready', None, None
    try:
        if run.provider != model.PROVIDER:
            raise ValueError('Only the mock provider is enabled')
        payload = json.loads(run.model_json)
        response = _provider(copy.deepcopy(payload))
        if time.monotonic() - started > WORKER_SECONDS:
            raise TimeoutError()
        model.validate_proposal(payload, response)
    except TimeoutError:
        state, failure, response = 'Timed Out', 'Mock deadline exceeded. Review the original run before explicitly retrying.', None
    except ValueError as exc:
        state, failure, response = 'Failed', str(exc)[:500], None
    except Exception:
        state, failure, response = 'Failed', 'Mock provider failed. No Trip order was changed; review and explicitly retry.', None
    run = frappe.get_doc(RUN, run_name, for_update=True)
    if run.status != 'Running' or cint(run.attempt_count) != cint(attempt):
        return
    run.status, run.failure_message, run.finished_on = state, failure, now_datetime()
    run.response_json = model.encode(response) if response else None
    _save(run)
    frappe.db.commit()


def _run_for_trip(run_name):
    run = office._read(RUN, run_name)
    doc = _locked(run.delivery_trip)
    if run.company != doc.company:
        frappe.throw('Planning Run belongs to another Company', frappe.PermissionError)
    return doc, office._read(RUN, run_name, current=True)


def _reason(value):
    result = str(value or '').strip()
    if not result or len(result) > 500:
        frappe.throw('Enter a decision/retry reason of 1 to 500 characters')
    return result


@frappe.whitelist()
def retry_mock_proposal(run_name, reason):
    doc, run = _run_for_trip(run_name)
    reason = _reason(reason)
    snapshot, result = _ready(doc, current=True)
    if _require_ready(snapshot, result) != run.input_key:
        frappe.throw('The original planning inputs changed; request a new proposal for the saved Trip')
    if run.status in ('Queued', 'Running', 'Ready', 'Accepted'):
        return _view(run, snapshot)
    if run.status not in ('Failed', 'Timed Out'):
        frappe.throw('Only a failed or interrupted mock solve can be retried')
    _attempts(doc, cint(snapshot['settings']['max_attempts_per_trip']))
    history = json.loads(run.attempt_history_json or '[]')
    history.append(dict(attempt=run.attempt_count, status=run.status, failure=run.failure_message,
                        prior_decision_by=run.decided_by, prior_decision_on=str(run.decided_on or ''), prior_decision_reason=run.decision_reason,
                        retry_by=frappe.session.user, retry_on=str(now_datetime()), reason=reason))
    run.attempt_history_json = model.encode(history)
    run.attempt_count = cint(run.attempt_count) + 1
    run.status, run.started_on, run.finished_on, run.failure_message, run.response_json = 'Queued', None, None, None, None
    _save(run); _enqueue(run)
    return _view(run, snapshot)


@frappe.whitelist()
def decide_mock_proposal(run_name, decision, reason):
    doc, run = _run_for_trip(run_name)
    reason = _reason(reason)
    if decision not in ('Accept', 'Reject', 'Mark Interrupted'):
        frappe.throw('Choose a valid planning decision and enter its reason')
    # Resolve a successful replay before mutable source/stage checks. Never reapply to a later edit.
    if run.status == 'Accepted' and decision == 'Accept':
        return dict(run=_view(run), accepted=True, already_recorded=True, trip=doc.name)
    if run.status == 'Rejected' and decision == 'Reject':
        return dict(run=_view(run), accepted=False, already_recorded=True, trip=doc.name)
    previous_status = run.status
    if decision == 'Mark Interrupted':
        if run.status == 'Timed Out':
            return dict(run=_view(run), accepted=False, already_recorded=True, trip=doc.name)
        if run.status not in ('Queued', 'Running') or (now_datetime() - get_datetime(run.started_on or run.requested_on)).total_seconds() <= WORKER_SECONDS + 60:
            frappe.throw('Only a queued/running mock older than 90 seconds can be marked interrupted')
        run.status, run.finished_on = 'Timed Out', now_datetime()
        run.failure_message = 'Office marked the mock worker interrupted; no Trip order was changed.'
    elif decision == 'Reject':
        if run.status not in ('Ready', 'Failed', 'Timed Out'):
            frappe.throw('Wait for this mock request to finish before rejecting it')
        run.status = 'Rejected'
    else:
        if run.status != 'Ready':
            frappe.throw('Only a Ready mock proposal can be accepted')
        snapshot, result = _ready(doc, current=True)
        key = _require_ready(snapshot, result)
        if key != run.input_key or model.fingerprint(json.loads(run.snapshot_json)) != run.input_key:
            frappe.throw('The Trip, source balances, pins, vehicle or settings changed; request a new proposal')
        captured_model = json.loads(run.model_json)
        if captured_model != result['model']:
            frappe.throw('Stored planning inputs differ from the saved Trip; request a new proposal')
        try:
            labels = model.validate_proposal(captured_model, json.loads(run.response_json))
        except ValueError as exc:
            frappe.throw(str(exc))
        mapping = {f'S{i + 1:04d}': row.stop_key for i, row in enumerate(doc.stops)}
        stops = {row.stop_key: row.as_dict() for row in doc.stops}
        doc.set('stops', [stops[mapping[label]] for label in labels])
        doc.planner_accepted_run, doc.planner_accepted_by, doc.planner_accepted_on = run.name, frappe.session.user, now_datetime()
        _flag(doc, True).save()  # Native permissions, exact SO validation, revisions and LIFO.
        run.status, run.accepted_by, run.accepted_on = 'Accepted', frappe.session.user, now_datetime()
        run.resulting_revision = doc.planning_revision
    run.decision_reason, run.decided_by, run.decided_on = reason, frappe.session.user, now_datetime()
    _save(run)
    record('Route Planning Decision', reference_doctype=office.TRIP, reference_name=doc.name,
        idempotency_key='route-planner:' + run.name + ':' + str(run.attempt_count) + ':' + decision,
        previous_state=previous_status, new_state=run.status,
        payload=dict(run=run.name, provider=run.provider, decision=decision, reason=run.decision_reason,
                     source_revision=run.source_revision, resulting_revision=run.resulting_revision))
    return dict(run=_view(run), accepted=run.status == 'Accepted', already_recorded=False, trip=doc.name)

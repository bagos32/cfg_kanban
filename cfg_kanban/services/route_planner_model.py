"""Pure, bounded single-day planning contract. The mock never calls a routing service."""
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json

PROVIDER = 'Mock (test only)'
MYT = dt.timezone(dt.timedelta(hours=8))
MAX_STOPS = 50


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def number(value, label, *, integer=False, maximum=1_000_000_000):
    try:
        if isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result > maximum:
            raise ValueError()
        if integer and result != result.to_integral_value():
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{label} must be a positive finite {"whole number" if integer else "number"}') from None


def clock(value, date):
    text = str(value or '')
    if text.count(':') in (1, 2) and len(text.split(':')[0]) == 1:
        text = '0' + text
    if len(text) == 5:
        text += ':00'
    try:
        time = dt.time.fromisoformat(text)
        if time.tzinfo or time.microsecond:
            raise ValueError()
        return dt.datetime.combine(date, time, MYT)
    except (ValueError, TypeError):
        raise ValueError('Enter a valid local time (HH:MM or HH:MM:SS)') from None


def point(value, label):
    if not isinstance(value, dict) or set(value) != {'latitude', 'longitude'}:
        raise ValueError(f'{label}: save one verified entrance pin')
    for key, bound in [('latitude', 90), ('longitude', 180)]:
        try:
            n = Decimal(str(value[key]))
            if isinstance(value[key], bool) or not n.is_finite() or abs(n) > bound:
                raise ValueError()
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f'{label}: invalid {key}') from None
    return {key: float(value[key]) for key in ('latitude', 'longitude')}


def readiness(snapshot):
    """Return every modelling blocker; do not change the input or any operational record."""
    errors = list(snapshot.get('errors') or [])
    warnings = ['Mock fixture only: reversed flexible order and ten-minute legs; no road, traffic or savings estimate.']
    trip, setup = snapshot['trip'], snapshot.get('settings') or {}
    if not setup.get('enabled'):
        errors.append('Enable the company Mock Route Planner Settings for this test pilot')
    if setup.get('provider') != PROVIDER:
        errors.append('Only the mock provider is supported in this package')
    if not trip.get('planner_enabled'):
        errors.append('Enable Mock Route Planner on this Draft Trip')
    if not trip.get('planner_load_verified'):
        errors.append('Confirm packed-weight conversions, vehicle/site access and volume/segregation fit on the Trip')
    model = {'vehicle_label': 'V0001', 'shipments': [], 'preserve_order': trip.get('sequence_policy') == 'Planned Order'}
    if model['preserve_order']:
        warnings.append('Planned Order is preserved. Change the manual Draft order first if another order is required.')
    try:
        date = dt.date.fromisoformat(str(trip['trip_date']))
        if trip.get('expected_return_date') and str(trip['expected_return_date']) != str(date):
            raise ValueError('This pilot supports one day; Expected Return Date must equal Trip Date or be blank')
        start, end = clock(setup.get('shift_start'), date), clock(setup.get('shift_end'), date)
        if end <= start:
            raise ValueError('The single-day return deadline must be after the departure time')
        model.update(start_time=start.isoformat(), end_time=end.isoformat(),
                     start_location=point(setup.get('start_pin'), 'Depot start gate'),
                     end_location=point(setup.get('end_pin'), 'Depot return gate'),
                     capacity_grams=int(number(setup.get('capacity_grams'), 'Usable payload (grams)', integer=True)))
    except (KeyError, ValueError) as exc:
        errors.append(str(exc))
        date = None
    if not setup.get('gates_verified'):
        errors.append('Verify both depot gates in Mock Route Planner Settings')
    stops = snapshot.get('stops') or []
    try:
        stop_limit = int(number(setup.get('max_stops'), 'Maximum visits', integer=True, maximum=MAX_STOPS))
    except ValueError as exc:
        errors.append(str(exc)); stop_limit = MAX_STOPS
    if not 1 <= len(stops) <= stop_limit:
        errors.append('The stop count exceeds the configured pilot limit, or there are no stops')
    keys = [s.get('stop_key') for s in stops]
    if len(set(keys)) != len(keys) or any(not key for key in keys):
        errors.append('Every visit must retain a distinct stable stop identity')
    demand = {}; total = 0
    identities = set()
    for row in snapshot.get('lines') or []:
        identity = (row.get('sales_order'), row.get('sales_order_item'))
        if identity in identities:
            errors.append(f'Duplicate Sales Order Item assignment: {identity[0]} / {identity[1]}')
        identities.add(identity)
        if row.get('stop_key') not in keys:
            errors.append(f'Order {identity[0]} / {identity[1]} has no matching delivery visit')
        if not row.get('is_stock_item'):
            continue
        try:
            qty = number(row.get('planned_qty'), 'Assigned stock quantity')
            grams = number(row.get('planner_grams_per_stock_uom'), 'Packed grams per Stock UOM')
            load = int((qty * grams).to_integral_value(rounding=ROUND_CEILING))
            demand[row.get('stop_key')] = demand.get(row.get('stop_key'), 0) + load
            total += load
        except ValueError as exc:
            errors.append(f'{identity[0]} / {row.get("item_code")}: {exc}')
    if total > model.get('capacity_grams', 0):
        errors.append(f'Packed load {total} g exceeds usable payload {model.get("capacity_grams", 0)} g')
    for index, stop in enumerate(stops):
        label = f'S{index + 1:04d}'
        prefix = f'Stop {index + 1} ({stop.get("site_name") or stop.get("stop_key")})'
        try:
            if stop.get('stop_purpose') != 'Delivery' or stop.get('cancelled'):
                raise ValueError('Only uncancelled confirmed Delivery stops are supported in this pilot')
            if not stop.get('pin_verified'):
                raise ValueError('Verify the Customer Site entrance pin')
            pin = point(stop.get('pin'), prefix)
            seconds = number(stop.get('planner_service_minutes'), 'Service minutes', maximum=480) * 60
            if seconds != seconds.to_integral_value():
                raise ValueError('Service duration must resolve to whole seconds')
            if not demand.get(stop.get('stop_key')):
                raise ValueError('Assign at least one submitted stock Sales Order Item to this visit')
            if date is None:
                continue
            opening = clock(stop.get('planner_window_start'), date)
            closing = clock(stop.get('planner_window_end'), date)
            latest = closing - dt.timedelta(seconds=int(seconds)) if stop.get('planner_finish_by_close') else closing
            if latest < opening or closing <= opening or opening < start or closing > end:
                raise ValueError('Receiving window/service duration must fit the same-day departure and return window')
            model['shipments'].append(dict(label=label, arrival_location=pin, service_seconds=int(seconds),
                earliest_start=opening.isoformat(), latest_start=latest.isoformat(), load_grams=demand[stop['stop_key']]))
        except ValueError as exc:
            errors.append(f'{prefix}: {exc}')
    return dict(ready=not errors, errors=errors, warnings=warnings,
                model=model if not errors else None, total_load_grams=total)


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(MYT)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Proposal contains an invalid or undated service time') from None


def mock_solve(model):
    """A deterministic contract fixture, deliberately not a route optimizer."""
    shipments = list(model['shipments'])
    if not model['preserve_order']:
        shipments.reverse()
    current = timestamp(model['start_time'])
    visits = []
    for shipment in shipments:
        current = max(current + dt.timedelta(minutes=10), timestamp(shipment['earliest_start']))
        visits.append(dict(shipment_label=shipment['label'], start_time=current.isoformat()))
        current += dt.timedelta(seconds=shipment['service_seconds'])
    return dict(vehicle_label=model['vehicle_label'], visits=visits, skipped_shipments=[],
                end_time=(current + dt.timedelta(minutes=10)).isoformat())


def validate_proposal(model, response):
    """Never accept an omitted, unknown, duplicated, late or wrong-vehicle mandatory visit."""
    if not isinstance(response, dict) or response.get('vehicle_label') != model['vehicle_label']:
        raise ValueError('Proposal contains the wrong vehicle')
    if set(response) != {'vehicle_label', 'visits', 'skipped_shipments', 'end_time'}:
        raise ValueError('Mock response contains unsupported or missing fields')
    if response.get('skipped_shipments') != []:
        raise ValueError('Proposal skipped a mandatory delivery; keep the manual Trip')
    visits = response.get('visits')
    if not isinstance(visits, list) or len(visits) != len(model['shipments']) or len(visits) > MAX_STOPS:
        raise ValueError('Proposal must contain every mandatory visit exactly once')
    expected = {row['label']: row for row in model['shipments']}
    if any(not isinstance(row, dict) or set(row) != {'shipment_label', 'start_time'} for row in visits):
        raise ValueError('Mock visits contain unsupported or missing fields')
    labels = [row.get('shipment_label') if isinstance(row, dict) else None for row in visits]
    if any(not isinstance(label, str) for label in labels) or len(set(labels)) != len(labels) or set(labels) != set(expected):
        raise ValueError('Proposal contains duplicate, unknown or missing visits')
    if model['preserve_order'] and labels != list(expected):
        raise ValueError('Proposal changed the required Planned Order')
    current = timestamp(model['start_time'])
    for row in visits:
        shipment = expected[row['shipment_label']]
        service = timestamp(row.get('start_time'))
        if service < current or not timestamp(shipment['earliest_start']) <= service <= timestamp(shipment['latest_start']):
            raise ValueError(f'{shipment["label"]}: proposed service is out of sequence or outside its receiving window')
        current = service + dt.timedelta(seconds=shipment['service_seconds'])
    end = timestamp(response.get('end_time'))
    if end < current or end > timestamp(model['end_time']):
        raise ValueError('Proposal cannot return within the single-day shift')
    return labels


def planning_metadata(doc):
    return dict(enabled=bool(doc.get('planner_enabled')), verified=bool(doc.get('planner_load_verified')),
        stops=sorted((row.stop_key, str(row.get('planner_service_minutes') or ''),
            str(row.get('planner_window_start') or ''), str(row.get('planner_window_end') or ''),
            bool(row.get('planner_finish_by_close'))) for row in doc.stops
            if any(row.get(f) for f in ('planner_service_minutes', 'planner_window_start', 'planner_window_end', 'planner_finish_by_close'))),
        lines=sorted((row.sales_order, row.sales_order_item, str(row.get('planner_grams_per_stock_uom') or ''))
                     for row in doc.orders if row.get('planner_grams_per_stock_uom')))


def protect_trip_metadata(doc, before):
    """Default-off fields do not change ordinary execution hashes or require a provider."""
    internal = bool((getattr(doc, 'flags', None) or {}).get('cfg_route_planner'))
    controlled = ('planner_accepted_run', 'planner_accepted_by', 'planner_accepted_on')
    if not internal and any((doc.get(f) or None) != (before.get(f) or None if before else None) for f in controlled):
        raise ValueError('Route planner acceptance facts are controlled; use Accept Mock Proposal')
    if before and planning_metadata(doc) != planning_metadata(before):
        if (before.state != 'Draft' or doc.state != 'Draft' or before.dispatch_plans
                or before.get('open_route_plan') or before.get('dispatch_generated_on')
                or before.get('driver_route_state') not in (None, '', 'Not Started')):
            raise ValueError('Change planner inputs only on an editable Draft before generating dispatch work')

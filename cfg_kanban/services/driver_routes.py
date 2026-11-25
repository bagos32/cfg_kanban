"""Driver visibility over saved office trips and existing delivery records.

No route publication, stock allocation, visit completion or ERP posting is performed here.
"""
import math

import frappe
from frappe.utils import cint, flt, now_datetime
from cfg_kanban.services.operator_auth import require_operator, public_operator

TRIP = 'CFG Kanban Delivery Trip'
PLAN = 'CFG Kanban Dispatch Plan'
SHEET = 'CFG Kanban Route Sheet'
ALLOCATION = 'CFG Kanban Dispatch Allocation'
DELIVERY_ALLOCATION = 'CFG Kanban Delivery Allocation'
TERMINAL = {'Completed with refusal', 'Completed', 'Cancelled', 'Closed Incomplete', 'Visit completed'}
LOADED = {'Loaded', 'In Fulfilment', 'Fulfilled'}
EPSILON = 0.000001


def _delivery():
    from cfg_kanban.services import customer_delivery
    return customer_delivery


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def _access(token, interactive=0):
    # A passive route display must not keep an unattended terminal session alive.
    operator, session = require_operator(token, touch_activity=bool(cint(interactive)))
    _delivery()._require_customer_delivery(operator)
    return operator, session


def _all(operator):
    return bool(operator.kanban_role in ('Supervisor', 'Development Proxy')
                and operator.get('view_all_responsibilities'))


def assigned(doc, operator):
    return bool(doc.driver == operator.employee or any(row.employee == operator.employee for row in doc.get('assistant_drivers') or []))


def _trip(name, operator):
    doc = _read(TRIP, name)
    if not (_all(operator) or assigned(doc, operator)):
        frappe.throw('This Delivery Trip is not assigned to this driver', frappe.PermissionError)
    _read('Company', doc.company)
    return doc


def _header(doc):
    return dict(name=doc.name, follow_on_of=doc.get('follow_on_of'),follow_on_trip=doc.get('follow_on_trip'),return_only=bool(doc.get('follow_on_of') and not doc.stops),trip_title=doc.trip_title or doc.name, company=doc.company,
                route_template=doc.route_template, trip_date=doc.trip_date,
                expected_return_date=doc.expected_return_date, driver=doc.driver,driver_display=trip_driver_display(doc),
                gps_auto_start=bool(cint(doc.get('gps_auto_start'))),gps_publish_interval_seconds=doc.get('gps_publish_interval_seconds') or 15,
                assistant_drivers=[dict(employee=r.employee,employee_name=r.employee_name) for r in doc.get('assistant_drivers') or []],
                team_revision=cint(doc.get('team_revision')),
                planning_state=doc.state, driver_route_state=doc.get('driver_route_state') or 'Not Started', vehicle_warehouse=trip_vehicle_warehouse(doc),
                region=doc.region, direction=doc.direction,
                office_sequence_policy=doc.sequence_policy, planning_revision=doc.planning_revision)


def trip_driver_display(doc):
    if not doc.driver:return ''
    name=frappe.db.get_value('Employee',doc.driver,'employee_name')
    return str(name)+' ('+doc.driver+')' if name and name!=doc.driver else doc.driver


def trip_vehicle_warehouse(doc):
    """Use the certified departure for older trips whose planning header stayed blank."""
    name=doc.vehicle_warehouse
    if doc.get('driver_route_state') not in ('In Progress','Completed','Closed Incomplete') or not doc.get('driver_route_snapshot_json'):
        return name
    import json
    try:saved=json.loads(doc.driver_route_snapshot_json)
    except (ValueError,TypeError):frappe.throw('Reconcile the Trip departure lorry snapshot')
    if not isinstance(saved,dict) or (saved.get('vehicle') is not None and not isinstance(saved['vehicle'],str)):
        frappe.throw('Reconcile the Trip departure lorry snapshot')
    vehicle=saved.get('vehicle')
    if name and name!=vehicle:frappe.throw('Trip Lorry Warehouse differs from its frozen departure; Supervisor review required')
    return vehicle or name


@frappe.whitelist()
def get_driver_trips(operator_session_token, include_closed=0, start=0, page_length=30, interactive=0):
    operator, session = _access(operator_session_token, interactive)
    filters = {}
    choices = {}
    if not _all(operator):
        assistant_trips = frappe.get_all('CFG Kanban Trip Assistant', filters={'employee':operator.employee,
            'parenttype':TRIP,'parentfield':'assistant_drivers'}, pluck='parent',limit_page_length=0)
        if assistant_trips:
            choices['or_filters'] = {'driver':operator.employee,'name':['in',assistant_trips]}
        else:
            filters['driver'] = operator.employee
    if not cint(include_closed):
        filters['state'] = ['in', ['Draft', 'Planned']]
    start = max(0, cint(start)); size = max(1, min(cint(page_length) or 30, 100))
    names = frappe.get_list(TRIP, filters=filters, pluck='name',
        order_by='trip_date asc, name asc', limit_start=start, limit_page_length=size + 1, **choices)
    rows = []
    for name in names[:size]:
        # get_list and each source permission remain authoritative under native User Permissions.
        doc = _trip(name, operator)
        rows.append(_header(doc))
    identity = public_operator(operator, session)
    return dict(trips=rows, start=start, page_length=size, has_more=len(names) > size,
        operator=dict({key: identity.get(key) for key in ('employee', 'employee_name', 'kanban_role')},
                      can_override=bool(cint(operator.get('can_override')))),
        can_view_all=_all(operator), refreshed_on=now_datetime())


def _qty(value):
    qty = flt(value)
    if not math.isfinite(qty) or qty < -EPSILON:
        frappe.throw('Source quantities need Supervisor review before displaying this route')
    return max(0, qty)


def _cached(cache, doctype, name):
    key = (doctype, name)
    if key not in cache:
        cache[key] = _read(doctype, name)
    return cache[key]


def _warehouse(cache, name, company):
    if not name:
        return None
    warehouse = _cached(cache, 'Warehouse', name)
    if warehouse.company != company:
        frappe.throw('Trip source Warehouse belongs to another Company', frappe.PermissionError)
    return warehouse


def _stop(doc, source, cache):
    from cfg_kanban.services.customer_locations import pin_projection
    location=pin_projection(None)
    customer = _cached(cache, 'Customer', source.customer)
    if source.customer_address:
        address = _cached(cache, 'Address', source.customer_address)
        if not any(link.link_doctype == 'Customer' and link.link_name == source.customer
                   for link in address.get('links') or []):
            frappe.throw('Trip Customer Address no longer matches; ask the office to review it')
    if source.customer_scan_point:
        site = _cached(cache, 'CFG Kanban Customer Scan Point', source.customer_scan_point)
        if (site.selling_company != doc.company or site.customer != source.customer
                or site.customer_address != source.customer_address):
            frappe.throw('Trip Customer Site no longer matches its Company, Customer or address')
        location=pin_projection(site.get('delivery_location'))
    return dict(stop_key=source.stop_key, office_sequence=cint(source.delivery_sequence),
        sequence=cint(source.delivery_sequence), purpose=source.stop_purpose or 'Delivery',
        customer=source.customer, customer_name=customer.customer_name or source.customer,
        site_name=source.site_name or customer.customer_name or source.customer,
        customer_site=source.customer_scan_point, customer_address=source.customer_address,
        address=source.address_display or '', instructions=source.instructions or '',
        state='Visit planned' if source.stop_purpose == 'Visit Only' else 'Awaiting preparation',
        driver_completed_on=source.get('driver_completed_on'), driver_completed_by=source.get('driver_completed_by'),
        driver_visit_notes=source.get('driver_visit_notes'), items=[], sources=[], plans=[], route_sheets=[], warnings=[], **location)


def _items(doc, stops, cache):
    groups = {}
    for row in doc.orders:
        stop = stops.get(row.stop_key)
        if stop and stop.get('cancelled'):continue
        if not stop or stop['purpose'] != 'Delivery':
            frappe.throw('Trip order has no exact delivery stop; ask the office to review it')
        order = _cached(cache, 'Sales Order', row.sales_order)
        if order.company != doc.company or order.customer != stop['customer']:
            frappe.throw('Trip Sales Order belongs to another Company or Customer')
        item = _cached(cache, 'Item', row.item_code)
        key = (row.stop_key, row.item_code, row.stock_uom)
        values = groups.setdefault(key, dict(item_code=row.item_code,
            item_name=row.item_name or item.item_name or row.item_code, stock_uom=row.stock_uom,
            is_stock_item=cint(row.is_stock_item), planned_qty=0, prepared_qty=0,
            loaded_qty=0, delivered_qty=0, remaining_qty=0, unprepared_qty=0, orders=[]))
        values['planned_qty'] += _qty(row.planned_qty)
        if not any(source['sales_order'] == row.sales_order for source in values['orders']):
            values['orders'].append(dict(sales_order=row.sales_order, customer_po=row.customer_po or ''))
    for (stop_key, _item, _uom), values in groups.items():
        stops[stop_key]['items'].append(values)
    return groups


def _session(plan, operator, cache):
    if not plan.delivery_session:
        return dict(state='Not Started', accessible=False, name=None, posted_note=None, needs_review=False)
    delivery = _cached(cache, 'CFG Kanban Delivery Session', plan.delivery_session)
    if (delivery.dispatch_plan != plan.name or delivery.selling_company != plan.company
            or delivery.customer_scan_point != plan.customer_site or delivery.customer != plan.customer):
        frappe.throw('Linked Delivery Session does not match this trip source')
    accessible = _delivery()._can_view_delivery(operator, delivery)
    note = _cached(cache, 'Delivery Note', delivery.delivery_note) if delivery.delivery_note else None
    if note and (note.company != plan.company or note.customer != plan.customer):
        frappe.throw('Delivery Note does not match this trip Company or Customer')
    posted = bool(note and note.docstatus == 1 and not note.is_return)
    all_refused = _full_refusal(delivery) if delivery.get('driver_delivery_outcome') else False
    needs_review = bool((delivery.state in ('Delivered', 'Invoiced', 'Closed') and not posted and not all_refused)
                        or (note and note.docstatus == 2 and delivery.state != 'Cancelled'))
    return dict(state=delivery.state, accessible=accessible, name=delivery.name if accessible else None,
                posted_note=note.name if posted else None, needs_review=needs_review)


def _posted_load(plan, cache):
    if plan.get('follow_on_trip'):
        from cfg_kanban.services.trip_carry_in import validate_loading
        validate_loading(plan)
        return True
    if not plan.movement_manifest:
        return False
    manifest = _cached(cache, 'CFG Kanban Movement Manifest', plan.movement_manifest)
    if manifest.source_company != plan.company or manifest.destination_warehouse != plan.vehicle_warehouse:
        frappe.throw('Loading Manifest no longer matches the trip Company or lorry')
    if not manifest.dispatch_stock_entry:
        return False
    entry = _cached(cache, 'Stock Entry', manifest.dispatch_stock_entry)
    if entry.company != plan.company:
        frappe.throw('Loading Stock Entry belongs to another Company', frappe.PermissionError)
    return entry.docstatus == 1


def _plan_state(plan, session):
    if session['needs_review'] or plan.state == 'Exception' or plan.dispatch_review_state not in (None, '', 'Settled'):
        return 'Review required'
    if session['state'] == 'Closed':
        return 'Completed' if plan.fulfilment_status == 'Completed' else 'Review required'
    if session['state'] in ('Delivered', 'Invoiced'):
        return 'Awaiting proof'
    if session['state'] == 'ERP Document Pending':
        return 'Delivery Note pending'
    if session['state'] not in ('Not Started', 'Cancelled'):
        return 'In Progress'
    if plan.state == 'Cancelled':
        return 'Cancelled'
    if plan.state == 'Reconciled':
        return 'Closed Incomplete'
    return 'Loaded' if plan.state == 'Loaded' else 'Awaiting loading'


def _plan(doc, link, stop, operator, cache):
    plan = _cached(cache, PLAN, link.dispatch_plan)
    if (plan.company != doc.company or plan.plan_type != 'Customer Order'
            or plan.fulfilment_mode != 'Vehicle Delivery' or plan.customer_site != stop['customer_site']
            or plan.customer != stop['customer'] or not plan.sales_order):
        frappe.throw('Linked Dispatch Plan does not match this trip stop')
    if plan.sales_order not in {source['sales_order'] for item in stop['items'] for source in item['orders']}:
        frappe.throw('Linked Dispatch Plan has no assigned Sales Order at this stop')
    _warehouse(cache, plan.source_warehouse, doc.company)
    _warehouse(cache, plan.vehicle_warehouse, doc.company)
    session = _session(plan, operator, cache)
    posted = _posted_load(plan, cache)
    result = dict(name=plan.name, state=plan.state, visit_state=_plan_state(plan, session),
        sales_order=plan.sales_order, vehicle_warehouse=plan.vehicle_warehouse,
        fulfilment_status=plan.fulfilment_status or 'Not Started', load_posted=posted,
        loading_evidence='Confirmed existing lorry stock' if plan.get('follow_on_trip') else 'Loading Stock Entry',
        delivery_session=session['name'], delivery_note=session['posted_note'],
        session_accessible=session['accessible'], session_state=session['state'])
    if plan.state == 'Loaded' and not posted:
        stop['warnings'].append('Loading is not confirmed by a submitted Stock Entry')
    if plan.delivery_session and not session['accessible'] and session['state'] not in ('Closed', 'Cancelled'):
        stop['warnings'].append('The existing Delivery Session belongs to another operator')
    stop['plans'].append(result)
    return plan, session, posted


def _allocations(plan, session, posted, stop, groups, cache):
    # Permission-check every named source: a restricted query must not silently understate a load.
    names = frappe.get_all(ALLOCATION, filters={'dispatch_plan': plan.name,
        'state': ['not in', ['Released', 'Cancelled']]}, pluck='name', order_by='name asc', limit_page_length=0)
    allocations = [_cached(cache, ALLOCATION, name) for name in names]
    delivered = {}
    refusals = _refusals(plan) if plan.get('driver_delivery_outcome') else {}
    if allocations:
        usage = frappe.get_all(DELIVERY_ALLOCATION, filters={'dispatch_allocation': ['in', names],
            'state': 'Delivered'}, pluck='name', order_by='name asc', limit_page_length=0)
        for name in usage:
            row = _cached(cache, DELIVERY_ALLOCATION, name)
            if row.delivery_session != plan.delivery_session:
                stop['warnings'].append('An allocation has delivery feedback outside the current Session; Supervisor review required')
                continue
            if session['posted_note']:
                delivered[row.dispatch_allocation] = delivered.get(row.dispatch_allocation, 0) + _qty(row.delivered_qty)
    for row in allocations:
        key = (stop['stop_key'], row.item_code, row.stock_uom)
        group = groups.get(key)
        if not group or not group['is_stock_item']:
            frappe.throw('Dispatch allocation does not match the trip Item and stock UOM')
        qty = _qty(row.allocated_qty); used = delivered.get(row.name, 0)
        if used > qty + EPSILON:
            frappe.throw('Delivery quantities exceed the prepared allocation; Supervisor review required')
        loaded = qty if posted and row.state in LOADED else 0
        refused = refusals.get(row.name,{})
        refused_qty = refused.get('refused_qty',0)
        remaining = max(0, loaded - used - refused_qty)
        group['prepared_qty'] += qty; group['loaded_qty'] += loaded
        group['delivered_qty'] += used; group['remaining_qty'] += remaining
        group['refused_qty'] = group.get('refused_qty',0) + refused_qty
        stop['sources'].append(dict(dispatch_plan=plan.name, dispatch_allocation=row.name,
            item_code=row.item_code, stock_uom=row.stock_uom, allocation_kind=row.allocation_kind,
            tag_code=row.visible_code if row.allocation_kind == 'Tagged Stock' else None,
            batch_no=row.batch_no, assigned_qty=qty, loaded_qty=loaded, delivered_qty=used,
            remaining_qty=remaining, source_state=row.state,refused_qty=refused_qty,
            refused_stock_state=refused.get('stock_state'),refused_warehouse=refused.get('current_warehouse'),qc_return_case=refused.get('qc_return_case'),
            refusal_outcome=refused.get('outcome')))


def _stop_state(stop):
    if stop['purpose'] == 'Visit Only':
        return 'Visit completed' if stop.get('driver_completed_on') else 'Visit planned'
    states = [plan['visit_state'] for plan in stop['plans']]
    if not states:
        return 'Awaiting preparation'
    for state in ('Review required', 'Awaiting proof', 'Delivery Note pending', 'In Progress'):
        if state in states:
            return state
    if all(state in TERMINAL for state in states):
        if all(state == 'Completed' for state in states) and all(
                not item['is_stock_item'] or item['delivered_qty'] + item.get('refused_qty',0) + EPSILON >= item['planned_qty'] for item in stop['items']):
            return 'Completed with refusal' if any(r.get('refused_qty',0)>EPSILON for r in stop['items']) else 'Completed'
        return 'Closed Incomplete'
    complete_load = all(not item['is_stock_item'] or item['loaded_qty'] + EPSILON >= item['planned_qty']
                        for item in stop['items'])
    if all(state == 'Loaded' for state in states) and complete_load and not stop['warnings']:
        return 'Loaded'
    return 'Partially loaded' if any(item['loaded_qty'] > EPSILON for item in stop['items']) else 'Awaiting loading'


def _route_order(doc, stops, plans, cache, warnings):
    names = sorted({plan.active_route_sheet for plan in plans.values() if plan.active_route_sheet})
    required = any(plan.route_approval_required or plan.route_sequence_scope == 'Combined Lorry Trip' or plan.active_route_sheet
                   for plan in plans.values())
    by_plan = {link.dispatch_plan: link.stop_key for link in doc.dispatch_plans}
    approved = []; projected = None
    for name in names:
        sheet = _cached(cache, SHEET, name)
        if sheet.company != doc.company:
            frappe.throw('Route Sheet belongs to another Company', frappe.PermissionError)
        if any(plan.vehicle_warehouse != sheet.vehicle_warehouse for plan in plans.values() if plan.active_route_sheet == name):
            warnings.append('Approved Route Sheet lorry does not match the linked load; Supervisor review required')
            continue
        rows = []
        for row in sheet.stops:
            key = by_plan.get(row.dispatch_plan)
            if row.dispatch_plan==doc.get('open_route_plan'):
                from cfg_kanban.services.trip_sales import sheet_target
                key=sheet_target(doc,row)
            if not key or stops[key]['customer_site'] != row.customer_scan_point:
                rows.append(None)
                continue
            rows.append(key)
            stops[key]['route_sheets'].append(dict(name=sheet.name, state=sheet.state,
                delivery_sequence=len(rows), sequence_policy=sheet.sequence_policy,
                verification_policy=sheet.verification_policy))
        if sheet.state in ('Approved', 'In Progress', 'Ready to Close'):
            approved.append(sheet)
            distinct = []
            for key in rows:
                if not distinct or distinct[-1] != key:
                    distinct.append(key)
            delivery_keys = {key for key, stop in stops.items() if stop['purpose'] == 'Delivery' or (doc.get('open_route_plan') and stop['customer_site'])}
            if (None not in rows and set(rows) == delivery_keys and len(distinct) == len(set(distinct))
                    and (len(delivery_keys) == len(stops) or bool(doc.get('open_route_plan')))
                    and {row.dispatch_plan for row in sheet.stops} == set(plans)
                    and len(sheet.stops) == (len(doc.dispatch_plans)+sum(1 for r in doc.stops if r.stop_purpose=='Visit Only' and r.customer_scan_point) if doc.get('open_route_plan') else len(plans))
                    and all(plan.active_route_sheet == sheet.name for plan in plans.values())):
                projected = distinct
    source = 'Office plan'
    if len(approved) == 1 and projected:
        source = 'Approved Route Sheet'
        ordered = [stops[key] for key in projected]
    else:
        ordered = list(stops.values())
        if required and not approved:
            warnings.append('Supervisor route approval is required before delivery; the displayed order is the office plan')
        elif approved:
            warnings.append('Operational routes do not map one-to-one to all office stops; review the approved route before delivery')
    for index, stop in enumerate(ordered, 1):
        stop['sequence'] = index
    return ordered, source


@frappe.whitelist()
def get_driver_trip(trip_name, operator_session_token, interactive=0):
    operator, _session = _access(operator_session_token, interactive)
    doc = _trip(trip_name, operator); cache = {}; warnings = []
    _warehouse(cache, doc.vehicle_warehouse, doc.company)
    stops = {}
    for row in doc.stops:
        if not row.stop_key or row.stop_key in stops:
            frappe.throw('Trip stops require distinct identities; ask the office to review them')
        if row.get('cancellation_request'):
            from cfg_kanban.services.trip_stop_cancellation import history_stop
            stops[row.stop_key]=history_stop(doc,row)
        else:stops[row.stop_key] = _stop(doc, row, cache)
    groups = _items(doc, stops, cache)
    plans = {}; vehicles = set()
    for link in doc.dispatch_plans:
        stop = stops.get(link.stop_key)
        if not stop or link.dispatch_plan in plans:
            frappe.throw('Trip Dispatch Plan links need office review')
        if stop.get('cancelled'):
            plan=_cached(cache,PLAN,link.dispatch_plan)
            if plan.company!=doc.company or plan.stop_cancellation!=stop['cancellation_request']:frappe.throw('Cancelled stop Plan no longer matches its decision')
            plans[plan.name]=plan
            stop['plans'].append(dict(name=plan.name,state=plan.state,sales_order=plan.sales_order))
            continue
        plan, session, posted = _plan(doc, link, stop, operator, cache)
        plans[plan.name] = plan
        if plan.vehicle_warehouse:
            vehicles.add(plan.vehicle_warehouse)
        _allocations(plan, session, posted, stop, groups, cache)
    if doc.get('open_route_plan'):
        shared=_cached(cache,'CFG Kanban Dispatch Plan',doc.open_route_plan)
        if shared.vehicle_warehouse:vehicles.add(shared.vehicle_warehouse)
    departure_vehicle=trip_vehicle_warehouse(doc)
    if departure_vehicle:
        vehicles.add(departure_vehicle)
    if len(vehicles) > 1:
        warnings.append('Trip sources are assigned to different lorries; Supervisor review required')
    for stop in stops.values():
        if stop.get('cancelled'):continue
        for item in stop['items']:
            if item['prepared_qty'] > item['planned_qty'] + EPSILON:
                frappe.throw('Prepared quantities exceed office trip assignments; Supervisor review required')
            item['unprepared_qty'] = max(0, item['planned_qty'] - item['prepared_qty']) if item['is_stock_item'] else 0
        stop['state'] = _stop_state(stop)
    open_pool=None
    if doc.get('open_route_plan'):
        from cfg_kanban.services.trip_sales import projection
        open_pool=projection(doc,stops,operator)
        plans[shared.name]=shared
    if doc.get('driver_route_state') == 'In Progress':
        for stop in stops.values():
            if stop['state'] in ('Completed','Completed with refusal') and not stop.get('driver_completed_on'):
                stop['state'] = 'Awaiting stop completion'
            elif (stop['stop_key'] == doc.get('driver_active_stop_key') and not stop.get('driver_completed_on')
                  and stop['state'] not in ('Review required', 'Awaiting proof', 'Delivery Note pending')):
                stop['state'] = 'In Progress'
    ordered, source = _route_order(doc, stops, plans, cache, warnings)
    source_stop_order=[r['stop_key'] for r in ordered]
    if any(r.get('cancellation_request') for r in doc.stops) and doc.driver_route_snapshot_json:
        import json
        source_stop_order=json.loads(doc.driver_route_snapshot_json).get('stop_order') or source_stop_order
    sequence=None
    if doc.get('route_sequence_revision') is not None:
        from cfg_kanban.services.trip_sequence import project
        ordered,sequence=project(doc,ordered,operator)
        if sequence and sequence.get('source'):source=sequence['source']
    cancelled_stops=[row for row in ordered if row.get('cancelled')]
    ordered=[row for row in ordered if not row.get('cancelled')]
    for n,row in enumerate(ordered,1):row['sequence']=n
    active = [stop for stop in ordered if stop['state'] in ('In Progress', 'Awaiting proof', 'Delivery Note pending', 'Awaiting stop completion')]
    pending = [stop for stop in ordered if stop['state'] not in TERMINAL]
    current = active[0] if len(active) == 1 else None
    if len(active) > 1:
        warnings.append('More than one customer delivery is active; Supervisor review required')
    next_stop = current or (pending[0] if pending and len(active) <= 1 else None)
    if doc.state in ('Closed', 'Cancelled') or doc.get('driver_route_state') == 'Completed' or len(vehicles) > 1:
        next_stop = current = None
    vehicle = _warehouse(cache, next(iter(vehicles)), doc.company) if len(vehicles) == 1 else None
    return dict(trip=_header(doc), stops=ordered, source_stop_order=source_stop_order, route_sequence=sequence, warnings=list(dict.fromkeys(warnings)),
        sequence_source=source, current_stop_key=current['stop_key'] if current else None,
        next_stop_key=next_stop['stop_key'] if next_stop else None,
        completed_stops=sum(stop['state'] in ('Completed', 'Completed with refusal', 'Visit completed') for stop in ordered), total_stops=len(ordered),
        vehicle_warehouse=vehicle.name if vehicle else None,
        vehicle_reference=vehicle.cfg_vehicle_reference if vehicle else None,
        cancelled_stops=cancelled_stops,cancelled_stop_count=len(cancelled_stops),original_total_stops=len(ordered)+len(cancelled_stops),
        can_request_stop_cancellation=bool(operator.get('can_start') and doc.state in ('Draft','Planned') and doc.get('driver_route_state') in (None,'','Not Started','In Progress')),
        can_cancel_stop=bool(_all(operator) and operator.can_override and operator.can_complete and doc.state in ('Draft','Planned') and doc.get('driver_route_state') in (None,'','Not Started','In Progress')),
        open_pool=open_pool, can_add_assistant=bool(doc.driver==operator.employee and operator.get('can_start') and doc.state=='Planned' and doc.get('driver_route_state') in (None,'','Not Started','In Progress')), refreshed_on=now_datetime(), return_cases=_trip_returns(doc.name), read_only=True)


def _refusals(plan):
    from cfg_kanban.services.driver_delivery_outcomes import refused_by_source
    return refused_by_source(frappe.get_doc('CFG Kanban Delivery Session',plan.delivery_session)) if plan.delivery_session else {}


def _full_refusal(delivery):
    from cfg_kanban.services.driver_delivery_outcomes import full_refusal
    return full_refusal(delivery)


def _trip_returns(name):
    if not frappe.db.exists('DocType','CFG Kanban Delivery Outcome'):
        return []
    from cfg_kanban.services.driver_collections import summaries
    return summaries(name)

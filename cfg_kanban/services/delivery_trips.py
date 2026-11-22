"""Office trip planning. These records do not reserve or move ERP stock."""
import math
import re
import uuid

import frappe
from frappe.utils import cint, flt, getdate, get_datetime, now_datetime

TRIP = 'CFG Kanban Delivery Trip'
TEMPLATE = 'CFG Kanban Route Template'
ACTIVE = ('Draft', 'Planned')
TERMINAL = ('Closed', 'Cancelled')
EXECUTING = {'Vehicle Claimed', 'Loading', 'Ready to Dispatch', 'Dispatch Pending',
             'Loaded', 'Fulfilment In Progress', 'Fulfilled', 'Reconciled'}
EDITORS = ('Stock Manager', 'Sales Manager', 'System Manager', 'CFG Kanban System Maintenance')
EPSILON = 0.000001


def _read(doctype, name, current=False):
    doc = frappe.get_doc(doctype, name, **({'for_update': True} if current else {}))
    doc.check_permission('read')
    return doc


def _company(name):
    doc = _read('Company', name)
    if doc.get('is_group') or doc.get('disabled'):
        frappe.throw('Select an active operating Company')
    return doc


def _template(name, company=None, current=False):
    doc = _read(TEMPLATE, name, current=current)
    if not doc.active or (company and doc.company != company):
        frappe.throw('Select an active Standard Route / Template for this Company')
    _company(doc.company)
    return doc


def _snapshot(template):
    return dict(name=template.name, company=template.company, revision=cint(template.revision),
                region=template.get('region'), direction=template.get('direction'),
                sequence_policy=template.get('sequence_policy') or 'Flexible Order',
                auto_generate_dispatch=cint(template.get('auto_generate_dispatch')),
                dispatch_profile=template.get('dispatch_profile'),open_route_profile=template.get('open_route_profile'),
                stops=[dict(template_row=row.name, stop_purpose=row.get('stop_purpose') or 'Delivery',
                            customer_scan_point=row.get('customer_scan_point'), customer=row.customer,
                            customer_address=row.get('customer_address'), instructions=row.instructions or '')
                       for row in template.stops])


def _key():
    return 'S' + uuid.uuid4().hex[:20]


@frappe.whitelist()
def get_route_template(route_template, company=None):
    template = _template(route_template, company)
    snapshot = _snapshot(template)
    return dict(company=template.company, route_template=template.name,
                template_revision=snapshot['revision'], template_snapshot_json=frappe.as_json(snapshot),
                region=snapshot['region'], direction=snapshot['direction'],
                sequence_policy=snapshot['sequence_policy'],auto_generate_dispatch=snapshot['auto_generate_dispatch'],
                dispatch_profile=snapshot['dispatch_profile'],open_route_profile=snapshot['open_route_profile'],
                stops=[dict(row, stop_key=_key()) for row in snapshot['stops']])


def _identity(value):
    return str(value or '').strip()


def _address(name, customer):
    if not name:
        return ''
    address = _read('Address', name)
    if address.get('disabled'):
        frappe.throw('The selected customer Address is disabled')
    if not any(row.link_doctype == 'Customer' and row.link_name == customer
               for row in (address.get('links') or [])):
        frappe.throw('Customer Address must belong to the selected Customer')
    return ', '.join(str(address.get(field) or '').strip() for field in
                     ('address_line1', 'address_line2', 'city', 'state', 'pincode', 'country')
                     if address.get(field))


def validate_stops(doc, assign_keys=True):
    seen = set()
    for number, row in enumerate(doc.stops, 1):
        if assign_keys:
            row.stop_key = row.get('stop_key') or _key()
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', row.stop_key) or row.stop_key in seen:
                frappe.throw('Every customer stop requires its own stable identity')
            seen.add(row.stop_key)
            row.delivery_sequence = number
        row.stop_purpose = row.get('stop_purpose') or 'Delivery'
        if row.stop_purpose not in ('Delivery', 'Visit Only'):
            frappe.throw('Stop Purpose must be Delivery or Visit Only')
        if row.customer_scan_point:
            site = _read('CFG Kanban Customer Scan Point', row.customer_scan_point)
            if not site.active or site.selling_company != doc.company:
                frappe.throw('Customer Site must be active and belong to the trip Company')
            row.customer, row.customer_address = site.customer, site.customer_address
            row.site_name = site.site_name
        elif row.stop_purpose == 'Delivery':
            frappe.throw('Select a Customer Site for each Delivery stop')
        elif not row.customer:
            frappe.throw('Select a Customer for each Visit Only stop')
        else:
            row.site_name = _read('Customer', row.customer).get('customer_name') or row.customer
        customer = _read('Customer', row.customer)
        if customer.get('disabled'):
            frappe.throw('Customer is disabled')
        row.address_display = _address(row.get('customer_address'), row.customer)
    if not doc.stops:
        frappe.throw('Add customer stops or load a Standard Route / Template')
    return {row.stop_key: row for row in doc.stops} if assign_keys else None


def _locks(doctype, names):
    # Only server constants supply table names. All user values are bound parameters.
    if doctype not in (TRIP, TEMPLATE, 'Sales Order', 'CFG Kanban Dispatch Plan'):
        raise ValueError('Unsupported planning lock')
    for name in sorted(set(filter(None, names))):
        frappe.db.sql(f'SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE', (name,))


def _assignments(order_names, exclude_trip=None, current=False):
    names = sorted(set(filter(None, order_names)))
    if not names or not frappe.db.table_exists(TRIP):
        return {}
    placeholders = ','.join(['%s'] * len(names))
    rows = frappe.db.sql(f'''
        SELECT assignment.sales_order, assignment.sales_order_item, assignment.planned_qty,
               assignment.parent
        FROM `tabCFG Kanban Delivery Trip Order` assignment
        INNER JOIN `tabCFG Kanban Delivery Trip` trip ON trip.name=assignment.parent
        WHERE assignment.parenttype=%s AND assignment.parentfield='orders'
          AND trip.state IN ('Draft','Planned') AND assignment.sales_order IN ({placeholders})
          AND trip.name != %s
        ORDER BY assignment.parent, assignment.name
        {'FOR UPDATE' if current else ''}
    ''', tuple([TRIP] + names + [exclude_trip or '']), as_dict=True)
    delivered = _delivered_assignments(names, current=current)
    result = {}
    for row in rows:
        key = (row.sales_order, row.sales_order_item)
        outstanding = max(0, flt(row.planned_qty) - delivered.get((row.parent, *key), 0))
        result[key] = result.get(key, 0) + outstanding
    return result



def _delivered_assignments(order_names, current=False):
    if not order_names:
        return {}
    placeholders = ','.join(['%s'] * len(order_names))
    rows = frappe.db.sql(f"""
        SELECT links.parent AS trip, delivery.sales_order, item.so_detail AS sales_order_item,
               item.name AS delivery_note_item, item.stock_qty
        FROM `tabCFG Kanban Delivery Trip Plan` links
        INNER JOIN `tabCFG Kanban Delivery Session` delivery ON delivery.dispatch_plan=links.dispatch_plan
        INNER JOIN `tabDelivery Note` note ON note.name=delivery.delivery_note
        INNER JOIN `tabDelivery Note Item` item ON item.parent=note.name
        WHERE links.parenttype=%s AND links.parentfield='dispatch_plans'
          AND delivery.sales_order IN ({placeholders}) AND item.against_sales_order=delivery.sales_order
          AND item.parenttype='Delivery Note' AND note.docstatus=1 AND coalesce(note.is_return,0)=0
        {'FOR UPDATE' if current else ''}
    """, tuple([TRIP] + list(order_names)), as_dict=True)
    result = {}; seen = set()
    for row in rows:
        key = (row.trip, row.sales_order, row.sales_order_item)
        identity = (row.trip, row.delivery_note_item)
        if identity not in seen:
            result[key] = result.get(key, 0) + max(0, flt(row.stock_qty))
            seen.add(identity)
    return result


def _order(name, company, route, allow_draft=False, current=False):
    order = _read('Sales Order', name, current=current)
    if order.company != company or order.get('cfg_delivery_route') != route:
        frappe.throw('Sales Order must belong to this Company and Standard Route')
    if order.docstatus != 1:
        if not (allow_draft and order.docstatus == 0):
            frappe.throw('Only submitted Sales Orders can be assigned to a trip')
    if order.status in ('Closed', 'Cancelled', 'Completed', 'On Hold'):
        frappe.throw('Sales Order is no longer open for trip assignment')
    return order


def _line(order, name):
    row = next((item for item in (order.get('items') or []) if item.name == name), None)
    if not row:
        frappe.throw('Sales Order Item does not belong to the selected Sales Order')
    factor = flt(row.conversion_factor)
    qty, delivered = flt(row.qty), flt(row.delivered_qty)
    if (not all(math.isfinite(value) for value in (factor, qty, delivered))
            or factor <= 0 or qty < 0 or delivered < -EPSILON):
        frappe.throw('Sales Order conversion and quantities must be finite and valid')
    return row, max(0, (qty - delivered) * factor)


def _quantity(value, uom):
    qty = flt(value)
    if not math.isfinite(qty) or qty <= 0:
        frappe.throw('Assigned stock quantity must be positive and finite')
    if frappe.db.get_value('UOM', uom, 'must_be_whole_number') and abs(qty - round(qty)) > EPSILON:
        frappe.throw(f'Quantity for {uom} must be a whole number')
    if abs(qty - round(qty, 6)) > 0.000000001:
        frappe.throw('Assigned stock quantity supports at most six decimal places')
    return qty


@frappe.whitelist()
def get_route_order_inbox(route_template, company=None, trip_name=None, start=0, page_length=50):
    template = _template(route_template, company)
    current = None
    if trip_name:
        current = _read(TRIP, trip_name)
        if current.company != template.company or current.route_template != template.name:
            frappe.throw('Trip does not match the selected Standard Route')
    start = max(0, cint(start)); size = max(1, min(cint(page_length) or 50, 100))
    names = frappe.get_list('Sales Order', filters={
        'company': template.company, 'cfg_delivery_route': template.name,
        'docstatus': ['in', [0, 1]], 'status': ['not in', ['Closed', 'Cancelled', 'Completed', 'On Hold']]},
        pluck='name', order_by='delivery_date asc, transaction_date asc, name asc',
        limit_start=start, limit_page_length=size + 1)
    quantities = _assignments(names[:size], current.name if current else None)
    delivered = _delivered_assignments(names[:size]) if current and names[:size] else {}
    own = {(row.sales_order, row.sales_order_item): max(0, flt(row.planned_qty) -
           delivered.get((current.name, row.sales_order, row.sales_order_item), 0))
           for row in (current.orders if current and current.state in ACTIVE else [])}
    rows = []
    for name in names[:size]:
        order = _order(name, template.company, template.name, allow_draft=True)
        for item in (order.get('items') or []):
            source, remaining = _line(order, item.name)
            if remaining <= EPSILON:
                continue
            assigned = quantities.get((name, item.name), 0)
            here = own.get((name, item.name), 0)
            available = max(0, remaining - assigned)
            rows.append(dict(sales_order=name, sales_order_item=item.name, item_code=source.item_code,
                item_name=source.item_name, stock_uom=source.stock_uom, customer=order.customer,
                customer_name=order.get('customer_name') or order.customer,
                customer_po=order.get('po_no'), customer_address=order.get('shipping_address_name'),
                delivery_date=str(source.get('delivery_date') or order.get('delivery_date') or ''),
                ordered_qty=flt(source.qty) * flt(source.conversion_factor),
                delivered_qty=flt(source.delivered_qty) * flt(source.conversion_factor),
                assigned_elsewhere=assigned, assigned_here=here, available_qty=available,
                unassigned_qty=max(0, available - here), status=order.status,
                assignable=int(order.docstatus == 1 and available > EPSILON)))
    return dict(rows=rows, start=start, page_length=size, has_more=len(names) > size)


def validate_sales_order_route(doc, method=None):
    route = doc.get('cfg_delivery_route')
    before = doc.get_doc_before_save() if not doc.is_new() else None
    changed = not before or any((doc.get(field) or '') != (before.get(field) or '') for field in
                               ('cfg_delivery_route', 'company', 'customer', 'shipping_address_name'))
    if not changed:
        return
    _locks(TEMPLATE, [route, before.get('cfg_delivery_route') if before else None])
    if before:
        _locks('Sales Order', [doc.name])
        if _assignments([doc.name], current=True):
            frappe.throw('Release this Sales Order from active Delivery Trips before changing its route, Company, Customer or address')
    if route:
        template = _template(route, doc.company, current=True)
        if not any(row.customer == doc.customer for row in template.stops):
            frappe.throw('Select a Standard Route containing this Customer')


def _plans(doc, current=False):
    result = {}
    stops = {row.stop_key: row for row in doc.stops}
    before = doc.get_doc_before_save() if current and not doc.is_new() else None
    prior = {row.dispatch_plan for row in before.dispatch_plans} if before else set()
    seen = set()
    for row in doc.dispatch_plans:
        if not row.stop_key:
            stop = next((stop for stop in doc.stops if stop.delivery_sequence == cint(row.stop_sequence)), None)
            row.stop_key = stop.stop_key if stop else None
        if row.dispatch_plan in seen or row.stop_key not in stops:
            frappe.throw('Select one distinct Dispatch Plan and its exact trip stop')
        seen.add(row.dispatch_plan)
        plan = _read('CFG Kanban Dispatch Plan', row.dispatch_plan, current=current)
        stop = stops[row.stop_key]
        if plan.get('office_delivery_trip') and (plan.office_delivery_trip!=doc.name or plan.office_stop_key!=row.stop_key):
            frappe.throw('Generated customer dispatch must remain linked to its exact office Trip and stop')
        if current and row.dispatch_plan not in prior and plan.state in ('Reconciled', 'Cancelled'):
            frappe.throw('A settled or cancelled Dispatch Plan cannot be newly assigned to a Delivery Trip')
        if doc.vehicle_warehouse and plan.vehicle_warehouse and doc.vehicle_warehouse != plan.vehicle_warehouse:
            frappe.throw('Linked Dispatch Plan belongs to a different lorry Warehouse')
        if doc.source_warehouse and plan.source_warehouse != doc.source_warehouse:
            frappe.throw('Linked Dispatch Plan uses a different loading source Warehouse')
        if (plan.company != doc.company or plan.plan_type != 'Customer Order'
                or plan.fulfilment_mode != 'Vehicle Delivery' or stop.stop_purpose != 'Delivery'
                or plan.customer_site != stop.customer_scan_point or not plan.sales_order):
            frappe.throw('Linked Dispatch Plan must be a Vehicle Customer Order for this Company and Customer Site')
        other = frappe.db.sql(f'''
            SELECT source.parent FROM `tabCFG Kanban Delivery Trip Plan` source
            INNER JOIN `tabCFG Kanban Delivery Trip` trip ON trip.name=source.parent
            WHERE source.dispatch_plan=%s AND source.parenttype=%s AND source.parentfield='dispatch_plans'
              AND source.parent != %s LIMIT 1
        ''' + (' FOR UPDATE' if current else ''), (plan.name, TRIP, doc.name or ''), as_dict=True)
        if other:
            frappe.throw('Dispatch Plan is already linked to another Delivery Trip')
        row.stop_sequence, row.plan_state = stop.delivery_sequence, plan.state
        row.sales_order, row.vehicle_warehouse = plan.sales_order, plan.vehicle_warehouse
        result[plan.name] = (row, plan)
    vehicles = {plan.vehicle_warehouse for _row, plan in result.values() if plan.vehicle_warehouse}
    if len(vehicles) > 1:
        frappe.throw('A trip cannot combine different lorry Warehouses')
    return result


def _business(doc):
    result = dict(company=doc.company, route_template=doc.route_template,
        trip_date=str(doc.trip_date or ''), expected_return_date=str(doc.expected_return_date or ''),
        driver=doc.driver, vehicle_warehouse=doc.vehicle_warehouse, source_warehouse=doc.source_warehouse,
        region=doc.region, direction=doc.direction, sequence_policy=doc.sequence_policy,
        template_revision=cint(doc.template_revision), template_snapshot_json=doc.template_snapshot_json,
        stops=[(r.stop_key, r.stop_purpose, r.customer_scan_point, r.customer, r.customer_address, r.instructions)
               for r in doc.stops],
        orders=[(r.sales_order, r.sales_order_item, r.stop_key, flt(r.planned_qty)) for r in doc.orders],
        plans=[(r.dispatch_plan, r.stop_key) for r in doc.dispatch_plans])

    if doc.get('auto_generate_dispatch') or doc.get('dispatch_profile') or doc.get('open_route_profile') or doc.get('open_route_plan') or doc.get('route_stock'):
        result.update(auto_generate_dispatch=cint(doc.get('auto_generate_dispatch')),dispatch_profile=doc.get('dispatch_profile'),
            open_route_profile=doc.get('open_route_profile'),open_route_plan=doc.get('open_route_plan'),
            route_stock=[(r.item_code,r.batch_no,flt(r.qty),r.stock_uom) for r in doc.get('route_stock') or []])
    return result


def _copy_snapshot(doc, template, before):
    same = before and before.route_template == doc.route_template
    if same and cint(doc.template_revision) == cint(before.template_revision):
        if doc.template_snapshot_json != before.template_snapshot_json:
            frappe.throw('Saved template snapshot is immutable; use Load Route Template')
        return
    if before and (before.orders or before.dispatch_plans or doc.orders or doc.dispatch_plans):
        frappe.throw('Save the trip without orders and linked Plans before replacing its route template')
    if doc.template_revision and cint(doc.template_revision) != cint(template.revision):
        frappe.throw('The route template changed. Load it again before saving this trip')
    doc.template_revision = cint(template.revision)
    doc.template_snapshot_json = frappe.as_json(_snapshot(template))


def _source_rows(doc, plans):
    """Build loading instructions from real allocations plus unprepared order balances."""
    budgets = {}
    for row in doc.orders:
        if not cint(row.get('is_stock_item')):
            continue
        key = (row.stop_key, row.sales_order, row.item_code, row.stock_uom)
        budgets[key] = budgets.get(key, 0) + flt(row.planned_qty)
    requested = {}; covered = {}; rows = []
    for name, (link, plan) in plans.items():
        if plan.state == 'Cancelled':
            continue
        for line in plan.lines:
            key = (link.stop_key, plan.sales_order, line.item_code, line.stock_uom)
            requested[key] = requested.get(key, 0) + flt(line.requested_qty)
            if requested[key] > budgets.get(key, 0) + EPSILON:
                frappe.throw('Linked Dispatch Plan quantities exceed the trip orders; adjust the planning or link the correct Plan')
        allocations = frappe.get_list('CFG Kanban Dispatch Allocation', filters={
            'dispatch_plan': name, 'state': ['not in', ['Released', 'Cancelled']]},
            fields=['name', 'dispatch_plan_line', 'allocation_kind', 'handling_unit', 'visible_code',
                    'item_code', 'batch_no', 'stock_uom', 'allocated_qty', 'state', 'load_confirmed'],
            order_by='name asc', limit_page_length=0)
        for allocation in allocations:
            key = (link.stop_key, plan.sales_order, allocation.item_code, allocation.stock_uom)
            covered[key] = covered.get(key, 0) + flt(allocation.allocated_qty)
            if covered[key] > requested.get(key, 0) + EPSILON:
                frappe.throw('Dispatch allocation quantities exceed their linked Plan')
            rows.append(dict(stop_key=link.stop_key, sales_order=plan.sales_order,
                item_code=allocation.item_code, stock_uom=allocation.stock_uom,
                qty=flt(allocation.allocated_qty), dispatch_plan=name, dispatch_allocation=allocation.name,
                handling_unit=allocation.handling_unit, tag_code=allocation.visible_code,
                allocation_kind=allocation.allocation_kind,
                batch_no=allocation.batch_no, source_state=allocation.state,
                loaded_qty=flt(allocation.allocated_qty) if allocation.state in ('Loaded','In Fulfilment','Fulfilled') else 0,
                instruction='Linked dispatch allocation'))
    for key, qty in budgets.items():
        remaining = qty - covered.get(key, 0)
        if remaining > EPSILON:
            stop_key, sales_order, item, uom = key
            rows.append(dict(stop_key=stop_key, sales_order=sales_order, item_code=item,
                stock_uom=uom, qty=remaining, loaded_qty=0, source_state='Not Prepared', allocation_kind='Not Prepared',
                instruction='Prepare through the existing Dispatch Plan workflow'))
    stops = {row.stop_key: row for row in doc.stops}
    rows.sort(key=lambda row: (-stops[row['stop_key']].delivery_sequence,
                               row['sales_order'], row['item_code'], row.get('dispatch_allocation') or ''))
    for number, row in enumerate(rows, 1):
        stop = stops[row['stop_key']]
        row.update(loading_sequence=number, delivery_sequence=stop.delivery_sequence,
                   customer=stop.customer, customer_site=stop.customer_scan_point,
                   customer_po=next((order.customer_po for order in doc.orders if order.sales_order == row['sales_order']), None))
    if doc.get('open_route_plan'):
        from cfg_kanban.services.trip_dispatch import open_loading_rows
        extra=open_loading_rows(doc)
        for row in extra:row['loading_sequence']=len(rows)+1;rows.append(row)
    return rows


def _preserve_derived(doc, before):
    for field in ('template_snapshot_json', 'template_revision', 'planning_revision', 'closed_by', 'closed_on'):
        doc.set(field, before.get(field))
    for field in ('stops', 'orders', 'dispatch_plans', 'loading_sequence'):
        # Business identities/quantities were compared first; restore server-derived snapshots.
        doc.set(field, [row.as_dict() for row in before.get(field) or []])


def _protect_driver_execution(doc, before):
    fields = ('driver_route_state', 'driver_route_revision', 'driver_route_started_on',
              'driver_route_started_by', 'driver_route_completed_on', 'driver_active_stop_key',
              'driver_active_vehicle_key', 'driver_route_snapshot_json')
    for field in fields:
        doc.set(field, before.get(field) if before else
                'Not Started' if field == 'driver_route_state' else 0 if field == 'driver_route_revision' else None)
    for field in ('driver_stop_order_json','route_sequence_revision','route_order_source','route_change_request'):
        if doc.get(field) is not None or (before and before.get(field) is not None):
            doc.set(field,before.get(field) if before else 0 if field=='route_sequence_revision' else None)
    original = {row.stop_key: row for row in before.stops} if before else {}
    for row in doc.stops:
        source = original.get(row.stop_key)
        for field in ('driver_completed_on', 'driver_completed_by', 'driver_visit_notes'):
            row.set(field, source.get(field) if source else None)
    if before and before.get('driver_route_state') in ('In Progress', 'Completed'):
        if _business(doc) != _business(before):
            frappe.throw('Started driver routes retain their itinerary, assignments and driver; use controlled recovery')
        if before.get('driver_route_state') == 'In Progress' and doc.state != before.state and doc.state not in TERMINAL:
            frappe.throw('Complete the started driver route before closing its planning record')


def validate_trip(doc):
    frappe.only_for(EDITORS)
    doc.check_permission('create' if doc.is_new() else 'write')
    before = None if doc.is_new() else doc.get_doc_before_save()
    _protect_driver_execution(doc, before)
    doc.team_revision = cint(before.get('team_revision')) if before else 0
    if doc.get('assistant_drivers') or (before and before.get('assistant_drivers')):
        from cfg_kanban.services.trip_team import validate_office_team
        validate_office_team(doc, before)
    if doc.get('auto_generate_dispatch') or doc.get('open_route_plan') or (before and before.get('open_route_plan')):
        from cfg_kanban.services.trip_dispatch import validate_setup
        validate_setup(doc,before)
    if doc.state not in ACTIVE + TERMINAL:
        frappe.throw('Unsupported office trip planning status')
    # All assignments on a standard route serialize before source/order current reads.
    _locks(TEMPLATE, [doc.route_template, before.route_template if before else None])
    if before:
        before.check_permission('write')
        latest = frappe.db.sql('SELECT modified FROM `tabCFG Kanban Delivery Trip` WHERE name=%s FOR UPDATE',
                               (doc.name,), as_dict=True)
        if latest and before.get('modified') and get_datetime(latest[0].modified) != get_datetime(before.modified):
            frappe.throw('This trip was changed by another planner. Reload before saving')
    _locks('CFG Kanban Dispatch Plan', [r.dispatch_plan for r in doc.dispatch_plans] +
           ([r.dispatch_plan for r in before.dispatch_plans] if before else []))
    _locks('Sales Order', [r.sales_order for r in doc.orders] +
           ([r.sales_order for r in before.orders] if before else []))
    _company(doc.company)
    if before and before.state in TERMINAL:
        if doc.state != before.state or _business(doc) != _business(before):
            frappe.throw('Closed/cancelled planning history cannot be reopened or rewritten')
        _preserve_derived(doc, before)
        doc.closure_reason = before.closure_reason
        return
    if doc.state in TERMINAL:
        if not before or not _identity(doc.closure_reason) or _business(doc) != _business(before):
            frappe.throw('Save planning changes first, then enter a closure/cancellation reason')
        closing=[r.dispatch_plan for r in doc.dispatch_plans]+([doc.open_route_plan] if doc.get('open_route_plan') else [])
        for name in closing:
            if _read('CFG Kanban Dispatch Plan', name, current=True).state not in ('Reconciled', 'Cancelled'):
                frappe.throw('Settle or cancel linked Dispatch Plans through the existing workflow before closing this planning record')
        _preserve_derived(doc, before)
        if before.get('driver_route_state') == 'In Progress':
            # Only the existing office close/cancel path, after all linked Plans are settled,
            # may release a route with undelivered stops. Never invent stop/DN/proof completion.
            doc.driver_route_state = 'Closed Incomplete'
            doc.driver_route_completed_on = now_datetime()
            doc.driver_active_vehicle_key = doc.driver_active_stop_key = None
        doc.closed_by, doc.closed_on = frappe.session.user, now_datetime()
        doc.planning_revision = cint(before.planning_revision) + 1
        return
    if before and before.get('open_route_plan'):
        pool=_read('CFG Kanban Dispatch Plan',before.open_route_plan,current=True)
        unused_existing=(pool.get('existing_lorry_stock_only') and pool.state=='Ready for Fulfilment' and not pool.get('active_route_sheet')
            and not frappe.db.exists('CFG Kanban Delivery Session',{'dispatch_plan':pool.name}))
        if ((pool.state not in ('Draft','Awaiting Approval','Approved') and not unused_existing) or pool.get('movement_manifest') or pool.get('active_route_stop')) and _business(doc)!=_business(before):
            frappe.throw('Shared route stock execution has started; retain this Trip snapshot')
    if before:
        for row in before.dispatch_plans:
            plan = _read('CFG Kanban Dispatch Plan', row.dispatch_plan, current=True)
            if plan.state in EXECUTING or plan.get('movement_manifest') or plan.get('delivery_session'):
                # Office may sign off an unchanged saved load before driver departure.
                release_to_planned = (before.state == 'Draft' and doc.state == 'Planned'
                    and before.get('driver_route_state') in (None, '', 'Not Started'))
                if (doc.state != before.state and not release_to_planned) or _business(doc) != _business(before):
                    frappe.throw('Linked dispatch execution has started; retain this planning snapshot and use controlled operational changes')
                _preserve_derived(doc, before)
                if release_to_planned:
                    doc.planning_revision = cint(before.planning_revision) + 1
                doc.set('loading_sequence', _source_rows(doc, _plans(doc, current=True)))
                return
            if row.dispatch_plan not in {r.dispatch_plan for r in doc.dispatch_plans} and plan.state != 'Cancelled':
                active = frappe.db.exists('CFG Kanban Dispatch Allocation', {
                    'dispatch_plan': plan.name, 'state': ['not in', ['Released','Cancelled']]})
                if active:
                    frappe.throw('Release the linked Plan reservations before removing it from this trip')
    doc.closed_by = doc.closed_on = None
    template = _template(doc.route_template, doc.company, current=True)
    if not doc.trip_title:
        doc.trip_title = f'{template.name} · {doc.trip_date}'
    _copy_snapshot(doc, template, before)
    if getdate(doc.expected_return_date or doc.trip_date) < getdate(doc.trip_date):
        frappe.throw('Expected Return Date cannot precede Trip Date')
    if doc.sequence_policy not in ('Flexible Order','Planned Order'):
        frappe.throw('Select Flexible Order or Planned Order')
    if doc.driver:
        driver = _read('Employee', doc.driver)
        if driver.status != 'Active':
            frappe.throw('Trip driver Employee must be active')
    for field in ('source_warehouse', 'vehicle_warehouse'):
        if doc.get(field):
            warehouse = _read('Warehouse', doc.get(field))
            if warehouse.company != doc.company or warehouse.is_group or warehouse.disabled:
                frappe.throw('Trip Warehouses must be active leaf Warehouses of this Company')
            if field == 'vehicle_warehouse' and (not warehouse.get('cfg_is_vehicle_warehouse') or not warehouse.get('cfg_vehicle_reference')):
                frappe.throw('Select a configured Company-specific lorry Warehouse')
    stops = validate_stops(doc)
    quantities = _assignments([row.sales_order for row in doc.orders], doc.name, current=True)
    seen = set(); orders = {}
    for row in doc.orders:
        key = (row.sales_order, row.sales_order_item)
        if key in seen:
            frappe.throw('Combine duplicate Sales Order Item assignments in this trip')
        seen.add(key)
        stop = stops.get(row.stop_key)
        if not stop or stop.stop_purpose != 'Delivery':
            frappe.throw('Assign each order line to an exact Delivery stop')
        if row.sales_order not in orders:
            orders[row.sales_order] = _order(row.sales_order, doc.company, doc.route_template, current=True)
        order = orders[row.sales_order]
        source, remaining = _line(order, row.sales_order_item)
        if (order.customer != stop.customer or (order.get('shipping_address_name') and
                order.shipping_address_name != stop.customer_address)):
            frappe.throw('Trip stop must match the Sales Order Customer and delivery address')
        item = _read('Item', source.item_code)
        if item.disabled:
            frappe.throw('Sales Order Item is disabled')
        qty = _quantity(row.planned_qty, source.stock_uom)
        if qty + quantities.get(key, 0) > remaining + EPSILON:
            frappe.throw(f'Assigned quantity exceeds the unassigned Sales Order balance for {order.name} / {source.item_code}')
        row.customer, row.customer_po = order.customer, order.get('po_no')
        row.item_code, row.item_name = source.item_code, source.item_name
        row.stock_uom, row.stop_sequence = source.stock_uom, stop.delivery_sequence
        row.is_stock_item = cint(item.is_stock_item)
        row.planned_qty = qty
        row.delivery_date = source.get('delivery_date') or order.get('delivery_date')
    if cint(doc.get('auto_generate_dispatch')) and doc.state=='Planned' and not (getattr(doc,'flags',None) or {}).get('cfg_generating_trip_dispatch'):
        if doc.is_new():frappe.throw('Save this Delivery Trip as Draft before Mark Planned generates its dispatch work')
        from cfg_kanban.services.trip_dispatch import generate
        generate(doc,save=False)
    plans = _plans(doc, current=True)
    doc.set('loading_sequence', _source_rows(doc, plans))
    doc.planning_revision = (cint(before.planning_revision) + int(_business(doc) != _business(before)
                              or doc.state != before.state)) if before else 1


@frappe.whitelist()
def get_loading_sequence(trip_name):
    doc = _read(TRIP, trip_name)
    rows = ([row.as_dict() for row in doc.loading_sequence] if doc.state in TERMINAL
            else _source_rows(doc, _plans(doc)))
    return dict(rows=rows, planning_revision=doc.planning_revision,
                refreshed_on=now_datetime())

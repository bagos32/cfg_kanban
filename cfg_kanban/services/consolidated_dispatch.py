"""One warehouse request with immutable customer/SO demand and per-stop execution.

The root Dispatch Plan owns picking, the loading Manifest and E5. A native Route
Stop owns each customer's prepared-delivery facts. ScopedPlan is a restricted
view of that same Plan, used by E4A; it never creates another stock document.
"""
import json

import frappe
from frappe.utils import cint, flt, now_datetime

PLAN = 'CFG Kanban Dispatch Plan'
STOP = 'CFG Kanban Route Stop'
LINE = 'CFG Kanban Dispatch Plan Line'
EPS = 0.000001
SCOPED = {'delivery_session', 'delivery_note', 'delivery_proof', 'driver_delivery_outcome',
          'stop_cancellation', 'fulfilment_status', 'total_delivered_qty', 'fulfilment_completed_on'}
STATES = {'Not Started': 'Planned', 'In Progress': 'In Progress',
          'Delivery Note Pending': 'Delivery Note Pending', 'Delivered': 'Delivered',
          'Completed': 'Completed', 'Exception': 'Exception', 'Closed Incomplete': 'Skipped'}


def enabled(plan):
    return bool(cint(plan.get('consolidated_customer_orders')))


def stops(plan, current=False):
    names = frappe.get_all(STOP, filters={'dispatch_plan': plan.name,
        'office_delivery_trip': plan.office_delivery_trip}, pluck='name', order_by='planned_sequence asc, name asc', limit_page_length=0)
    return [frappe.get_doc(STOP, name, **({'for_update': True} if current else {})) for name in names]


def linked(trip, stop_key=None):
    """Expand a single office Plan link into its saved customer links for readers."""
    result = []
    for link in trip.dispatch_plans:
        plan = frappe.get_doc(PLAN, link.dispatch_plan)
        if enabled(plan):
            if plan.office_delivery_trip != trip.name or link.stop_key:
                frappe.throw('Consolidated dispatch must retain its one whole-Trip link')
            result.extend(frappe._dict(dispatch_plan=plan.name, stop_key=row.office_stop_key)
                          for row in stops(plan) if stop_key is None or row.office_stop_key == stop_key)
        elif stop_key is None or link.stop_key == stop_key:
            result.append(link)
    return result


class ScopedPlan:
    """Customer fields write only to its Route Stop; stock/header fields stay shared."""
    def __init__(self, root, stop):
        self.root, self.customer_dispatch_stop = root, stop
        self.lines = [row for row in root.lines if row.get('office_stop_key') == stop.office_stop_key]
        if not self.lines:
            frappe.throw('Consolidated customer has no exact Sales Order demand lines')

    def get(self, key, default=None):
        if key == 'lines':
            return self.lines
        if key == 'office_stop_key':
            return self.customer_dispatch_stop.office_stop_key
        if key in ('customer', 'customer_address'):
            return self.customer_dispatch_stop.get(key, default)
        if key == 'customer_site':
            return self.customer_dispatch_stop.customer_scan_point
        if key == 'sales_order':
            orders = {row.sales_order for row in self.lines}
            return next(iter(orders)) if len(orders) == 1 else None
        if key == 'active_route_stop':
            return self.root.get(key) if self.root.get(key) == self.customer_dispatch_stop.name else None
        if key in SCOPED:
            native = 'completed_on' if key == 'fulfilment_completed_on' else key
            return self.customer_dispatch_stop.get(native, default)
        return self.root.get(key, default)

    def __getattr__(self, key):
        return self.get(key)

    def check_permission(self, *args, **kwargs):
        return self.root.check_permission(*args, **kwargs)

    def as_dict(self):
        data = dict(self.root.as_dict())
        for key in SCOPED | {'office_stop_key', 'customer', 'customer_address', 'customer_site', 'sales_order'}:
            data[key] = self.get(key)
        data['lines'] = [row.as_dict() for row in self.lines]
        data['customer_dispatch_stop'] = self.customer_dispatch_stop.name
        return frappe._dict(data)

    def set(self, key, rows):
        if key != 'lines':
            frappe.throw('Customer-scoped dispatch cannot replace shared Plan fields')
        self.lines = [row for row in rows if row.get('office_stop_key') == self.office_stop_key]

    def db_set(self, field, value=None, **kwargs):
        values = dict(field) if isinstance(field, dict) else {field: value}
        # E4A retains the shared preparation hold until E5; it is never cleared
        # just because the first customer completes or releases a refusal.
        commitment = values.pop('prepared_stock_commitment', None)
        if commitment is not None and cint(commitment) != 1:
            frappe.throw('Only E5 may release the consolidated Plan commitment')
        if set(values) - SCOPED:
            frappe.throw('Customer-scoped dispatch cannot mutate shared loading or E5 state')
        if 'fulfilment_status' in values:
            values['state'] = STATES[values['fulfilment_status']]
        if 'fulfilment_completed_on' in values:
            values['completed_on'] = values.pop('fulfilment_completed_on')
        self.customer_dispatch_stop.db_set(values, **kwargs)
        aggregate(self.root)
        return self


def scoped(plan, stop_key=None, native_stop=None, current=False):
    if not enabled(plan):
        return plan
    root = plan.root if isinstance(plan, ScopedPlan) else plan
    if native_stop:
        candidates = [frappe.get_doc(STOP, native_stop, **({'for_update': True} if current else {}))]
    else:
        names = frappe.get_all(STOP, filters={'dispatch_plan':root.name,
            'office_delivery_trip':root.office_delivery_trip,'office_stop_key':stop_key},
            pluck='name',limit_page_length=2)
        candidates = [frappe.get_doc(STOP,name,**({'for_update': True} if current else {})) for name in names]
    if len(candidates) != 1:
        frappe.throw('Select the exact customer stop on this consolidated Dispatch Plan')
    stop = candidates[0]
    if (stop.dispatch_plan != root.name or stop.office_delivery_trip != root.office_delivery_trip
            or not stop.office_stop_key or (stop_key and stop.office_stop_key != stop_key)
            or stop.company != root.company):
        frappe.throw('Consolidated customer scope differs from its Plan, Trip or Company')
    stop.check_permission('read')
    return ScopedPlan(root, stop)


def for_delivery(plan, delivery, current=False):
    if not enabled(plan):
        return plan
    if not delivery.get('customer_dispatch_stop'):
        frappe.throw('Consolidated delivery lost its exact customer stop identity')
    view = scoped(plan, native_stop=delivery.customer_dispatch_stop, current=current)
    if view.delivery_session != delivery.name:
        frappe.throw('Consolidated customer stop belongs to another Delivery Session')
    return view


def for_scan(plan, scan, native_stop=None):
    from cfg_kanban.services import customer_delivery
    site = customer_delivery._resolve_customer_site(scan)
    if native_stop:
        view = scoped(plan,native_stop=native_stop,current=True)
        if view.customer_site != site.name:
            frappe.throw('Select the exact assigned consolidated customer stop for this Site')
        return view
    matches = frappe.get_all(STOP, filters={'dispatch_plan':plan.name,
        'office_delivery_trip':plan.office_delivery_trip,'customer_scan_point':site.name},
        fields=['name'],limit_page_length=2)
    if len(matches) != 1:
        frappe.throw('Select the exact assigned consolidated customer stop; this Site is outside the Plan or has several visits')
    return scoped(plan, native_stop=matches[0].name)


def seed(trip, plan):
    if not enabled(plan):
        return
    keys = {row.office_stop_key for row in plan.lines}
    existing = {row.office_stop_key: row for row in stops(plan, current=True)}
    from cfg_kanban.services.idempotency import canonical_key
    for stop in trip.stops:
        if stop.stop_key not in keys:
            continue
        if stop.stop_key in existing:
            continue
        doc = frappe.get_doc(dict(doctype=STOP, state='Planned', dispatch_plan=plan.name,
            company=plan.company, customer_scan_point=stop.customer_scan_point,
            customer=stop.customer, customer_address=stop.customer_address, site_name=stop.site_name,
            office_delivery_trip=trip.name, office_stop_key=stop.stop_key,
            planned_sequence=stop.delivery_sequence, fulfilment_status='Not Started',
            created_on=now_datetime(), idempotency_key=canonical_key('consolidated-customer', plan.name, stop.stop_key)))
        doc.flags.cfg_office_dispatch = True
        doc.insert(ignore_permissions=True)


def aggregate(plan):
    rows = frappe.db.get_values(STOP,{'dispatch_plan':plan.name,'office_delivery_trip':plan.office_delivery_trip},
        ['name','stop_cancellation','fulfilment_status','delivery_session','total_delivered_qty','completed_on'],
        as_dict=True,for_update=True,order_by='name')
    active = [row for row in rows if not row.get('stop_cancellation')]
    complete = bool(active) and all(row.get('fulfilment_status') == 'Completed' for row in active)
    started = any(row.delivery_session for row in rows)
    working = [row for row in rows if row.get('fulfilment_status') in ('In Progress','Delivery Note Pending','Delivered','Exception')]
    if len(working) > 1:
        frappe.throw('Consolidated Plan has several active deliveries; supervised reconciliation required')
    plan.db_set(dict(total_delivered_qty=sum(flt(row.get('total_delivered_qty')) for row in rows),
        active_route_stop=working[0].name if working else None,
        fulfilment_status='Completed' if complete else 'In Progress' if started else 'Not Started',
        completed_stop_count=sum(row.get('fulfilment_status') == 'Completed' for row in rows),
        fulfilment_completed_on=max((row.completed_on for row in active if row.completed_on), default=None) if complete else None,
        prepared_stock_commitment=1 if plan.state == 'Loaded' else cint(plan.get('prepared_stock_commitment'))), update_modified=True)


def prepared_choices(site_name, operator, plan=None):
    from cfg_kanban.services import dispatch_planning as planning, customer_delivery as delivery
    names = [plan.name] if plan else frappe.get_all(PLAN, filters={
        'consolidated_customer_orders':1,'state':'Loaded','plan_type':'Customer Order'}, pluck='name', limit_page_length=0)
    result = []
    for name in names:
        root = plan if plan and plan.name == name else frappe.get_doc(PLAN,name)
        if root.state != 'Loaded' or root.get('dispatch_review_state'):
            continue
        if not (planning._view_all(operator) or root.dispatch_responsibility in planning._responsibilities(operator)):
            continue
        root.check_permission('read')
        for stop in stops(root):
            if (site_name and stop.customer_scan_point != site_name) or stop.get('stop_cancellation') or stop.get('fulfilment_status') == 'Completed':
                continue
            view = scoped(root,native_stop=stop.name)
            if view.delivery_session and not delivery._can_view_delivery(operator,frappe.get_doc('CFG Kanban Delivery Session',view.delivery_session)):
                continue
            data=view.as_dict()
            data['business_label']=str(root.business_label or root.name)+' / '+str(stop.planned_sequence)+'. '+str(stop.site_name or stop.customer)
            result.append(data)
    return result


def sheet_target(trip, row):
    if not row.source_route_stop:
        frappe.throw('A consolidated route row requires its exact saved customer scope')
    source = frappe.get_doc(STOP, row.source_route_stop)
    if (source.dispatch_plan != row.dispatch_plan or source.office_delivery_trip != trip.name
            or source.customer_scan_point != row.customer_scan_point):
        frappe.throw('Route row differs from its consolidated customer scope')
    return source.office_stop_key


def order_assignments(plan, allocations):
    """Use each immutable SO row, including repeated SKUs and different prices."""
    from cfg_kanban.services import dispatch_fulfilment as prepared
    orders = {}; assigned = {}
    for name in sorted({row.sales_order for row in plan.lines}):
        sub = ScopedPlan(plan.root, plan.customer_dispatch_stop)
        sub.lines = [row for row in plan.lines if row.sales_order == name]
        selected = [row for row in allocations if row.dispatch_plan_line in {line.name for line in sub.lines}]
        order, mapped = prepared._order_assignments(sub, selected, consolidated=False)
        orders[name] = order; assigned.update(mapped)
    contexts = [{key: order.get(key) for key in ('currency','conversion_rate','price_list_currency','plc_conversion_rate','project')}
                for order in orders.values()]
    if contexts and any(any(not prepared._same_currency_context(key, value, contexts[0][key])
                           for key, value in data.items()) for data in contexts[1:]):
        frappe.throw('Customer Sales Orders need matching currency, conversion and Project context for one Delivery Note')
    price_lists = {order.selling_price_list or '' for order in orders.values()}
    if len(price_lists) > 1:
        frappe.throw('Customer Sales Orders need one matching Price List for a consolidated Delivery Note')
    return next(iter(orders.values())) if orders else None, assigned


def apply_order_payload(delivery, payload, allocations):
    from cfg_kanban.services import dispatch_fulfilment as prepared
    plan = for_delivery(frappe.get_doc(PLAN, delivery.dispatch_plan), delivery)
    lines = {row.name: row for row in plan.lines}
    mapping = {row.name: row for row in frappe.get_all('CFG Kanban Dispatch Allocation',
        filters={'name': ['in', [row.dispatch_allocation for row in allocations]]},
        fields=['name','dispatch_plan_line'], limit_page_length=0)}
    by_allocation = {row.name: row for row in allocations}
    groups = {}
    for row in payload['items']:
        allocated = by_allocation[row['delivery_allocation']]
        source = mapping.get(allocated.dispatch_allocation)
        line = lines.get(source.dispatch_plan_line) if source else None
        if not line or line.sales_order_item != allocated.sales_order_item:
            frappe.throw('Delivery allocation lost its exact customer Sales Order row')
        groups.setdefault(line.sales_order, []).append(row)
    for name, rows in groups.items():
        order = frappe.get_doc('Sales Order', name)
        context = json.loads(delivery.sales_order_context_json or '{}')
        shadow = frappe._dict(delivery.as_dict(), sales_order=name,
            sales_order_context_json=json.dumps(context))
        subset = dict(items=rows)
        prepared.apply_sales_order_payload(shadow, subset, allocations, consolidated=False)
        payload.update({key: value for key, value in subset.items() if key != 'items'})


def other_untagged_commitment(plan, stop_key, item_code, batch_no, current=False):
    """Excluding a shared Plan must not make the other stops' stock available."""
    from cfg_kanban.services import dispatch_fulfilment as prepared, driver_delivery_outcomes as outcomes
    from cfg_kanban.services.cancelled_stop_stock import released_source_qty
    root = plan.root if isinstance(plan,ScopedPlan) else plan
    line_keys = {line.name:line.office_stop_key for line in root.lines}
    total = 0
    for source in prepared._loaded_allocations(root,for_update=current):
        if (source.allocation_kind != 'Untagged ERP Stock' or source.item_code != item_code
                or (source.batch_no or '') != (batch_no or '') or line_keys[source.dispatch_plan_line] == stop_key):
            continue
        picked = frappe.db.get_values('CFG Kanban Delivery Allocation',{
            'dispatch_allocation':source.name,'state':['in',['Reserved','Delivery Pending','Exception','Delivered']]},
            ['allocated_qty'],as_dict=True,for_update=current,order_by='name')
        total += max(0,flt(source.allocated_qty)-sum(flt(row.allocated_qty) for row in picked)
            -outcomes.declared_source_qty(source.name,current=current)-released_source_qty(source.name,current=current))
    return total


def own_held_untagged(plan, item_code, batch_no, current=False):
    """E5 measures these same company-owned held goods; do not subtract them twice."""
    from cfg_kanban.services import driver_delivery_outcomes as outcomes
    total = 0
    for row in outcomes.held_rows({'handling_unit':['is','not set'],'current_warehouse':plan.vehicle_warehouse,
            'item_code':item_code,'batch_no':batch_no or ['is','not set']},current=current):
        parent=frappe.db.get_value(outcomes.OUTCOME,row.parent,'dispatch_plan',for_update=current)
        if parent == plan.name:
            total += flt(row.refused_qty)
    return total


def assert_request(trip, plan):
    """Validate the generated demand against the immutable office assignments."""
    if not (plan.office_delivery_trip == trip.name and plan.plan_type == 'Customer Order'
            and plan.fulfilment_mode == 'Vehicle Delivery' and plan.company == trip.company
            and not plan.office_stop_key and not plan.sales_order and not plan.customer_site):
        frappe.throw('Consolidated dispatch must be one generated Customer Order Plan for this Trip')
    demand = {(row.stop_key, row.sales_order, row.sales_order_item): row for row in trip.orders if cint(row.is_stock_item)}
    seen = set()
    for line in plan.lines:
        key = (line.office_stop_key, line.sales_order, line.sales_order_item)
        source = demand.get(key)
        if (key in seen or not source or source.item_code != line.item_code or source.stock_uom != line.stock_uom
                or abs(flt(source.planned_qty) - flt(line.requested_qty)) > EPS):
            frappe.throw('Consolidated demand differs from the exact office stop and Sales Order row')
        seen.add(key)
    expected = {key for key in demand if not next(s for s in trip.stops if s.stop_key == key[0]).get('cancellation_request')}
    if not expected <= seen:
        frappe.throw('Consolidated Plan is missing customer demand')
    customers=stops(plan)
    if len({row.office_stop_key for row in customers})!=len(customers) or {row.office_stop_key for row in customers}!={row.office_stop_key for row in plan.lines}:
        frappe.throw('Consolidated Plan must retain one saved customer scope for every demand stop')
    for stop in customers:
        source = next((row for row in trip.stops if row.stop_key == stop.office_stop_key), None)
        if (not source or source.stop_purpose != 'Delivery' or source.customer != stop.customer
                or source.customer_address != stop.customer_address or source.customer_scan_point != stop.customer_scan_point):
            frappe.throw('Consolidated customer snapshot differs from its exact office stop')


def cancel_customer(plan, request, operator, session, reason, key):
    """Cancel only this demand; a posted shared load is never reversed here."""
    from cfg_kanban.services import dispatch_planning as planning
    root = plan.root
    if root.state not in ('Loaded','Reconciled','Cancelled'):
        if root.movement_manifest:
            manifest = frappe.get_doc('CFG Kanban Movement Manifest',root.movement_manifest,for_update=True)
            # Native release retains all other stock reservations, but invalidates
            # their unused physical loading confirmations for a fresh claim.
            planning.release_vehicle_claim(manifest,operator,session,reason,key+':claim')
            root = frappe.get_doc(PLAN,root.name,for_update=True)
            plan = scoped(root,plan.office_stop_key,current=True)
        if root.get('has_loose_tags'):
            from cfg_kanban.services import loose_tags
            for pack in loose_tags.packs_for_plan(plan):
                loose_tags._undo(pack,plan,operator,session,reason,key+':unpack')
        for row in frappe.db.get_values('CFG Kanban Dispatch Allocation',{
                'dispatch_plan':root.name,'dispatch_plan_line':['in',[line.name for line in plan.lines]],
                'state':'Reserved'},['name'],as_dict=True,for_update=True,order_by='name'):
            allocation=frappe.get_doc('CFG Kanban Dispatch Allocation',row.name,for_update=True)
            planning._release_allocation(allocation,root,operator,session,reason,key+':release')
        for line in plan.lines:
            line.db_set(dict(cancelled_before_loading=1,line_state='Cancelled',reserved_qty=0),update_modified=False)
        root.db_set('total_requested_qty',sum(flt(line.requested_qty) for line in root.lines if not line.get('cancelled_before_loading')),update_modified=True)
        planning._refresh_plan_totals(root.name)
        if not root.total_requested_qty:
            planning._cancel_unposted_plan(root,operator,session,reason,key+':empty',supervisor_cancel=True)
    plan.customer_dispatch_stop.db_set(dict(stop_cancellation=request.name,state='Skipped',
        fulfilment_status='Closed Incomplete',skip_reason=reason,skipped_by=operator.employee,
        skipped_on=now_datetime()),update_modified=True)
    aggregate(root)


"""E4A joins prepared known-customer loads to the existing customer-delivery engine."""
import json

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, today

from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.events import record
from cfg_kanban.services.operator_auth import require_operator


def _delivery_services():
    from cfg_kanban.services import customer_delivery
    return customer_delivery


def _planning_services():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def prepared_plans(site_name, operator):
    """Read-only, responsibility-filtered queue for the exact scanned customer site."""
    delivery = _delivery_services()
    if not delivery._customer_delivery_allowed(operator):
        return []
    planning = _planning_services()
    rows = frappe.get_all('CFG Kanban Dispatch Plan', filters={
        'state': 'Loaded', 'plan_type': 'Customer Order', 'fulfilment_mode': 'Vehicle Delivery',
        'customer_site': site_name,
    }, fields=['name', 'company', 'customer', 'customer_site', 'vehicle_warehouse',
               'vehicle_reference', 'business_label', 'dispatch_responsibility',
               'delivery_session', 'fulfilment_status', 'total_loaded_qty', 'dispatch_review_state'],
        order_by='loaded_on asc, name asc', limit_page_length=200)
    eligible = [row for row in rows if not row.get('dispatch_review_state') and row.fulfilment_status != 'Completed' and
            (planning._view_all(operator) or row.dispatch_responsibility in planning._responsibilities(operator)) and
            (not row.delivery_session or delivery._can_view_delivery(operator,
             frappe.get_doc('CFG Kanban Delivery Session', row.delivery_session)))]
    for row in eligible:
        lines=frappe.get_all('CFG Kanban Dispatch Plan Line',filters={'parent':row.name},
                            fields=['stock_uom','loaded_qty'],limit_page_length=0)
        quantities={}
        for line in lines:quantities[line.stock_uom]=quantities.get(line.stock_uom,0)+flt(line.loaded_qty)
        row['quantity_summary']=' / '.join(f'{qty:g} {uom}' for uom,qty in sorted(quantities.items()))
    return eligible


@frappe.whitelist()
def prepared_delivery_context(scan_value, operator_session_token):
    operator, _session = require_operator(operator_session_token)
    delivery = _delivery_services()
    delivery._require_customer_delivery(operator)
    value = str(scan_value or '').strip()
    if value.upper().startswith('DPL-') or frappe.db.exists('CFG Kanban Dispatch Plan', value):
        plan = frappe.get_doc('CFG Kanban Dispatch Plan', value)
        _planning_services()._assert_plan_authorized(plan, operator)
        if plan.get('fulfilment_mode') in ('Direct Warehouse Delivery','Customer Pickup'):
            from cfg_kanban.services.warehouse_fulfilment import _assert_plan
            _assert_plan(plan)
            if plan.delivery_session and not delivery._can_view_delivery(operator,
                    frappe.get_doc('CFG Kanban Delivery Session',plan.delivery_session)):
                frappe.throw('Prepared Delivery Session belongs to another operator')
            return {'plans':[plan.as_dict()],'customer_scan':None}
        if plan.state != 'Loaded' or plan.plan_type != 'Customer Order' or plan.fulfilment_mode != 'Vehicle Delivery':
            frappe.throw('Select a Loaded Customer Order / Vehicle Delivery Plan')
        if plan.delivery_session:
            session = frappe.get_doc('CFG Kanban Delivery Session', plan.delivery_session)
            if not delivery._can_view_delivery(operator, session):
                frappe.throw('Prepared Delivery Session belongs to another operator')
        return {'plans': [plan.as_dict()], 'customer_scan': None}
    site = delivery._resolve_customer_site(value)
    from cfg_kanban.services.warehouse_fulfilment import warehouse_plans
    return {'plans': prepared_plans(site.name, operator) + warehouse_plans(site.name, operator), 'customer_scan': value}


def validate_prepared_loading(plan):
    """Shared read-only loading gate for departure and native prepared-delivery entry."""
    manifest = frappe.get_doc('CFG Kanban Movement Manifest', plan.movement_manifest)
    if (manifest.dispatch_plan != plan.name or manifest.state != 'Received' or
            manifest.source_company != plan.company or manifest.source_warehouse != plan.source_warehouse or
            manifest.destination_company != plan.company or
            manifest.destination_warehouse != plan.vehicle_warehouse or not manifest.dispatch_stock_entry):
        frappe.throw('Prepared Plan does not have a completed loading Manifest for this lorry')
    entry = frappe.db.get_value('Stock Entry', manifest.dispatch_stock_entry,
                               ['docstatus', 'company'], as_dict=True)
    if not entry or entry.docstatus != 1 or entry.company != plan.company:
        frappe.throw('The lorry loading Stock Entry must be submitted for the Plan Company')
    return manifest


@frappe.whitelist()
def start_prepared_delivery(dispatch_plan, customer_scan, event_token, operator_session_token):
    if not str(event_token or '').strip():
        frappe.throw('A stable prepared-delivery event token is required')
    operator, session = require_operator(operator_session_token, 'start')
    engine, planning = _delivery_services(), _planning_services()
    engine._require_customer_delivery(operator)
    candidate=frappe.get_doc('CFG Kanban Dispatch Plan',dispatch_plan)
    route_scope_lock=None
    if candidate.get('route_approval_required') or candidate.get('route_sequence_scope')=='Combined Lorry Trip' or candidate.get('active_route_sheet'):
        from cfg_kanban.services.route_sheets import lock_plan_route_scope, check_plan_route_scope
        route_scope_lock=lock_plan_route_scope(candidate,operator)
    plan = planning._locked_authorized_plan(dispatch_plan, operator)
    if route_scope_lock:check_plan_route_scope(plan,route_scope_lock)
    if plan.get('fulfilment_mode') in ('Direct Warehouse Delivery','Customer Pickup'):
        from cfg_kanban.services.warehouse_fulfilment import start_warehouse_delivery
        return start_warehouse_delivery(plan,customer_scan,event_token,operator,session,operator_session_token)
    # A Plan lock serializes creation; the Session also has a unique active Plan key.
    request_token = canonical_key('prepared-customer-delivery', plan.name, event_token)
    replay = frappe.db.get_value('CFG Kanban Delivery Session',
        {'idempotency_key': canonical_key('customer-delivery-session', plan.customer_site,
                                        plan.vehicle_warehouse, request_token)}, 'name')
    existing = replay or plan.get('delivery_session')
    if existing:
        result = frappe.get_doc('CFG Kanban Delivery Session', existing)
        identity = engine.resolve_logistics_scan(customer_scan)
        if not identity or identity.get('identity_type') != 'Customer Scan Point' or identity['name'] != result.customer_scan_point:
            frappe.throw('Scan the Customer Site assigned to this prepared delivery')
        if result.dispatch_plan != plan.name or not engine._can_view_delivery(operator, result):
            frappe.throw('Prepared Delivery Session belongs to another Plan or operator')
        return engine.get_delivery_session(result.name, operator_session_token)
    if plan.get('dispatch_review_state'):
        frappe.throw('Resolve the frozen Dispatch Review before starting customer fulfilment')
    if plan.state != 'Loaded' or plan.plan_type != 'Customer Order' or plan.fulfilment_mode != 'Vehicle Delivery':
        frappe.throw('Customer fulfilment requires a Loaded Customer Order / Vehicle Delivery Plan')
    site = engine._resolve_customer_site(customer_scan)
    if (site.name != plan.customer_site or site.selling_company != plan.company or
            site.customer != plan.customer or site.customer_address != plan.customer_address):
        frappe.throw('Scanned Customer Site does not match the prepared Plan Company, Customer and address')
    if plan.get('route_approval_required') or plan.get('route_sequence_scope')=='Combined Lorry Trip' or plan.get('active_route_sheet'):
        from cfg_kanban.services.route_sheets import assert_visit_allowed
        assert_visit_allowed(plan,site.name)
    validate_prepared_loading(plan)
    allocations = _loaded_allocations(plan)
    outcome = _driver_outcomes().pending_for(plan, operator) if plan.get('driver_delivery_outcome') else None
    accepted = {r.dispatch_allocation:flt(r.accepted_qty) for r in outcome.lines} if outcome else {}
    # Native ERP stock and physical identities are locked in consistent sorted order.
    for item in sorted({row.item_code for row in allocations}):
        planning._lock_erp_bin(item, plan.vehicle_warehouse)
    for name in sorted({row.handling_unit for row in allocations if row.handling_unit}):
        frappe.db.sql('select name from `tabCFG Kanban Handling Unit` where name=%s for update', name)
    sale_sources = [frappe._dict(dict(row, allocated_qty=accepted[row.name])) for row in allocations if accepted[row.name]>0] if outcome else allocations
    order, order_rows = _order_assignments(plan, sale_sources) if sale_sources else (None, {})
    policy = plan.proof_policy
    if not policy or policy == 'Inherit Customer Site':
        policy = site.proof_policy
    if policy not in {'Required', 'Optional', 'Unattended Delivery Allowed', 'No Proof Required'}:
        frappe.throw('Unsupported prepared-delivery proof policy')
    snapshot = json.loads(plan.profile_snapshot_json)
    extra = {'dispatch_plan': plan.name, 'active_dispatch_plan_key': plan.name,
             'sales_order': plan.sales_order, 'proof_policy': policy,
             'auto_submit_delivery_note': cint(snapshot.get('auto_submit_delivery_note'))}
    if order:
        price_list=order.selling_price_list or site.default_price_list
        if price_list:
            extra['price_list'] = price_list
        extra['sales_order_context_json'] = json.dumps({key: order.get(key) for key in
            ('currency', 'conversion_rate', 'price_list_currency', 'plc_conversion_rate', 'project')}, sort_keys=True)
    created = engine._start_delivery_session(site, plan.vehicle_warehouse, request_token,
                                               operator, session, snapshots=extra)
    if outcome:
        _driver_outcomes().bind(outcome, created)
    for source in allocations:
        if outcome and accepted[source.name] <= 0:
            continue
        source = frappe._dict(dict(source, allocated_qty=accepted[source.name])) if outcome else source
        link = {'dispatch_allocation': source.name, 'sales_order_item': order_rows.get(source.name)}
        if source.allocation_kind == 'Tagged Stock':
            unit = frappe.get_doc('CFG Kanban Handling Unit', source.handling_unit)
            if (unit.item_code != source.item_code or (unit.batch_no or '') != (source.batch_no or '') or
                    unit.stock_uom != source.stock_uom or
                    abs(flt(unit.current_qty) - (next(flt(r.prepared_qty) for r in outcome.lines if r.dispatch_allocation==source.name) if outcome else flt(source.allocated_qty))) > 0.000001):
                frappe.throw('Loaded Stock Tag identity or quantity changed; reconcile the prepared Plan')
            assert_delivery_tag_expiry(unit)
            membership = engine.active_container_membership(unit.name)
            engine._reserve_unit(created, unit, source.allocated_qty, request_token, operator, session,
                membership.container_handling_unit if membership else None,
                membership.container_visible_code if membership else None, snapshots=link)
        else:
            _reserve_untagged(created, source, request_token, operator, session, link)
    created.db_set('state', 'Allocating Stock', update_modified=True)
    if outcome:
        _driver_outcomes().activate(outcome, created, operator, session)
    validate_prepared_allocations(created)
    plan.db_set({'delivery_session': created.name, 'fulfilment_status': 'In Progress', 'prepared_stock_commitment': 1}, update_modified=True)
    if outcome:
        sync_plan_delivery(created)
    record('Prepared Customer Delivery Started', delivery_session=created.name,
           reference_doctype=plan.doctype, reference_name=plan.name,
           operator=operator.employee, operator_session=session.name,
           terminal_user=session.terminal_user, device_id=request_token,
           notes=f'{site.site_code}; lorry {plan.vehicle_warehouse}; exact loaded allocations')
    return engine.get_delivery_session(created.name, operator_session_token)


def _loaded_allocations(plan, for_update=False):
    if plan.get('existing_lorry_stock_only'):
        from cfg_kanban.services.trip_dispatch import existing_pool
        if existing_pool(plan):return []
        frappe.throw('Existing-stock context cannot have a loading Manifest or planned quantities')
    filters = {'dispatch_plan': plan.name, 'movement_manifest': plan.movement_manifest, 'state': 'Loaded'}
    fields = ['name', 'dispatch_plan_line', 'allocation_kind', 'handling_unit', 'item_code',
              'batch_no', 'stock_uom', 'allocated_qty', 'load_confirmed']
    rows = (frappe.db.get_values('CFG Kanban Dispatch Allocation', filters, fields,
                                as_dict=True, for_update=True, order_by='name asc') if for_update else
            frappe.get_all('CFG Kanban Dispatch Allocation', filters=filters, fields=fields,
                           order_by='name asc', limit_page_length=0))
    by_line = {}
    for row in rows:
        if not row.load_confirmed or flt(row.allocated_qty) <= 0:
            frappe.throw('Every prepared allocation must have confirmed positive loaded quantity')
        if row.allocation_kind not in {'Tagged Stock', 'Untagged ERP Stock'}:
            frappe.throw('Unsupported loaded allocation kind')
        if (row.allocation_kind == 'Tagged Stock') != bool(row.handling_unit):
            frappe.throw('Loaded allocation physical identity is inconsistent')
        by_line[row.dispatch_plan_line] = by_line.get(row.dispatch_plan_line, 0) + flt(row.allocated_qty)
    if not rows or set(by_line) != {row.name for row in plan.lines}:
        frappe.throw('Prepared Plan loading allocations do not match its Item lines')
    for line in plan.lines:
        if abs(by_line[line.name] - flt(line.loaded_qty)) > 0.000001:
            frappe.throw('Prepared Plan loaded quantities do not match its allocation audit')
        if any(row.item_code != line.item_code or row.stock_uom != line.stock_uom or
               (line.batch_no and row.batch_no != line.batch_no)
               for row in rows if row.dispatch_plan_line == line.name):
            frappe.throw('Prepared Plan allocation Item, UOM or Batch differs from its line')
    return rows


def _order_assignments(plan, allocations):
    if not plan.sales_order:
        return None, {}
    frappe.db.sql('select name from `tabSales Order` where name=%s for update', plan.sales_order)
    order = frappe.get_doc('Sales Order', plan.sales_order)
    if order.docstatus != 1 or order.company != plan.company or order.customer != plan.customer or order.status in {'Closed','On Hold','Cancelled'}:
        frappe.throw('Prepared Sales Order must remain open, submitted, and match Company/Customer')
    remaining = {row.name: max(flt(row.qty)-flt(row.delivered_qty),0)*flt(row.conversion_factor) for row in order.items}
    assigned = {}
    for allocation in allocations:
        exact=None
        if plan.get('office_delivery_trip'):
            line=next((r for r in plan.lines if r.name==allocation.dispatch_plan_line),None)
            if not line or not line.sales_order_item:frappe.throw('Generated stock source lost its exact Sales Order row')
            exact=line.sales_order_item
        match = next((row for row in order.items if (not exact or row.name==exact) and row.item_code == allocation.item_code and
                      row.stock_uom == allocation.stock_uom and flt(row.conversion_factor)>0 and
                      remaining[row.name]+0.000001 >= flt(allocation.allocated_qty)), None)
        if not match:
            frappe.throw(f'Loaded quantity for {allocation.item_code} must fit an undelivered Sales Order row; split preparation by order row before loading')
        assigned[allocation.name] = match.name
        remaining[match.name] -= flt(allocation.allocated_qty)
    return order, assigned


def active_untagged_delivery_qty(company, warehouse, item_code, batch_no, current=False):
    condition = 'and allocation.batch_no=%(batch)s' if batch_no else "and ifnull(allocation.batch_no,'')=''"
    if current:
        rows = frappe.db.sql(f'''
            select allocation.allocated_qty
            from `tabCFG Kanban Delivery Allocation` allocation
            inner join `tabCFG Kanban Delivery Session` delivery on delivery.name=allocation.delivery_session
            where allocation.allocation_kind='Untagged ERP Stock'
              and allocation.state in ('Reserved','Delivery Pending','Exception')
              and delivery.selling_company=%(company)s and allocation.source_warehouse=%(warehouse)s
              and allocation.item_code=%(item)s {condition}
            order by allocation.name for update
            ''', {'company':company,'warehouse':warehouse,'item':item_code,'batch':batch_no}, as_dict=True)
        return sum(flt(row.allocated_qty) for row in rows)
    return flt(frappe.db.sql(f'''
        select coalesce(sum(allocation.allocated_qty),0)
        from `tabCFG Kanban Delivery Allocation` allocation
        inner join `tabCFG Kanban Delivery Session` delivery on delivery.name=allocation.delivery_session
        where allocation.allocation_kind='Untagged ERP Stock'
          and allocation.state in ('Reserved','Delivery Pending','Exception')
          and delivery.selling_company=%(company)s and allocation.source_warehouse=%(warehouse)s
          and allocation.item_code=%(item)s {condition}
        ''', {'company':company,'warehouse':warehouse,'item':item_code,'batch':batch_no})[0][0])


def _reserve_untagged(delivery, source, event_token, operator, session, snapshots, prepared=True):
    planning = _planning_services()
    inventory = frappe.db.get_value('Item', source.item_code,
                                   ['is_stock_item','has_serial_no','has_batch_no','stock_uom'], as_dict=True)
    if (not inventory or not inventory.is_stock_item or inventory.has_serial_no or
            (inventory.has_batch_no and not source.batch_no) or inventory.stock_uom != source.stock_uom):
        frappe.throw('Untagged delivery requires a non-serialized stock Item, stock UOM and exact Batch where required')
    planning._validate_batch(source.item_code, source.batch_no)
    _assert_untagged_batch_expiry(source.batch_no)
    if frappe.db.get_value('UOM', source.stock_uom, 'must_be_whole_number') and flt(source.allocated_qty)%1:
        frappe.throw('Untagged delivery quantity must respect whole-number UOM')
    available = planning._untagged_available(delivery.selling_company, delivery.source_warehouse,
                                            source.item_code, source.batch_no, exclude_prepared_plan=delivery.dispatch_plan if prepared else None)
    if flt(source.allocated_qty) > available + 0.000001:
        frappe.throw(f'Untagged source stock available for {source.item_code} is {available}')
    return frappe.get_doc({'doctype':'CFG Kanban Delivery Allocation', 'state':'Reserved',
        'allocation_kind':'Untagged ERP Stock', 'delivery_session':delivery.name,
        'visible_code':'ERP STOCK', 'item_code':source.item_code, 'batch_no':source.batch_no,
        'stock_uom':source.stock_uom, 'allocated_qty':source.allocated_qty,
        'source_warehouse':delivery.source_warehouse, 'reserved_by_operator':operator.employee,
        'operator_session':session.name, 'reserved_on':now_datetime(),
        'reservation_key':canonical_key('prepared-untagged-delivery',delivery.name,source.name,event_token),
        **snapshots}).insert(ignore_permissions=True)


def validate_untagged_delivery_stock(delivery, allocation):
    planning = _planning_services()
    planning._lock_erp_bin(allocation.item_code, delivery.source_warehouse)
    planning._validate_batch(allocation.item_code, allocation.batch_no)
    _assert_untagged_batch_expiry(allocation.batch_no)
    planning._assert_untagged_allocation_available(frappe._dict(
        source_company=delivery.selling_company, source_warehouse=delivery.source_warehouse,
        item_code=allocation.item_code, batch_no=allocation.batch_no))


def validate_prepared_allocations(delivery, allocations=None):
    if delivery.get('route_stop'):
        from cfg_kanban.services.route_delivery import validate_route_allocations
        return validate_route_allocations(delivery, allocations)
    if not delivery.get('dispatch_plan'):
        return
    if delivery.get('fulfilment_mode') in ('Direct Warehouse Delivery','Customer Pickup'):
        from cfg_kanban.services.warehouse_fulfilment import validate_warehouse_allocations
        return validate_warehouse_allocations(delivery,allocations)
    plan = frappe.get_doc('CFG Kanban Dispatch Plan', delivery.dispatch_plan)
    if (plan.state != 'Loaded' or plan.customer_site != delivery.customer_scan_point or
            plan.company != delivery.selling_company or plan.customer != delivery.customer or
            plan.customer_address != delivery.customer_address or plan.vehicle_warehouse != delivery.source_warehouse):
        frappe.throw('Delivery Session no longer matches its loaded Customer Order Plan')
    if delivery.get('driver_delivery_outcome'):
        if allocations is None:
            allocations=frappe.get_all('CFG Kanban Delivery Allocation',filters={'delivery_session':delivery.name,'state':['in',['Reserved','Delivery Pending']]},
                fields=['name','dispatch_allocation','handling_unit','item_code','batch_no','stock_uom','allocated_qty'],limit_page_length=0)
        _driver_outcomes().validate_allocations(delivery, allocations)
        return
    sources = {row.name:row for row in _loaded_allocations(plan)}
    if allocations is None:
        allocations = frappe.get_all('CFG Kanban Delivery Allocation', filters={
            'delivery_session':delivery.name,'state':['in',['Reserved','Delivery Pending']]},
            fields=['name','dispatch_allocation','handling_unit','item_code','batch_no','stock_uom','allocated_qty'],
            limit_page_length=0)
    seen=set()
    for row in allocations:
        source=sources.get(row.dispatch_allocation)
        if not source or row.dispatch_allocation in seen or any(
            (row.get(field) or '') != (source.get(field) or '')
            for field in ('handling_unit','item_code','batch_no','stock_uom')) or abs(
                flt(row.allocated_qty)-flt(source.allocated_qty))>0.000001:
            frappe.throw('Delivery allocations must match the exact prepared load; partial or replacement delivery requires reconciliation')
        seen.add(row.dispatch_allocation)
    if seen != set(sources):
        frappe.throw('Every loaded allocation is required; release all and cancel the empty Session to restart')


def apply_sales_order_payload(delivery, payload, allocations):
    if not delivery.get('sales_order'):
        return
    order=frappe.get_doc('Sales Order',delivery.sales_order)
    if order.docstatus != 1 or order.company != delivery.selling_company or order.customer != delivery.customer or order.status in {'Closed','On Hold','Cancelled'}:
        frappe.throw('Linked Sales Order is no longer open for this Company and Customer')
    remaining={row.name:max(flt(row.qty)-flt(row.delivered_qty),0)*flt(row.conversion_factor) for row in order.items}
    order_rows={row.name:row for row in order.items}
    by_allocation={row.name:row for row in allocations}
    for row in payload['items']:
        source=by_allocation[row['delivery_allocation']]
        item=order_rows.get(source.sales_order_item)
        if not item or item.item_code != row['item_code'] or item.stock_uom != row['uom'] or flt(item.conversion_factor)<=0:
            frappe.throw('Delivery allocation does not match its Sales Order item row')
        remaining[item.name]-=flt(row['qty'])
        if remaining[item.name]<-0.000001:
            frappe.throw('Prepared delivery exceeds current Sales Order remaining stock quantity')
        row.update(against_sales_order=order.name,so_detail=item.name,stock_uom=row['uom'],
                   stock_qty=row['qty'],uom=item.uom,qty=flt(row['qty'])/flt(item.conversion_factor),
                   conversion_factor=flt(item.conversion_factor),rate=flt(item.rate))
    saved=json.loads(delivery.sales_order_context_json or '{}')
    if order.selling_price_list and order.selling_price_list != delivery.price_list:
        frappe.throw('Sales Order price list changed after delivery started')
    if any(not _same_currency_context(key,order.get(key),value) for key,value in saved.items()):
        frappe.throw('Sales Order currency context changed after delivery started')
    payload.update({key:value for key,value in saved.items() if value not in (None,'')})


def sync_plan_delivery(delivery):
    """Mirror existing execution records; E3 Loaded remains a separate lifecycle."""
    if delivery.get('route_stop'):
        from cfg_kanban.services.route_delivery import sync_route_delivery
        return sync_route_delivery(delivery)
    if not delivery.get('dispatch_plan'):
        return
    if delivery.get('fulfilment_mode') in ('Direct Warehouse Delivery','Customer Pickup'):
        from cfg_kanban.services.warehouse_fulfilment import sync_warehouse_delivery
        return sync_warehouse_delivery(delivery)
    # Delivery services hold their Session lock before this Plan lock. Start holds Plan only
    # while creating a new Session; it never locks an existing Session during replay.
    frappe.db.sql('select name from `tabCFG Kanban Dispatch Plan` where name=%s for update',delivery.dispatch_plan)
    plan=frappe.get_doc('CFG Kanban Dispatch Plan',delivery.dispatch_plan)
    if plan.delivery_session and plan.delivery_session != delivery.name:
        frappe.throw('Dispatch Plan is linked to a different Delivery Session')
    state=delivery.state
    status=('Completed' if state=='Closed' else 'Delivered' if state in {'Delivered','Invoiced'} else
            'Delivery Note Pending' if state=='ERP Document Pending' else
            'Exception' if state=='Exception' else 'Not Started' if state=='Cancelled' else 'In Progress')
    qty=frappe.db.sql("""select coalesce(sum(delivered_qty),0) from `tabCFG Kanban Delivery Allocation`
        where delivery_session=%s and state='Delivered'""",delivery.name)[0][0]
    plan.db_set({'delivery_session':None if state=='Cancelled' else delivery.name,
        'fulfilment_status':status,'delivery_note':delivery.delivery_note,'delivery_proof':delivery.delivery_proof,
        'total_delivered_qty':flt(qty),'fulfilment_completed_on':delivery.completed_on if state=='Closed' else None},update_modified=True)
    if state=='Cancelled':
        delivery.db_set('active_dispatch_plan_key',None,update_modified=False)
    if delivery.get('driver_delivery_outcome'):
        _driver_outcomes().auto_release(delivery)


def assert_delivery_tag_expiry(unit):
    from cfg_kanban.services.logistics_stock_identity import identity_snapshot, _expiry
    expiry = _expiry(identity_snapshot(unit))
    if expiry and getdate(expiry) < getdate(today()):
        frappe.throw(f'Stock Tag {unit.handling_unit_id} has expired material or printed expiry')


def validate_prepared_delivery_note(doc, method=None):
    """Run before native stock posting, including manual submission of a saved Draft."""
    name=doc.get('cfg_delivery_session')
    if not name or doc.get('is_return'):
        return
    frappe.db.sql('select name from `tabCFG Kanban Delivery Session` where name=%s for update',name)
    delivery=frappe.get_doc('CFG Kanban Delivery Session',name,for_update=True)
    if not delivery.get('dispatch_plan'):
        return
    if delivery.state not in {'Awaiting Confirmation','ERP Document Pending','Exception'}:
        frappe.throw('Prepared Delivery Session cannot submit a Delivery Note in its current state')
    engine=_delivery_services()
    payload=engine._customer_delivery_payload(delivery)
    allocations=frappe.get_all('CFG Kanban Delivery Allocation',filters={
        'delivery_session':name,'state':'Delivery Pending'},
        fields=['name','handling_unit','visible_code','item_code','batch_no','stock_uom','allocated_qty','sales_order_item'],
        limit_page_length=0)
    from cfg_kanban.integrations.logistics_feedback import _validate_customer_delivery_header, _validate_customer_delivery_rows
    _validate_customer_delivery_header(doc,delivery)
    rows=_validate_customer_delivery_rows(doc,delivery,allocations)
    for expected in payload['items']:
        actual=rows[expected['delivery_allocation']]
        if not expected.get('handling_unit') and actual.get('batch_no') and not actual.get('use_serial_batch_fields'):
            frappe.throw('Untagged batch delivery must retain its exact Batch fields')
        if not expected.get('handling_unit') and actual.get('process_certificate_set'):
            frappe.throw('Untagged delivery cannot acquire a certificate identity from another stock source')
        if abs(flt(rows[expected['delivery_allocation']].rate)-flt(expected['rate']))>0.000001:
            frappe.throw('Prepared Delivery Note rate differs from the controlled customer/order price')
    for key in ('currency','conversion_rate','price_list_currency','plc_conversion_rate','project'):
        if key in payload and not _same_currency_context(key,doc.get(key),payload[key]):
            frappe.throw('Prepared Delivery Note currency context differs from its Sales Order')


def _same_currency_context(key, left, right):
    if key in {'conversion_rate','plc_conversion_rate'}:
        return abs(flt(left)-flt(right))<=0.000001
    return (left or '') == (right or '')


def assert_prepared_tag_scope(handling_unit, delivery):
    rows=frappe.db.sql("""
        select allocation.dispatch_plan, plan.plan_type
        from `tabCFG Kanban Dispatch Allocation` allocation
        inner join `tabCFG Kanban Dispatch Plan` plan on plan.name=allocation.dispatch_plan
        where allocation.handling_unit=%s and allocation.state='Loaded' and plan.state='Loaded'
          and plan.fulfilment_mode='Vehicle Delivery'
          and ((plan.plan_type='Customer Order' and plan.prepared_stock_commitment=1
                and ifnull(plan.fulfilment_status,'Not Started') not in ('Completed','Delivered'))
               or (plan.plan_type='Open Route Stock' and plan.route_stock_commitment=1))
          and allocation.allocated_qty > coalesce((select sum(picked.allocated_qty)
               from `tabCFG Kanban Delivery Allocation` picked
               where picked.dispatch_allocation=allocation.name
                 and picked.state in ('Reserved','Delivery Pending','Exception','Delivered')),0) + 0.000001
        """,handling_unit)
    if any(row[0] != delivery.get('dispatch_plan') or
           (len(row)>1 and row[1]=='Open Route Stock' and not delivery.get('route_stop')) for row in rows):
        frappe.throw('Stock Tag belongs to a prepared Customer Order/Route load; start that Plan instead of ad-hoc allocation')


def waiting_prepared_untagged_qty(company, warehouse, item_code, batch_no, exclude_plan=None, current=False, exclude_refusal_outcome=None):
    """Keep each undelivered prepared quantity committed without double-counting reservations."""
    condition='and allocation.batch_no=%(batch)s' if batch_no else "and ifnull(allocation.batch_no,'')=''"
    if current:
        rows = frappe.db.sql(f"""
        select allocation.name, allocation.allocated_qty
        from `tabCFG Kanban Dispatch Allocation` allocation
        inner join `tabCFG Kanban Dispatch Plan` plan on plan.name=allocation.dispatch_plan
        where allocation.allocation_kind='Untagged ERP Stock' and allocation.state='Loaded'
          and plan.state='Loaded' and plan.fulfilment_mode='Vehicle Delivery' and plan.company=%(company)s
          and plan.vehicle_warehouse=%(warehouse)s and allocation.item_code=%(item)s
          and ((plan.plan_type='Customer Order' and plan.prepared_stock_commitment=1
                and ifnull(plan.fulfilment_status,'Not Started') not in ('Completed','Delivered'))
               or (plan.plan_type='Open Route Stock' and plan.route_stock_commitment=1))
          and (%(excluded)s is null or plan.name!=%(excluded)s) {condition}
        order by allocation.name for update
        """, {'company':company,'warehouse':warehouse,'item':item_code,'batch':batch_no,
               'excluded':exclude_plan}, as_dict=True)
        picked = {}
        if rows:
            for row in frappe.db.get_values('CFG Kanban Delivery Allocation',
                    {'dispatch_allocation':['in',[row.name for row in rows]],
                     'state':['in',['Reserved','Delivery Pending','Exception','Delivered']]},
                    ['dispatch_allocation','allocated_qty'], as_dict=True, for_update=True, order_by='name'):
                picked[row.dispatch_allocation] = picked.get(row.dispatch_allocation, 0) + flt(row.allocated_qty)
        refusals = {r.name:_driver_outcomes().declared_source_qty(r.name, current=True) for r in rows} if frappe.db.exists('DocType','CFG Kanban Delivery Outcome') else {}
        return sum(max(flt(row.allocated_qty)-picked.get(row.name, 0)-refusals.get(row.name,0), 0) for row in rows) + held_refused_untagged_qty(company,warehouse,item_code,batch_no,current=True,exclude_outcome=exclude_refusal_outcome)
    return flt(frappe.db.sql(f"""
        select coalesce(sum(greatest(allocation.allocated_qty - coalesce((select sum(refused.refused_qty) from `tabCFG Kanban Delivery Outcome Line` refused where refused.dispatch_allocation=allocation.name),0) - coalesce((
            select sum(picked.allocated_qty) from `tabCFG Kanban Delivery Allocation` picked
            where picked.dispatch_allocation=allocation.name
              and picked.state in ('Reserved','Delivery Pending','Exception','Delivered')
        ),0),0)),0)
        from `tabCFG Kanban Dispatch Allocation` allocation
        inner join `tabCFG Kanban Dispatch Plan` plan on plan.name=allocation.dispatch_plan
        where allocation.allocation_kind='Untagged ERP Stock' and allocation.state='Loaded'
          and plan.state='Loaded' and plan.fulfilment_mode='Vehicle Delivery' and plan.company=%(company)s
          and plan.vehicle_warehouse=%(warehouse)s and allocation.item_code=%(item)s
          and ((plan.plan_type='Customer Order' and plan.prepared_stock_commitment=1
                and ifnull(plan.fulfilment_status,'Not Started') not in ('Completed','Delivered'))
               or (plan.plan_type='Open Route Stock' and plan.route_stock_commitment=1))
          and (%(excluded)s is null or plan.name!=%(excluded)s) {condition}
        """,{'company':company,'warehouse':warehouse,'item':item_code,'batch':batch_no,
              'excluded':exclude_plan})[0][0]) + held_refused_untagged_qty(company,warehouse,item_code,batch_no,exclude_outcome=exclude_refusal_outcome)


def _assert_untagged_batch_expiry(batch_no):
    expiry=frappe.db.get_value('Batch',batch_no,'expiry_date') if batch_no else None
    if expiry and getdate(expiry)<getdate(today()):
        frappe.throw(f'Batch {batch_no} is expired and cannot be delivered')


def _driver_outcomes():
    from cfg_kanban.services import driver_delivery_outcomes
    return driver_delivery_outcomes


def held_refused_untagged_qty(company, warehouse, item_code, batch_no, current=False, exclude_outcome=None):
    if not frappe.db.exists('DocType','CFG Kanban Delivery Outcome'):
        return 0
    return _driver_outcomes().held_untagged(company,warehouse,item_code,batch_no,current=current,exclude_outcome=exclude_outcome)

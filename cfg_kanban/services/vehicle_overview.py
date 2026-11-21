"""Read-only lorry stock, loaded work and upcoming loads after E3 completes.

ERP ledger quantity and tag identity are separate views of the same material.
A completed loading Manifest is not evidence that the lorry is currently empty.
"""
import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.operator_auth import require_operator

PLAN = 'CFG Kanban Dispatch Plan'
PLAN_FIELDS = ['name','business_label','company','source_warehouse','plan_type',
    'state','customer','customer_site','customer_address','territory','logistics_route',
    'delivery_route_reference','stop_sequence_policy','vehicle_warehouse','vehicle_reference',
    'fulfilment_status','dispatch_review_state','delivery_session','delivery_note',
    'dispatch_responsibility','destination_assignment_policy','destination_warehouse',
    'required_date','trip_date','priority','loaded_on','movement_manifest','modified',
    'route_sequence_scope','route_template','customer_verification']
PREPARING = ('Draft','Awaiting Approval','Approved','Picking','Ready for Vehicle')
ASSIGNED = ('Vehicle Claimed','Loading','Ready to Dispatch','Dispatch Pending','Loaded','Ready for Fulfilment','Exception')


def _planning():
    from cfg_kanban.services import dispatch_planning
    return dispatch_planning


def _rows(company, operator=None, states=None, warehouse=None, source=None):
    filters = {'company':company,'fulfilment_mode':'Vehicle Delivery'}
    if states:
        filters['state'] = ['in',states]
    if warehouse:
        filters['vehicle_warehouse'] = warehouse
    if source:
        filters['source_warehouse'] = source
    if operator and not _planning()._view_all(operator):
        responsibilities = sorted(_planning()._responsibilities(operator))
        if not responsibilities:
            return []
        filters['dispatch_responsibility'] = ['in',responsibilities]
    result = frappe.get_list(PLAN, filters=filters, fields=PLAN_FIELDS,
        order_by='required_date asc, trip_date asc, name asc', limit_page_length=0)
    result.sort(key=lambda row: ({'Urgent':0,'High':1,'Normal':2,'Low':3}.get(row.priority,2),
                               str(row.required_date or row.trip_date or ''),str(row.name)))
    return _details(result)


def _details(plans):
    if not plans:
        return plans
    by_name = {row.name:row for row in plans}
    for row in plans:
        row['lines'] = []
        row['stops'] = []
    for line in frappe.get_all('CFG Kanban Dispatch Plan Line',
            filters={'parent':['in',list(by_name)]},
            fields=['name','parent','item_code','batch_no','stock_uom','requested_qty',
                    'reserved_qty','loaded_qty'],
            order_by='parent asc, idx asc',limit_page_length=0):
        by_name[line.parent]['lines'].append(line)
    for stop in frappe.get_all('CFG Kanban Route Stop',
            filters={'dispatch_plan':['in',list(by_name)]},
            fields=['name','dispatch_plan','planned_sequence','actual_sequence','state',
                    'customer_scan_point','site_name','customer','customer_address',
                    'delivery_session','delivery_note','delivery_proof'],
            order_by='planned_sequence asc, actual_sequence asc, name asc',limit_page_length=0):
        by_name[stop.dispatch_plan]['stops'].append(stop)
    for row in plans:
        totals = {}
        for line in row['lines']:
            values = totals.setdefault(line.stock_uom,{'requested':0,'reserved':0,'loaded':0})
            for field in values:
                values[field] += flt(line.get(field+'_qty'))
        row['quantities_by_uom'] = totals
    return plans


def _can_read_stock(vehicle, operator, plans):
    if not frappe.has_permission('Warehouse',ptype='read',doc=vehicle.name):
        return False
    if _planning()._view_all(operator):
        return True
    responsibilities = _planning()._responsibilities(operator)
    if plans or responsibilities.intersection({'Customer Delivery','Logistics Reconciliation'}):
        return True
    routes = frappe.get_all('CFG Kanban Logistics Route',
        filters={'active':1,'source_company':vehicle.company,'destination_company':vehicle.company},
        fields=['dispatch_responsibility','receipt_responsibility'],limit_page_length=0)
    return any(row.dispatch_responsibility in responsibilities or row.receipt_responsibility in responsibilities
               for row in routes)


def _stock(vehicle):
    from cfg_kanban.services.route_reconciliation import _erp_balances
    balances = _erp_balances(vehicle.company,vehicle.name,now_datetime())
    tags = frappe.get_all('CFG Kanban Handling Unit',filters={
        'inventory_company':vehicle.company,'current_warehouse':vehicle.name,
        'identity_state':'Active','current_qty':['>',0.000001]},
        fields=['name','handling_unit_id','physical_container','virtual_content','item_code',
                'batch_no','stock_uom','expiry_date','process_certificate_set',
                'current_qty','reserved_qty','available_qty','quality_state','movement_state'],
        order_by='item_code asc, batch_no asc, handling_unit_id asc',limit_page_length=0)
    codes = {key[0] for key in balances} | {row.item_code for row in tags if row.item_code}
    items = {row.name:row for row in frappe.get_list('Item', filters={'name':['in',sorted(codes)]},
        fields=['name','item_name','stock_uom','is_stock_item'],limit_page_length=0)} if codes else {}
    batches = sorted({key[1] for key in balances if key[1]})
    expiry = {row.name:row.expiry_date for row in frappe.get_all('Batch',
        filters={'name':['in',batches]},fields=['name','expiry_date'],limit_page_length=0)} if batches else {}
    containers = sorted({row.physical_container for row in tags if row.physical_container})
    physical = {row.name:row.handling_unit_id for row in frappe.get_all('CFG Kanban Handling Unit',
        filters={'name':['in',containers]},fields=['name','handling_unit_id'],limit_page_length=0)} if containers else {}
    grouped = {}
    visible_tags = []
    for row in tags:
        if row.item_code not in items:
            continue
        row['physical_scan_code'] = physical.get(row.physical_container) or row.handling_unit_id
        visible_tags.append(row)
        grouped.setdefault((row.item_code,row.batch_no or ''),[]).append(row)
    rows = []
    for key in sorted(set(balances) | set(grouped)):
        item = items.get(key[0])
        if not item:
            continue
        tag_qty = sum(flt(tag.current_qty) for tag in grouped.get(key,[]))
        erp_qty = flt(balances.get(key))
        rows.append(dict(item_code=key[0],item_name=item.item_name,batch_no=key[1] or None,
            stock_uom=item.stock_uom,inventory_control_mode='ERP Stock' if item.is_stock_item else 'Kanban Operational Inventory',
            erp_qty=erp_qty if item.is_stock_item else None,tag_qty=tag_qty,
            untagged_qty=max(erp_qty-tag_qty,0) if item.is_stock_item else None,
            identity_variance=bool(item.is_stock_item and tag_qty>erp_qty+0.000001),
            expiry_date=expiry.get(key[1]),tags=grouped.get(key,[])))
    return dict(stock=rows,tags=visible_tags,stock_as_of=now_datetime(),
                item_rows_restricted=bool(codes-set(items)))


def vehicle_context(warehouse, operator):
    vehicle = _planning()._vehicle_warehouse(warehouse)
    if not frappe.has_permission('Warehouse',ptype='read',doc=vehicle.name):
        return dict(warehouse=vehicle.name,company=vehicle.company,vehicle_reference=vehicle.cfg_vehicle_reference,
            can_view_stock=False,assigned_plans=[],upcoming_plans=[],ready_plans=[],stock=[],tags=[])
    assigned = _rows(vehicle.company,operator,ASSIGNED,warehouse=vehicle.name)
    preparing = _rows(vehicle.company,operator,PREPARING)
    preparing = [row for row in preparing if row.destination_assignment_policy!='Select at Receipt'
        and (row.destination_assignment_policy!='Fixed' or row.destination_warehouse==vehicle.name)]
    result = dict(warehouse=vehicle.name,company=vehicle.company,vehicle_reference=vehicle.cfg_vehicle_reference,
        assigned_plans=assigned,upcoming_plans=[row for row in preparing if row.state!='Ready for Vehicle'],
        ready_plans=[row for row in preparing if row.state=='Ready for Vehicle'],stock=[],tags=[])
    result['can_view_stock'] = _can_read_stock(vehicle,operator,assigned+preparing)
    if result['can_view_stock']:
        result.update(_stock(vehicle))
    from cfg_kanban.services.route_sheets import vehicle_sheets
    result['route_sheets']=vehicle_sheets(vehicle.name,operator)
    return result


@frappe.whitelist()
def get_vehicle_overview(warehouse,operator_session_token):
    operator,_session = require_operator(operator_session_token)
    return vehicle_context(warehouse,operator)


def floor_context(profile):
    """Read-only Logistics and Delivery branch of the existing Kanban Floor."""
    if not profile.company:
        frappe.throw('Logistics and Delivery display requires a Company')
    frappe.get_doc('Company',profile.company).check_permission('read')
    filters = dict(company=profile.company,disabled=0,is_group=0,cfg_is_vehicle_warehouse=1)
    source = None
    if profile.warehouse:
        warehouse = frappe.get_doc('Warehouse',profile.warehouse)
        warehouse.check_permission('read')
        if warehouse.company!=profile.company:
            frappe.throw('Dashboard Warehouse must belong to its Company')
        if warehouse.get('cfg_is_vehicle_warehouse'):
            filters['name'] = warehouse.name
        else:
            source = warehouse.name
    vehicles = frappe.get_list('Warehouse',filters=filters,
        fields=['name','company','cfg_vehicle_reference'],order_by='cfg_vehicle_reference asc, name asc',limit_page_length=0)
    readable_sources = {row.name for row in frappe.get_list('Warehouse',
        filters={'company':profile.company,'disabled':0,'is_group':0},fields=['name'],limit_page_length=0)}
    preparing = [row for row in _rows(profile.company,states=PREPARING,source=source)
                 if row.source_warehouse in readable_sources]
    assigned = [row for row in _rows(profile.company,states=ASSIGNED,source=source)
                if row.vehicle_warehouse in {vehicle.name for vehicle in vehicles}]
    assigned = [row for row in assigned if row.source_warehouse in readable_sources]
    if profile.warehouse and filters.get('name'):
        preparing=[row for row in preparing if row.destination_assignment_policy!='Fixed' or row.destination_warehouse==profile.warehouse]
    if profile.customer:
        preparing = [row for row in preparing if row.customer==profile.customer or
                     any(stop.customer==profile.customer for stop in row.stops)]
        assigned = [row for row in assigned if row.customer==profile.customer or
                    any(stop.customer==profile.customer for stop in row.stops)]
    return dict(mode='logistics',profile=dict(name=profile.name,profile_name=profile.profile_name,
        view_type=profile.view_type,access_mode='Read Only',refresh_interval_seconds=profile.refresh_interval_seconds,
        column_count=profile.column_count,show_statistics=profile.show_statistics,description=profile.description,queue_depth=profile.queue_depth),
        company=profile.company,vehicles=[dict(name=row.name,vehicle_reference=row.cfg_vehicle_reference,
            plans=[plan for plan in assigned if plan.vehicle_warehouse==row.name]) for row in vehicles],
        preparing=preparing,stock_note='Loaded quantities are dispatch history; scan a lorry card for current ERP stock.',
        refreshed_on=now_datetime())

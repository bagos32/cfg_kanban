"""Read intermediate hopper WIP independently of native ERP stock or WO completion."""
import frappe
from frappe.utils import flt


def _rows(filters=None):
    if not frappe.db.table_exists('CFG Kanban Operation Hopper Fill'):
        return []
    filters=frappe._dict(filters or {})
    conditions=["fill.status in ('Filling','Ready','Empty')"]
    values={}
    columns={'company':'fill.company','warehouse':'hu.current_warehouse',
             'item_code':"coalesce(nullif(ow.production_item,''),master.item_code)",
             'stock_uom':'fill.stock_uom','quality_state':'hu.quality_state',
             'operation_hopper':'hu.name'}
    for name,column in columns.items():
        if filters.get(name):
            conditions.append(column+'=%('+name+')s');values[name]=filters[name]
    if not filters.get('include_zero_balance'):
        conditions.append("(fill.status='Filling' or fill.qty-fill.used_qty-coalesce(fill.cleared_qty,0)>0.000001)")
    else:
        conditions.append("(fill.status in ('Filling','Ready') or hu.operation_hopper_fill=fill.name)")
    return frappe.db.sql('''
        select fill.name as hopper_fill,hu.name as operation_hopper,hu.handling_unit_id,
               coalesce(nullif(fill.current_work_order,''),fill.work_order) as work_order,
               fill.work_order as original_work_order,fill.carry_in,ow.status as work_order_status,
               fill.company,hu.current_warehouse as warehouse,
               coalesce(nullif(ow.production_item,''),master.item_code) as item_code,item.item_name,
               fill.source_operation,fill.destination_operation,fill.source_execution,
               fill.source_material_run,fill.source_progress,fill.stock_uom,fill.status,
               fill.qty as loaded_qty,fill.used_qty,coalesce(fill.cleared_qty,0) as cleared_qty,
               greatest(fill.qty-fill.used_qty-coalesce(fill.cleared_qty,0),0) as operation_wip_qty,
               fill.reserved_qty as operation_wip_reserved_qty,
               case when hu.quality_state='Released' and hu.identity_state='Active'
                         and coalesce(hu.movement_state,'') not in ('Internal Transit','Intercompany Transit','Delivered','Quarantined')
                    then greatest(fill.qty-fill.used_qty-coalesce(fill.cleared_qty,0)-fill.reserved_qty,0)
                    else 0 end as operation_wip_available_qty,
               hu.quality_state,hu.identity_state,hu.movement_state
        from `tabCFG Kanban Operation Hopper Fill` fill
        inner join `tabCFG Kanban Handling Unit` hu
          on hu.name=coalesce(nullif(fill.current_handling_unit,''),fill.handling_unit)
        left join `tabWork Order` ow on ow.name=coalesce(nullif(fill.current_work_order,''),fill.work_order)
        left join `tabCFG Kanban Process Execution` execution on execution.name=fill.source_execution
        left join `tabCFG Kanban Master` master on master.name=execution.kanban_master
        left join `tabItem` item on item.name=coalesce(nullif(ow.production_item,''),master.item_code)
        where '''+' and '.join(conditions)+''' order by fill.company,hu.current_warehouse,hu.handling_unit_id
    ''',values,as_dict=True)


def hopper_snapshot(unit):
    if unit.tag_kind!='Reusable Container':return None
    rows=_rows({'operation_hopper':unit.name,'include_zero_balance':1})
    active=[row for row in rows if row.status in ('Filling','Ready')]
    if len(active)>1:
        frappe.throw('Multiple operation fills claim this Hopper; supervisor reconciliation is required')
    return active[0] if active else None


def report_rows(filters):
    if (filters.get('inventory_control_mode')=='ERP Stock'
            or filters.get('certificate_posting_status') not in (None,'','Operation WIP')
            or filters.get('process_certificate_set')):
        return []
    rows=_rows(filters)
    for row in rows:
        row.update(inventory_control_mode='Operation WIP',certificate_posting_status='Operation WIP',
            handling_unit=row.operation_hopper,container_visible_code=row.handling_unit_id,
            container_tag_label=row.handling_unit_id,physical_scan_code=row.handling_unit_id,
            physical_container=row.operation_hopper,tag_kind='Reusable Container',
            tag_count=0,pending_tag_count=0,operation_wip_hopper_count=1,
            total_qty=0,current_qty=0,reserved_qty=0,available_qty=0,
            material_run_reserved_qty=0,material_run_pending_consumed_qty=0,
            operational_qty=0,operational_available_qty=0,restricted_qty=0,
            released_available_qty=0,pending_certificate_qty=0,
            erp_actual_qty=None,all_active_tagged_qty=None,untagged_erp_qty=None,tagged_excess_qty=None)
    return rows


def report_summary(data):
    rows=[row for row in data if row.get('certificate_posting_status')=='Operation WIP']
    if not rows:return []
    result=[{'label':'Operation WIP Hoppers','value':len(rows),'datatype':'Int'}]
    uoms={row.stock_uom for row in rows}
    if len(uoms)==1:
        for field,label in [('operation_wip_qty','Operation WIP'),('operation_wip_reserved_qty','WIP Reserved'),('operation_wip_available_qty','WIP Available')]:
            result.append({'label':label+' ('+next(iter(uoms))+')','value':sum(flt(row.get(field)) for row in rows),'datatype':'Float'})
    return result

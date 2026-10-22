import frappe
from frappe import _
from frappe.utils import cint, flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    conditions, values = _conditions(filters)
    if filters.display_mode == "Tag Detail":
        data = _tag_detail_data(filters, conditions, values)
        return _tag_detail_columns(), data, None, None, _tag_detail_summary(data)

    columns = _columns()

    having = ""
    if not cint(filters.include_zero_balance):
        having = "having abs(sum(hu.current_qty)) > 0.000001 or abs(sum(hu.reserved_qty)) > 0.000001"

    data = frappe.db.sql(
        f"""
        select
            hu.inventory_company as company,
            hu.current_warehouse as warehouse,
            hu.item_code,
            max(item.item_name) as item_name,
            hu.stock_uom,
            case when coalesce(item.is_stock_item, 0) = 1
                 then 'ERP Stock' else 'Kanban Operational Inventory' end
                 as inventory_control_mode,
            count(hu.name) as tag_count,
            sum(hu.current_qty) as total_qty,
            sum(hu.reserved_qty) as reserved_qty,
            sum(hu.available_qty) as available_qty,
            sum(case when hu.quality_state = 'Released' then hu.available_qty else 0 end)
                as released_available_qty,
            sum(case when hu.quality_state in ('Hold', 'Quarantined', 'Rejected')
                     then hu.current_qty else 0 end) as restricted_qty,
            max(hu.last_reconciled_on) as last_reconciled_on
        from `tabCFG Kanban Handling Unit` hu
        left join `tabItem` item on item.name = hu.item_code
        where {' and '.join(conditions)}
        group by hu.inventory_company, hu.current_warehouse, hu.item_code,
                 hu.stock_uom, coalesce(item.is_stock_item, 0)
        {having}
        order by hu.inventory_company, hu.current_warehouse, hu.item_code, hu.stock_uom
        """,
        values,
        as_dict=True,
    )
    for row in data:
        if row.inventory_control_mode != "ERP Stock" or not row.warehouse:
            row["erp_actual_qty"] = None
            row["all_active_tagged_qty"] = row.total_qty
            row["untagged_erp_qty"] = None
            row["tagged_excess_qty"] = None
            continue
        erp_qty = flt(frappe.db.get_value(
            "Bin", {"item_code": row.item_code, "warehouse": row.warehouse}, "actual_qty"
        ))
        tagged_qty = flt(frappe.db.sql(
            """
            select coalesce(sum(current_qty), 0)
            from `tabCFG Kanban Handling Unit`
            where inventory_company=%s and current_warehouse=%s and item_code=%s
              and tag_kind!='Reusable Container' and identity_state='Active'
            """,
            (row.company, row.warehouse, row.item_code),
        )[0][0])
        row["erp_actual_qty"] = erp_qty
        row["all_active_tagged_qty"] = tagged_qty
        row["untagged_erp_qty"] = max(erp_qty - tagged_qty, 0)
        row["tagged_excess_qty"] = max(tagged_qty - erp_qty, 0)
    return columns, data, None, None, _summary(data)


def _conditions(filters):
    conditions = [
        "hu.tag_kind != 'Reusable Container'",
        "hu.identity_state = 'Active'",
        "coalesce(hu.item_code, '') != ''",
        "coalesce(hu.inventory_company, '') != ''",
        "coalesce(hu.stock_uom, '') != ''",
    ]
    values = {}

    for filter_name, column in (
        ("company", "hu.inventory_company"),
        ("warehouse", "hu.current_warehouse"),
        ("item_code", "hu.item_code"),
        ("stock_uom", "hu.stock_uom"),
        ("quality_state", "hu.quality_state"),
    ):
        if filters.get(filter_name):
            conditions.append(f"{column} = %({filter_name})s")
            values[filter_name] = filters.get(filter_name)

    if filters.inventory_control_mode == "Kanban Operational Inventory":
        conditions.append("coalesce(item.is_stock_item, 0) = 0")
    elif filters.inventory_control_mode == "ERP Stock":
        conditions.append("coalesce(item.is_stock_item, 0) = 1")
    return conditions, values


def _tag_detail_data(filters, conditions, values):
    if not cint(filters.include_zero_balance):
        conditions.append(
            "(abs(hu.current_qty) > 0.000001 or abs(hu.reserved_qty) > 0.000001)"
        )
    return frappe.db.sql(
        f"""
        select
            hu.name as handling_unit,
            hu.handling_unit_id,
            case
                when coalesce(hu.virtual_content, 0) = 1 and hu.physical_container is not null
                    then coalesce(
                        nullif(pc.container_reference, ''),
                        nullif(pc.short_description, ''),
                        pc.handling_unit_id
                    )
                else coalesce(nullif(hu.container_reference, ''), hu.handling_unit_id)
            end as container_tag_label,
            hu.physical_container,
            case
                when coalesce(hu.virtual_content, 0) = 1 and hu.physical_container is not null
                    then pc.handling_unit_id
                else hu.handling_unit_id
            end as physical_scan_code,
            hu.tag_kind,
            hu.inventory_company as company,
            hu.current_warehouse as warehouse,
            hu.item_code,
            item.item_name,
            hu.stock_uom,
            case when coalesce(item.is_stock_item, 0) = 1
                 then 'ERP Stock' else 'Kanban Operational Inventory' end
                 as inventory_control_mode,
            hu.batch_no,
            hu.quality_state,
            hu.movement_state,
            hu.current_qty,
            hu.reserved_qty,
            hu.available_qty,
            hu.physical_custodian,
            hu.source_location,
            hu.destination_location,
            hu.last_reconciled_on,
            hu.last_scan_time
        from `tabCFG Kanban Handling Unit` hu
        left join `tabItem` item on item.name = hu.item_code
        left join `tabCFG Kanban Handling Unit` pc on pc.name = hu.physical_container
        where {' and '.join(conditions)}
        order by hu.inventory_company, hu.current_warehouse, hu.item_code,
                 hu.stock_uom, hu.handling_unit_id
        """,
        values,
        as_dict=True,
    )


def _columns():
    return [
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 170},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 190},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": _("Item Name"), "fieldname": "item_name", "width": 220},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 85},
        {"label": _("Inventory Control"), "fieldname": "inventory_control_mode", "width": 190},
        {"label": _("Active Tags"), "fieldname": "tag_count", "fieldtype": "Int", "width": 95},
        {"label": _("ERP Actual Qty"), "fieldname": "erp_actual_qty", "fieldtype": "Float", "width": 120},
        {"label": _("All Active Tagged"), "fieldname": "all_active_tagged_qty", "fieldtype": "Float", "width": 130},
        {"label": _("Untagged ERP Qty"), "fieldname": "untagged_erp_qty", "fieldtype": "Float", "width": 130},
        {"label": _("Tagged Excess"), "fieldname": "tagged_excess_qty", "fieldtype": "Float", "width": 110},
        {"label": _("Total Quantity"), "fieldname": "total_qty", "fieldtype": "Float", "width": 125},
        {"label": _("Reserved Quantity"), "fieldname": "reserved_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Available Quantity"), "fieldname": "available_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Released Available"), "fieldname": "released_available_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Hold / Restricted"), "fieldname": "restricted_qty", "fieldtype": "Float", "width": 125},
        {"label": _("Last Reconciled"), "fieldname": "last_reconciled_on", "fieldtype": "Datetime", "width": 155},
    ]


def _tag_detail_columns():
    return [
        {"label": _("Container / Tag Label"), "fieldname": "container_tag_label", "width": 180},
        {"label": _("Physical Scan Code"), "fieldname": "physical_scan_code", "width": 155},
        {"label": _("Physical Container"), "fieldname": "physical_container", "fieldtype": "Link", "options": "CFG Kanban Handling Unit", "width": 145},
        {"label": _("Handling Unit"), "fieldname": "handling_unit", "fieldtype": "Link", "options": "CFG Kanban Handling Unit", "width": 145},
        {"label": _("Audit Identity Code"), "fieldname": "handling_unit_id", "width": 155},
        {"label": _("Tag Kind"), "fieldname": "tag_kind", "width": 125},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 170},
        {"label": _("Warehouse / Place"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 190},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 145},
        {"label": _("Item Name"), "fieldname": "item_name", "width": 190},
        {"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 125},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 80},
        {"label": _("Current Qty"), "fieldname": "current_qty", "fieldtype": "Float", "width": 105},
        {"label": _("Reserved Qty"), "fieldname": "reserved_qty", "fieldtype": "Float", "width": 105},
        {"label": _("Available Qty"), "fieldname": "available_qty", "fieldtype": "Float", "width": 105},
        {"label": _("Quality"), "fieldname": "quality_state", "width": 100},
        {"label": _("Movement State"), "fieldname": "movement_state", "width": 125},
        {"label": _("Custodian / Vehicle"), "fieldname": "physical_custodian", "width": 150},
        {"label": _("Immediate Source"), "fieldname": "source_location", "width": 145},
        {"label": _("Immediate Destination"), "fieldname": "destination_location", "width": 155},
        {"label": _("Last Reconciled"), "fieldname": "last_reconciled_on", "fieldtype": "Datetime", "width": 155},
        {"label": _("Last Scanned"), "fieldname": "last_scan_time", "fieldtype": "Datetime", "width": 155},
    ]


def _summary(data):
    tag_count = sum(int(row.tag_count or 0) for row in data)
    summary = [{"value": tag_count, "label": _("Tags Included"), "datatype": "Int"}]
    uoms = {row.stock_uom for row in data if row.stock_uom}
    if len(uoms) == 1:
        uom = next(iter(uoms))
        for fieldname, label, indicator in (
            ("total_qty", _("Combined Total"), "Blue"),
            ("reserved_qty", _("Combined Reserved"), "Orange"),
            ("available_qty", _("Combined Available"), "Green"),
        ):
            summary.append({
                "value": sum(flt(row.get(fieldname)) for row in data),
                "label": f"{label} ({uom})",
                "datatype": "Float",
                "indicator": indicator,
            })
    return summary


def _tag_detail_summary(data):
    summary = [{"value": len(data), "label": _("Active Tags Listed"), "datatype": "Int"}]
    uoms = {row.stock_uom for row in data if row.stock_uom}
    if len(uoms) == 1:
        uom = next(iter(uoms))
        for fieldname, label, indicator in (
            ("current_qty", _("Listed Total"), "Blue"),
            ("reserved_qty", _("Listed Reserved"), "Orange"),
            ("available_qty", _("Listed Available"), "Green"),
        ):
            summary.append({
                "value": sum(flt(row.get(fieldname)) for row in data),
                "label": f"{label} ({uom})",
                "datatype": "Float",
                "indicator": indicator,
            })
    return summary

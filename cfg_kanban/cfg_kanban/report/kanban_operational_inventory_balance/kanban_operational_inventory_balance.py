import frappe
from frappe import _
from frappe.utils import cint, flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = _columns()
    conditions = [
        "hu.tag_kind != 'Reusable Container'",
        "hu.identity_state not in ('Void', 'Replaced')",
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
    return columns, data, None, None, _summary(data)


def _columns():
    return [
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 170},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 190},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": _("Item Name"), "fieldname": "item_name", "width": 220},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 85},
        {"label": _("Inventory Control"), "fieldname": "inventory_control_mode", "width": 190},
        {"label": _("Active Tags"), "fieldname": "tag_count", "fieldtype": "Int", "width": 95},
        {"label": _("Total Quantity"), "fieldname": "total_qty", "fieldtype": "Float", "width": 125},
        {"label": _("Reserved Quantity"), "fieldname": "reserved_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Available Quantity"), "fieldname": "available_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Released Available"), "fieldname": "released_available_qty", "fieldtype": "Float", "width": 135},
        {"label": _("Hold / Restricted"), "fieldname": "restricted_qty", "fieldtype": "Float", "width": 125},
        {"label": _("Last Reconciled"), "fieldname": "last_reconciled_on", "fieldtype": "Datetime", "width": 155},
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

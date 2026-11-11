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

    data = [] if filters.certificate_posting_status == "Pending ERP Consolidation" else frappe.db.sql(
        f"""
        select
            hu.inventory_company as company,
            hu.current_warehouse as warehouse,
            hu.item_code,
            max(item.item_name) as item_name,
            hu.stock_uom,
            hu.process_certificate_set,
            max(pcs.set_name) as certificate_set_name,
            max(pcs.member_codes) as certificate_codes,
            'ERP Posted' as certificate_posting_status,
            0 as pending_certificate_qty,
            0 as pending_tag_count,
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
        left join `tabCFG Process Certificate Set` pcs
          on pcs.name = hu.process_certificate_set
        where {' and '.join(conditions)}
        group by hu.inventory_company, hu.current_warehouse, hu.item_code,
                 hu.stock_uom, hu.process_certificate_set,
                 coalesce(item.is_stock_item, 0)
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
    data.extend(_pending_summary_rows(filters))
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
        ("process_certificate_set", "hu.process_certificate_set"),
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
    data = [] if filters.certificate_posting_status == "Pending ERP Consolidation" else frappe.db.sql(
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
            hu.process_certificate_set,
            pcs.set_name as certificate_set_name,
            pcs.member_codes as certificate_codes,
            'ERP Posted' as certificate_posting_status,
            0 as pending_certificate_qty,
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
        left join `tabCFG Process Certificate Set` pcs
          on pcs.name = hu.process_certificate_set
        where {' and '.join(conditions)}
        order by hu.inventory_company, hu.current_warehouse, hu.item_code,
                 hu.stock_uom, hu.handling_unit_id
        """,
        values,
        as_dict=True,
    )
    pending = _pending_tag_rows(filters)
    existing = {row.handling_unit: row for row in data if row.handling_unit}
    for row in pending:
        if row.handling_unit and row.handling_unit in existing:
            base = existing[row.handling_unit]
            base.pending_certificate_qty = flt(base.pending_certificate_qty) + flt(
                row.pending_certificate_qty
            )
            base.pending_result_certificate_set = row.pending_result_certificate_set
            base.pending_certificate_set_name = row.pending_certificate_set_name
            base.pending_certificate_codes = row.pending_certificate_codes
            base.certificate_posting_status = "ERP Posted + Pending ERP Consolidation"
        else:
            data.append(row)
    if filters.certificate_posting_status:
        wanted = filters.certificate_posting_status
        data = [row for row in data if wanted in (row.certificate_posting_status or "")]
    return data


def _pending_summary_rows(filters):
    if not frappe.db.table_exists("CFG Certificate Process Progress"):
        return []
    conditions, values = _pending_conditions(filters)
    return frappe.db.sql(
        f"""
        select
            p.company,
            run.output_warehouse as warehouse,
            p.item_code,
            max(item.item_name) as item_name,
            p.stock_uom,
            p.result_certificate_set as process_certificate_set,
            max(pcs.set_name) as certificate_set_name,
            max(pcs.member_codes) as certificate_codes,
            case when coalesce(item.is_stock_item, 0) = 1
                 then 'ERP Stock' else 'Kanban Operational Inventory' end
                 as inventory_control_mode,
            'Pending ERP Consolidation' as certificate_posting_status,
            0 as tag_count,
            count(distinct p.output_tag_code) as pending_tag_count,
            0 as total_qty,
            0 as reserved_qty,
            0 as available_qty,
            0 as released_available_qty,
            0 as restricted_qty,
            sum(p.good_qty) as pending_certificate_qty,
            null as erp_actual_qty,
            null as all_active_tagged_qty,
            null as untagged_erp_qty,
            null as tagged_excess_qty,
            max(p.recorded_on) as last_reconciled_on
        from `tabCFG Certificate Process Progress` p
        inner join `tabCFG Process Certificate Run` run
          on run.name = p.certificate_process_run
        left join `tabItem` item on item.name = p.item_code
        left join `tabCFG Process Certificate Set` pcs
          on pcs.name = p.result_certificate_set
        where {' and '.join(conditions)}
        group by p.company, run.output_warehouse, p.item_code, p.stock_uom,
                 p.result_certificate_set, coalesce(item.is_stock_item, 0)
        order by p.company, run.output_warehouse, p.item_code, p.stock_uom
        """,
        values,
        as_dict=True,
    )


def _pending_tag_rows(filters):
    if not frappe.db.table_exists("CFG Certificate Process Progress"):
        return []
    conditions, values = _pending_conditions(filters)
    return frappe.db.sql(
        f"""
        select
            p.output_handling_unit as handling_unit,
            p.output_tag_code as handling_unit_id,
            p.output_tag_code as container_tag_label,
            null as physical_container,
            p.output_tag_code as physical_scan_code,
            case when p.output_handling_unit is null then 'Pending Stock Tag'
                 else 'Existing Stock Tag' end as tag_kind,
            p.company,
            run.output_warehouse as warehouse,
            p.item_code,
            max(item.item_name) as item_name,
            p.stock_uom,
            case when coalesce(item.is_stock_item, 0) = 1
                 then 'ERP Stock' else 'Kanban Operational Inventory' end
                 as inventory_control_mode,
            p.output_batch as batch_no,
            null as process_certificate_set,
            null as certificate_set_name,
            null as certificate_codes,
            p.result_certificate_set as pending_result_certificate_set,
            max(pcs.set_name) as pending_certificate_set_name,
            max(pcs.member_codes) as pending_certificate_codes,
            'Pending ERP Consolidation' as certificate_posting_status,
            sum(p.good_qty) as pending_certificate_qty,
            0 as current_qty,
            0 as reserved_qty,
            0 as available_qty,
            'Pending ERP' as quality_state,
            'Pending ERP Consolidation' as movement_state,
            null as physical_custodian,
            p.source_handling_unit as source_location,
            p.output_tag_code as destination_location,
            max(p.recorded_on) as last_reconciled_on,
            max(p.recorded_on) as last_scan_time
        from `tabCFG Certificate Process Progress` p
        inner join `tabCFG Process Certificate Run` run
          on run.name = p.certificate_process_run
        left join `tabItem` item on item.name = p.item_code
        left join `tabCFG Process Certificate Set` pcs
          on pcs.name = p.result_certificate_set
        where {' and '.join(conditions)}
        group by p.output_handling_unit, p.output_tag_code, p.company,
                 run.output_warehouse, p.item_code, p.stock_uom, p.output_batch,
                 p.result_certificate_set, p.source_handling_unit,
                 coalesce(item.is_stock_item, 0)
        order by max(p.recorded_on) desc
        """,
        values,
        as_dict=True,
    )


def _pending_conditions(filters):
    conditions = ["p.status = 'Recorded'"]
    values = {}
    for filter_name, column in (
        ("company", "p.company"),
        ("warehouse", "run.output_warehouse"),
        ("item_code", "p.item_code"),
        ("stock_uom", "p.stock_uom"),
        ("process_certificate_set", "p.result_certificate_set"),
    ):
        if filters.get(filter_name):
            conditions.append(f"{column} = %({filter_name})s")
            values[filter_name] = filters.get(filter_name)
    if filters.inventory_control_mode == "Kanban Operational Inventory":
        conditions.append("coalesce(item.is_stock_item, 0) = 0")
    elif filters.inventory_control_mode == "ERP Stock":
        conditions.append("coalesce(item.is_stock_item, 0) = 1")
    if filters.certificate_posting_status == "ERP Posted":
        conditions.append("1 = 0")
    if filters.quality_state:
        conditions.append("1 = 0")
    return conditions, values


def _columns():
    return [
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 170},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 190},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": _("Item Name"), "fieldname": "item_name", "width": 220},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 85},
        {"label": _("Inventory Control"), "fieldname": "inventory_control_mode", "width": 190},
        {"label": _("Process Certificate Set"), "fieldname": "process_certificate_set", "fieldtype": "Link", "options": "CFG Process Certificate Set", "width": 175},
        {"label": _("Certificate Set Name"), "fieldname": "certificate_set_name", "width": 180},
        {"label": _("Certificate Codes"), "fieldname": "certificate_codes", "width": 200},
        {"label": _("Certificate Posting"), "fieldname": "certificate_posting_status", "width": 175},
        {"label": _("Active Tags"), "fieldname": "tag_count", "fieldtype": "Int", "width": 95},
        {"label": _("Pending Output Tags"), "fieldname": "pending_tag_count", "fieldtype": "Int", "width": 135},
        {"label": _("Pending Certificate Qty"), "fieldname": "pending_certificate_qty", "fieldtype": "Float", "width": 155},
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
        {"label": _("Posted Certificate Set"), "fieldname": "process_certificate_set", "fieldtype": "Link", "options": "CFG Process Certificate Set", "width": 175},
        {"label": _("Posted Certificate Name"), "fieldname": "certificate_set_name", "width": 175},
        {"label": _("Posted Certificate Codes"), "fieldname": "certificate_codes", "width": 190},
        {"label": _("Pending Certificate Set"), "fieldname": "pending_result_certificate_set", "fieldtype": "Link", "options": "CFG Process Certificate Set", "width": 180},
        {"label": _("Pending Certificate Name"), "fieldname": "pending_certificate_set_name", "width": 180},
        {"label": _("Pending Certificate Codes"), "fieldname": "pending_certificate_codes", "width": 195},
        {"label": _("Certificate Posting"), "fieldname": "certificate_posting_status", "width": 185},
        {"label": _("Pending Certificate Qty"), "fieldname": "pending_certificate_qty", "fieldtype": "Float", "width": 155},
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
    pending_tag_count = sum(int(row.pending_tag_count or 0) for row in data)
    summary = [
        {"value": tag_count, "label": _("ERP-Posted Tags Included"), "datatype": "Int"},
        {"value": pending_tag_count, "label": _("Pending Certificate Output Tags"), "datatype": "Int", "indicator": "Orange"},
    ]
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
        summary.append({
            "value": sum(flt(row.get("pending_certificate_qty")) for row in data),
            "label": f"{_('Pending Certificate Qty')} ({uom})",
            "datatype": "Float",
            "indicator": "Orange",
        })
    return summary


def _tag_detail_summary(data):
    posted_count = sum(1 for row in data if flt(row.current_qty) or row.handling_unit)
    pending_count = sum(1 for row in data if flt(row.pending_certificate_qty))
    summary = [
        {"value": posted_count, "label": _("Posted Tags Listed"), "datatype": "Int"},
        {"value": pending_count, "label": _("Pending Certificate Tags"), "datatype": "Int", "indicator": "Orange"},
    ]
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
        summary.append({
            "value": sum(flt(row.get("pending_certificate_qty")) for row in data),
            "label": f"{_('Pending Certificate Qty')} ({uom})",
            "datatype": "Float",
            "indicator": "Orange",
        })
    return summary

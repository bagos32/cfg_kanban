import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, time_diff_in_hours


ACTIVE_LOAD_STATUSES = (
    "Transfer Draft", "Ready", "In Use", "Consumption Pending ERP",
    "Consumption Draft", "Return Draft",
)
EXPECTED_BIN_STATES = {
    "Transfer Draft": "Reserved",
    "Ready": "Ready",
    "In Use": "In Use",
    "Consumption Pending ERP": "In Use",
    "Consumption Draft": "In Use",
    "Return Draft": "In Use",
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    rows = _physical_bins(filters)
    _attach_runtime(rows)
    rows = _apply_runtime_filters(rows, filters)
    return _columns(), rows, None, _chart(rows), _summary(rows)


def _physical_bins(filters):
    conditions = [
        "hu.tag_kind='Reusable Container'",
        "hu.reusable_container_role in ('Standard Quantity WIP Bin', "
        "'Loose Multi-Item WIP Bin')",
    ]
    values = {}
    for fieldname, expression in (
        ("company", "hu.inventory_company"),
        ("wip_bin_pool", "pool.name"),
        ("operation", "pool.operation"),
        ("workstation", "entry.workstation"),
        ("wip_warehouse", "hu.current_warehouse"),
        ("wip_bin_state", "hu.wip_bin_state"),
    ):
        if filters.get(fieldname):
            conditions.append(f"{expression}=%({fieldname})s")
            values[fieldname] = filters.get(fieldname)
    if not cint(filters.include_unavailable):
        conditions.extend([
            "coalesce(pool.active, 1)=1",
            "coalesce(entry.active, 1)=1",
            "hu.identity_state not in ('Void', 'Replaced')",
            "hu.quality_state='Released'",
        ])
    return frappe.db.sql(
        f"""
        select
            hu.name as reusable_bin,
            hu.handling_unit_id as visible_bin_code,
            hu.reusable_container_role,
            hu.wip_bin_state,
            hu.inventory_company as company,
            hu.current_warehouse as wip_warehouse,
            hu.identity_state,
            hu.quality_state,
            hu.modified as bin_modified,
            pool.name as wip_bin_pool,
            pool.active as pool_active,
            pool.pool_mode,
            pool.loose_consumption_policy,
            pool.operation,
            entry.workstation,
            entry.priority as fill_priority,
            entry.active as assignment_active
        from `tabCFG Kanban Handling Unit` hu
        left join `tabCFG Kanban WIP Bin Pool Entry` entry
          on entry.reusable_bin=hu.name
         and entry.parenttype='CFG Kanban WIP Bin Pool'
        left join `tabCFG Kanban WIP Bin Pool` pool on pool.name=entry.parent
        where {' and '.join(conditions)}
        order by coalesce(pool.operation, ''), coalesce(entry.priority, 9999),
                 hu.handling_unit_id
        """,
        values,
        as_dict=True,
    )


def _attach_runtime(rows):
    bin_names = [row.reusable_bin for row in rows]
    if not bin_names:
        return
    loads = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"reusable_bin": ["in", bin_names], "status": ["in", list(ACTIVE_LOAD_STATUSES)]},
        ["name", "reusable_bin", "status", "item_code", "batch_no", "actual_qty",
         "consumed_qty", "return_qty", "return_stock_entry",
         "stock_uom", "wip_bin_pool", "company", "operation", "workstation",
         "wip_warehouse", "source_handling_unit", "kanban_cycle", "work_order", "job_card",
         "transfer_stock_entry", "consumption_stock_entry", "reserved_on", "ready_on",
         "in_use_on", "modified"],
        order_by="creation desc", limit_page_length=0,
    )
    loads_by_bin = {}
    active_by_bin = {}
    active_count_by_bin = {}
    for load in loads:
        loads_by_bin.setdefault(load.reusable_bin, []).append(load)
        active_count_by_bin[load.reusable_bin] = active_count_by_bin.get(load.reusable_bin, 0) + 1
        active_by_bin.setdefault(load.reusable_bin, load)
    reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        {"reusable_bin": ["in", bin_names], "status": "Open"},
        ["name", "reusable_bin", "wip_bin_load", "reversal_context",
         "cancelled_stock_entry", "raised_on"],
        order_by="raised_on desc", limit_page_length=0,
    )
    reconciliation_by_bin = {}
    for reconciliation in reconciliations:
        reconciliation_by_bin.setdefault(reconciliation.reusable_bin, reconciliation)
    reversed_names = [
        row.wip_bin_load for row in reconciliation_by_bin.values()
        if row.wip_bin_load and row.reusable_bin not in active_by_bin
    ]
    if reversed_names:
        for load in frappe.get_all(
                "CFG Kanban WIP Bin Load", {"name": ["in", reversed_names]},
                ["name", "reusable_bin", "status", "item_code", "batch_no", "actual_qty",
                 "consumed_qty", "return_qty", "return_stock_entry",
                 "stock_uom", "wip_bin_pool", "company", "operation", "workstation",
                 "wip_warehouse", "source_handling_unit", "kanban_cycle", "work_order", "job_card",
                 "transfer_stock_entry", "consumption_stock_entry", "modified"],
                limit_page_length=0):
            active_by_bin.setdefault(load.reusable_bin, load)
    loose_usages = frappe.get_all(
        "CFG Kanban Loose WIP Usage",
        {"reusable_bin": ["in", bin_names],
         "status": ["in", ["Recorded", "Consumption Draft", "Posted"]]},
        ["reusable_bin", "item_code", "batch_no", "qty", "stock_uom", "status"],
        limit_page_length=0,
    )
    usages_by_bin = {}
    for usage in loose_usages:
        usages_by_bin.setdefault(usage.reusable_bin, []).append(usage)
    current = now_datetime()
    for row in rows:
        load = active_by_bin.get(row.reusable_bin)
        bin_loads = loads_by_bin.get(row.reusable_bin, [])
        reconciliation = reconciliation_by_bin.get(row.reusable_bin)
        row["active_load_count"] = active_count_by_bin.get(row.reusable_bin, 0)
        row["active_load_statuses"] = sorted({value.status for value in bin_loads})
        row["active_loaded_qty"] = sum(flt(value.actual_qty) for value in bin_loads)
        row["reported_usage_qty"] = sum(
            flt(value.qty) for value in usages_by_bin.get(row.reusable_bin, [])
        )
        identities = sorted({
            f"{value.item_code}{' / ' + value.batch_no if value.batch_no else ''}"
            for value in bin_loads
        })
        row["loaded_items"] = ", ".join(identities)
        row["loaded_item_codes"] = sorted({value.item_code for value in bin_loads})
        if row.reusable_container_role == "Loose Multi-Item WIP Bin":
            row["runtime_expected_bin_state"] = _loose_expected_state(bin_loads)
        if load:
            for fieldname in (
                "name", "status", "item_code", "batch_no", "actual_qty", "consumed_qty",
                "return_qty", "stock_uom",
                "source_handling_unit", "kanban_cycle", "work_order", "job_card",
                "transfer_stock_entry", "consumption_stock_entry", "return_stock_entry",
            ):
                target = "wip_bin_load" if fieldname == "name" else (
                    "load_status" if fieldname == "status" else fieldname
                )
                row[target] = load.get(fieldname)
            for fieldname in ("wip_bin_pool", "company", "operation", "workstation",
                              "wip_warehouse"):
                row[f"active_{fieldname}"] = load.get(fieldname)
        if reconciliation:
            row["reconciliation"] = reconciliation.name
            row["reversal_context"] = reconciliation.reversal_context
            row["cancelled_stock_entry"] = reconciliation.cancelled_stock_entry
        timestamp = _state_timestamp(row, load, reconciliation)
        row["state_since"] = timestamp
        row["age_hours"] = round(flt(time_diff_in_hours(current, timestamp)), 1) if timestamp else None
        row["attention"], row["attention_level"] = _attention(row, load, reconciliation)


def _state_timestamp(row, load, reconciliation):
    if reconciliation:
        return reconciliation.raised_on
    if not load:
        return row.bin_modified
    if load.status == "Transfer Draft":
        return load.get("reserved_on") or load.modified
    if load.status == "Ready":
        return load.get("ready_on") or load.modified
    if load.status in ("In Use", "Consumption Pending ERP", "Consumption Draft", "Return Draft"):
        return load.get("in_use_on") or load.modified
    return load.modified


def _attention(row, load, reconciliation):
    if reconciliation:
        return _("Critical: Supervisor reconciliation required"), "Critical"
    if row.wip_bin_state == "Exception":
        return _("Critical: Exception without open reconciliation"), "Critical"
    if row.identity_state in ("Void", "Replaced") or row.quality_state != "Released":
        return _("Unavailable identity or quality state"), "Warning"
    if load:
        if (row.reusable_container_role == "Standard Quantity WIP Bin"
                and row.active_load_count > 1):
            return _("Critical: More than one active load uses this physical bin"), "Critical"
        expected = row.get("runtime_expected_bin_state") or EXPECTED_BIN_STATES.get(load.status)
        if expected and row.wip_bin_state != expected:
            return _("Critical: Bin state and load status do not agree"), "Critical"
        if any((
            row.get("active_wip_bin_pool") != row.get("wip_bin_pool"),
            row.get("active_company") != row.get("company"),
            row.get("active_operation") != row.get("operation"),
            row.get("active_workstation") != row.get("workstation"),
            row.get("active_wip_warehouse") != row.get("wip_warehouse"),
        )):
            return _("Critical: Active load no longer matches the bin assignment"), "Critical"
    if row.reusable_container_role == "Loose Multi-Item WIP Bin":
        statuses = set(row.get("active_load_statuses") or [])
        if "Transfer Draft" in statuses:
            return _("Action: Submit or cancel loose WIP transfer Draft"), "Warning"
        if statuses.intersection({"Consumption Draft", "Return Draft"}):
            return _("Action: Submit consolidated consumption or unused return Draft"), "Warning"
    if not row.wip_bin_pool or not row.workstation:
        return _("Configuration: Bin is not assigned to a Pool / Workstation"), "Warning"
    if not cint(row.pool_active) or not cint(row.assignment_active):
        return _("Configuration disabled"), "Warning"
    if load:
        if load.status == "Transfer Draft":
            return _("Action: Submit or cancel transfer Draft"), "Warning"
        if (row.reusable_container_role == "Loose Multi-Item WIP Bin"
                and load.status in ("Ready", "In Use")):
            return _("Active: Accumulating controlled use for final Work Order posting"), "Normal"
        if load.status == "Ready":
            return _("Action: Awaiting Job Card consumption"), "Warning"
        if load.status == "Consumption Pending ERP":
            return _("Action: Physical use recorded; awaiting ERP posting"), "Warning"
        if load.status in ("In Use", "Consumption Draft"):
            return _("Action: Submit or cancel consumption Draft"), "Warning"
        if load.status == "Return Draft":
            return _("Action: Submit unused-material return Draft"), "Warning"
        if load.status == "Reversed":
            return _("Critical: Reversed load requires reconciliation"), "Critical"
    if row.wip_bin_state != "Empty":
        return _("Critical: Non-empty state has no active load"), "Critical"
    return _("Available"), "Normal"


def _apply_runtime_filters(rows, filters):
    if filters.item_code:
        rows = [row for row in rows if filters.item_code in row.get("loaded_item_codes", [])]
    if filters.reusable_container_role:
        rows = [row for row in rows
                if row.get("reusable_container_role") == filters.reusable_container_role]
    if filters.load_status:
        rows = [row for row in rows if row.get("load_status") == filters.load_status]
    if cint(filters.attention_only):
        rows = [row for row in rows if row.get("attention_level") != "Normal"]
    return rows


def _columns():
    return [
        {"label": _("Bin Code"), "fieldname": "visible_bin_code", "width": 145},
        {"label": _("Handling Unit"), "fieldname": "reusable_bin", "fieldtype": "Link",
         "options": "CFG Kanban Handling Unit", "width": 140},
        {"label": _("Bin Role"), "fieldname": "reusable_container_role", "width": 170},
        {"label": _("Pool Mode"), "fieldname": "pool_mode", "width": 125},
        {"label": _("Bin State"), "fieldname": "wip_bin_state", "width": 100},
        {"label": _("Attention / Next Action"), "fieldname": "attention", "width": 260},
        {"label": _("Age Hours"), "fieldname": "age_hours", "fieldtype": "Float", "width": 90},
        {"label": _("Pool"), "fieldname": "wip_bin_pool", "fieldtype": "Link",
         "options": "CFG Kanban WIP Bin Pool", "width": 170},
        {"label": _("Operation"), "fieldname": "operation", "fieldtype": "Link",
         "options": "Operation", "width": 130},
        {"label": _("Workstation"), "fieldname": "workstation", "fieldtype": "Link",
         "options": "Workstation", "width": 130},
        {"label": _("Priority"), "fieldname": "fill_priority", "fieldtype": "Int", "width": 70},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link",
         "options": "Company", "width": 170},
        {"label": _("WIP Warehouse"), "fieldname": "wip_warehouse", "fieldtype": "Link",
         "options": "Warehouse", "width": 180},
        {"label": _("Load"), "fieldname": "wip_bin_load", "fieldtype": "Link",
         "options": "CFG Kanban WIP Bin Load", "width": 145},
        {"label": _("Active Loads"), "fieldname": "active_load_count", "fieldtype": "Int",
         "width": 85},
        {"label": _("Loaded Items"), "fieldname": "loaded_items", "width": 210},
        {"label": _("Active Loaded Qty"), "fieldname": "active_loaded_qty",
         "fieldtype": "Float", "width": 105},
        {"label": _("Reported Loose Use"), "fieldname": "reported_usage_qty",
         "fieldtype": "Float", "width": 115},
        {"label": _("Load Status"), "fieldname": "load_status", "width": 120},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link",
         "options": "Item", "width": 130},
        {"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link",
         "options": "Batch", "width": 110},
        {"label": _("Qty"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 75},
        {"label": _("Consumed"), "fieldname": "consumed_qty", "fieldtype": "Float", "width": 80},
        {"label": _("To Return"), "fieldname": "return_qty", "fieldtype": "Float", "width": 80},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link",
         "options": "UOM", "width": 75},
        {"label": _("Job Card"), "fieldname": "job_card", "fieldtype": "Link",
         "options": "Job Card", "width": 135},
        {"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link",
         "options": "Work Order", "width": 140},
        {"label": _("Cycle"), "fieldname": "kanban_cycle", "fieldtype": "Link",
         "options": "CFG Kanban Cycle", "width": 130},
        {"label": _("Reconciliation"), "fieldname": "reconciliation", "fieldtype": "Link",
         "options": "CFG Kanban WIP Bin Reconciliation", "width": 150},
        {"label": _("State Since"), "fieldname": "state_since", "fieldtype": "Datetime",
         "width": 155},
    ]


def _summary(rows):
    counts = {state: 0 for state in (
        "Empty", "Reserved", "Filling", "Ready", "Accumulating", "In Use",
        "Awaiting Consumption", "Exception",
    )}
    attention = 0
    for row in rows:
        counts[row.wip_bin_state] = counts.get(row.wip_bin_state, 0) + 1
        if row.attention_level != "Normal":
            attention += 1
    return [
        {"value": len(rows), "label": _("Physical WIP Bins"), "datatype": "Int",
         "indicator": "Blue"},
        {"value": counts.get("Empty", 0), "label": _("Available Empty"), "datatype": "Int",
         "indicator": "Green"},
        {"value": counts.get("Ready", 0), "label": _("Ready for Consumption"),
         "datatype": "Int", "indicator": "Orange"},
        {"value": counts.get("Accumulating", 0), "label": _("Loose WIP Accumulating"),
         "datatype": "Int", "indicator": "Blue"},
        {"value": attention, "label": _("Attention Required"), "datatype": "Int",
         "indicator": "Red" if attention else "Green"},
    ]


def _chart(rows):
    states = ("Empty", "Reserved", "Filling", "Ready", "Accumulating", "In Use",
              "Awaiting Consumption", "Exception")
    counts = [sum(1 for row in rows if row.wip_bin_state == state) for state in states]
    return {
        "data": {"labels": list(states), "datasets": [{"name": _("Bins"), "values": counts}]},
        "type": "donut",
        "height": 260,
        "colors": ["#28a745", "#6c757d", "#8b5cf6", "#f0ad4e", "#2490ef",
                   "#0ea5e9", "#f97316", "#dc3545"],
    }


def _loose_expected_state(loads):
    if not loads:
        return "Empty"
    statuses = {row.status for row in loads}
    if "Transfer Draft" in statuses:
        return "Filling"
    if statuses.intersection({"Consumption Draft", "Return Draft"}):
        return "Awaiting Consumption"
    return "Accumulating"

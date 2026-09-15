import frappe
from frappe.utils import flt

from cfg_kanban.services.dispatch import overlay_dispatch


ACTIVE_EXECUTION_STATUSES = ("Not Ready", "Ready", "In Progress", "Paused", "Waiting Input", "Blocked")
PRIORITY_ORDER = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
STATUS_ORDER = {"In Progress": 0, "Paused": 1, "Ready": 2, "Waiting Input": 3,
                "Not Ready": 4, "Blocked": 5, "Completed": 6}


def _require_dashboard_role():
    frappe.only_for(("Manufacturing User", "Manufacturing Manager", "System Manager"))


@frappe.whitelist()
def get_profiles():
    _require_dashboard_role()
    return frappe.get_list(
        "CFG Kanban Dashboard Profile",
        filters={"active": 1},
        fields=["name", "profile_name", "view_type", "access_mode", "description"],
        order_by="profile_name asc",
        limit_page_length=500,
    )


@frappe.whitelist()
def get_dashboard(profile_name):
    _require_dashboard_role()
    profile = frappe.get_doc("CFG Kanban Dashboard Profile", profile_name)
    profile.check_permission("read")
    selected = sorted(
        (row for row in profile.workstations if row.enabled),
        key=lambda row: (row.display_order, row.idx),
    )
    workstation_names = [row.workstation for row in selected]
    if profile.view_type in ("Station Display", "Plant Queue", "Supervisor Sequence Control"):
        if not workstation_names:
            frappe.throw("This Dashboard Profile has no enabled workstation")

    executions = overlay_dispatch(_execution_rows(profile, workstation_names))
    can_control_dispatch = profile.access_mode == "Supervisor" and bool(
        set(frappe.get_roles()).intersection({"Manufacturing Manager", "System Manager"})
    )
    by_workstation = {name: [] for name in workstation_names}
    for row in executions:
        by_workstation.setdefault(row.workstation or "Unassigned", []).append(row)

    depth = int(profile.queue_depth or 5)
    stations = []
    for selected_row in selected:
        rows = by_workstation.get(selected_row.workstation, [])
        current = [row for row in rows if row.status == "In Progress"]
        paused = [row for row in rows if row.status == "Paused"]
        all_queue = [row for row in rows if row.status not in ("In Progress", "Paused")]
        queue = all_queue if can_control_dispatch else all_queue[:depth]
        stations.append({
            "workstation": selected_row.workstation,
            "display_order": selected_row.display_order,
            "current": current,
            "paused": paused,
            "queue": queue,
            "total_queued": len(all_queue),
            "state": "Running" if current else "Paused" if paused else "Idle",
        })

    return {
        "profile": {
            "name": profile.name, "profile_name": profile.profile_name,
            "view_type": profile.view_type, "access_mode": profile.access_mode,
            "refresh_interval_seconds": profile.refresh_interval_seconds,
            "column_count": profile.column_count, "show_statistics": profile.show_statistics,
            "show_completed": profile.show_completed, "show_alerts": profile.show_alerts,
            "description": profile.description,
            "can_control_dispatch": can_control_dispatch,
        },
        "statistics": _statistics(executions),
        "stations": stations,
        "sequence_source": "Persistent dispatch queue; supervisor overrides are audited and do not change the BOM route",
    }


def _execution_rows(profile, workstation_names):
    statuses = list(ACTIVE_EXECUTION_STATUSES)
    if profile.show_completed:
        statuses.append("Completed")
    filters = {"status": ["in", statuses]}
    if workstation_names:
        filters["workstation"] = ["in", workstation_names]
    rows = frappe.get_all(
        "CFG Kanban Process Execution",
        filters=filters,
        fields=["name", "kanban_cycle", "kanban_master", "operation", "sequence", "lane_sequence", "job_card",
                "workstation", "status", "target_qty", "allocated_qty", "input_available_qty",
                "processed_qty", "good_qty", "reject_qty", "released_qty", "blocked",
                "creation", "modified"],
        limit_page_length=1000,
    )
    cycle_names = list({row.kanban_cycle for row in rows if row.kanban_cycle})
    cycles = {row.name: row for row in frappe.get_all(
        "CFG Kanban Cycle", filters={"name": ["in", cycle_names or ["__none__"]]},
        fields=["name", "item_code", "planned_qty", "priority", "status", "work_order",
                "kanban_card", "sales_order", "production_policy", "source_warehouse",
                "destination_warehouse"], limit_page_length=1000,
    )}
    master_names = list({row.kanban_master for row in rows if row.kanban_master})
    masters = {row.name: row for row in frappe.get_all(
        "CFG Kanban Master", filters={"name": ["in", master_names or ["__none__"]]},
        fields=["name", "company"], limit_page_length=1000,
    )}
    job_names = list({row.job_card for row in rows if row.job_card})
    jobs = {row.name: row for row in frappe.get_all(
        "Job Card", filters={"name": ["in", job_names or ["__none__"]]},
        fields=["name", "status", "docstatus", "for_quantity", "total_completed_qty"],
        limit_page_length=1000,
    )}
    item_codes = list({cycle.item_code for cycle in cycles.values() if cycle.item_code})
    items = {row.name: row for row in frappe.get_all(
        "Item", filters={"name": ["in", item_codes or ["__none__"]]},
        fields=["name", "item_name", "item_group"], limit_page_length=1000,
    )}
    sales_order_names = list({cycle.get("sales_order") for cycle in cycles.values()
                              if cycle.get("sales_order")})
    sales_orders = {row.name: row for row in frappe.get_all(
        "Sales Order", filters={"name": ["in", sales_order_names or ["__none__"]]},
        fields=["name", "customer", "cfg_production_line"], limit_page_length=1000,
    )}
    result = []
    for row in rows:
        cycle = cycles.get(row.kanban_cycle) or frappe._dict()
        item = items.get(cycle.item_code) or frappe._dict()
        job = jobs.get(row.job_card) or frappe._dict()
        master = masters.get(row.kanban_master) or frappe._dict()
        sales_order = sales_orders.get(cycle.get("sales_order")) or frappe._dict()
        if profile.company and master.company != profile.company:
            continue
        if profile.item_group and item.item_group != profile.item_group:
            continue
        if profile.customer and sales_order.customer != profile.customer:
            continue
        if profile.production_line and sales_order.get("cfg_production_line") != profile.production_line:
            continue
        if profile.warehouse and profile.warehouse not in (
                cycle.source_warehouse, cycle.destination_warehouse):
            continue
        row.update({
            "item_code": cycle.item_code, "item_name": item.item_name,
            "item_group": item.item_group, "priority": cycle.priority or "Normal",
            "company": master.company, "customer": sales_order.customer,
            "cycle_status": cycle.status, "work_order": cycle.work_order,
            "kanban_card": cycle.kanban_card, "sales_order": cycle.get("sales_order"),
            "production_policy": cycle.get("production_policy"),
            "job_card_status": job.status, "job_card_docstatus": job.docstatus,
            "job_card_target_qty": flt(job.for_quantity),
            "job_card_completed_qty": flt(job.total_completed_qty),
            "progress_percent": min(100, (flt(row.good_qty) / flt(row.target_qty) * 100)
                                    if flt(row.target_qty) else 0),
            "readiness": _readiness(row),
        })
        result.append(row)
    return sorted(result, key=lambda row: (
        STATUS_ORDER.get(row.status, 99), PRIORITY_ORDER.get(row.priority, 99), row.creation
    ))


def _readiness(row):
    if row.blocked or row.status == "Blocked":
        return "Blocked"
    if row.status == "Waiting Input" or (
            row.status == "Not Ready" and flt(row.input_available_qty) <= 0):
        return "Waiting Input"
    if row.status == "Ready":
        return "Ready"
    return row.status


def _statistics(rows):
    return {
        "running": sum(row.status == "In Progress" for row in rows),
        "ready": sum(row.status == "Ready" for row in rows),
        "waiting": sum(row.status in ("Not Ready", "Waiting Input") for row in rows),
        "paused": sum(row.status == "Paused" for row in rows),
        "blocked": sum(row.status == "Blocked" or row.blocked for row in rows),
        "urgent": sum(row.get("effective_priority", row.priority) == "Urgent" for row in rows),
        "target_qty": sum(flt(row.target_qty) for row in rows),
        "good_qty": sum(flt(row.good_qty) for row in rows),
        "reject_qty": sum(flt(row.reject_qty) for row in rows),
    }

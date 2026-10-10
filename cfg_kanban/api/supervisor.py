import frappe
from frappe import _
from frappe.utils import cint


SUPERVISOR_ROLES = {
    "Manufacturing Manager", "Purchase Manager", "Stock Manager", "System Manager"
}
SIGNAL_APPROVAL_ROLES = {
    "Manufacturing Manager", "Purchase Manager", "Stock Manager", "System Manager"
}
ACTIONABLE_SIGNAL_STATUSES = ("Waiting Approval", "Validated", "Failed", "Blocked")


def _require_supervisor():
    roles = set(frappe.get_roles())
    if not roles.intersection(SUPERVISOR_ROLES):
        frappe.throw(_("A Kanban supervisor or manager role is required"), frappe.PermissionError)
    return roles


@frappe.whitelist()
def get_action_centre(limit=100):
    """Return read-only supervisor queues; mutations remain in their domain APIs."""
    roles = _require_supervisor()
    limit = min(max(cint(limit) or 100, 1), 500)
    signals = _signal_actions(limit) if frappe.has_permission("CFG Kanban Signal", "read") else []
    service_tasks = _service_verifications(limit)
    process_tasks = _process_verifications(limit)
    exceptions = _open_exceptions(limit)
    return {
        "permissions": {
            "can_approve_signals": bool(roles.intersection(SIGNAL_APPROVAL_ROLES)),
            "can_cancel_signals": bool(roles.intersection(SIGNAL_APPROVAL_ROLES)),
        },
        "counts": {
            "signals": len(signals),
            "service_verifications": len(service_tasks),
            "process_verifications": len(process_tasks),
            "exceptions": len(exceptions),
        },
        "signals": signals,
        "service_verifications": service_tasks,
        "process_verifications": process_tasks,
        "exceptions": exceptions,
    }


def _signal_actions(limit):
    rows = frappe.get_list(
        "CFG Kanban Signal",
        filters={"status": ["in", ACTIONABLE_SIGNAL_STATUSES]},
        fields=[
            "name", "signal_type", "kanban_master", "kanban_card", "kanban_cycle",
            "item_code", "requested_qty", "stock_uom", "status", "priority",
            "automation_level", "requested_on", "validated_on", "command",
            "erp_reference_doctype", "erp_reference_name", "error_message",
            "trigger_source", "balance_source", "observed_balance_qty",
            "reorder_point_qty", "target_stock_qty",
        ],
        order_by="requested_on asc",
        limit_page_length=limit,
    )
    if not rows:
        return []
    master_names = list({row.kanban_master for row in rows if row.kanban_master})
    masters = {row.name: row for row in frappe.get_list(
        "CFG Kanban Master", filters={"name": ["in", master_names or ["__none__"]]},
        fields=[
            "name", "kanban_name", "company", "control_type", "bom", "default_supplier",
            "source_warehouse", "destination_warehouse", "purchase_uom",
            "purchase_uom_conversion_factor", "purchase_replenishment_qty",
            "purchase_execution_mode",
        ], limit_page_length=limit,
    )}
    # A Signal has no direct Company field, therefore filter it through the
    # permission-aware Master query before exposing it on a multi-company desk.
    rows = [row for row in rows if row.kanban_master in masters]
    cycle_names = list({row.kanban_cycle for row in rows if row.kanban_cycle})
    item_codes = list({row.item_code for row in rows if row.item_code})
    cycles = {row.name: row for row in frappe.get_list(
        "CFG Kanban Cycle", filters={"name": ["in", cycle_names or ["__none__"]]},
        fields=["name", "status", "blocked", "work_order", "material_request", "purchase_order"],
        limit_page_length=limit,
    )}
    items = {row.name: row for row in frappe.get_list(
        "Item", filters={"name": ["in", item_codes or ["__none__"]]},
        fields=["name", "item_name", "item_group"], limit_page_length=limit,
    )}
    priority_order = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
    rows.sort(key=lambda row: (priority_order.get(row.priority, 9), row.requested_on or ""))
    output = []
    for row in rows:
        master = masters.get(row.kanban_master) or frappe._dict()
        cycle = cycles.get(row.kanban_cycle) or frappe._dict()
        item = items.get(row.item_code) or frappe._dict()
        output.append({
            **row,
            "item_name": item.get("item_name"),
            "item_group": item.get("item_group"),
            "master_name": master.get("kanban_name") or row.kanban_master,
            "company": master.get("company"),
            "control_type": master.get("control_type"),
            "bom": master.get("bom"),
            "supplier": master.get("default_supplier"),
            "source_warehouse": master.get("source_warehouse"),
            "destination_warehouse": master.get("destination_warehouse"),
            "purchase_uom": master.get("purchase_uom"),
            "purchase_uom_conversion_factor": master.get("purchase_uom_conversion_factor"),
            "purchase_replenishment_qty": master.get("purchase_replenishment_qty"),
            "purchase_execution_mode": master.get("purchase_execution_mode") or "Material Request Only",
            "cycle_status": cycle.get("status"),
            "cycle_blocked": cycle.get("blocked"),
            "work_order": cycle.get("work_order"),
            "material_request": cycle.get("material_request"),
            "purchase_order": cycle.get("purchase_order"),
            "approval_action": (
                (master.get("purchase_execution_mode") or "Material Request Only")
                if row.signal_type == "Purchase Replenishment"
                else "Release Internal Transfer"
                if row.signal_type == "Transfer Replenishment"
                else "Release Stock Withdrawal"
                if row.signal_type == "Stock Withdrawal"
                else "Create Work Order"
            ),
        })
    return output


def _service_verifications(limit):
    if not frappe.has_permission("CFG Kanban Task", "read"):
        return []
    rows = frappe.get_list(
        "CFG Kanban Task",
        filters={"status": "Awaiting Verification"},
        fields=[
            "name", "task_name", "task_category", "company", "priority", "due_on",
            "assigned_employee", "completed_by", "completed_on", "workstation", "asset",
            "location", "verification_status", "last_progress_summary",
        ],
        order_by="due_on asc",
        limit_page_length=limit,
    )
    priority_order = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
    rows.sort(key=lambda row: (priority_order.get(row.priority, 9), row.due_on or ""))
    return rows


def _process_verifications(limit):
    if not frappe.has_permission("CFG Kanban Process Task", "read"):
        return []
    rows = frappe.get_list(
        "CFG Kanban Process Task",
        filters={"status": "Awaiting Verification"},
        fields=[
            "name", "task_name", "task_category", "kanban_cycle", "kanban_master",
            "linked_operation", "workstation", "item_code", "batch_no", "work_order",
            "completed_by", "completed_on", "qc_controlled", "qc_result", "sample_id",
        ],
        order_by="completed_on asc",
        limit_page_length=limit,
    )
    master_names = list({row.kanban_master for row in rows if row.kanban_master})
    visible_masters = {row.name for row in frappe.get_list(
        "CFG Kanban Master",
        filters={"name": ["in", master_names or ["__none__"]]},
        fields=["name"], limit_page_length=limit,
    )}
    return [row for row in rows if row.kanban_master in visible_masters]


def _open_exceptions(limit):
    if not frappe.has_permission("CFG Kanban Exception", "read"):
        return []
    rows = frappe.get_list(
        "CFG Kanban Exception",
        filters={"status": ["in", ["Open", "Acknowledged"]]},
        fields=[
            "name", "exception_type", "severity", "status", "kanban_cycle", "kanban_card",
            "process_execution", "process_task", "standalone_task", "movement_manifest",
            "delivery_session", "handling_unit", "message", "reference_doctype",
            "reference_name", "raised_on",
        ],
        order_by="raised_on asc",
        limit_page_length=limit,
    )
    severity_order = {"Critical": 0, "Error": 1, "Warning": 2, "Info": 3}
    rows.sort(key=lambda row: (severity_order.get(row.severity, 9), row.raised_on or ""))
    return rows

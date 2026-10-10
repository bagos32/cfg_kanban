import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.demand_math import calculate_threshold_replenishment
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.process_tasks import ensure_tasks, evaluate_gate
from cfg_kanban.services.purchase_replenishment import (
    continue_purchase_execution,
    create_material_request_command,
)
from cfg_kanban.services.triggers import create_work_order_command


SUPPORTED_CONTROL_TYPES = ("Production", "Purchase Replenishment", "Transfer")
OPEN_SIGNAL_STATES = (
    "Open", "Validating", "Validated", "Waiting Approval", "Executing", "Blocked", "Failed"
)
MANAGER_ROLES = ("Manufacturing Manager", "Purchase Manager", "Stock Manager", "System Manager")


def evaluate_inventory_thresholds():
    """Hourly scheduler entry point. One failing Master must not stop the others."""
    if not frappe.db.exists("DocType", "CFG Kanban Master"):
        return []
    names = frappe.get_all(
        "CFG Kanban Master",
        filters={"active": 1, "enable_inventory_threshold_trigger": 1},
        pluck="name",
        order_by="name asc",
        limit_page_length=0,
    )
    results = []
    for index, name in enumerate(names):
        savepoint = f"cfg_threshold_{index}"
        frappe.db.savepoint(savepoint)
        try:
            results.append(evaluate_master(name))
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            frappe.log_error(
                title=f"CFG Kanban threshold evaluation failed: {name}",
                message=frappe.get_traceback(),
            )
            _update_snapshot(name, None, "Evaluation failed; see Error Log")
            results.append({"master": name, "status": "Error"})
    return results


@frappe.whitelist()
def evaluate_master_now(master_name):
    frappe.only_for(MANAGER_ROLES)
    return evaluate_master(master_name)


def evaluate_master(master_name):
    # Serialize evaluations for one Master so concurrent workers cannot create two Signals.
    frappe.db.sql(
        "select name from `tabCFG Kanban Master` where name=%s for update",
        (master_name,),
    )
    master = frappe.get_doc("CFG Kanban Master", master_name)
    if not master.active or not cint(master.get("enable_inventory_threshold_trigger")):
        return _result(master, "Disabled")
    if master.control_type not in SUPPORTED_CONTROL_TYPES:
        return _result(master, "Unsupported control type")

    source, balance = get_observed_balance(master)
    reorder_point, target = get_threshold_configuration(master)
    count, requested_qty = calculate_threshold_replenishment(
        balance,
        reorder_point,
        target,
        master.replenishment_qty,
        master.get("inventory_max_cards_per_run") or 10,
    )
    if not count:
        return _result(master, "Above threshold", balance, source)

    existing = frappe.db.get_value(
        "CFG Kanban Signal",
        {"kanban_master": master.name, "status": ["in", OPEN_SIGNAL_STATES]},
        ["name", "kanban_cycle"],
        as_dict=True,
    )
    if existing:
        return _result(
            master,
            f"Existing replenishment {existing.name} remains open",
            balance,
            source,
            signal=existing.name,
            cycle=existing.kanban_cycle,
        )

    cycle = frappe.get_doc({
        "doctype": "CFG Kanban Cycle",
        "kanban_master": master.name,
        "item_code": master.item_code,
        "planned_qty": requested_qty,
        "nominal_card_qty": master.replenishment_qty,
        "effective_cycle_qty": requested_qty,
        "stock_uom": master.stock_uom,
        "status": "New",
        "priority": master.default_priority,
        "source_warehouse": master.source_warehouse,
        "destination_warehouse": master.destination_warehouse,
    }).insert(ignore_permissions=True)
    ensure_tasks(cycle.name)
    gate = evaluate_gate(cycle.name, "Before Cycle Start")
    automatic = master.automation_level == "Automatic" and gate["open"]
    sequence = frappe.db.count("CFG Kanban Signal", {"kanban_master": master.name}) + 1
    key = canonical_key("inventory-threshold", master.name, sequence)
    signal_type = {
        "Purchase Replenishment": "Purchase Replenishment",
        "Transfer": "Transfer Replenishment",
    }.get(master.control_type, "Production Replenishment")
    signal, created = insert_once(frappe.get_doc({
        "doctype": "CFG Kanban Signal",
        "signal_type": signal_type,
        "kanban_master": master.name,
        "kanban_cycle": cycle.name,
        "trigger_source": "Inventory Threshold",
        "balance_source": source,
        "observed_balance_qty": balance,
        "reorder_point_qty": reorder_point,
        "target_stock_qty": target,
        "item_code": master.item_code,
        "requested_qty": requested_qty,
        "stock_uom": master.stock_uom,
        "status": "Validated" if automatic else "Waiting Approval",
        "priority": master.default_priority,
        "automation_level": master.automation_level,
        "requested_on": now_datetime(),
        "validated_on": now_datetime() if automatic else None,
    }), key, ignore_permissions=True)
    if not created:
        cycle.delete(ignore_permissions=True)
        return _result(master, "Duplicate evaluation ignored", balance, source,
                       signal=signal.name, cycle=signal.kanban_cycle)
    cycle.db_set({"signal": signal.name, "status": "Signalled"})
    event = record(
        "Inventory Threshold Signal Created",
        cycle=cycle.name,
        qty=requested_qty,
        reference_doctype=signal.doctype,
        reference_name=signal.name,
        notes=(
            f"{source}: {balance} {master.stock_uom}; reorder below {reorder_point}; "
            f"target {target}; {count} replenishment quantities"
        ),
    )
    signal.db_set("source_event", event.name, update_modified=False)

    if automatic:
        _execute_automatic(signal, master)
    return _result(master, "Signal created", balance, source,
                   signal=signal.name, cycle=cycle.name,
                   requested_qty=requested_qty)


def get_observed_balance(master):
    is_stock_item = cint(frappe.db.get_value("Item", master.item_code, "is_stock_item"))
    if is_stock_item:
        balance = frappe.db.get_value(
            "Bin",
            {"item_code": master.item_code, "warehouse": master.destination_warehouse},
            "projected_qty",
        )
        return "ERPNext Projected Quantity", flt(balance)
    balance = frappe.db.sql(
        """
        select coalesce(sum(available_qty), 0)
        from `tabCFG Kanban Handling Unit`
        where item_code=%s and inventory_company=%s and current_warehouse=%s
          and tag_kind!='Reusable Container' and identity_state='Active'
          and quality_state='Released' and available_qty>0
        """,
        (master.item_code, master.company, master.destination_warehouse),
    )[0][0]
    return "Kanban Operational Inventory", flt(balance)


def get_threshold_configuration(master):
    source = master.get("inventory_threshold_source") or "Kanban Master Override"
    if source == "Kanban Master Override":
        return (
            flt(master.get("inventory_reorder_point_qty")),
            flt(master.get("inventory_target_qty")),
        )
    reorder = frappe.db.get_value(
        "Item Reorder",
        {"parent": master.item_code, "warehouse": master.destination_warehouse},
        ["warehouse_reorder_level", "warehouse_reorder_qty"],
        as_dict=True,
    )
    if not reorder or flt(reorder.warehouse_reorder_level) <= 0:
        frappe.throw(
            "ERPNext Warehouse Reorder Level is missing for the destination Warehouse"
        )
    reorder_point = flt(reorder.warehouse_reorder_level)
    reorder_qty = flt(reorder.warehouse_reorder_qty)
    target = reorder_point + (reorder_qty or flt(master.replenishment_qty))
    return reorder_point, target


def _execute_automatic(signal, master):
    try:
        if master.control_type == "Transfer":
            from cfg_kanban.services.internal_transfer import create_transfer_manifest
            create_transfer_manifest(signal.name)
            return
        command = (
            create_material_request_command(signal.name)
            if master.control_type == "Purchase Replenishment"
            else create_work_order_command(signal.name)
        )
        execute_command(command.name)
        if master.control_type == "Purchase Replenishment":
            continue_purchase_execution(signal.kanban_cycle)
    except Exception as exc:
        signal.db_set({"status": "Failed", "error_message": str(exc)})
        record(
            "Inventory Threshold Automation Failed",
            cycle=signal.kanban_cycle,
            reference_doctype=signal.doctype,
            reference_name=signal.name,
            notes=frappe.get_traceback(),
        )


def _result(master, status, balance=None, source=None, **extra):
    _update_snapshot(master.name, balance, status)
    return {
        "master": master.name,
        "status": status,
        "balance": balance,
        "balance_source": source or master.get("inventory_balance_source"),
        **extra,
    }


def _update_snapshot(master_name, balance, status):
    values = {
        "last_threshold_check_on": now_datetime(),
        "last_threshold_result": status,
    }
    if balance is not None:
        values["last_observed_balance_qty"] = flt(balance)
    frappe.db.set_value("CFG Kanban Master", master_name, values, update_modified=False)

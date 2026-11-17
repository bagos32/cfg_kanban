"""Same-Work-Order intermediate hopper WIP. No ERP stock or manufactured fill is created."""
import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

TOLERANCE = 0.000001
FILL = "Fill Hopper"
CONSUME = "Consume Hopper"


def hopper_mode(execution):
    return execution.get("material_run_hopper_mode") or "None"


def _order(execution):
    order_name = frappe.db.get_value("Job Card", execution.job_card, "work_order")
    if not order_name:
        frappe.throw("Operation hopper use requires the exact Job Card and Work Order")
    order = frappe.get_doc("Work Order", order_name)
    if order.docstatus != 1 or order.status in ("Completed", "Closed", "Stopped", "Cancelled"):
        frappe.throw("Operation hopper use requires an active submitted Work Order")
    company = frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "company")
    if order.company != company:
        frappe.throw("Operation hopper Work Order belongs to another Company")
    return order


def _unit(execution, scan, *, lock=False, by_name=False):
    from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
    from cfg_kanban.services.container_contents import (
        active_container_contents, assert_container_not_in_open_manifest,
    )
    identity = ({"identity_type": "Handling Unit", "name": scan}
                if by_name else resolve_logistics_scan(scan))
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan the physical Hopper identity")
    current = frappe.db.sql("select * from `tabCFG Kanban Handling Unit` where name=%s for update",
                            identity["name"], as_dict=True) if lock else None
    if lock and not current:
        frappe.throw("The Hopper was not found")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if current:
        unit.update(current[0])
    if (unit.tag_kind != "Reusable Container" or unit.handling_unit_type != "Hopper"
            or unit.reusable_container_role != "Production Output Container"):
        frappe.throw("Use a reusable Hopper with role Production Output Container for operation WIP")
    if unit.get("movement_state") in ("Internal Transit", "Intercompany Transit", "Delivered", "Quarantined"):
        frappe.throw("A Hopper in transit or under movement restriction cannot be used")
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw("The Hopper must be Active and quality Released")
    order = _order(execution)
    if unit.inventory_company != order.company or unit.current_warehouse != execution.get("material_run_hopper_warehouse"):
        frappe.throw("The Hopper is outside this operation's Company or configured Hopper Warehouse")
    if active_container_contents(unit.name):
        frappe.throw("This Hopper already contains ERP-manufactured stock; empty it before operation WIP use")
    assert_container_not_in_open_manifest(unit.name, "using it as an operation Hopper")
    return unit, order


def _active_fill(unit_name, *, lock=False):
    rows = frappe.db.sql("""
        select * from `tabCFG Kanban Operation Hopper Fill`
        where active_hopper_key=%s
    """ + (" for update" if lock else ""), unit_name, as_dict=True)
    return rows[0] if rows else None


def _check_fill(execution, fill, order):
    if not fill or fill.status != "Ready":
        frappe.throw("This Hopper has no released operation fill for Packing; report the Rinse Material Run into it first")
    if ((fill.get("current_work_order") or fill.work_order) != order.name or fill.destination_operation != execution.operation
            or fill.source_operation != execution.get("material_run_hopper_source_operation")):
        frappe.throw("The Hopper fill belongs to another Work Order or operation route")
    if fill.get("current_work_order"):
        from cfg_kanban.services.hopper_carry_in import validate_fill_owner
        validate_fill_owner(fill, order.name)
    source_master = frappe.db.get_value("CFG Kanban Process Execution", fill.source_execution, "kanban_master")
    if source_master != execution.kanban_master:
        frappe.throw("The Hopper fill belongs to another Kanban Master")
    uom = frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "stock_uom")
    if fill.stock_uom != uom:
        frappe.throw("The Hopper fill uses another production output UOM")
    return max(0, flt(fill.qty) - flt(fill.used_qty) - flt(fill.get("cleared_qty")) - flt(fill.reserved_qty))


def _allocation_context(execution):
    target, processed = flt(execution.target_qty), flt(execution.processed_qty)
    remaining = max(0, target - processed)
    reason = None
    if remaining <= TOLERANCE:
        reason = (
            "This Operation Card allocation is complete. Cancel this dialog, close the Operation Card cycle, "
            "then allocate its next cycle against the remaining Job Card demand."
            if execution.get("runtime_allocation") else
            "This operation has reached its target. Cancel this dialog and review the Job Card before continuing."
        )
    return {"allocation_target_qty": target, "allocation_processed_qty": processed,
            "allocation_remaining_qty": remaining, "allocation_block_reason": reason}


@frappe.whitelist()
def preview_scanner_hopper(execution_name, scan_value, operator_session_token=None):
    from cfg_kanban.services.operator_auth import require_operator
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "report_progress", execution=execution)
    mode = hopper_mode(execution)
    if mode not in (FILL, CONSUME):
        frappe.throw("This execution has no operation Hopper mode; configure and release a new Cycle")
    unit, order = _unit(execution, scan_value)
    fill = _active_fill(unit.name)
    if mode == FILL and fill:
        frappe.throw("The Hopper is filling or still contains operation WIP; select an empty Hopper")
    available = _check_fill(execution, fill, order) if mode == CONSUME else 0
    if mode == CONSUME and available <= TOLERANCE:
        frappe.throw("The Hopper has no unreserved operation WIP available")
    allocation = _allocation_context(execution) if mode == CONSUME else {}
    return {"handling_unit": unit.name, "visible_code": unit.handling_unit_id,
            "hopper_mode": mode, "loaded_qty": flt(fill.qty) - flt(fill.used_qty) - flt(fill.get("cleared_qty")) if fill else 0,
            "available_qty": available, "reserved_qty": flt(fill.reserved_qty) if fill else 0,
            "stock_uom": frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "stock_uom"),
            "work_order": order.name, "item_code": order.production_item,
            "source_operation": fill.source_operation if fill else None,
            "hopper_fill": fill.name if fill else None,
            "source_boundary": frappe.db.get_value("CFG Kanban Operation Material Run", fill.source_material_run, "output_serial_boundary") if fill else None,
            "run_qty": min(available, allocation["allocation_remaining_qty"]) if mode == CONSUME else 0,
            **allocation}


def prepare_run_hopper(execution, run, scan):
    mode = hopper_mode(execution)
    if mode == "None":
        if scan:
            frappe.throw("This execution has no operation Hopper mode")
        return
    if not scan:
        frappe.throw("Scan the physical Hopper before confirming this Material Run")
    unit, order = _unit(execution, scan, lock=True)
    fill = _active_fill(unit.name, lock=True)
    if mode == FILL:
        if fill:
            frappe.throw("The Hopper is filling or still contains operation WIP; select an empty Hopper")
        fill = frappe.get_doc({
            "doctype": "CFG Kanban Operation Hopper Fill", "status": "Filling",
            "handling_unit": unit.name, "active_hopper_key": unit.name,
            "work_order": order.name, "company": order.company,
            "warehouse": unit.current_warehouse, "stock_uom": frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "stock_uom"),
            "source_operation": execution.operation,
            "destination_operation": execution.destination_operation,
            "source_execution": execution.name, "source_material_run": run.name,
            "qty": 0, "used_qty": 0, "reserved_qty": 0, "opened_on": now_datetime(),
        }).insert(ignore_permissions=True)
        reserved = 0
    else:
        available = _check_fill(execution, fill, order)
        allocation = _allocation_context(execution)
        if allocation["allocation_block_reason"]:
            frappe.throw(allocation["allocation_block_reason"])
        reserved = min(available, allocation["allocation_remaining_qty"])
        if reserved <= TOLERANCE:
            frappe.throw("The Hopper has no available quantity for this operation allocation")
        frappe.db.set_value("CFG Kanban Operation Hopper Fill", fill.name,
                            "reserved_qty", flt(fill.reserved_qty) + reserved)
    run.db_set({"operation_hopper": unit.name, "operation_hopper_fill": fill.name,
                "hopper_reserved_qty": reserved, "hopper_used_qty": 0}, update_modified=False)
    _sync_unit(fill.name)
    record("Operation Hopper Prepared", cycle=execution.kanban_cycle, execution=execution.name,
           handling_unit=unit.name, work_order=order.name, qty=reserved,
           reference_doctype="CFG Kanban Operation Material Run", reference_name=run.name,
           payload={"mode": mode, "fill": fill.name},
           idempotency_key=canonical_key("prepare-operation-hopper", run.name))


def validate_run_hopper(execution, run, good_qty, processed_qty):
    mode = hopper_mode(execution)
    if mode == "None":
        return
    if not run or not run.get("operation_hopper_fill"):
        frappe.throw("Start a Material Run and scan its Hopper before physical work")
    unit, order = _unit(execution, run.operation_hopper, lock=True, by_name=True)
    fill = _active_fill(unit.name, lock=True)
    if not fill or fill.name != run.operation_hopper_fill:
        frappe.throw("The Hopper fill changed; cancel and rescan this Material Run")
    if mode == FILL:
        from cfg_kanban.services.crew_authorization import release_execution_wip_if_authorized
        if not release_execution_wip_if_authorized(execution.name):
            frappe.throw("Complete the crew authorization gate before releasing this Hopper output")
        if fill.status != "Filling" or fill.source_material_run != run.name:
            frappe.throw("This Material Run does not own the Hopper fill")
        multiple = flt(execution.transfer_multiple)
        if multiple <= 0 or abs(flt(good_qty) / multiple - round(flt(good_qty) / multiple)) > TOLERANCE:
            frappe.throw("Hopper good quantity must be a complete Transfer Multiple; configure the correct output-UOM multiple")
    else:
        _check_fill(execution, fill, order)
        if (flt(processed_qty) > flt(run.hopper_reserved_qty) + TOLERANCE
                or flt(processed_qty) > flt(fill.qty) - flt(fill.used_qty) - flt(fill.get("cleared_qty")) + TOLERANCE):
            frappe.throw("Progress exceeds this Material Run's reserved Hopper quantity; use the displayed loaded/available balance")


def apply_run_hopper(execution, run, progress):
    mode = hopper_mode(execution)
    if mode == "None":
        return
    fill = _active_fill(run.operation_hopper, lock=True)
    if not fill or fill.name != run.operation_hopper_fill:
        frappe.throw("The Hopper fill changed before progress was applied")
    if mode == FILL:
        qty = flt(progress.good_qty)
        values = {"qty": qty, "source_progress": progress.name,
                  "status": "Ready" if qty > TOLERANCE else "Empty",
                  "active_hopper_key": fill.handling_unit if qty > TOLERANCE else None}
        frappe.db.set_value("CFG Kanban Operation Hopper Fill", fill.name, values)
        fill.update(values)
        event_type = "Operation Hopper Loaded"
    else:
        qty = flt(progress.processed_qty)
        used = flt(fill.used_qty) + qty
        reserved = max(0, flt(fill.reserved_qty) - flt(run.hopper_reserved_qty))
        values = {"used_qty": used, "reserved_qty": reserved,
                  "status": "Empty" if used + flt(fill.get("cleared_qty")) + TOLERANCE >= flt(fill.qty) else "Ready",
                  "active_hopper_key": None if used + flt(fill.get("cleared_qty")) + TOLERANCE >= flt(fill.qty) else (fill.get("current_handling_unit") or fill.handling_unit)}
        frappe.db.set_value("CFG Kanban Operation Hopper Fill", fill.name, values)
        fill.update(values)
        frappe.get_doc({"doctype": "CFG Kanban Operation Hopper Use", "hopper_fill": fill.name,
            "material_run": run.name, "progress": progress.name, "process_execution": execution.name,
            "work_order": (fill.get("current_work_order") or fill.work_order), "qty": qty, "stock_uom": fill.stock_uom,
            "used_on": now_datetime()}).insert(ignore_permissions=True)
        run.db_set({"hopper_used_qty": qty, "hopper_reserved_qty": 0}, update_modified=False)
        # Consume the owning WO's digital handoff, not another ERP raw-material row.
        owner_cycle = frappe.db.get_value("Work Order", fill.get("current_work_order") or fill.work_order, "cfg_kanban_cycle")
        if owner_cycle:
            from cfg_kanban.services.wip import append_entry
            append_entry(owner_cycle, "Consumed", qty, source_execution=(fill.get("current_source_execution") or fill.source_execution),
                         destination_execution=execution.name, source_operation=fill.source_operation,
                         destination_operation=fill.destination_operation, source_progress=progress.name,
                         stock_uom=fill.stock_uom, notes=f"Operation Hopper fill {fill.name}")
        event_type = "Operation Hopper Consumed"
    _sync_unit(fill.name)
    record(event_type, cycle=execution.kanban_cycle, execution=execution.name,
           handling_unit=(fill.get("current_handling_unit") or fill.handling_unit), work_order=(fill.get("current_work_order") or fill.work_order), qty=qty,
           reference_doctype="CFG Kanban Operation Hopper Fill", reference_name=fill.name,
           payload={"material_run": run.name, "progress": progress.name,
                    "source_progress": fill.source_progress},
           idempotency_key=canonical_key("operation-hopper-progress", run.name, progress.name))


def cancel_run_hopper(run_name, reason):
    run = frappe.get_doc("CFG Kanban Operation Material Run", run_name)
    if not run.get("operation_hopper_fill") or flt(run.get("hopper_used_qty")) > TOLERANCE:
        return
    frappe.db.sql("select name from `tabCFG Kanban Handling Unit` where name=%s for update", run.operation_hopper)
    fill = _active_fill(run.operation_hopper, lock=True)
    if not fill or fill.name != run.operation_hopper_fill:
        return
    if fill.source_material_run == run.name and fill.status == "Filling":
        frappe.db.set_value("CFG Kanban Operation Hopper Fill", fill.name,
                            {"status": "Cancelled", "active_hopper_key": None})
    elif flt(run.hopper_reserved_qty) > TOLERANCE:
        frappe.db.set_value("CFG Kanban Operation Hopper Fill", fill.name,
                            "reserved_qty", max(0, flt(fill.reserved_qty) - flt(run.hopper_reserved_qty)))
    run.db_set("hopper_reserved_qty", 0, update_modified=False)
    _sync_unit(fill.name)
    record("Operation Hopper Reservation Released", execution=run.process_execution,
           cycle=run.kanban_cycle, handling_unit=run.operation_hopper, work_order=run.work_order,
           reference_doctype="CFG Kanban Operation Material Run", reference_name=run.name,
           notes=reason, idempotency_key=canonical_key("cancel-operation-hopper", run.name))


def _sync_unit(fill_name):
    fill = frappe.get_doc("CFG Kanban Operation Hopper Fill", fill_name)
    remaining = max(0, flt(fill.qty) - flt(fill.used_qty) - flt(fill.get("cleared_qty")))
    frappe.db.set_value("CFG Kanban Handling Unit", (fill.get("current_handling_unit") or fill.handling_unit), {
        "operation_hopper_fill": fill.name, "operation_wip_qty": remaining,
        "operation_wip_reserved_qty": flt(fill.reserved_qty),
        "operation_wip_available_qty": max(0, remaining - flt(fill.reserved_qty)),
        "operation_wip_uom": fill.stock_uom,
        "movement_state": ("Reserved" if fill.status == "Filling" else
                           "Loaded" if fill.status == "Ready" else "Empty"),
    }, update_modified=False)


def assert_no_open_hoppers(work_order):
    rows = frappe.get_all("CFG Kanban Operation Hopper Fill", filters={
        "status": ["in", ["Filling", "Ready"]]},
        or_filters={"work_order": work_order, "current_work_order": work_order},
        fields=["name", "work_order", "current_work_order"], limit_page_length=0)
    names = [row.name for row in rows if (row.get("current_work_order") or row.work_order) == work_order]
    if names:
        frappe.throw("Consume or reconcile the remaining operation Hopper WIP before final closure: " + ", ".join(names))


def validate_hopper_profiles(master):
    profiles = {row.operation: row for row in master.operation_profiles}
    for profile in profiles.values():
        mode = profile.get("material_run_hopper_mode") or "None"
        if mode == "None":
            continue
        if mode not in (FILL, CONSUME):
            frappe.throw("Unsupported Operation Hopper Mode")
        if (master.production_material_mode != "Skip WIP Transfer"
                or profile.material_run_control != "Required Before Progress"
                or profile.output_reporting_mode != "Incremental"):
            frappe.throw("Operation Hoppers require Skip WIP Transfer, Incremental output and Required Before Progress Material Runs")
        warehouse = profile.get("material_run_hopper_warehouse")
        if not warehouse or frappe.db.get_value("Warehouse", warehouse, "company") != master.company:
            frappe.throw("Select a Hopper Warehouse belonging to this Master Company")
        if mode == FILL:
            other = profiles.get(profile.destination_operation)
            if (profile.handoff_mode != "Digital Quantity Handoff" or not other
                    or other.get("material_run_hopper_mode") != CONSUME
                    or other.dependency_operation != profile.operation):
                frappe.throw("Fill Hopper requires Digital Quantity Handoff to a matching Consume Hopper operation")
        else:
            other = profiles.get(profile.dependency_operation)
            if (not other or other.get("material_run_hopper_mode") != FILL
                    or other.destination_operation != profile.operation
                    or profile.start_rule != "Minimum Qty Available"):
                frappe.throw("Consume Hopper requires Minimum Qty Available and the matching Fill Hopper dependency")
        if warehouse != other.get("material_run_hopper_warehouse"):
            frappe.throw("Paired Hopper operations must use the same Hopper Warehouse")


def assert_no_operation_fill(unit_name, action):
    if not frappe.db.table_exists("CFG Kanban Operation Hopper Fill"):
        return
    if frappe.db.exists("CFG Kanban Operation Hopper Fill", {"active_hopper_key": unit_name}):
        frappe.throw(f"This Hopper contains active operation WIP; finish its Work Order flow before {action}")


def lock_execution(execution_name, *, allow_closed=False):
    """Serialize progress, run preparation and closure on their exact execution and Cycle."""
    rows = frappe.db.sql("""
        select execution.*, cycle.status as locked_cycle_status
        from `tabCFG Kanban Process Execution` execution
        inner join `tabCFG Kanban Cycle` cycle on cycle.name=execution.kanban_cycle
        where execution.name=%s for update
    """, execution_name, as_dict=True)
    if not rows:
        frappe.throw("Process Execution was not found")
    row = rows[0]
    if not allow_closed and row.locked_cycle_status in ("Completed", "Cancelled"):
        frappe.throw("This Cycle is closed; scan the current active Card Cycle")
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    execution.update({key: value for key, value in row.items() if key != "locked_cycle_status"})
    return execution


def assert_hopper_prepared(execution):
    if hopper_mode(execution) == "None":
        return
    run_name = execution.get("open_material_run")
    run = frappe.get_doc("CFG Kanban Operation Material Run", run_name) if run_name else None
    if not run or run.status != "Open" or not run.get("operation_hopper_fill"):
        frappe.throw("Prepare Start Material Run and scan its Hopper before starting physical work")
    _unit(execution, run.operation_hopper, lock=True, by_name=True)

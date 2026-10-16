"""Controlled load episodes for fixed-quantity reusable WIP bins.

This service deliberately follows native ERPNext Stock Entry state. A Draft entry may reserve a
physical bin, but it never makes material Ready or Consumed. Those states are confirmed only from
the Stock Entry submit hook.
"""

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record


TOLERANCE = 0.000001
TRANSFER_PURPOSE = "Material Transfer for Manufacture"
CONSUMPTION_PURPOSES = ("Material Consumption for Manufacture", "Manufacture")
def create_transfer_load(*, stock_entry, stock_entry_detail, reusable_bin,
                         kanban_cycle, job_card, item_code, actual_qty,
                         source_handling_unit=None, batch_no=None,
                         process_execution=None, operator=None,
                         operator_session=None, idempotency_key=None):
    """Create one auditable Draft transfer/load episode for a scanned fixed bin.

    The scanner runtime calls this only after ERPNext has created and saved the Draft native
    Material Transfer for Manufacture. No stock or WIP quantity is confirmed here.
    """
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) != TRANSFER_PURPOSE:
        frappe.throw("A WIP Bin load requires a Draft Material Transfer for Manufacture")
    if entry.get("cfg_kanban_cycle") != kanban_cycle:
        frappe.throw("Material Transfer does not belong to the selected Kanban Cycle")
    row = _entry_row(entry, stock_entry_detail)
    if row.item_code != item_code or not row.s_warehouse or not row.t_warehouse:
        frappe.throw("Selected Stock Entry row is not the requested WIP material transfer")

    cycle = frappe.get_doc("CFG Kanban Cycle", kanban_cycle)
    job = frappe.db.get_value(
        "Job Card", {"name": job_card, "work_order": entry.work_order, "docstatus": ["<", 2]},
        ["name", "operation", "workstation"], as_dict=True,
    )
    if not job:
        frappe.throw("Select an active Job Card from the transfer Work Order")
    rule = _wip_rule(cycle.kanban_master, item_code, job.operation)
    pool = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool", rule.wip_bin_pool,
        ["company", "wip_warehouse"], as_dict=True,
    )
    if not pool or pool.company != entry.company or pool.wip_warehouse != row.t_warehouse:
        frappe.throw("WIP Bin Pool does not match the ERPNext transfer Company/WIP Warehouse")
    qty = flt(actual_qty)
    if qty <= 0 or qty > _row_stock_qty(row) + TOLERANCE:
        frappe.throw("WIP Bin load quantity must be positive and within the Stock Entry row")

    key = idempotency_key or (
        f"wip-bin-load:{entry.name}:{row.name}:{reusable_bin}:{qty}"
    )
    existing = frappe.db.get_value("CFG Kanban WIP Bin Load", {"idempotency_key": key}, "name")
    if existing:
        return frappe.get_doc("CFG Kanban WIP Bin Load", existing), False

    _lock_reusable_bin(reusable_bin)
    load = frappe.get_doc({
        "doctype": "CFG Kanban WIP Bin Load",
        "status": "Transfer Draft",
        "reusable_bin": reusable_bin,
        "wip_bin_pool": rule.wip_bin_pool,
        "company": entry.company,
        "item_code": item_code,
        "batch_no": batch_no or row.get("batch_no"),
        "standard_qty": rule.standard_bin_qty,
        "actual_qty": qty,
        "stock_uom": row.stock_uom,
        "kanban_master": cycle.kanban_master,
        "kanban_cycle": cycle.name,
        "work_order": entry.work_order,
        "job_card": job.name,
        "process_execution": process_execution,
        "operation": job.operation,
        "workstation": job.workstation,
        "source_handling_unit": source_handling_unit,
        "source_warehouse": row.s_warehouse,
        "wip_warehouse": row.t_warehouse,
        "transfer_stock_entry": entry.name,
        "transfer_stock_entry_detail": row.name,
        "idempotency_key": key,
        "reserved_on": now_datetime(),
        "reserved_by_operator": operator,
        "operator_session": operator_session,
        "notes": "Awaiting ERPNext Material Transfer submission",
    }).insert(ignore_permissions=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", reusable_bin, "wip_bin_state", "Reserved",
        update_modified=False,
    )
    record(
        "WIP Bin Load Reserved", card=cycle.kanban_card, cycle=cycle.name,
        execution=process_execution, handling_unit=reusable_bin, qty=qty,
        reference_doctype="CFG Kanban WIP Bin Load", reference_name=load.name,
        operator=operator, operator_session=operator_session,
        notes=f"{item_code} / {row.s_warehouse} -> {row.t_warehouse}; ERP Draft {entry.name}",
    )
    return load, True


def bind_consumption_draft(load_name, stock_entry, stock_entry_detail):
    """Bind a Ready/In-Use load to a Draft ERP consumption row without consuming it."""
    _lock_load(load_name)
    load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
    if load.status not in ("Ready", "In Use"):
        frappe.throw(f"WIP Bin Load {load.name} is {load.status}, not Ready for consumption")
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or _purpose(entry) not in CONSUMPTION_PURPOSES:
        frappe.throw("WIP Bin consumption requires a Draft production consumption Stock Entry")
    if entry.get("cfg_kanban_cycle") != load.kanban_cycle or entry.work_order != load.work_order:
        frappe.throw("Consumption Stock Entry does not belong to the WIP Bin Load production context")
    if entry.get("job_card") and entry.job_card != load.job_card:
        frappe.throw("Consumption Stock Entry Job Card does not match the WIP Bin Load")
    row = _entry_row(entry, stock_entry_detail)
    _assert_consumption_row(load, row)
    load.db_set({
        "status": "Consumption Draft",
        "consumption_stock_entry": entry.name,
        "consumption_stock_entry_detail": row.name,
        "notes": "Awaiting ERPNext consumption submission",
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Kanban Handling Unit", load.reusable_bin, "wip_bin_state", "In Use",
        update_modified=False,
    )
    return frappe.get_doc("CFG Kanban WIP Bin Load", load.name)


def validate_wip_bin_stock_entry(doc):
    """Validate every linked load and require complete coverage of WIP-bin material rows."""
    purpose = _purpose(doc)
    if purpose not in (TRANSFER_PURPOSE, *CONSUMPTION_PURPOSES):
        return
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    expected_statuses = (
        ("Transfer Draft",) if direction == "transfer" else ("Consumption Draft",)
    )
    rows = {row.name: row for row in doc.items}
    allocated = {}
    for load in loads:
        if load.status not in expected_statuses:
            frappe.throw(f"WIP Bin Load {load.name} is {load.status}; expected {expected_statuses[0]}")
        row_name = (load.transfer_stock_entry_detail if direction == "transfer"
                    else load.consumption_stock_entry_detail)
        row = rows.get(row_name)
        if not row:
            frappe.throw(f"WIP Bin Load {load.name} no longer matches a Stock Entry row")
        if direction == "transfer":
            _assert_transfer_row(load, row, doc)
        else:
            _assert_consumption_row(load, row)
        allocated[row.name] = allocated.get(row.name, 0) + flt(load.actual_qty)
    for row_name, qty in allocated.items():
        row_qty = _row_stock_qty(rows[row_name])
        if abs(qty - row_qty) > TOLERANCE:
            frappe.throw(
                f"WIP Bin loads cover {qty} of {row_qty} {rows[row_name].stock_uom} "
                f"for Item {rows[row_name].item_code}; allocate the complete Stock Entry row"
            )


def confirm_wip_bin_stock_entry(doc):
    """Advance bin/load state only after ERPNext has submitted the native transaction."""
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    validate_wip_bin_stock_entry(doc)
    timestamp = now_datetime()
    for summary in loads:
        _lock_load(summary.name)
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        if direction == "transfer":
            if load.status == "Ready":
                continue
            load.db_set({
                "status": "Ready", "ready_on": timestamp,
                "notes": f"Ready after submitted ERPNext transfer {doc.name}",
            }, update_modified=True)
            bin_state = "Ready"
            event_type = "WIP Bin Load Ready"
        else:
            if load.status == "Consumed":
                continue
            load.db_set({
                "status": "Consumed", "consumed_on": timestamp,
                "notes": f"Consumed by submitted ERPNext entry {doc.name}",
            }, update_modified=True)
            bin_state = "Empty"
            event_type = "WIP Bin Load Consumed"
        frappe.db.set_value(
            "CFG Kanban Handling Unit", load.reusable_bin,
            "wip_bin_state", bin_state, update_modified=False,
        )
        record(
            event_type, cycle=load.kanban_cycle, execution=load.process_execution,
            handling_unit=load.reusable_bin, qty=load.actual_qty,
            reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name}; ERPNext confirmed",
        )


def reverse_wip_bin_stock_entry(doc):
    """Make ERP cancellation visible and stop automatic reuse pending reconciliation."""
    loads, direction = _loads_for_entry(doc.name)
    if not loads:
        return
    for summary in loads:
        _lock_load(summary.name)
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        if load.status == "Reversed":
            continue
        if direction == "transfer" and load.status not in ("Transfer Draft", "Ready"):
            frappe.throw(
                f"Cannot cancel transfer: WIP Bin Load {load.name} is already {load.status}"
            )
        if direction == "consumption" and load.status != "Consumed":
            frappe.throw(
                f"Cannot cancel consumption: WIP Bin Load {load.name} is {load.status}"
            )
        bin_state = "Empty" if direction == "transfer" else "Exception"
        load.db_set({
            "status": "Reversed", "reversed_on": now_datetime(),
            "notes": (f"ERPNext {direction} Stock Entry {doc.name} cancelled; "
                      "supervisor reconciliation required"),
        }, update_modified=True)
        frappe.db.set_value(
            "CFG Kanban Handling Unit", load.reusable_bin,
            "wip_bin_state", bin_state, update_modified=False,
        )
        record(
            "WIP Bin Load Reversed", cycle=load.kanban_cycle,
            execution=load.process_execution, handling_unit=load.reusable_bin,
            qty=load.actual_qty, reference_doctype="Stock Entry", reference_name=doc.name,
            notes=f"WIP Bin Load {load.name}; physical state {bin_state}",
        )


def _loads_for_entry(stock_entry):
    fields = [
        "name", "status", "reusable_bin", "item_code", "batch_no", "actual_qty",
        "stock_uom", "company", "source_warehouse", "wip_warehouse", "kanban_cycle",
        "process_execution", "transfer_stock_entry_detail",
        "consumption_stock_entry_detail",
    ]
    transfer = frappe.get_all(
        "CFG Kanban WIP Bin Load", {"transfer_stock_entry": stock_entry}, fields,
    )
    consumption = frappe.get_all(
        "CFG Kanban WIP Bin Load", {"consumption_stock_entry": stock_entry}, fields,
    )
    if transfer and consumption:
        frappe.throw("One Stock Entry cannot be both WIP Bin transfer and consumption")
    return (transfer, "transfer") if transfer else (consumption, "consumption")


def _wip_rule(master, item_code, operation):
    rule = frappe.db.get_value("CFG Kanban Material Flow Rule", {
        "parent": master,
        "parenttype": "CFG Kanban Master",
        "item_code": item_code,
        "operation": operation,
        "wip_presentation_method": "Standard Quantity Reusable WIP Bin",
    }, ["wip_bin_pool", "standard_bin_qty", "stock_uom"], as_dict=True)
    if not rule:
        frappe.throw(f"Item {item_code} is not configured as a reusable WIP Bin material")
    return rule


def _entry_row(doc, row_name):
    row = next((candidate for candidate in doc.items if candidate.name == row_name), None)
    if not row:
        frappe.throw("Selected Stock Entry material row was not found")
    return row


def _assert_transfer_row(load, row, doc):
    if (_purpose(doc) != TRANSFER_PURPOSE or row.item_code != load.item_code
            or row.s_warehouse != load.source_warehouse
            or row.t_warehouse != load.wip_warehouse
            or row.stock_uom != load.stock_uom
            or (row.get("batch_no") or "") != (load.batch_no or "")):
        frappe.throw(f"WIP Bin Load {load.name} no longer matches its ERP transfer row")


def _assert_consumption_row(load, row):
    if (row.item_code != load.item_code or row.s_warehouse != load.wip_warehouse
            or row.stock_uom != load.stock_uom
            or (row.get("batch_no") or "") != (load.batch_no or "")):
        frappe.throw(f"WIP Bin Load {load.name} no longer matches its ERP consumption row")


def _row_stock_qty(row):
    return flt(row.get("transfer_qty") or row.get("qty"))


def _purpose(doc):
    return doc.get("stock_entry_type") or doc.get("purpose")


def _lock_reusable_bin(reusable_bin):
    if not frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        reusable_bin,
    ):
        frappe.throw("Reusable WIP Bin was not found")


def _lock_load(load_name):
    if not frappe.db.sql(
        "select name from `tabCFG Kanban WIP Bin Load` where name=%s for update",
        load_name,
    ):
        frappe.throw("WIP Bin Load was not found")

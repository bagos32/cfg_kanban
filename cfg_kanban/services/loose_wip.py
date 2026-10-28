"""Cumulative usage control for reusable Loose Multi-Item WIP Bins.

ERPNext remains the stock authority. Loading is confirmed by native Material Transfer for
Manufacture. These immutable usage rows record floor consumption by operation-card cycle; one
consolidated native Material Consumption for Manufacture is prepared when the owning Job Card
completes (with a legacy Work Order-wide fallback for older records).
"""

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan


TOLERANCE = 0.000001
OPEN_USAGE_STATUSES = ("Recorded", "Consumption Draft", "Posted")
ACTIVE_LOAD_STATUSES = ("Ready", "In Use")


def loose_bin_balance(*, material_owner_cycle, work_order, job_card, reusable_bin_scan,
                      requesting_cycle=None):
    """Return audited available quantities in one bin for the selected Job Card boundary."""
    unit, pool = _resolve_loose_bin(reusable_bin_scan)
    _validate_cycle_boundary(
        material_owner_cycle, work_order, job_card, requesting_cycle=requesting_cycle,
    )
    loads = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {
            "reusable_bin": unit.name,
            "wip_bin_pool": pool.name,
            "bin_mode": "Loose Multi-Item",
            "work_order": work_order,
            "job_card": job_card,
            "status": ["in", list(ACTIVE_LOAD_STATUSES)],
        },
        ["name", "item_code", "batch_no", "actual_qty", "stock_uom",
         "source_warehouse", "wip_warehouse", "operation", "workstation", "creation"],
        order_by="creation asc",
        limit_page_length=0,
    )
    rows = []
    for load in loads:
        used = _load_reported_qty(load.name)
        available = max(flt(load.actual_qty) - used, 0)
        if available <= TOLERANCE:
            continue
        rows.append({
            "wip_bin_load": load.name,
            "item_code": load.item_code,
            "batch_no": load.batch_no,
            "loaded_qty": flt(load.actual_qty),
            "reported_qty": used,
            "available_qty": available,
            "stock_uom": load.stock_uom,
            "source_warehouse": load.source_warehouse,
            "wip_warehouse": load.wip_warehouse,
        })
    grouped = {}
    for row in rows:
        key = (row["item_code"], row["batch_no"] or "", row["stock_uom"])
        target = grouped.setdefault(key, {
            "item_code": row["item_code"], "batch_no": row["batch_no"],
            "stock_uom": row["stock_uom"], "loaded_qty": 0,
            "reported_qty": 0, "available_qty": 0,
        })
        for field in ("loaded_qty", "reported_qty", "available_qty"):
            target[field] += row[field]
    return {
        "reusable_bin": unit.name,
        "handling_unit_id": unit.handling_unit_id,
        "wip_bin_pool": pool.name,
        "consumption_policy": pool.loose_consumption_policy,
        "work_order": work_order,
        "job_card": job_card,
        "rows": rows,
        "items": list(grouped.values()),
    }


def record_loose_usage(*, material_owner_cycle, work_order, job_card,
                       reusable_bin_scan, qty, item_code=None, batch_no=None,
                       requesting_cycle=None, process_execution=None, operator=None,
                       operator_session=None, notes=None, event_token=None):
    """Allocate one reported quantity FIFO across physical loose-bin load episodes."""
    requested_qty = flt(qty)
    if requested_qty <= TOLERANCE:
        frappe.throw("Enter a positive Loose WIP quantity before scanning the bin")
    boundary = _validate_cycle_boundary(
        material_owner_cycle, work_order, job_card, requesting_cycle=requesting_cycle,
    )
    unit, pool = _resolve_loose_bin(reusable_bin_scan)
    if pool.loose_consumption_policy != "Accumulate until Work Order close":
        frappe.throw(
            "This release supports Loose WIP accumulation only for Pools configured as "
            "Accumulate until Work Order close"
        )
    _lock_bin(unit.name)
    root_key = event_token or frappe.generate_hash(length=24)
    existing = frappe.get_all(
        "CFG Kanban Loose WIP Usage",
        {"idempotency_key": ["like", f"{root_key}:%"]},
        ["name", "qty", "item_code", "batch_no", "stock_uom"],
        order_by="creation asc", limit_page_length=0,
    )
    if existing:
        return _usage_result(unit, pool, existing, duplicate=True)
    loads = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {
            "reusable_bin": unit.name,
            "wip_bin_pool": pool.name,
            "bin_mode": "Loose Multi-Item",
            "work_order": work_order,
            "job_card": job_card,
            "operation": boundary.operation,
            "workstation": boundary.workstation,
            "status": ["in", list(ACTIVE_LOAD_STATUSES)],
        },
        ["name", "item_code", "batch_no", "actual_qty", "stock_uom", "company",
         "kanban_master", "kanban_cycle", "source_warehouse", "wip_warehouse",
         "process_execution", "operation", "workstation", "creation"],
        order_by="creation asc",
        limit_page_length=0,
    )
    candidates = []
    for load in loads:
        if item_code and load.item_code != item_code:
            continue
        if batch_no not in (None, "") and (load.batch_no or "") != batch_no:
            continue
        available = max(flt(load.actual_qty) - _load_reported_qty(load.name), 0)
        if available > TOLERANCE:
            candidates.append((load, available))
    identities = {(load.item_code, load.batch_no or "", load.stock_uom)
                  for load, _available in candidates}
    if not candidates:
        frappe.throw(
            f"Loose WIP Bin {unit.handling_unit_id} has no available matching material "
            f"for Job Card {job_card}"
        )
    if not item_code and len(identities) != 1:
        frappe.throw(
            "This Loose WIP Bin contains multiple Items or Batches. Select the numbered "
            "material row before scanning the bin."
        )
    total_available = sum(available for _load, available in candidates)
    if requested_qty > total_available + TOLERANCE:
        frappe.throw(
            f"Loose WIP Bin {unit.handling_unit_id} has only {total_available} available; "
            f"reported use is {requested_qty}"
        )
    remaining = requested_qty
    created = []
    for load, available in candidates:
        if remaining <= TOLERANCE:
            break
        use_qty = min(remaining, available)
        usage = frappe.get_doc({
            "doctype": "CFG Kanban Loose WIP Usage",
            "status": "Recorded",
            "reusable_bin": unit.name,
            "wip_bin_load": load.name,
            "wip_bin_pool": pool.name,
            "company": load.company,
            "item_code": load.item_code,
            "batch_no": load.batch_no,
            "qty": use_qty,
            "stock_uom": load.stock_uom,
            "kanban_master": load.kanban_master,
            "material_owner_cycle": material_owner_cycle,
            "requesting_cycle": requesting_cycle,
            "work_order": work_order,
            "job_card": job_card,
            "process_execution": process_execution or load.process_execution,
            "operation": load.operation,
            "workstation": load.workstation,
            "source_warehouse": load.source_warehouse,
            "wip_warehouse": load.wip_warehouse,
            "idempotency_key": f"{root_key}:{load.name}",
            "reported_by_operator": operator,
            "operator_session": operator_session,
            "reported_on": now_datetime(),
            "notes": notes,
        }).insert(ignore_permissions=True)
        created.append(usage)
        remaining -= use_qty
        if frappe.db.get_value("CFG Kanban WIP Bin Load", load.name, "status") == "Ready":
            frappe.db.set_value(
                "CFG Kanban WIP Bin Load", load.name,
                {"status": "In Use", "in_use_on": now_datetime()},
                update_modified=True,
            )
        record(
            "Loose WIP Usage Recorded",
            cycle=requesting_cycle or material_owner_cycle,
            execution=process_execution or load.process_execution,
            handling_unit=unit.name,
            qty=use_qty,
            reference_doctype="CFG Kanban Loose WIP Usage",
            reference_name=usage.name,
            operator=operator,
            operator_session=operator_session,
            notes=(f"Material owner Cycle {material_owner_cycle}; Job Card {job_card}; "
                   f"Item {load.item_code}; Batch {load.batch_no or '-'}"),
        )
    from cfg_kanban.services.wip_bin_loads import _refresh_wip_bin_state
    _refresh_wip_bin_state(unit.name)
    return _usage_result(unit, pool, created, duplicate=False)


def reverse_recorded_usage(usage_name, *, reason, operator=None, operator_session=None):
    usage = frappe.get_doc("CFG Kanban Loose WIP Usage", usage_name)
    if usage.status != "Recorded" or usage.consumption_stock_entry:
        frappe.throw("Only unposted Loose WIP usage may be reversed")
    if not (reason or "").strip():
        frappe.throw("A reversal reason is required")
    usage.db_set({
        "status": "Reversed", "reversal_reason": reason.strip(),
    }, update_modified=True)
    record(
        "Loose WIP Usage Reversed", cycle=usage.requesting_cycle or usage.material_owner_cycle,
        execution=usage.process_execution, handling_unit=usage.reusable_bin,
        qty=usage.qty, reference_doctype=usage.doctype, reference_name=usage.name,
        operator=operator, operator_session=operator_session, notes=reason.strip(),
    )
    return {"usage": usage.name, "status": "Reversed"}


def bind_consolidated_consumption(stock_entry, usage_names):
    """Bind Recorded usage and source loads to one Job Card/Work Order ERP draft."""
    from cfg_kanban.services.wip_bin_loads import _refresh_wip_bin_state, bind_consumption_draft

    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 0 or entry.purpose != "Material Consumption for Manufacture":
        frappe.throw("Loose WIP usage requires a Draft Material Consumption for Manufacture")
    usages = [frappe.get_doc("CFG Kanban Loose WIP Usage", name) for name in usage_names]
    if not usages:
        frappe.throw("No recorded Loose WIP usage was selected")
    by_load = {}
    for usage in usages:
        if usage.status != "Recorded" or usage.consumption_stock_entry:
            frappe.throw(f"Loose WIP Usage {usage.name} is no longer awaiting ERP posting")
        if usage.work_order != entry.work_order or usage.material_owner_cycle != entry.cfg_kanban_cycle:
            frappe.throw(f"Loose WIP Usage {usage.name} belongs to another production context")
        if entry.get("cfg_kanban_job_card") and usage.job_card != entry.cfg_kanban_job_card:
            frappe.throw(
                f"Loose WIP Usage {usage.name} belongs to Job Card {usage.job_card}, "
                f"not {entry.cfg_kanban_job_card}"
            )
        by_load.setdefault(usage.wip_bin_load, []).append(usage)
    rows = {}
    for row in entry.items:
        key = (row.item_code, row.s_warehouse, row.get("batch_no") or "", row.stock_uom)
        rows.setdefault(key, []).append(row)
    touched_bins = set()
    for load_name, values in by_load.items():
        load = frappe.get_doc("CFG Kanban WIP Bin Load", load_name)
        consumed = sum(flt(value.qty) for value in values)
        key = (load.item_code, load.wip_warehouse, load.batch_no or "", load.stock_uom)
        matching = rows.get(key) or []
        if len(matching) != 1:
            frappe.throw(
                f"Loose WIP Load {load.name} does not map to one unambiguous ERP consumption row"
            )
        bound = bind_consumption_draft(
            load.name, entry.name, matching[0].name, consumed_qty=consumed,
            consumption_reason="Accumulated Loose WIP use across operation-card cycles",
            reported_by=values[-1].reported_by_operator,
        )
        touched_bins.add(load.reusable_bin)
        for usage in values:
            usage.db_set({
                "status": "Consumption Draft",
                "consumption_stock_entry": entry.name,
                "consumption_stock_entry_detail": bound.consumption_stock_entry_detail,
            }, update_modified=True)

    for reusable_bin in touched_bins:
        _refresh_wip_bin_state(reusable_bin)
    return usages


def abandon_consumption_draft(stock_entry):
    usage_names = frappe.get_all(
        "CFG Kanban Loose WIP Usage",
        {"consumption_stock_entry": stock_entry, "status": "Consumption Draft"},
        pluck="name", limit_page_length=0,
    )
    for name in usage_names:
        frappe.db.set_value(
            "CFG Kanban Loose WIP Usage", name,
            {"status": "Recorded", "consumption_stock_entry": None,
             "consumption_stock_entry_detail": None},
            update_modified=True,
        )


def confirm_consumption(stock_entry):
    timestamp = now_datetime()
    entry = frappe.get_doc("Stock Entry", stock_entry)
    usage_names = frappe.get_all(
        "CFG Kanban Loose WIP Usage",
        {"consumption_stock_entry": stock_entry, "status": "Consumption Draft"},
        pluck="name", limit_page_length=0,
    )
    for name in usage_names:
        frappe.db.set_value(
            "CFG Kanban Loose WIP Usage", name,
            {"status": "Posted", "posted_on": timestamp}, update_modified=True,
        )
    if not entry.get("cfg_loose_wip_consolidated"):
        return
    from cfg_kanban.services.wip_bin_loads import (
        _create_wip_bin_return_draft,
        _refresh_wip_bin_state,
    )
    untouched_filters = {
        "bin_mode": "Loose Multi-Item", "kanban_cycle": entry.cfg_kanban_cycle,
        "work_order": entry.work_order, "status": ["in", ["Ready", "In Use"]],
    }
    if entry.get("cfg_kanban_job_card"):
        untouched_filters["job_card"] = entry.cfg_kanban_job_card
    untouched = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        untouched_filters,
        ["name", "reusable_bin"], limit_page_length=0,
    )
    for summary in untouched:
        load = frappe.get_doc("CFG Kanban WIP Bin Load", summary.name)
        load.db_set({
            "status": "Return Draft", "consumed_qty": 0,
            "return_qty": load.actual_qty,
            "consumption_reason": (
                "Unused Loose WIP material returned at Job Card close"
                if entry.get("cfg_kanban_job_card")
                else "Unused Loose WIP material returned at Work Order close"
            ),
            "consumption_reported_on": timestamp,
        }, update_modified=True)
        return_entry = _create_wip_bin_return_draft(load)
        load.db_set({
            "return_stock_entry": return_entry.name,
            "return_stock_entry_detail": return_entry.items[0].name,
        }, update_modified=True)
        _refresh_wip_bin_state(load.reusable_bin)


def _resolve_loose_bin(scan_value):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Loose Multi-Item WIP Bin")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if (unit.tag_kind != "Reusable Container"
            or unit.reusable_container_role != "Loose Multi-Item WIP Bin"):
        frappe.throw(f"Tag {unit.handling_unit_id} is not a Loose Multi-Item WIP Bin")
    if unit.identity_state not in ("Active", "Empty") or unit.quality_state != "Released":
        frappe.throw(
            f"Loose WIP Bin {unit.handling_unit_id} is "
            f"{unit.identity_state} / {unit.quality_state}"
        )
    pool_name = frappe.db.get_value(
        "CFG Kanban WIP Bin Pool Entry",
        {"reusable_bin": unit.name, "active": 1}, "parent",
    )
    pool = frappe.get_doc("CFG Kanban WIP Bin Pool", pool_name) if pool_name else None
    if not pool or not pool.active or pool.pool_mode != "Loose Multi-Item":
        frappe.throw(f"Loose WIP Bin {unit.handling_unit_id} has no active Loose WIP Pool")
    return unit, pool


def _validate_cycle_boundary(material_owner_cycle, work_order, job_card,
                             requesting_cycle=None):
    owner = frappe.db.get_value(
        "CFG Kanban Cycle", material_owner_cycle,
        ["name", "kanban_master", "work_order"], as_dict=True,
    )
    job = frappe.db.get_value(
        "Job Card", job_card,
        ["name", "work_order", "operation", "workstation", "docstatus"], as_dict=True,
    )
    if not owner or owner.work_order != work_order:
        frappe.throw("Material owner Cycle does not match the Work Order")
    if not job or job.docstatus == 2 or job.work_order != work_order:
        frappe.throw("Job Card does not match the Work Order")
    if requesting_cycle and requesting_cycle != material_owner_cycle:
        request = frappe.db.get_value(
            "CFG Kanban Cycle", requesting_cycle,
            ["work_order", "selected_job_card", "runtime_allocation", "status"],
            as_dict=True,
        )
        if (not request or not request.runtime_allocation
                or request.work_order != work_order
                or request.selected_job_card != job_card
                or request.status in ("Cancelled", "Closed")):
            frappe.throw("Requesting operation Card Cycle does not control this Job Card")
    return frappe._dict({
        "kanban_master": owner.kanban_master,
        "operation": job.operation,
        "workstation": job.workstation,
    })


def _load_reported_qty(load_name):
    value = frappe.db.sql(
        """
        select coalesce(sum(qty), 0)
          from `tabCFG Kanban Loose WIP Usage`
         where wip_bin_load=%s and status in ('Recorded', 'Consumption Draft', 'Posted')
        """,
        load_name,
    )[0][0]
    return flt(value)


def _usage_result(unit, pool, usages, duplicate=False):
    rows = [{
        "name": value.name, "item_code": value.item_code,
        "batch_no": value.batch_no, "qty": flt(value.qty),
        "stock_uom": value.stock_uom,
    } for value in usages]
    return {
        "reusable_bin": unit.name,
        "handling_unit_id": unit.handling_unit_id,
        "wip_bin_pool": pool.name,
        "usage_rows": rows,
        "qty": sum(row["qty"] for row in rows),
        "duplicate": duplicate,
    }


def _lock_bin(reusable_bin):
    if not frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        reusable_bin,
    ):
        frappe.throw("Loose WIP Bin was not found")

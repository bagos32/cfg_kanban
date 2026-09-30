import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.handling_unit_math import apply_balance_delta, event_deltas


def validate_warehouse_company(warehouse, company, label="Warehouse"):
    if not warehouse:
        return
    actual_company = frappe.db.get_value("Warehouse", warehouse, "company")
    if not actual_company:
        frappe.throw(f"{label} {warehouse} does not have a Company")
    if actual_company != company:
        frappe.throw(f"{label} {warehouse} belongs to {actual_company}, not {company}")


def validate_price_list_mode(price_list, mode, label):
    if not price_list:
        return
    flag = "selling" if mode == "selling" else "buying"
    enabled = frappe.db.get_value("Price List", price_list, flag)
    if not enabled:
        frappe.throw(f"{label} {price_list} is not enabled for {mode.title()} transactions")


def resolve_logistics_token(token):
    handling_unit = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"opaque_token": token}, "name"
    )
    if handling_unit:
        return {"identity_type": "Handling Unit", "name": handling_unit}
    customer_site = frappe.db.get_value(
        "CFG Kanban Customer Scan Point", {"opaque_token": token, "active": 1}, "name"
    )
    if customer_site:
        return {"identity_type": "Customer Scan Point", "name": customer_site}
    tag = frappe.db.get_value(
        "CFG Kanban Tag Identity",
        {"opaque_token": token},
        ["parent", "visible_code", "state", "handling_unit"],
        as_dict=True,
    )
    if tag:
        return {
            "identity_type": "Registered Tag Identity",
            "name": tag.visible_code,
            "tag_family": tag.parent,
            "state": tag.state,
            "handling_unit": tag.handling_unit,
        }
    return None


def post_quantity_event(*, event_type, qty, stock_uom, idempotency_key,
                        source_handling_unit=None, destination_handling_unit=None,
                        item_code=None, batch_no=None, transaction_uom=None,
                        conversion_factor=1, source_company=None, destination_company=None,
                        source_warehouse=None, destination_warehouse=None,
                        reference_doctype=None, reference_name=None, operator=None,
                        operator_session=None, device_id=None, reason=None,
                        release_reserved=False, posting_datetime=None):
    existing = _existing_ledger(idempotency_key)
    if existing:
        return frappe.get_doc("CFG Kanban Handling Unit Quantity Ledger", existing)

    stock_qty = flt(qty) * flt(conversion_factor or 1)
    try:
        deltas = event_deltas(event_type, stock_qty, release_reserved=release_reserved)
    except ValueError as exc:
        frappe.throw(str(exc))

    _require_event_endpoints(
        event_type,
        deltas,
        source_handling_unit,
        destination_handling_unit,
    )
    handling_units = sorted({value for value in (source_handling_unit, destination_handling_unit)
                             if value})
    _lock_handling_units(handling_units)
    # Two retries can pass the first lookup together. The Handling Unit row lock
    # serializes them, so check the unique key again after acquiring that lock.
    existing = _existing_ledger(idempotency_key)
    if existing:
        return frappe.get_doc("CFG Kanban Handling Unit Quantity Ledger", existing)
    updates = _calculate_updates(handling_units, source_handling_unit,
                                 destination_handling_unit, deltas)

    ledger = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit Quantity Ledger",
        "event_type": event_type,
        "posting_datetime": posting_datetime or now_datetime(),
        "idempotency_key": idempotency_key,
        "source_handling_unit": source_handling_unit,
        "destination_handling_unit": destination_handling_unit,
        "item_code": item_code,
        "batch_no": batch_no,
        "transaction_uom": transaction_uom or stock_uom,
        "conversion_factor": conversion_factor or 1,
        "qty": qty,
        "stock_uom": stock_uom,
        "stock_qty": stock_qty,
        "source_qty_delta": float(deltas["source_qty_delta"]),
        "destination_qty_delta": float(deltas["destination_qty_delta"]),
        "source_reserved_delta": float(deltas["source_reserved_delta"]),
        "destination_reserved_delta": float(deltas["destination_reserved_delta"]),
        "source_company": source_company,
        "destination_company": destination_company,
        "source_warehouse": source_warehouse,
        "destination_warehouse": destination_warehouse,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "operator": operator,
        "operator_session": operator_session,
        "device_id": device_id,
        "reason": reason,
        "system_generated": 1,
    }).insert(ignore_permissions=True)

    for handling_unit, values in updates.items():
        frappe.db.set_value("CFG Kanban Handling Unit", handling_unit, values,
                            update_modified=False)
    return ledger


def _existing_ledger(idempotency_key):
    if not idempotency_key:
        frappe.throw("Idempotency Key is required for a quantity-ledger event")
    return frappe.db.get_value(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"idempotency_key": idempotency_key},
        "name",
    )


def rebuild_handling_unit_balance(handling_unit, *, apply=False):
    if not frappe.db.exists("CFG Kanban Handling Unit", handling_unit):
        frappe.throw(f"Handling Unit {handling_unit} does not exist")
    result = frappe.db.sql(
        """
        select
            coalesce(sum(case when source_handling_unit = %(name)s then source_qty_delta else 0 end), 0)
            + coalesce(sum(case when destination_handling_unit = %(name)s then destination_qty_delta else 0 end), 0),
            coalesce(sum(case when source_handling_unit = %(name)s then source_reserved_delta else 0 end), 0)
            + coalesce(sum(case when destination_handling_unit = %(name)s then destination_reserved_delta else 0 end), 0)
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where source_handling_unit = %(name)s or destination_handling_unit = %(name)s
        """,
        {"name": handling_unit},
    )[0]
    try:
        current, reserved, available = apply_balance_delta(0, 0, qty_delta=result[0],
                                                           reserved_delta=result[1])
    except ValueError as exc:
        frappe.throw(str(exc))
    values = {
        "current_qty": float(current),
        "reserved_qty": float(reserved),
        "available_qty": float(available),
        "last_reconciled_on": now_datetime(),
    }
    if apply:
        frappe.db.set_value("CFG Kanban Handling Unit", handling_unit, values,
                            update_modified=False)
    return values


def _require_event_endpoints(event_type, deltas, source, destination):
    if (deltas["source_qty_delta"] or deltas["source_reserved_delta"]) and not source:
        frappe.throw("Source Handling Unit is required for this ledger event")
    if (deltas["destination_qty_delta"] or deltas["destination_reserved_delta"]) and not destination:
        frappe.throw("Destination Handling Unit is required for this ledger event")
    if event_type in {
        "Location Transfer", "Return to Warehouse", "Quarantine", "Release"
    } and not source:
        frappe.throw("Source Handling Unit is required for this ledger event")
    if event_type in {
        "Split", "Replace", "Load into Container", "Unload from Container"
    } and source == destination:
        frappe.throw("Source and Destination Handling Units must be different")


def _lock_handling_units(names):
    if not names:
        return
    placeholders = ", ".join(["%s"] * len(names))
    locked = frappe.db.sql(
        f"""
        select name
        from `tabCFG Kanban Handling Unit`
        where name in ({placeholders})
        order by name
        for update
        """,
        tuple(names),
    )
    if len(locked) != len(names):
        frappe.throw("One or more Handling Units no longer exist")


def _calculate_updates(names, source, destination, deltas):
    updates = {}
    for name in names:
        current, reserved = frappe.db.get_value(
            "CFG Kanban Handling Unit", name, ["current_qty", "reserved_qty"]
        ) or (0, 0)
        qty_delta = 0
        reserved_delta = 0
        if name == source:
            qty_delta += deltas["source_qty_delta"]
            reserved_delta += deltas["source_reserved_delta"]
        if name == destination:
            qty_delta += deltas["destination_qty_delta"]
            reserved_delta += deltas["destination_reserved_delta"]
        try:
            new_current, new_reserved, available = apply_balance_delta(
                current, reserved, qty_delta=qty_delta, reserved_delta=reserved_delta
            )
        except ValueError as exc:
            frappe.throw(f"Handling Unit {name}: {exc}")
        updates[name] = {
            "current_qty": float(new_current),
            "reserved_qty": float(new_reserved),
            "available_qty": float(available),
        }
    return updates

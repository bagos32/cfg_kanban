import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.handling_unit_math import apply_balance_delta, event_deltas
from cfg_kanban.services.physical_identity import normalize_physical_code


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


def validate_physical_code_namespace(code, identity_type, tag_family=None):
    """Prevent a visible code from resolving to unrelated physical identities."""
    if identity_type != "Customer Scan Point" and frappe.db.exists(
        "CFG Kanban Customer Scan Point", {"site_code": code}
    ):
        frappe.throw(
            f"Physical code {code} is already used by a Customer Scan Point. "
            "Use a globally unique issuer/company prefix."
        )
    if identity_type != "Handling Unit" and frappe.db.exists(
        "CFG Kanban Handling Unit", {"handling_unit_id": code}
    ):
        frappe.throw(
            f"Physical code {code} is already used by a Handling Unit. "
            "Use a globally unique issuer/company prefix."
        )
    registered_family = frappe.db.get_value(
        "CFG Kanban Tag Identity", {"visible_code": code}, "parent"
    )
    if registered_family and not (
        identity_type == "Handling Unit" and registered_family == tag_family
    ):
        frappe.throw(
            f"Physical code {code} is already registered in Tag Family {registered_family}. "
            "Use a globally unique issuer/company prefix."
        )


def resolve_logistics_scan(scan_value):
    """Resolve a preprinted visible code first and an internal UUID alias second.

    The visible code is the stable, logistics-style waybill identity used on the
    physical tag.  UUIDs remain valid for backward compatibility and audit, but
    are not required on preprinted labels.
    """
    try:
        code = normalize_physical_code(scan_value)
    except ValueError as exc:
        frappe.throw(str(exc))

    candidates = {}
    _add_handling_unit_match(candidates, code, "handling_unit_id", "visible_code")
    _add_handling_unit_match(candidates, code, "opaque_token", "internal_uuid_alias")
    _add_tag_identity_match(candidates, code, "visible_code", "visible_code")
    _add_tag_identity_match(candidates, code, "opaque_token", "internal_uuid_alias")
    _add_customer_match(candidates, code, "site_code", "visible_code")
    _add_customer_match(candidates, code, "opaque_token", "internal_uuid_alias")

    # An activated registered identity and its Handling Unit represent the same
    # physical tag. Prefer the live Handling Unit rather than reporting ambiguity.
    for key, candidate in list(candidates.items()):
        if candidate["identity_type"] != "Registered Tag Identity":
            continue
        handling_unit = candidate.get("handling_unit")
        if handling_unit and ("Handling Unit", handling_unit) in candidates:
            candidates.pop(key)

    if len(candidates) > 1:
        identities = ", ".join(
            f"{row['identity_type']} {row['name']}" for row in candidates.values()
        )
        frappe.throw(
            f"Physical code {code} is ambiguous ({identities}). "
            "Use globally unique company/issuer prefixes and correct the registry before scanning."
        )
    return next(iter(candidates.values()), None)


def resolve_logistics_token(token):
    """Backward-compatible name for integrations created before visible-code scanning."""
    return resolve_logistics_scan(token)


def _add_handling_unit_match(candidates, code, fieldname, matched_by):
    row = frappe.db.get_value(
        "CFG Kanban Handling Unit",
        {fieldname: code},
        ["name", "handling_unit_id", "tag_kind", "tag_family", "identity_state",
         "movement_state", "inventory_company", "current_warehouse"],
        as_dict=True,
    )
    if not row:
        return
    candidates[("Handling Unit", row.name)] = {
        "identity_type": "Handling Unit",
        "name": row.name,
        "visible_code": row.handling_unit_id,
        "matched_by": matched_by,
        "tag_kind": row.tag_kind,
        "tag_family": row.tag_family,
        "identity_state": row.identity_state,
        "movement_state": row.movement_state,
        "inventory_company": row.inventory_company,
        "current_warehouse": row.current_warehouse,
    }


def _add_tag_identity_match(candidates, code, fieldname, matched_by):
    row = frappe.db.get_value(
        "CFG Kanban Tag Identity",
        {fieldname: code},
        ["name", "parent", "visible_code", "tag_role", "child_index", "state",
         "handling_unit"],
        as_dict=True,
    )
    if not row:
        return
    issued_company = frappe.db.get_value("CFG Kanban Tag Family", row.parent, "issued_company")
    candidates[("Registered Tag Identity", row.name)] = {
        "identity_type": "Registered Tag Identity",
        "name": row.visible_code,
        "visible_code": row.visible_code,
        "matched_by": matched_by,
        "tag_family": row.parent,
        "tag_role": row.tag_role,
        "child_index": row.child_index,
        "state": row.state,
        "handling_unit": row.handling_unit,
        "issued_company": issued_company,
    }


def _add_customer_match(candidates, code, fieldname, matched_by):
    row = frappe.db.get_value(
        "CFG Kanban Customer Scan Point",
        {fieldname: code},
        ["name", "site_code", "site_name", "active", "selling_company", "customer",
         "customer_address"],
        as_dict=True,
    )
    if not row:
        return
    candidates[("Customer Scan Point", row.name)] = {
        "identity_type": "Customer Scan Point",
        "name": row.name,
        "visible_code": row.site_code,
        "matched_by": matched_by,
        "site_name": row.site_name,
        "active": bool(row.active),
        "selling_company": row.selling_company,
        "customer": row.customer,
        "customer_address": row.customer_address,
    }


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

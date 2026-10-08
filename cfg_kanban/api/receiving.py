import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    resolve_logistics_scan,
)
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.serial_evidence import (
    assigned_serials_for_reference,
    assign_serials,
    erp_row_serials,
    item_uses_serials,
    select_serials_for_tag,
)
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


ALLOWED_ROLES = (
    "Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager",
    "System Manager",
)


@frappe.whitelist()
def get_purchase_receipt_trace_plan(purchase_receipt):
    frappe.only_for(ALLOWED_ROLES)
    receipt = frappe.get_doc("Purchase Receipt", purchase_receipt)
    receipt.check_permission("read")
    if receipt.docstatus != 1:
        frappe.throw("Submit the Purchase Receipt before activating received-material tags")
    if receipt.get("is_return"):
        frappe.throw("Purchase Return tagging requires the controlled return workflow")
    rows = []
    for item in receipt.items:
        policy = effective_trace_policy(item.item_code, receipt.company)
        stock_qty = _row_stock_qty(item)
        tagged_qty = _tagged_origin_qty(receipt.name, item.name)
        remaining_qty = max(stock_qty - tagged_qty, 0)
        warehouse = item.warehouse or receipt.set_warehouse
        batch_numbers = _row_batch_numbers(item)
        tagging_permitted = policy.receiving_tag_policy != NO_TAG
        blocking_reason = None
        if not tagging_permitted:
            blocking_reason = (
                "ERP-only receiving: configure an enabled Item/Company Material Trace Policy "
                "with Optional or Required Physical Tag to activate a Stock Tag"
            )
        elif remaining_qty <= 0.000001:
            blocking_reason = "The confirmed receipt quantity is already fully tagged"
        elif not warehouse:
            blocking_reason = "Set the accepted Warehouse on the Purchase Receipt row"
        elif len(batch_numbers) > 1:
            blocking_reason = "Split this row so each physical tag represents only one Batch"
        elif policy.require_batch and not batch_numbers:
            blocking_reason = "Complete the ERPNext Batch information before tagging"
        serial_controlled = item_uses_serials(item.item_code)
        row_serials = erp_row_serials(item) if serial_controlled else []
        assigned_serials = set(assigned_serials_for_reference(
            "Purchase Receipt", receipt.name, item.name
        ))
        rows.append({
            "row_name": item.name,
            "item_code": item.item_code,
            "item_name": item.item_name,
            "warehouse": warehouse,
            "batch_no": batch_numbers[0] if len(batch_numbers) == 1 else "Multiple batches" if batch_numbers else None,
            "stock_uom": item.stock_uom,
            "confirmed_stock_qty": stock_qty,
            "tagged_stock_qty": tagged_qty,
            "remaining_stock_qty": remaining_qty,
            "trace_level": policy.trace_level,
            "tag_policy": policy.receiving_tag_policy,
            "policy_source": policy.policy_source,
            "tagging_available": tagging_permitted,
            "tagging_ready": not blocking_reason,
            "tagging_status": "Ready to tag" if not blocking_reason else blocking_reason,
            "tag_required": policy.receiving_tag_policy == "Required Physical Tag",
            "allow_partial_tag_quantity": bool(policy.allow_partial_tag_quantity),
            "require_batch": bool(policy.require_batch),
            "serial_controlled": serial_controlled,
            "available_serial_numbers": [value for value in row_serials
                                         if value not in assigned_serials],
        })
    return {
        "purchase_receipt": receipt.name,
        "company": receipt.company,
        "supplier": receipt.supplier,
        "posting_date": receipt.posting_date,
        "rows": rows,
        "all_rows_satisfied": all(
            not row["tag_required"] or row["remaining_stock_qty"] <= 0.000001
            for row in rows
        ),
    }


@frappe.whitelist()
def activate_purchase_receipt_tag(purchase_receipt, item_row, scan_value, qty,
                                  handling_unit_type="Container", serial_numbers=None):
    frappe.only_for(ALLOWED_ROLES)
    try:
        visible_code = normalize_physical_code(scan_value)
    except ValueError as exc:
        frappe.throw(str(exc))
    qty = flt(qty)
    if qty <= 0:
        frappe.throw("Tag quantity must be positive")

    frappe.db.sql(
        "select name from `tabPurchase Receipt` where name=%s for update",
        purchase_receipt,
    )
    receipt = frappe.get_doc("Purchase Receipt", purchase_receipt)
    receipt.check_permission("read")
    if receipt.docstatus != 1:
        frappe.throw("Only a submitted Purchase Receipt can activate received-material tags")
    if receipt.get("is_return"):
        frappe.throw("Purchase Return tagging requires the controlled return workflow")
    row = next((candidate for candidate in receipt.items if candidate.name == item_row), None)
    if not row:
        frappe.throw("The selected item row does not belong to this Purchase Receipt")

    policy = effective_trace_policy(row.item_code, receipt.company)
    if policy.receiving_tag_policy == NO_TAG:
        frappe.throw(
            f"Item {row.item_code} uses ERP warehouse stock without physical receiving tags. "
            "Change its Material Trace Policy only when physical tagging is operationally required."
        )
    warehouse = row.warehouse or receipt.set_warehouse
    if not warehouse:
        frappe.throw("The Purchase Receipt item has no accepted Warehouse")
    batch_no = _tag_batch_no(row)
    if policy.require_batch and not batch_no:
        frappe.throw(f"Item {row.item_code} requires a Batch before a tag can be activated")

    activation_key = canonical_key("purchase-receipt-tag", receipt.name, row.name, visible_code)
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": activation_key}, "name"
    )
    if existing:
        return _activation_result(existing, receipt, row)

    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
        if (unit.origin_reference_doctype == "Purchase Receipt"
                and unit.origin_reference_name == receipt.name
                and unit.origin_reference_row == row.name):
            return _activation_result(unit.name, receipt, row)
        frappe.throw(f"Preprinted tag {visible_code} is already active as {unit.name}")
    if not identity or identity.get("identity_type") not in (
        "Registered Tag Identity", "Tag Range Candidate"
    ):
        frappe.throw(
            f"Preprinted tag {visible_code} is not covered by an active Tag Family or Tag Range"
        )
    if identity.get("tag_role") != "Main":
        frappe.throw("A detachable child tag can only split an already active main Stock Tag")
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(f"Preprinted tag {visible_code} is {identity.get('state')}")
    tag_family = identity.get("tag_family")
    if tag_family and not frappe.db.get_value("CFG Kanban Tag Family", tag_family, "active"):
        frappe.throw(f"Tag Family {tag_family} is inactive")

    confirmed = _row_stock_qty(row)
    tagged = _tagged_origin_qty(receipt.name, row.name)
    remaining = max(confirmed - tagged, 0)
    if qty > remaining + 0.000001:
        frappe.throw(
            f"Tag quantity {qty} exceeds the untagged confirmed receipt quantity {remaining} "
            f"for Item {row.item_code}"
        )
    if not policy.allow_partial_tag_quantity and abs(qty - remaining) > 0.000001:
        frappe.throw(
            f"Item {row.item_code} requires the remaining confirmed quantity {remaining} "
            "to be activated on one tag"
        )

    selected_serials = select_serials_for_tag(
        row, qty, serial_numbers,
        exclude=assigned_serials_for_reference("Purchase Receipt", receipt.name, row.name),
    )

    expiry_date = (frappe.db.get_value("Batch", batch_no, "expiry_date")
                   if batch_no else None)
    unit = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": visible_code,
        "handling_unit_type": handling_unit_type or "Container",
        "tag_kind": "Main Stock Tag",
        "item_code": row.item_code,
        "short_description": row.item_name,
        "qty": qty,
        "stock_uom": row.stock_uom,
        "batch_no": batch_no,
        "expiry_date": expiry_date,
        "inventory_company": receipt.company,
        "current_warehouse": warehouse,
        "source_location": receipt.supplier,
        "destination_location": warehouse,
        "state": "Received",
        "movement_state": "Received",
        "origin_reference_doctype": "Purchase Receipt",
        "origin_reference_name": receipt.name,
        "origin_reference_row": row.name,
        "activation_key": activation_key,
    })
    unit.flags.activation_reason = "Physical tag activated from submitted Purchase Receipt"
    unit.insert(ignore_permissions=True)
    if selected_serials:
        assign_serials(unit, selected_serials, "Purchase Receipt", receipt.name, row.name)
    record(
        "Purchase Receipt Material Tag Activated",
        handling_unit=unit.name,
        qty=qty,
        reference_doctype="Purchase Receipt",
        reference_name=receipt.name,
        notes=f"{row.item_code} / {batch_no or 'no Batch'} / {warehouse}",
        system_generated=True,
    )
    return _activation_result(unit.name, receipt, row)


def void_cancelled_purchase_receipt_tags(receipt):
    """Void untouched tags whose ERP receipt has just been cancelled.

    The ERP cancellation and this reconciliation run in one database transaction. If a
    tag has already moved into a later physical process, throwing here also rolls back
    the Purchase Receipt cancellation instead of leaving ERP stock and tag evidence out
    of agreement.
    """
    units = frappe.get_all(
        "CFG Kanban Handling Unit",
        filters={
            "origin_reference_doctype": "Purchase Receipt",
            "origin_reference_name": receipt.name,
            "identity_state": ["not in", ["Void", "Replaced"]],
        },
        pluck="name",
        limit_page_length=10000,
    )
    if not units:
        return 0
    receipt_rows = {row.name: row for row in receipt.items}
    for unit_name in units:
        unit = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
        row = receipt_rows.get(unit.origin_reference_row)
        expected_warehouse = ((row.warehouse or receipt.set_warehouse) if row else None)
        _assert_receipt_tag_untouched(unit, expected_warehouse)

    for unit_name in units:
        unit = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
        post_quantity_event(
            event_type="Reconcile Decrease",
            qty=unit.current_qty,
            stock_uom=unit.stock_uom,
            idempotency_key=canonical_key(
                "purchase-receipt-cancel-tag", receipt.name, unit.name
            ),
            source_handling_unit=unit.name,
            item_code=unit.item_code,
            batch_no=unit.batch_no,
            source_company=unit.inventory_company,
            source_warehouse=unit.current_warehouse,
            reference_doctype="Purchase Receipt",
            reference_name=receipt.name,
            reason="Origin Purchase Receipt cancelled; received Stock Tag voided",
        )
        if unit.serial_count:
            from cfg_kanban.services.serial_evidence import release_unit_serials
            release_unit_serials(
                unit.name, "Origin Purchase Receipt cancelled",
                "Purchase Receipt", receipt.name,
            )
        frappe.db.set_value(
            "CFG Kanban Handling Unit",
            unit.name,
            {
                "state": "Void",
                "identity_state": "Void",
                "movement_state": "Empty",
                "void_reason": f"Origin Purchase Receipt {receipt.name} cancelled",
                "last_scan_time": now_datetime(),
            },
            update_modified=False,
        )
        record(
            "Purchase Receipt Material Tag Voided",
            handling_unit=unit.name,
            qty=unit.current_qty,
            reference_doctype="Purchase Receipt",
            reference_name=receipt.name,
            notes=f"{unit.item_code} / {unit.handling_unit_id}",
            system_generated=True,
        )
    return len(units)


def _assert_receipt_tag_untouched(unit, expected_warehouse):
    from cfg_kanban.services.container_contents import active_container_membership

    changed = (
        unit.identity_state != "Active"
        or abs(flt(unit.current_qty) - flt(unit.original_qty)) > 0.000001
        or flt(unit.reserved_qty) > 0.000001
        or not expected_warehouse
        or unit.current_warehouse != expected_warehouse
        or bool(active_container_membership(unit.name))
        or bool(frappe.db.exists(
            "CFG Kanban Handling Unit",
            {"parent_handling_unit": unit.name,
             "identity_state": ["not in", ["Void", "Replaced"]]},
        ))
    )
    downstream_ledger = frappe.db.sql(
        """
        select name
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where (source_handling_unit=%s or destination_handling_unit=%s)
          and idempotency_key != %s
        limit 1
        """,
        (unit.name, unit.name, f"handling-unit-activation:{unit.name}"),
    )
    if changed or downstream_ledger:
        frappe.throw(
            f"Cannot cancel Purchase Receipt while Stock Tag {unit.handling_unit_id} has "
            "moved, split, been loaded, reserved, or consumed. Reconcile the physical tag "
            "and downstream stock activity first."
        )


def _activation_result(unit_name, receipt, row):
    unit = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
    confirmed = _row_stock_qty(row)
    tagged = _tagged_origin_qty(receipt.name, row.name)
    return {
        "handling_unit": unit.as_dict(),
        "confirmed_stock_qty": confirmed,
        "tagged_stock_qty": tagged,
        "remaining_stock_qty": max(confirmed - tagged, 0),
    }


def _row_stock_qty(row):
    return flt(row.get("stock_qty") or (flt(row.qty) * flt(row.conversion_factor or 1)))


def _tagged_origin_qty(purchase_receipt, item_row):
    return flt(frappe.db.sql(
        """
        select coalesce(sum(original_qty), 0)
        from `tabCFG Kanban Handling Unit`
        where origin_reference_doctype='Purchase Receipt'
          and origin_reference_name=%s
          and origin_reference_row=%s
          and identity_state not in ('Void', 'Replaced')
        """,
        (purchase_receipt, item_row),
    )[0][0])


def _row_batch_numbers(row):
    if row.get("batch_no"):
        return [row.batch_no]
    bundle = row.get("serial_and_batch_bundle")
    if not bundle:
        return []
    values = frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": bundle, "parenttype": "Serial and Batch Bundle",
                 "batch_no": ["is", "set"]},
        pluck="batch_no",
        order_by="idx asc",
    )
    return list(dict.fromkeys(value for value in values if value))


def _tag_batch_no(row):
    batches = _row_batch_numbers(row)
    if len(batches) > 1:
        frappe.throw(
            f"Purchase Receipt row {row.idx} contains multiple Batches. Split it into one row or "
            "Serial and Batch Bundle per Batch before assigning physical Handling Unit tags."
        )
    return batches[0] if batches else None

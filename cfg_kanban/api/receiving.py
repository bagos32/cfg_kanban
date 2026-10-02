import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.physical_identity import normalize_physical_code
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
        rows.append({
            "row_name": item.name,
            "item_code": item.item_code,
            "item_name": item.item_name,
            "warehouse": item.warehouse or receipt.set_warehouse,
            "batch_no": item.batch_no,
            "stock_uom": item.stock_uom,
            "confirmed_stock_qty": stock_qty,
            "tagged_stock_qty": tagged_qty,
            "remaining_stock_qty": max(stock_qty - tagged_qty, 0),
            "trace_level": policy.trace_level,
            "tag_policy": policy.receiving_tag_policy,
            "policy_source": policy.policy_source,
            "tagging_available": policy.receiving_tag_policy != NO_TAG,
            "tag_required": policy.receiving_tag_policy == "Required Physical Tag",
            "allow_partial_tag_quantity": bool(policy.allow_partial_tag_quantity),
            "require_batch": bool(policy.require_batch),
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
                                  handling_unit_type="Container"):
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
    if policy.require_batch and not row.batch_no:
        frappe.throw(f"Item {row.item_code} requires a Batch before a tag can be activated")

    activation_key = canonical_key("purchase-receipt-tag", receipt.name, row.name, visible_code)
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": activation_key}, "name"
    )
    if existing:
        return _activation_result(existing, receipt, row)

    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        unit = frappe.get_doc("CFG Kanban Handling Unit", identity.name)
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

    expiry_date = (frappe.db.get_value("Batch", row.batch_no, "expiry_date")
                   if row.batch_no else None)
    unit = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": visible_code,
        "handling_unit_type": handling_unit_type or "Container",
        "tag_kind": "Main Stock Tag",
        "item_code": row.item_code,
        "short_description": row.item_name,
        "qty": qty,
        "stock_uom": row.stock_uom,
        "batch_no": row.batch_no,
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
    record(
        "Purchase Receipt Material Tag Activated",
        handling_unit=unit.name,
        qty=qty,
        reference_doctype="Purchase Receipt",
        reference_name=receipt.name,
        notes=f"{row.item_code} / {row.batch_no or 'no Batch'} / {warehouse}",
        system_generated=True,
    )
    return _activation_result(unit.name, receipt, row)


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

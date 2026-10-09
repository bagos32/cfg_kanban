import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.purchase_receipt_math import calculate_receipt_result
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


MANAGER_ROLES = ("Purchase Manager", "Stock Manager", "Manufacturing Manager", "System Manager")
DISPOSITION_STATUS = {
    "Awaiting Decision": "Open",
    "Supplier Replacement": "Replacement Pending",
    "Supplier Credit / Return": "Return Pending",
    "Accept by Concession": "Concession Pending",
    "Scrap / Dispose": "Scrap Pending",
}


def receipt_cycle(doc):
    """Find the Kanban Cycle for both an original receipt and its native return."""
    if doc.get("cfg_kanban_cycle"):
        return doc.cfg_kanban_cycle
    if doc.get("is_return") and doc.get("return_against"):
        return frappe.db.get_value("Purchase Receipt", doc.return_against, "cfg_kanban_cycle")
    return None


def reconcile_purchase_cycle(cycle_name, latest_receipt=None):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if not cycle.purchase_order or not cycle.get("purchase_order_item"):
        return cycle

    receipts = frappe.get_all(
        "Purchase Receipt",
        filters={"cfg_kanban_cycle": cycle.name, "docstatus": 1},
        fields=["name", "is_return"],
        order_by="posting_date asc, posting_time asc, creation asc",
    )
    original_names = [row.name for row in receipts if not row.is_return]
    if original_names:
        legacy_returns = frappe.get_all(
            "Purchase Receipt",
            filters={"return_against": ["in", original_names], "docstatus": 1,
                     "cfg_kanban_cycle": ["is", "not set"]},
            pluck="name",
        )
        for name in legacy_returns:
            frappe.db.set_value("Purchase Receipt", name, "cfg_kanban_cycle",
                                cycle.name, update_modified=False)
            receipts.append(frappe._dict({"name": name, "is_return": 1}))
    if not latest_receipt and receipts:
        latest_receipt = receipts[-1].name
    # Backfill dispositions for submitted receipts created before this feature
    # was deployed, then calculate returns from native ERP documents.
    for receipt in receipts:
        if not receipt.is_return:
            ensure_receipt_dispositions(frappe.get_doc("Purchase Receipt", receipt.name))
    _recalculate_disposition_returns(cycle.name)
    totals = {"delivered": 0.0, "accepted": 0.0, "rejected": 0.0}
    for receipt in receipts:
        rows = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": receipt.name, "purchase_order_item": cycle.purchase_order_item},
            fields=["received_qty", "qty", "rejected_qty"],
        )
        for row in rows:
            totals["delivered"] += flt(row.received_qty)
            totals["accepted"] += flt(row.qty)
            totals["rejected"] += flt(row.rejected_qty)

    dispositions = frappe.get_all(
        "CFG Kanban Receipt Disposition",
        filters={"kanban_cycle": cycle.name, "status": ["!=", "Cancelled"]},
        fields=["name", "approved_concession_qty", "open_rejected_qty",
                "disposition", "status"],
    )
    concession = sum(flt(row.approved_concession_qty) for row in dispositions)
    short_closed = flt(cycle.get("purchase_short_closed_qty"))
    open_rejected = sum(flt(row.open_rejected_qty) for row in dispositions)
    ordered = flt(cycle.ordered_purchase_qty or cycle.requested_purchase_qty)
    factor = flt(cycle.purchase_uom_conversion_factor or 1)
    physically_received = max(totals["delivered"], 0)
    rejected_net = max(totals["rejected"], 0)
    potential_usable = max(totals["accepted"], 0) + concession
    if potential_usable + short_closed + 0.000001 >= ordered:
        for disposition in dispositions:
            if (disposition.disposition == "Supplier Replacement"
                    and flt(disposition.open_rejected_qty) <= 0.000001
                    and disposition.status != "Resolved"):
                frappe.db.set_value("CFG Kanban Receipt Disposition", disposition.name, {
                    "status": "Resolved", "resolved_on": now_datetime(),
                    "resolved_by": frappe.session.user,
                })
                disposition.status = "Resolved"

    pending_disposition = any(row.status not in ("Resolved", "Cancelled")
                              for row in dispositions)
    result = calculate_receipt_result(
        ordered, physically_received, totals["accepted"], open_rejected,
        concession, short_closed, pending_disposition,
    )
    usable = result["usable"]
    usable_outstanding = result["outstanding"]
    unresolved = result["unresolved"]
    complete = result["complete"]
    status = result["status"]
    purchase_status = result["purchase_status"]

    cycle.db_set({
        "latest_purchase_receipt": latest_receipt or cycle.latest_purchase_receipt,
        "received_purchase_qty": physically_received,
        "received_stock_qty": physically_received * factor,
        "delivered_purchase_qty": physically_received,
        "accepted_purchase_qty": max(totals["accepted"], 0),
        "rejected_purchase_qty": rejected_net,
        "rejected_open_purchase_qty": open_rejected,
        "concession_purchase_qty": concession,
        "usable_fulfilment_purchase_qty": usable,
        "purchase_short_closed_qty": short_closed,
        "outstanding_purchase_qty": usable_outstanding,
        "outstanding_stock_qty": usable_outstanding * factor,
        "received_qty": physically_received,
        "outstanding_qty": usable_outstanding,
        "receipt_disposition_status": "Open" if unresolved else "Resolved",
        "purchase_status": purchase_status,
    })
    set_cycle_state(cycle, status, event_type="Purchase Receipt Usable Quantity Reconciled",
                    reference_doctype="Purchase Receipt", reference_name=latest_receipt)
    _sync_card(cycle, complete, unresolved, usable)
    record("Purchase Receipt Quantity Reconciled", card=cycle.kanban_card, cycle=cycle.name,
           qty=usable, reference_doctype="Purchase Receipt", reference_name=latest_receipt,
           notes=(f"Delivered {physically_received}; accepted {totals['accepted']}; "
                  f"rejected on hand {open_rejected}; concession {concession}; "
                  f"short close {short_closed}; usable outstanding {usable_outstanding}"))
    return cycle


def ensure_receipt_dispositions(receipt):
    if receipt.get("is_return"):
        _refresh_returned_dispositions(receipt)
        return []
    cycle_name = receipt_cycle(receipt)
    if not cycle_name:
        return []
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    created = []
    for row in receipt.items:
        rejected = flt(row.rejected_qty)
        if rejected <= 0 or row.purchase_order_item != cycle.get("purchase_order_item"):
            continue
        existing = frappe.db.get_value(
            "CFG Kanban Receipt Disposition", {"purchase_receipt_item": row.name}, "name"
        )
        if existing:
            created.append(existing)
            continue
        disposition = frappe.get_doc({
            "doctype": "CFG Kanban Receipt Disposition",
            "kanban_cycle": cycle.name,
            "kanban_card": cycle.kanban_card,
            "company": receipt.company,
            "supplier": receipt.supplier,
            "item_code": row.item_code,
            "purchase_uom": row.uom,
            "stock_uom": row.stock_uom,
            "purchase_receipt": receipt.name,
            "purchase_receipt_item": row.name,
            "rejected_warehouse": row.rejected_warehouse,
            "delivered_qty": row.received_qty,
            "accepted_qty": row.qty,
            "rejected_qty": rejected,
            "returned_rejected_qty": 0,
            "open_rejected_qty": rejected,
            "disposition": "Awaiting Decision",
            "status": "Open",
            "opened_on": now_datetime(),
        }).insert(ignore_permissions=True)
        created.append(disposition.name)
        record("Supplier Receipt Rejection Opened", card=cycle.kanban_card, cycle=cycle.name,
               qty=rejected, reference_doctype=disposition.doctype,
               reference_name=disposition.name)
    return created


def set_disposition(disposition_name, disposition, reason):
    _require_manager()
    if disposition not in DISPOSITION_STATUS or disposition == "Awaiting Decision":
        frappe.throw(_("Select a controlled rejection disposition"))
    if not (reason or "").strip():
        frappe.throw(_("A disposition reason is required"))
    doc = frappe.get_doc("CFG Kanban Receipt Disposition", disposition_name)
    if doc.status in ("Resolved", "Cancelled"):
        frappe.throw(_("This receipt disposition is already {0}").format(doc.status))
    doc.db_set({"disposition": disposition, "status": DISPOSITION_STATUS[disposition],
                "decision_reason": reason})
    record("Supplier Receipt Disposition Selected", card=doc.kanban_card,
           cycle=doc.kanban_cycle, qty=doc.open_rejected_qty,
           reference_doctype=doc.doctype, reference_name=doc.name,
           notes=f"{disposition}: {reason}", system_generated=False)
    reconcile_purchase_cycle(doc.kanban_cycle)
    return doc.reload()


def approve_concession(disposition_name, stock_entry, qty, reason):
    _require_manager()
    doc = frappe.get_doc("CFG Kanban Receipt Disposition", disposition_name)
    if doc.disposition != "Accept by Concession":
        frappe.throw(_("Select Accept by Concession before recording its Stock Entry"))
    qty = flt(qty)
    if qty <= 0 or qty > flt(doc.open_rejected_qty) + 0.000001:
        frappe.throw(_("Concession quantity exceeds the open rejected quantity"))
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 1:
        frappe.throw(_("Concession requires a submitted Stock Entry"))
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.kanban_cycle)
    required_stock_qty = qty * flt(cycle.purchase_uom_conversion_factor or 1)
    moved = sum(flt(row.transfer_qty or row.qty) for row in entry.items
                if row.item_code == doc.item_code
                and row.s_warehouse == doc.rejected_warehouse
                and row.t_warehouse == cycle.destination_warehouse)
    if moved + 0.000001 < required_stock_qty:
        frappe.throw(_("Stock Entry does not transfer the concession quantity from {0} to {1}")
                     .format(doc.rejected_warehouse, cycle.destination_warehouse))
    approved = flt(doc.approved_concession_qty) + qty
    open_qty = max(flt(doc.open_rejected_qty) - qty, 0)
    doc.db_set({"approved_concession_qty": approved, "open_rejected_qty": open_qty,
                "resolution_doctype": "Stock Entry", "resolution_document": entry.name,
                "decision_reason": reason,
                "status": "Resolved" if open_qty <= 0.000001 else "Concession Pending",
                "resolved_on": now_datetime() if open_qty <= 0.000001 else None,
                "resolved_by": frappe.session.user if open_qty <= 0.000001 else None})
    record("Rejected Material Accepted by Concession", card=doc.kanban_card,
           cycle=doc.kanban_cycle, qty=qty, reference_doctype="Stock Entry",
           reference_name=entry.name, notes=reason, system_generated=False)
    return reconcile_purchase_cycle(doc.kanban_cycle)


def confirm_disposal(disposition_name, stock_entry, qty, reason):
    _require_manager()
    doc = frappe.get_doc("CFG Kanban Receipt Disposition", disposition_name)
    if doc.disposition != "Scrap / Dispose":
        frappe.throw(_("Select Scrap / Dispose before recording its Stock Entry"))
    qty = flt(qty)
    if qty <= 0 or qty > flt(doc.open_rejected_qty) + 0.000001:
        frappe.throw(_("Disposal quantity exceeds the open rejected quantity"))
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if entry.docstatus != 1:
        frappe.throw(_("Disposal requires a submitted Stock Entry"))
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.kanban_cycle)
    required_stock_qty = qty * flt(cycle.purchase_uom_conversion_factor or 1)
    removed = sum(flt(row.transfer_qty or row.qty) for row in entry.items
                  if row.item_code == doc.item_code
                  and row.s_warehouse == doc.rejected_warehouse)
    if removed + 0.000001 < required_stock_qty:
        frappe.throw(_("Stock Entry does not remove the disposal quantity from {0}")
                     .format(doc.rejected_warehouse))
    disposed = flt(doc.get("disposed_qty")) + qty
    open_qty = max(flt(doc.open_rejected_qty) - qty, 0)
    doc.db_set({"disposed_qty": disposed, "open_rejected_qty": open_qty,
                "resolution_doctype": "Stock Entry", "resolution_document": entry.name,
                "decision_reason": reason,
                "status": "Resolved" if open_qty <= 0.000001 else "Scrap Pending",
                "resolved_on": now_datetime() if open_qty <= 0.000001 else None,
                "resolved_by": frappe.session.user if open_qty <= 0.000001 else None})
    record("Rejected Material Disposed", card=doc.kanban_card, cycle=doc.kanban_cycle,
           qty=qty, reference_doctype="Stock Entry", reference_name=entry.name,
           notes=reason, system_generated=False)
    return reconcile_purchase_cycle(doc.kanban_cycle)


def short_close(cycle_name, qty, reason):
    _require_manager()
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if not (reason or "").strip():
        frappe.throw(_("A short-close reason is required"))
    qty = flt(qty)
    remaining = max(flt(cycle.ordered_purchase_qty) -
                    flt(cycle.usable_fulfilment_purchase_qty) -
                    flt(cycle.purchase_short_closed_qty), 0)
    if qty <= 0 or qty > remaining + 0.000001:
        frappe.throw(_("Short-close quantity must be greater than zero and no more than {0}")
                     .format(remaining))
    cycle.db_set("purchase_short_closed_qty", flt(cycle.purchase_short_closed_qty) + qty)
    record("Purchase Replenishment Short Closed", card=cycle.kanban_card,
           cycle=cycle.name, qty=qty, notes=reason, system_generated=False)
    return reconcile_purchase_cycle(cycle.name)


def _refresh_returned_dispositions(receipt):
    cycle_name = receipt_cycle(receipt)
    if cycle_name:
        _recalculate_disposition_returns(cycle_name)


def _recalculate_disposition_returns(cycle_name):
    dispositions = frappe.get_all(
        "CFG Kanban Receipt Disposition",
        filters={"kanban_cycle": cycle_name, "status": ["!=", "Cancelled"]},
        fields=["name", "purchase_receipt", "purchase_receipt_item", "rejected_qty",
                "approved_concession_qty", "disposed_qty", "disposition", "status"],
    )
    submitted_returns = frappe.get_all(
        "Purchase Receipt",
        filters={"cfg_kanban_cycle": cycle_name, "docstatus": 1, "is_return": 1},
        pluck="name",
    )
    for disposition in dispositions:
        if frappe.db.get_value("Purchase Receipt", disposition.purchase_receipt, "docstatus") != 1:
            frappe.db.set_value("CFG Kanban Receipt Disposition", disposition.name,
                                {"status": "Cancelled", "open_rejected_qty": 0})
            continue
        rows = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": ["in", submitted_returns or [""]],
                     "purchase_receipt_item": disposition.purchase_receipt_item},
            fields=["parent", "received_qty", "rejected_qty", "return_qty_from_rejected_warehouse"],
        )
        returned = 0.0
        latest_return = None
        for row in rows:
            qty = abs(flt(row.rejected_qty))
            if qty <= 0 and row.return_qty_from_rejected_warehouse:
                qty = abs(flt(row.received_qty))
            returned += qty
            if qty:
                latest_return = row.parent
        returned = min(returned, flt(disposition.rejected_qty))
        disposed = flt(disposition.disposed_qty)
        open_qty = max(flt(disposition.rejected_qty) - returned -
                       flt(disposition.approved_concession_qty) - disposed, 0)
        status = disposition.status
        if open_qty <= 0.000001:
            status = ("Replacement Pending" if disposition.disposition == "Supplier Replacement"
                      else "Resolved")
        elif status == "Resolved":
            status = DISPOSITION_STATUS.get(disposition.disposition, "Open")
        values = {"returned_rejected_qty": returned, "open_rejected_qty": open_qty,
                  "status": status}
        if latest_return:
            values.update({"resolution_doctype": "Purchase Receipt",
                           "resolution_document": latest_return})
        if status == "Resolved":
            values.update({"resolved_on": now_datetime(), "resolved_by": frappe.session.user})
        frappe.db.set_value("CFG Kanban Receipt Disposition", disposition.name, values)


def _sync_card(cycle, complete, unresolved, usable):
    if not cycle.kanban_card:
        return
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    if complete:
        if card.current_state in ("Purchase Ordered", "Partially Received", "Receipt Exception"):
            transition_card(card, "Received", event_type="Usable Purchase Quantity Completed",
                            cycle=cycle.name)
        if card.current_state == "Received":
            transition_card(card, "Available", event_type="Purchase Kanban Card Recycled",
                            cycle=cycle.name)
            card.db_set("active_cycle", None, update_modified=False)
            cycle.db_set("completed_on", now_datetime())
        return
    target = "Receipt Exception" if unresolved else ("Partially Received" if usable else "Purchase Ordered")
    if card.current_state != target:
        transition_card(card, target, event_type="Purchase Receipt Usable Quantity Updated",
                        cycle=cycle.name)


def _require_manager():
    if not set(MANAGER_ROLES).intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw(_("A Purchase, Stock, Manufacturing, or System Manager role is required"),
                     frappe.PermissionError)

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event


def cancel_and_rollback(signal_name, reason):
    """Cancel an accidental signal and reverse only activity-free ERP documents."""
    if not (reason or "").strip():
        frappe.throw("Cancellation reason is required")
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    if signal.get("sales_demand"):
        frappe.throw(
            "This Signal belongs to a Sales Order demand. Cancel it through the Sales Demand workflow."
        )

    cycle = frappe.get_doc("CFG Kanban Cycle", signal.kanban_cycle)
    if cycle.status == "Completed":
        frappe.throw(f"Cycle {cycle.name} is already {cycle.status}")
    work_order_name = cycle.work_order or (
        signal.erp_reference_name if signal.erp_reference_doctype == "Work Order" else None
    )
    _assert_no_purchase_activity(cycle)
    _cancel_transfer_manifest(cycle, signal, reason)
    _assert_no_production_activity(cycle, work_order_name)
    if work_order_name and frappe.db.exists("Work Order", work_order_name):
        work_order = frappe.get_doc("Work Order", work_order_name)
        if work_order.docstatus == 0:
            frappe.delete_doc("Work Order", work_order.name, ignore_permissions=True, ignore_links=True)
            cycle.db_set("work_order", None, update_modified=False)
            signal.db_set({"erp_reference_doctype": None, "erp_reference_name": None},
                          update_modified=False)
        elif work_order.docstatus == 1:
            work_order.flags.ignore_permissions = True
            work_order.cancel()
    material_request_name = cycle.get("material_request")
    if material_request_name and frappe.db.exists("Material Request", material_request_name):
        request = frappe.get_doc("Material Request", material_request_name)
        if request.docstatus == 0:
            frappe.delete_doc("Material Request", request.name, ignore_permissions=True,
                              ignore_links=True)
        elif request.docstatus == 1:
            request.flags.ignore_permissions = True
            request.cancel()
        cycle.db_set("material_request", None, update_modified=False)

    previous_cycle_state = cycle.status
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card) if cycle.kanban_card else None
    previous_card_state = card.current_state if card else None
    cycle.db_set({
        "status": "Cancelled", "completed_on": now_datetime(), "blocked": 0,
        "remarks": ((cycle.remarks or "") + f"\nSignal rollback: {reason}").strip(),
    })
    signal.db_set({
        "status": "Cancelled", "cancelled_on": now_datetime(),
        "cancelled_by": frappe.session.user, "cancellation_reason": reason.strip(),
    }, update_modified=True)
    signal.reload()
    if signal.status != "Cancelled":
        frappe.throw(f"Signal rollback verification failed; {signal.name} is still {signal.status}")
    if card:
        card.db_set({
            "current_state": "Available", "active_cycle": None,
            "blocked": 0, "blocked_reason": None,
        }, update_modified=True)
        event = record(
            "Card Released after Signal Rollback", card=card.name, cycle=cycle.name,
            previous_state=previous_card_state, new_state="Available", notes=reason,
            system_generated=False,
        )
        card.db_set("last_event", event.name, update_modified=False)
    record(
        "Signal Cancelled and Rolled Back", card=cycle.kanban_card, cycle=cycle.name,
        previous_state=previous_cycle_state, new_state="Cancelled",
        reference_doctype="CFG Kanban Signal", reference_name=signal.name,
        notes=reason, system_generated=False,
    )
    return signal


def _assert_no_production_activity(cycle, work_order_name=None):
    if frappe.db.exists("CFG Kanban Operation Progress", {"kanban_cycle": cycle.name}):
        frappe.throw("This Signal cannot be rolled back because Kanban operation progress exists")
    if frappe.db.exists("CFG Kanban WIP Ledger", {"kanban_cycle": cycle.name}):
        frappe.throw("This Signal cannot be rolled back because WIP movement exists")
    if frappe.db.exists("Stock Entry", {"cfg_kanban_cycle": cycle.name, "docstatus": 1}):
        frappe.throw("This Signal cannot be rolled back because a submitted Stock Entry exists")
    if work_order_name and frappe.db.exists("Work Order", work_order_name):
        work_order = frappe.get_doc("Work Order", work_order_name)
        if flt(work_order.produced_qty) or flt(work_order.material_transferred_for_manufacturing):
            frappe.throw(
                "This Signal cannot be rolled back because the Work Order has production or material movement"
            )
        job_cards = frappe.get_all("Job Card", filters={"work_order": work_order.name}, pluck="name")
        if job_cards:
            if frappe.db.exists("Job Card", {"name": ["in", job_cards], "docstatus": 1}):
                frappe.throw("This Signal cannot be rolled back because a submitted Job Card exists")
            if frappe.db.exists("Job Card Time Log", {"parent": ["in", job_cards]}):
                frappe.throw("This Signal cannot be rolled back because Job Card time logs exist")


def _assert_no_purchase_activity(cycle):
    if not cycle.get("material_request") and not cycle.get("purchase_order"):
        return
    if frappe.db.exists("Purchase Receipt", {"cfg_kanban_cycle": cycle.name,
                                               "docstatus": 1}):
        frappe.throw("This Signal cannot be rolled back because a submitted Purchase Receipt exists")
    if cycle.get("purchase_order"):
        frappe.throw("This Signal has an effective Purchase Order. Cancel or close the ERPNext Purchase "
                     "Order first, then reconcile the Kanban Cycle; automatic rollback stops here to "
                     "protect purchasing history.")


def _cancel_transfer_manifest(cycle, signal, reason):
    manifest_name = cycle.get("movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if manifest.state == "Cancelled":
        return
    if manifest.state not in ("Draft", "Prepared"):
        frappe.throw(
            f"Transfer Manifest {manifest.name} is {manifest.state}. Use controlled logistics "
            "recovery; the Signal cannot be rolled back automatically."
        )
    if (manifest.dispatch_delivery_note or manifest.receipt_purchase_receipt
            or manifest.dispatch_stock_entry or manifest.receipt_stock_entry):
        frappe.throw(
            f"Transfer Manifest {manifest.name} already has an ERP document and requires "
            "controlled logistics recovery."
        )
    if manifest.state == "Prepared":
        for line in manifest.lines:
            if not line.handling_unit:
                continue
            unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
            if not flt(unit.reserved_qty):
                continue
            post_quantity_event(
                event_type="Unreserve",
                qty=min(flt(line.dispatch_qty), flt(unit.reserved_qty)),
                stock_uom=line.stock_uom,
                idempotency_key=canonical_key(
                    "signal-transfer-cancel-unreserve", signal.name, line.name
                ),
                source_handling_unit=line.handling_unit,
                item_code=line.item_code,
                batch_no=line.batch_no,
                source_company=manifest.source_company,
                source_warehouse=manifest.source_warehouse,
                reference_doctype=signal.doctype,
                reference_name=signal.name,
                reason=reason,
            )
    manifest.db_set({
        "state": "Cancelled",
        "cancelled_on": now_datetime(),
        "cancellation_reason": reason,
    }, update_modified=True)
    cycle.db_set("transfer_status", "Cancelled", update_modified=False)
    frappe.db.set_value(
        "CFG Kanban Manifest Line", {"parent": manifest.name}, "state", "Cancelled",
        update_modified=False,
    )

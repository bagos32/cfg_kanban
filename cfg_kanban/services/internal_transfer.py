import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.state_machine import set_cycle_state, transition_card
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


def create_transfer_manifest(signal_name):
    """Release one Transfer Kanban signal into the shared Logistics Panel."""
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    cycle = frappe.get_doc("CFG Kanban Cycle", signal.kanban_cycle)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type != "Transfer":
        frappe.throw("Only a Transfer Kanban Master can create an internal Movement Manifest")
    if cycle.get("movement_manifest"):
        return frappe.get_doc("CFG Kanban Movement Manifest", cycle.movement_manifest)
    route = frappe.get_doc("CFG Kanban Logistics Route", master.logistics_route)
    if not route.active or route.route_type != "Internal Warehouse Transfer":
        frappe.throw("The configured Internal Logistics Route is inactive or has the wrong type")
    if (route.source_company, route.source_warehouse, route.destination_company,
            route.destination_warehouse) != (
            master.company, master.source_warehouse, master.company,
            master.destination_warehouse):
        frappe.throw("The Internal Logistics Route no longer matches the Transfer Kanban Master")

    key = canonical_key("transfer-kanban-manifest", cycle.name, route.name)
    existing = frappe.db.get_value(
        "CFG Kanban Movement Manifest", {"preparation_key": key}, "name"
    )
    if existing:
        manifest = frappe.get_doc("CFG Kanban Movement Manifest", existing)
    else:
        manifest = frappe.get_doc({
            "doctype": "CFG Kanban Movement Manifest",
            "logistics_route": route.name,
            "kanban_cycle": cycle.name,
            "source_signal": signal.name,
            "state": "Draft",
            "preparation_key": key,
            "inventory_control_mode": (
                "ERP Stock" if frappe.db.get_value("Item", master.item_code, "is_stock_item")
                else "Kanban Operational Inventory"
            ),
        })
        policy = effective_trace_policy(master.item_code, master.company)
        maintains_stock = bool(frappe.db.get_value("Item", master.item_code, "is_stock_item"))
        if maintains_stock and (policy.get("warehouse_transfer_tag_policy") or NO_TAG) == NO_TAG:
            manifest.append("lines", {
                "line_kind": "ERP Stock without Physical Tag",
                "visible_code": "ERP STOCK",
                "item_code": master.item_code,
                "stock_uom": master.stock_uom,
                "available_qty_at_scan": cycle.planned_qty,
                "dispatch_qty": cycle.planned_qty,
                "received_qty": 0,
                "source_company": master.company,
                "source_warehouse": master.source_warehouse,
                "destination_company": master.company,
                "destination_warehouse": master.destination_warehouse,
                "state": "Prepared",
            })
        manifest.insert(ignore_permissions=True)

    cycle.db_set({
        "logistics_route": route.name,
        "movement_manifest": manifest.name,
        "transfer_status": "Requested",
    }, update_modified=True)
    set_cycle_state(cycle, "Transfer Requested", event_type="Internal Transfer Requested",
                    reference_doctype=manifest.doctype, reference_name=manifest.name)
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.current_state == "Signal Created":
            transition_card(card, "Replenishment Requested",
                            event_type="Internal Transfer Released", cycle=cycle.name)
    signal.db_set({
        "status": "Executing",
        "erp_reference_doctype": manifest.doctype,
        "erp_reference_name": manifest.name,
    }, update_modified=True)
    record("Internal Transfer Manifest Created", card=cycle.kanban_card,
           cycle=cycle.name, movement_manifest=manifest.name,
           reference_doctype=manifest.doctype, reference_name=manifest.name,
           qty=cycle.planned_qty)
    return manifest


def complete_transfer_cycle(manifest, reference_doctype, reference_name):
    if not manifest.kanban_cycle:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
    cycle.db_set({"transfer_status": "Completed", "completed_on": now_datetime()},
                 update_modified=True)
    set_cycle_state(cycle, "Completed", event_type="Internal Transfer Completed",
                    reference_doctype=reference_doctype, reference_name=reference_name)
    if manifest.source_signal:
        frappe.db.set_value("CFG Kanban Signal", manifest.source_signal, {
            "status": "Completed",
            "erp_reference_doctype": reference_doctype,
            "erp_reference_name": reference_name,
        }, update_modified=True)
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.current_state in ("Replenishment Requested", "In Transit"):
            if card.current_state == "Replenishment Requested":
                transition_card(card, "Received", event_type="Internal Stock Received",
                                cycle=cycle.name)
            else:
                transition_card(card, "Available", event_type="Internal Transfer Card Recycled",
                                cycle=cycle.name)
        if card.current_state == "Received":
            transition_card(card, "Available", event_type="Internal Transfer Card Recycled",
                            cycle=cycle.name)
        card.db_set("active_cycle", None, update_modified=False)


def mark_transfer_in_transit(manifest, stock_entry):
    if not manifest.kanban_cycle:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
    cycle.db_set({
        "transfer_dispatch_stock_entry": stock_entry.name,
        "transfer_status": "In Transit",
    }, update_modified=True)
    set_cycle_state(cycle, "In Transit", event_type="Internal Transfer Dispatched",
                    reference_doctype="Stock Entry", reference_name=stock_entry.name)
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.current_state == "Replenishment Requested":
            transition_card(card, "In Transit", event_type="Internal Transfer Dispatched",
                            cycle=cycle.name)

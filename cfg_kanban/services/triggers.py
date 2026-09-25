import frappe
from frappe.utils import now_datetime

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.state_machine import transition_card
from cfg_kanban.services.process_tasks import ensure_tasks, evaluate_gate
from cfg_kanban.services.purchase_replenishment import create_material_request_command


def consume_card(card_name, *, device_id=None, event_token=None, trusted_operator=False):
    """Create exactly one replenishment chain for a card's active-cycle window."""
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if not card.active or card.blocked:
        frappe.throw("Kanban card is inactive or blocked")
    if card.active_cycle:
        return {"duplicate": True, "cycle": card.active_cycle,
                "signal": frappe.db.get_value("CFG Kanban Signal", {"kanban_cycle": card.active_cycle}, "name")}

    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    event_key = canonical_key("consume-card", card.name, event_token or card.modified)
    existing = frappe.db.get_value("CFG Kanban Signal", {"idempotency_key": event_key}, ["name", "kanban_cycle"], as_dict=True)
    if existing:
        return {"duplicate": True, "cycle": existing.kanban_cycle, "signal": existing.name}

    transition_card(card, "Consumed", event_type="Card Scanned", notes=f"Device: {device_id or 'unknown'}")
    cycle = frappe.get_doc({
        "doctype": "CFG Kanban Cycle", "kanban_master": master.name, "kanban_card": card.name,
        "item_code": master.item_code, "planned_qty": card.kanban_qty or master.replenishment_qty,
        "stock_uom": master.stock_uom, "status": "New", "priority": master.default_priority,
        "source_warehouse": master.source_warehouse, "destination_warehouse": master.destination_warehouse,
    }).insert(ignore_permissions=trusted_operator)
    card.db_set("active_cycle", cycle.name)
    ensure_tasks(cycle.name)
    cycle_start_gate = evaluate_gate(cycle.name, "Before Cycle Start")
    automatic_release = master.automation_level == "Automatic" and cycle_start_gate["open"]
    signal_type = ("Purchase Replenishment" if master.control_type == "Purchase Replenishment"
                   else "Production Replenishment")
    signal, created = insert_once(frappe.get_doc({
        "doctype": "CFG Kanban Signal", "signal_type": signal_type,
        "kanban_master": master.name, "kanban_card": card.name, "kanban_cycle": cycle.name,
        "item_code": master.item_code, "requested_qty": cycle.planned_qty, "stock_uom": master.stock_uom,
        "status": "Validated" if automatic_release else "Waiting Approval",
        "priority": master.default_priority, "automation_level": master.automation_level,
        "requested_on": now_datetime(), "validated_on": now_datetime(),
    }), event_key, ignore_permissions=trusted_operator)
    cycle.db_set({"signal": signal.name, "status": "Signalled"})
    transition_card(card, "Signal Created", event_type="Signal Created", cycle=cycle.name)
    if created and automatic_release:
        command = (create_material_request_command(signal.name)
                   if master.control_type == "Purchase Replenishment"
                   else create_work_order_command(signal.name))
        execute_command(command.name)
    return {"duplicate": not created, "cycle": cycle.name, "signal": signal.name}


def create_work_order_command(signal_name):
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if signal.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", signal.kanban_card)
        if card.current_state == "Signal Created":
            transition_card(
                card,
                "Replenishment Requested",
                event_type="Replenishment Requested",
                cycle=signal.kanban_cycle,
            )
    key = canonical_key("command", signal.name, "Create Work Order")
    command, _ = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Work Order", "source_signal": signal.name,
        "kanban_cycle": signal.kanban_cycle, "status": "Pending", "target_doctype": "Work Order",
        "request_payload": frappe.as_json({"production_item": master.item_code, "bom_no": master.bom,
            "qty": signal.requested_qty, "company": master.company,
            "source_warehouse": master.source_warehouse, "wip_warehouse": master.wip_warehouse,
            "fg_warehouse": master.destination_warehouse}), "requested_on": now_datetime(),
        "created_by_system": 1,
    }), key)
    signal.db_set({"command": command.name, "status": "Executing"})
    record("ERP Command Created", card=signal.kanban_card, cycle=signal.kanban_cycle,
           reference_doctype=command.doctype, reference_name=command.name)
    return command

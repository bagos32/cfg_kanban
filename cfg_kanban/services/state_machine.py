import frappe
from frappe import _

from cfg_kanban.services.events import record


CARD_TRANSITIONS = {
    "Available": {"Consumed", "Inactive", "Blocked"},
    "Consumed": {"Signal Created", "Production Released", "Blocked"},
    "Signal Created": {"Replenishment Requested", "Blocked"},
    "Replenishment Requested": {"Production Released", "Purchase Ordered", "Partially Received", "Received", "Blocked"},
    "Purchase Ordered": {"Partially Received", "Received", "Blocked"},
    "Partially Received": {"Purchase Ordered", "Received", "Blocked"},
    "Received": {"Available", "Blocked"},
    "Production Released": {"In Production", "Blocked"},
    "In Production": {"Produced", "Blocked"},
    "Produced": {"In Transit", "Available", "Blocked"},
    "In Transit": {"Available", "Blocked"},
    "Blocked": {"Available", "Consumed", "Signal Created", "Replenishment Requested", "Purchase Ordered", "Partially Received", "Production Released", "In Production"},
}


def transition_card(card, new_state, *, event_type, cycle=None, notes=None):
    card = frappe.get_doc("CFG Kanban Card", card) if isinstance(card, str) else card
    previous = card.current_state
    if new_state == previous:
        return card
    if new_state not in CARD_TRANSITIONS.get(previous, set()):
        frappe.throw(_("Card cannot move from {0} to {1}").format(previous, new_state))
    card.db_set("current_state", new_state, update_modified=True)
    event = record(event_type, card=card.name, cycle=cycle or card.active_cycle,
                   previous_state=previous, new_state=new_state, notes=notes)
    card.db_set("last_event", event.name, update_modified=False)
    return card


def set_cycle_state(cycle, status, *, event_type, reference_doctype=None, reference_name=None):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle) if isinstance(cycle, str) else cycle
    previous = cycle.status
    if previous == status:
        return cycle
    cycle.db_set("status", status, update_modified=True)
    record(event_type, card=cycle.kanban_card, cycle=cycle.name, previous_state=previous,
           new_state=status, reference_doctype=reference_doctype, reference_name=reference_name)
    return cycle

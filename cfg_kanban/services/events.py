import frappe
from frappe.utils import now_datetime


def record(event_type, *, card=None, cycle=None, execution=None, qty=0, previous_state=None,
           new_state=None, reference_doctype=None, reference_name=None, device_id=None,
           notes=None, system_generated=True):
    event = frappe.get_doc({
        "doctype": "CFG Kanban Event",
        "event_type": event_type,
        "event_datetime": now_datetime(),
        "kanban_card": card,
        "kanban_cycle": cycle,
        "process_execution": execution,
        "user": frappe.session.user,
        "previous_state": previous_state,
        "new_state": new_state,
        "qty": qty or 0,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "device_id": device_id,
        "notes": notes,
        "system_generated": system_generated,
    }).insert(ignore_permissions=system_generated)
    return event


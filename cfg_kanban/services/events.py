import frappe
from frappe.utils import now_datetime


def record(event_type, *, card=None, cycle=None, execution=None, process_task=None,
           standalone_task=None, movement_manifest=None, delivery_session=None,
           return_case=None, route_reconciliation=None, handling_unit=None,
           qty=0, previous_state=None,
           new_state=None, reference_doctype=None, reference_name=None, device_id=None,
           notes=None, system_generated=True, operator=None, operator_session=None,
           terminal_user=None):
    event = frappe.get_doc({
        "doctype": "CFG Kanban Event",
        "event_type": event_type,
        "event_datetime": now_datetime(),
        "kanban_card": card,
        "kanban_cycle": cycle,
        "process_execution": execution,
        "process_task": process_task,
        "standalone_task": standalone_task,
        "movement_manifest": movement_manifest,
        "delivery_session": delivery_session,
        "return_case": return_case,
        "route_reconciliation": route_reconciliation,
        "handling_unit": handling_unit,
        "user": terminal_user or frappe.session.user,
        "operator": operator,
        "operator_session": operator_session,
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

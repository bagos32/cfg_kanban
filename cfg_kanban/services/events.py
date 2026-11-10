import json

import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.idempotency import insert_once


def record(event_type, *, card=None, cycle=None, execution=None, process_task=None,
           standalone_task=None, movement_manifest=None, delivery_session=None,
           return_case=None, route_reconciliation=None, handling_unit=None,
           action_run=None,
           qty=0, previous_state=None,
           new_state=None, reference_doctype=None, reference_name=None, device_id=None,
           notes=None, system_generated=True, operator=None, operator_session=None,
           terminal_user=None, ignore_permissions=None, observed_on=None,
           input_source=None, source_event_id=None, idempotency_key=None,
           work_order=None, job_card=None, operation=None, workstation=None,
           material_item=None, material_batch=None, output_serial_boundary=None,
           payload=None):
    event = frappe.get_doc({
        "doctype": "CFG Kanban Event",
        "event_type": event_type,
        "event_datetime": observed_on or now_datetime(),
        "received_on": now_datetime(),
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
        "action_run": action_run,
        "user": terminal_user or frappe.session.user,
        "operator": operator,
        "operator_session": operator_session,
        "previous_state": previous_state,
        "new_state": new_state,
        "qty": qty or 0,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "device_id": device_id,
        "input_source": input_source,
        "source_event_id": source_event_id,
        "work_order": work_order,
        "job_card": job_card,
        "operation": operation,
        "workstation": workstation,
        "material_item": material_item,
        "material_batch": material_batch,
        "output_serial_boundary": output_serial_boundary,
        "payload_json": (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            if payload is not None else None
        ),
        "notes": notes,
        "system_generated": system_generated,
    })
    bypass = system_generated if ignore_permissions is None else ignore_permissions
    if idempotency_key:
        event, _created = insert_once(event, idempotency_key, ignore_permissions=bypass)
    else:
        event.insert(ignore_permissions=bypass)
    return event

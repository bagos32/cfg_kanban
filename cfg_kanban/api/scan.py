import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.progress import report
from cfg_kanban.services.triggers import consume_card
from cfg_kanban.services.events import record
from cfg_kanban.services.wip import append_entry


@frappe.whitelist()
def scan(token, action="consume", device_id=None, event_token=None, payload=None):
    card_name = frappe.db.get_value("CFG Kanban Card", {"qr_code": token, "active": 1}, "name")
    if not card_name:
        frappe.throw("Unknown or inactive Kanban card")
    frappe.db.set_value("CFG Kanban Card", card_name, "last_scan_time", now_datetime())
    if action == "consume":
        return consume_card(card_name, device_id=device_id, event_token=event_token)
    if action == "physical_handoff":
        data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
        execution = frappe.get_doc("CFG Kanban Process Execution", data.get("execution"))
        if execution.handoff_mode != "Physical Card Handoff":
            frappe.throw("Execution is not configured for physical-card handoff")
        qty = data.get("qty") or execution.good_qty
        entry = append_entry(execution.kanban_cycle, "Released", qty,
            source_execution=execution.name, destination_execution=execution.destination_execution,
            source_progress=None, notes=f"Physical card scan {card_name}")
        record("Physical Card Handoff", card=card_name, cycle=execution.kanban_cycle,
            execution=execution.name, qty=qty, device_id=device_id,
            reference_doctype=entry.doctype, reference_name=entry.name)
        return {"ledger_entry": entry.name, "cycle": execution.kanban_cycle, "qty": qty}
    frappe.throw("Unsupported scan action")


@frappe.whitelist()
def report_progress(execution, good_qty, reject_qty=0, processed_qty=None, values=None,
                    event_token=None, notes=None):
    # Clients should retain event_token across retries. Progress-level unique keys are planned
    # before production rollout; duplicate protection currently relies on the request boundary.
    values = frappe.parse_json(values) if isinstance(values, str) else values
    return report(execution, good_qty, reject_qty, processed_qty, values=values, notes=notes).as_dict()

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.operation_summary import recalculate, refresh_destination
from cfg_kanban.services.runtime_selector import preview as preview_runtime_card
from cfg_kanban.services.progress import report
from cfg_kanban.services.triggers import consume_card
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.wip import append_entry


@frappe.whitelist()
def scan(token, action="consume", device_id=None, event_token=None, payload=None):
    card_name = frappe.db.get_value("CFG Kanban Card", {"qr_code": token, "active": 1}, "name")
    if not card_name:
        frappe.throw("Unknown or inactive Kanban card")
    frappe.db.set_value("CFG Kanban Card", card_name, "last_scan_time", now_datetime())
    if action == "consume":
        card_type = frappe.db.get_value("CFG Kanban Card", card_name, "card_type")
        if card_type in ("Process Kanban", "Station Kanban"):
            return {"requires_confirmation": True, "proposal": preview_runtime_card(card_name)}
        return consume_card(card_name, device_id=device_id, event_token=event_token)
    if action == "physical_handoff":
        data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
        execution = frappe.get_doc("CFG Kanban Process Execution", data.get("execution"))
        if execution.handoff_mode != "Physical Card Handoff":
            frappe.throw("Execution is not configured for physical-card handoff")
        key = canonical_key("physical-handoff", execution.name, event_token or "")
        if event_token:
            existing = frappe.db.get_value("CFG Kanban Event", {"device_id": key}, "reference_name")
            if existing:
                return {"ledger_entry": existing, "cycle": execution.kanban_cycle,
                        "duplicate": True}
        remaining = max(0, flt(execution.good_qty) - flt(execution.released_qty))
        qty = flt(data.get("qty") or remaining)
        if qty <= 0 or qty > remaining:
            frappe.throw(f"Physical handoff quantity must be between 0 and unreleased good quantity {remaining}")
        entry = append_entry(execution.kanban_cycle, "Released", qty,
            source_execution=execution.name, source_operation=execution.operation,
            destination_operation=execution.destination_operation,
            source_progress=None, notes=f"Physical card scan {card_name}")
        execution.db_set("released_qty", flt(execution.released_qty) + flt(qty))
        recalculate(execution.kanban_cycle, execution.operation)
        refresh_destination(execution.kanban_cycle, execution.operation,
                            execution.destination_operation)
        record("Physical Card Handoff", card=card_name, cycle=execution.kanban_cycle,
            execution=execution.name, qty=qty, device_id=device_id,
            reference_doctype=entry.doctype, reference_name=entry.name)
        if event_token:
            frappe.db.set_value("CFG Kanban Event", {"reference_doctype": entry.doctype,
                "reference_name": entry.name, "event_type": "Physical Card Handoff"},
                "device_id", key)
        return {"ledger_entry": entry.name, "cycle": execution.kanban_cycle, "qty": qty}
    frappe.throw("Unsupported scan action")


@frappe.whitelist()
def report_progress(execution, good_qty, reject_qty=0, processed_qty=None, values=None,
                    event_token=None, notes=None):
    # Clients should retain event_token across retries. Progress-level unique keys are planned
    # before production rollout; duplicate protection currently relies on the request boundary.
    values = frappe.parse_json(values) if isinstance(values, str) else values
    return report(execution, good_qty, reject_qty, processed_qty, values=values, notes=notes).as_dict()


@frappe.whitelist()
def scan_handling_unit(token, action, device_id=None, event_token=None, reason=None):
    name = frappe.db.get_value("CFG Kanban Handling Unit", {"opaque_token": token}, "name")
    if not name:
        frappe.throw("Unknown handling-unit tag")
    unit = frappe.get_doc("CFG Kanban Handling Unit", name)
    unit.check_permission("write")
    if unit.state in ("Received", "Void", "Replaced"):
        return {"name": unit.name, "state": unit.state, "terminal": True, "changed": False}
    target = {"attach": "Attached", "dispatch": "Dispatched", "receive": "Received",
              "void": "Void"}.get(action)
    if not target:
        frappe.throw("Unsupported handling-unit scan action")
    allowed = {"Issued": {"Attached", "Void"}, "Attached": {"Dispatched", "Void"},
               "Dispatched": {"Received", "Void"}}
    if target not in allowed.get(unit.state, set()):
        frappe.throw(f"Handling unit cannot move from {unit.state} to {target}")
    key = canonical_key("handling-unit-scan", unit.name, action,
                        event_token or f"{unit.state}:{target}")
    existing = frappe.db.get_value("CFG Kanban Event", {"device_id": key}, "name")
    if existing:
        return {"name": unit.name, "state": unit.state, "terminal": False, "changed": False}
    previous = unit.state
    values = {"state": target, "last_scan_time": now_datetime()}
    if target == "Void":
        values["void_reason"] = reason or "Voided by scan"
    unit.db_set(values, update_modified=True)
    event = record(f"Handling Unit {target}", card=unit.kanban_card, cycle=unit.kanban_cycle,
                   previous_state=previous, new_state=target,
                   reference_doctype=unit.doctype, reference_name=unit.name,
                   device_id=key, notes=reason, system_generated=False)
    return {"name": unit.name, "state": target, "event": event.name,
            "terminal": target in ("Received", "Void"), "changed": True}

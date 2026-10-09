import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.integrations.erp_gateway import (
    build_withdrawal_stock_entry,
    execute_command,
    get_required_erp_inputs,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.logistics_foundation import (
    assert_erp_stock,
    post_quantity_event,
    resolve_logistics_scan,
)
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.state_machine import set_cycle_state, transition_card
from cfg_kanban.services.trace_policy import NO_TAG, effective_trace_policy


WITHDRAWAL_RESPONSIBILITY = "Stock Withdrawal"
TOLERANCE = 0.000001


def release_withdrawal(signal_name):
    signal = frappe.get_doc("CFG Kanban Signal", signal_name)
    cycle = frappe.get_doc("CFG Kanban Cycle", signal.kanban_cycle)
    master = frappe.get_doc("CFG Kanban Master", signal.kanban_master)
    if master.control_type != "Withdrawal":
        frappe.throw("Only a Withdrawal Kanban Master can release stock withdrawal")
    policy = effective_trace_policy(master.item_code, master.company)
    tag_policy = policy.get("stock_withdrawal_tag_policy") or NO_TAG
    if not cycle.withdrawal_status:
        cycle.db_set({
            "withdrawal_status": "Requested",
            "withdrawal_reason": master.withdrawal_reason,
            "withdrawal_tag_policy": tag_policy,
        }, update_modified=True)
        if tag_policy == NO_TAG:
            cycle.append("withdrawal_allocations", _untagged_row(cycle))
            cycle.save(ignore_permissions=True)
        set_cycle_state(cycle, "Withdrawal Requested", event_type="Stock Withdrawal Requested")
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.current_state == "Signal Created":
            transition_card(card, "Withdrawal Requested", event_type="Stock Withdrawal Released",
                            cycle=cycle.name)
    signal.db_set("status", "Executing", update_modified=True)
    record("Stock Withdrawal Released", card=cycle.kanban_card, cycle=cycle.name,
           qty=cycle.planned_qty, reference_doctype=cycle.doctype,
           reference_name=cycle.name)
    return cycle


@frappe.whitelist()
def get_withdrawal(cycle_name, operator_session_token):
    profile, session = require_operator(operator_session_token)
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Withdrawal":
        frappe.throw("Cycle is not a controlled stock withdrawal")
    result = cycle.as_dict()
    result["card_number"] = (frappe.db.get_value(
        "CFG Kanban Card", cycle.kanban_card, "card_number"
    ) if cycle.kanban_card else None)
    result["selected_qty"] = sum(flt(row.qty) for row in cycle.withdrawal_allocations)
    result["remaining_qty"] = max(flt(cycle.planned_qty) - result["selected_qty"], 0)
    result["can_use_untagged_stock"] = bool(
        cycle.withdrawal_status == "Requested"
        and not cycle.withdrawal_allocations
        and cycle.withdrawal_tag_policy != "Required Physical Tag"
    )
    result["can_edit_selection"] = cycle.withdrawal_status == "Requested"
    result["can_prepare"] = bool(
        cycle.withdrawal_status == "Requested"
        and abs(result["selected_qty"] - flt(cycle.planned_qty)) <= TOLERANCE
    )
    result["can_confirm"] = cycle.withdrawal_status in ("Prepared", "Exception")
    result["stock_entry_status"] = _stock_entry_status(cycle.withdrawal_stock_entry)
    result["can_discard_draft"] = bool(
        profile.get("can_override") and result["stock_entry_status"]
        and result["stock_entry_status"].docstatus == 0
    )
    result["operator"] = {
        "employee": profile.employee,
        "employee_name": frappe.db.get_value("Employee", profile.employee, "employee_name")
                         or profile.employee,
        "session": session.name,
    }
    return result


@frappe.whitelist()
def select_untagged_stock(cycle_name, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status != "Requested" or cycle.withdrawal_allocations:
        frappe.throw("Untagged stock must be selected before adding any Stock Tags")
    if cycle.withdrawal_tag_policy == "Required Physical Tag":
        frappe.throw("This Item requires physical Stock Tags for withdrawal")
    _assert_untagged_allowed(cycle.item_code)
    key = canonical_key("withdrawal-untagged", cycle.name, event_token or "")
    cycle.append("withdrawal_allocations", {**_untagged_row(cycle), "scan_event_key": key})
    cycle.save(ignore_permissions=True)
    record("Untagged Withdrawal Stock Selected", card=cycle.kanban_card, cycle=cycle.name,
           qty=cycle.planned_qty, device_id=key, reference_doctype=cycle.doctype,
           reference_name=cycle.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)
    return get_withdrawal(cycle.name, operator_session_token)


@frappe.whitelist()
def add_withdrawal_tag(cycle_name, scan_value, qty, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status != "Requested":
        frappe.throw("Stock Tags can be selected only while withdrawal is Requested")
    if cycle.withdrawal_tag_policy == NO_TAG:
        frappe.throw("This withdrawal uses ordinary ERP stock without physical tags")
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Stock Tag Handling Unit")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    _validate_unit(cycle, unit)
    if any(row.handling_unit == unit.name for row in cycle.withdrawal_allocations):
        return get_withdrawal(cycle.name, operator_session_token)
    selected = sum(flt(row.qty) for row in cycle.withdrawal_allocations)
    remaining = flt(cycle.planned_qty) - selected
    requested = flt(qty or min(flt(unit.available_qty), remaining))
    if requested <= 0 or requested > remaining + TOLERANCE:
        frappe.throw(f"Withdrawal Tag quantity must be between 0 and remaining quantity {remaining}")
    if requested > flt(unit.available_qty) + TOLERANCE:
        frappe.throw(f"Stock Tag {unit.handling_unit_id} has only {unit.available_qty} available")
    policy = effective_trace_policy(cycle.item_code, cycle.company)
    if (requested < flt(unit.available_qty) - TOLERANCE
            and not cint(policy.get("allow_partial_tag_quantity"))):
        frappe.throw("This Item policy does not allow partial quantity from one Stock Tag")
    key = canonical_key("withdrawal-tag", cycle.name, unit.name, event_token or "")
    cycle.append("withdrawal_allocations", {
        "line_kind": "Tagged Stock", "handling_unit": unit.name,
        "visible_code": unit.handling_unit_id, "item_code": unit.item_code,
        "batch_no": unit.batch_no, "qty": requested, "stock_uom": unit.stock_uom,
        "state": "Selected", "scan_event_key": key,
    })
    cycle.save(ignore_permissions=True)
    record("Withdrawal Stock Tag Selected", card=cycle.kanban_card, cycle=cycle.name,
           handling_unit=unit.name, qty=requested, device_id=key,
           reference_doctype=unit.doctype, reference_name=unit.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_withdrawal(cycle.name, operator_session_token)


@frappe.whitelist()
def remove_withdrawal_tag(cycle_name, handling_unit, operator_session_token, event_token=None):
    profile, _session = require_operator(operator_session_token, "start")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status != "Requested":
        frappe.throw("Withdrawal selection cannot be changed after preparation")
    row = next((row for row in cycle.withdrawal_allocations
                if row.handling_unit == handling_unit), None)
    if row:
        cycle.remove(row)
        cycle.save(ignore_permissions=True)
    return get_withdrawal(cycle.name, operator_session_token)


@frappe.whitelist()
def prepare_withdrawal(cycle_name, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status == "Prepared":
        return get_withdrawal(cycle.name, operator_session_token)
    if cycle.withdrawal_status != "Requested" or not cycle.withdrawal_allocations:
        frappe.throw("Withdrawal must be Requested with selected stock before preparation")
    total = sum(flt(row.qty) for row in cycle.withdrawal_allocations)
    if abs(total - flt(cycle.planned_qty)) > TOLERANCE:
        frappe.throw(f"Selected quantity {total} must equal Card quantity {cycle.planned_qty}")
    for row in cycle.withdrawal_allocations:
        if row.line_kind == "ERP Stock without Physical Tag":
            _assert_untagged_stock(cycle.item_code, cycle.source_warehouse, row.qty)
            continue
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        _validate_unit(cycle, unit)
        assert_erp_stock(unit, cycle.source_warehouse, row.qty)
        ledger = post_quantity_event(
            event_type="Reserve", qty=row.qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key("withdrawal-reserve", cycle.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=cycle.company,
            source_warehouse=cycle.source_warehouse, reference_doctype=cycle.doctype,
            reference_name=cycle.name, operator=profile.employee,
            operator_session=session.name, reason=cycle.withdrawal_reason,
        )
        row.reserved_ledger = ledger.name
        row.state = "Reserved"
    cycle.withdrawal_status = "Prepared"
    cycle.save(ignore_permissions=True)
    set_cycle_state(cycle, "Withdrawal Prepared", event_type="Stock Withdrawal Prepared")
    record("Stock Withdrawal Prepared", card=cycle.kanban_card, cycle=cycle.name,
           qty=cycle.planned_qty, device_id=canonical_key(
               "withdrawal-prepare", cycle.name, event_token or ""
           ), reference_doctype=cycle.doctype, reference_name=cycle.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_withdrawal(cycle.name, operator_session_token)


@frappe.whitelist()
def get_withdrawal_requirements(cycle_name, operator_session_token):
    profile, _session = require_operator(operator_session_token, "complete")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status not in ("Prepared", "Exception"):
        frappe.throw(f"Withdrawal cannot post while it is {cycle.withdrawal_status}")
    entry = build_withdrawal_stock_entry(cycle, _withdrawal_payload(cycle))
    return {"doctype": "Stock Entry", "fields": get_required_erp_inputs(entry)}


@frappe.whitelist()
def confirm_withdrawal(cycle_name, event_token, operator_session_token,
                       required_erp_inputs=None):
    profile, session = require_operator(operator_session_token, "complete")
    _require_responsibility(profile)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if cycle.withdrawal_status not in ("Prepared", "Exception"):
        frappe.throw(f"Withdrawal cannot post while it is {cycle.withdrawal_status}")
    key = canonical_key("kanban-withdrawal", cycle.name)
    payload = _withdrawal_payload(cycle, required_erp_inputs)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command", "command_type": "Create Kanban Stock Withdrawal",
        "source_signal": cycle.signal, "kanban_cycle": cycle.name, "status": "Pending",
        "target_doctype": "Stock Entry", "request_payload": frappe.as_json(payload),
        "requested_by_operator": profile.employee, "operator_session": session.name,
        "terminal_user": session.terminal_user, "requested_on": now_datetime(),
        "created_by_system": 1,
    }), key, ignore_permissions=True)
    if not created:
        if command.status == "Completed" and command.target_document:
            return get_withdrawal(cycle.name, operator_session_token)
        if command.status not in ("Failed", "Pending"):
            frappe.throw(f"Withdrawal ERP Command is {command.status}; it cannot be retried")
        command.db_set({
            "status": "Pending", "request_payload": frappe.as_json(payload),
            "last_error": None, "requested_by_operator": profile.employee,
            "operator_session": session.name, "terminal_user": session.terminal_user,
            "requested_on": now_datetime(),
        }, update_modified=True)
    cycle.db_set({"withdrawal_command": command.name,
                  "withdrawal_status": "Document Pending"}, update_modified=True)
    set_cycle_state(cycle, "Withdrawal Document Pending",
                    event_type="Withdrawal Material Issue Requested")
    try:
        entry = execute_command(command.name)
    except Exception:
        cycle.db_set("withdrawal_status", "Exception", update_modified=True)
        raise
    if entry.docstatus == 0:
        cycle.db_set({"withdrawal_stock_entry": entry.name,
                      "withdrawal_status": "Document Pending"}, update_modified=True)
    return get_withdrawal(cycle.name, operator_session_token)


@frappe.whitelist()
def discard_withdrawal_draft(cycle_name, reason, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    _require_responsibility(profile)
    if not profile.get("can_override"):
        frappe.throw("Supervisor Override permission is required to discard a draft Material Issue")
    if not (reason or "").strip():
        frappe.throw("Draft discard reason is required")
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    entry_name = cycle.withdrawal_stock_entry
    if not entry_name or not frappe.db.exists("Stock Entry", entry_name):
        frappe.throw("Withdrawal Cycle has no Material Issue draft")
    entry = frappe.get_doc("Stock Entry", entry_name)
    if entry.docstatus != 0 or entry.get("cfg_withdrawal_cycle") != cycle.name:
        frappe.throw("Only the unused Draft Material Issue for this Cycle can be discarded")
    if cycle.withdrawal_command and frappe.db.exists("CFG ERP Command", cycle.withdrawal_command):
        frappe.db.set_value("CFG ERP Command", cycle.withdrawal_command, {
            "status": "Failed", "target_document": None,
            "completed_on": None,
            "last_error": f"Draft {entry.name} discarded: {reason.strip()}",
        }, update_modified=True)
    cycle.db_set("withdrawal_stock_entry", None, update_modified=False)
    frappe.delete_doc("Stock Entry", entry.name, ignore_permissions=True)
    cycle.db_set("withdrawal_status", "Prepared", update_modified=True)
    set_cycle_state(cycle, "Withdrawal Prepared",
                    event_type="Withdrawal Material Issue Draft Discarded")
    record(
        "Withdrawal Material Issue Draft Discarded", card=cycle.kanban_card,
        cycle=cycle.name, reference_doctype="Stock Entry", reference_name=entry.name,
        notes=reason.strip(), operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user, system_generated=False,
    )
    return get_withdrawal(cycle.name, operator_session_token)


def complete_withdrawal(doc):
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_withdrawal_cycle)
    if cycle.withdrawal_status == "Completed":
        return
    for row in cycle.withdrawal_allocations:
        if not row.handling_unit:
            row.state = "Consumed"
            continue
        ledger = post_quantity_event(
            event_type="Stock Withdrawal", qty=row.qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key("withdrawal-consume", cycle.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=cycle.company,
            source_warehouse=cycle.source_warehouse, reference_doctype="Stock Entry",
            reference_name=doc.name, reason=cycle.withdrawal_reason,
            release_reserved=True,
        )
        row.consumed_ledger = ledger.name
        row.state = "Consumed"
        if flt(frappe.db.get_value(
            "CFG Kanban Handling Unit", row.handling_unit, "current_qty"
        )) <= TOLERANCE:
            frappe.db.set_value("CFG Kanban Handling Unit", row.handling_unit, {
                "identity_state": "Empty", "movement_state": "Empty",
            }, update_modified=False)
    cycle.withdrawal_stock_entry = doc.name
    cycle.withdrawal_status = "Completed"
    cycle.completed_on = now_datetime()
    cycle.save(ignore_permissions=True)
    set_cycle_state(cycle, "Completed", event_type="Stock Withdrawal Completed",
                    reference_doctype="Stock Entry", reference_name=doc.name)
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "status": "Completed", "erp_reference_doctype": "Stock Entry",
            "erp_reference_name": doc.name,
        }, update_modified=True)
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.current_state == "Withdrawal Requested":
            transition_card(card, "Available", event_type="Withdrawal Card Recycled",
                            cycle=cycle.name)
        card.db_set("active_cycle", None, update_modified=False)
    record("Stock Withdrawal Posted", card=cycle.kanban_card, cycle=cycle.name,
           qty=cycle.planned_qty, reference_doctype="Stock Entry", reference_name=doc.name)


def validate_withdrawal_stock_entry(doc):
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_withdrawal_cycle)
    if cycle.withdrawal_stock_entry and cycle.withdrawal_stock_entry != doc.name:
        frappe.throw(
            f"Withdrawal Cycle {cycle.name} already uses Stock Entry "
            f"{cycle.withdrawal_stock_entry}"
        )
    if cycle.withdrawal_status != "Document Pending":
        frappe.throw(
            f"Withdrawal Cycle {cycle.name} is {cycle.withdrawal_status}; "
            "its Material Issue cannot be submitted"
        )
    if doc.company != cycle.company or doc.purpose != "Material Issue":
        frappe.throw("Controlled Withdrawal must remain a same-Company Material Issue")
    rows = {row.name: row for row in cycle.withdrawal_allocations}
    if len(doc.items) != len(rows):
        frappe.throw("Material Issue rows must match the controlled Withdrawal selection")
    seen = set()
    for item in doc.items:
        allocation = rows.get(item.get("cfg_withdrawal_allocation"))
        if not allocation or allocation.name in seen:
            frappe.throw("Material Issue contains stock outside the controlled Withdrawal")
        seen.add(allocation.name)
        if (item.item_code != allocation.item_code
                or item.s_warehouse != cycle.source_warehouse
                or item.t_warehouse
                or abs(flt(item.transfer_qty or item.qty) - flt(allocation.qty)) > TOLERANCE
                or (item.batch_no or None) != (allocation.batch_no or None)):
            frappe.throw(f"Material Issue row for {allocation.item_code} no longer matches Withdrawal")


def block_withdrawal_cancel(doc):
    frappe.throw(
        f"Stock Entry {doc.name} is controlled by Withdrawal Cycle {doc.cfg_withdrawal_cycle}. "
        "Use controlled recovery instead of cancelling a posted floor withdrawal directly."
    )


def _withdrawal_payload(cycle, required_erp_inputs=None):
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    payload = {
        "cycle": cycle.name, "submit": bool(master.auto_submit_withdrawal_stock_entry),
    }
    if required_erp_inputs:
        payload["required_erp_inputs"] = frappe.parse_json(required_erp_inputs)
    return payload


def _untagged_row(cycle):
    return {
        "line_kind": "ERP Stock without Physical Tag", "visible_code": "ERP STOCK",
        "item_code": cycle.item_code, "qty": cycle.planned_qty,
        "stock_uom": cycle.stock_uom, "state": "Selected",
    }


def _validate_unit(cycle, unit):
    from cfg_kanban.services.container_contents import active_container_membership

    if frappe.db.get_value("Item", unit.item_code, "has_serial_no"):
        frappe.throw(
            f"{unit.item_code} is serial controlled. L2 Withdrawal does not construct an "
            "ERPNext Serial and Batch Bundle; use an authorized native Material Issue for the "
            "exact Serial Numbers."
        )
    if unit.tag_kind == "Reusable Container":
        frappe.throw("Scan a Stock Tag, not a reusable container")
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw(
            f"Stock Tag {unit.handling_unit_id} is {unit.identity_state} / {unit.quality_state}"
        )
    if (unit.item_code != cycle.item_code or unit.inventory_company != cycle.company
            or unit.current_warehouse != cycle.source_warehouse
            or unit.stock_uom != cycle.stock_uom):
        frappe.throw(
            "Stock Tag Item, Company, Warehouse, or Stock UOM does not match the "
            "Withdrawal Card"
        )
    if active_container_membership(unit.name):
        frappe.throw("Unload this Stock Tag from its reusable container before withdrawal")


def _assert_untagged_allowed(item_code):
    tracking = frappe.db.get_value(
        "Item", item_code, ["has_batch_no", "has_serial_no"], as_dict=True
    )
    if tracking and (tracking.has_batch_no or tracking.has_serial_no):
        frappe.throw(
            f"{item_code} is batch/serial controlled. Use physical Stock Tags or an authorized "
            "native ERPNext Material Issue that selects the exact batch/serial stock."
        )


def _assert_untagged_stock(item_code, warehouse, qty):
    _assert_untagged_allowed(item_code)
    actual = flt(frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
    ))
    if actual + TOLERANCE < flt(qty):
        frappe.throw(f"ERPNext stock in {warehouse} is {actual}; {qty} is required")


def _require_responsibility(profile):
    can_view_all = bool(
        profile.get("view_all_responsibilities")
        and profile.kanban_role in ("Supervisor", "Development Proxy")
    )
    responsibilities = {row.responsibility for row in profile.responsibilities
                        if row.responsibility}
    if not can_view_all and WITHDRAWAL_RESPONSIBILITY not in responsibilities:
        frappe.throw("Operator is not assigned to Stock Withdrawal", frappe.PermissionError)


def _stock_entry_status(name):
    if not name or not frappe.db.exists("Stock Entry", name):
        return None
    return frappe.db.get_value(
        "Stock Entry", name, ["name", "status", "docstatus"], as_dict=True
    )

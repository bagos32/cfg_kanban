"""Validated PPHU production events shared by scanner and future industrial adapters.

This module records operational evidence only. It never posts ERPNext stock, changes
Work Order state, releases QC stock, or sends machine-control commands.
"""

import re

import frappe
from frappe import _
from frappe.utils import flt

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, get_existing
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.operator_auth import require_operator


EVENT_TYPES = {
    "PPHU Hopper Boundary": {"requires_handling_unit": True, "kind": "hopper"},
    "PPHU Material Batch Boundary": {"requires_handling_unit": True, "kind": "material"},
    "PPHU Output Serial Start": {"requires_handling_unit": False, "kind": "serial"},
}
INPUT_SOURCES = {"Scanner", "Sensor", "PLC", "SCADA", "System"}
ACTIVE_EXECUTION_STATES = {"Ready", "In Progress", "Paused"}


@frappe.whitelist()
def preview_scanned_identity(
    event_type,
    scan_value,
    card_name,
    execution_name,
    operator_session_token=None,
):
    """Validate a physical identity before the operator scans the output boundary."""
    require_operator(operator_session_token, "report_progress", execution=execution_name)
    if event_type not in EVENT_TYPES or not EVENT_TYPES[event_type]["requires_handling_unit"]:
        frappe.throw(_("This PPHU event does not accept a Handling Unit scan"))
    _card, cycle, _execution = _validated_context(card_name, execution_name)
    unit = _validated_unit(event_type, scan_value, cycle)
    return _unit_payload(unit)


@frappe.whitelist()
def record_scanner_event(
    event_type,
    card_name,
    execution_name,
    output_serial_boundary,
    event_token,
    operator_session_token=None,
    handling_unit_scan=None,
    quantity=0,
):
    """Record a scanner-first PPHU event under an authenticated operator session."""
    profile, session = require_operator(
        operator_session_token, "report_progress", execution=execution_name
    )
    return ingest_event(
        event_type=event_type,
        card_name=card_name,
        execution_name=execution_name,
        output_serial_boundary=output_serial_boundary,
        event_token=event_token,
        input_source="Scanner",
        handling_unit_scan=handling_unit_scan,
        quantity=quantity,
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
    )


def ingest_event(
    *,
    event_type,
    card_name,
    execution_name,
    output_serial_boundary,
    event_token,
    input_source,
    handling_unit_scan=None,
    quantity=0,
    operator=None,
    operator_session=None,
    terminal_user=None,
    device_id=None,
    source_event_id=None,
    observed_on=None,
    payload=None,
):
    """Common validated event contract for scanner and future trusted gateways.

    A future PLC/SCADA adapter must authenticate the device and authorize the
    Workstation before calling this function. It must not expose this internal
    function as an unrestricted RPC endpoint.
    """
    if event_type not in EVENT_TYPES:
        frappe.throw(_("Unsupported PPHU event type: {0}").format(event_type))
    if input_source not in INPUT_SOURCES:
        frappe.throw(_("Unsupported PPHU input source: {0}").format(input_source))
    if not event_token:
        frappe.throw(_("A stable event token is required"))

    card, cycle, execution = _validated_context(card_name, execution_name)
    boundary = _normalise_boundary(output_serial_boundary)
    unit = None
    if EVENT_TYPES[event_type]["requires_handling_unit"]:
        unit = _validated_unit(event_type, handling_unit_scan, cycle)
    elif handling_unit_scan:
        frappe.throw(_("This PPHU event does not accept a Handling Unit scan"))

    job_card = frappe.db.get_value(
        "Job Card", execution.job_card, ["name", "work_order"], as_dict=True
    ) if execution.job_card else None
    previous = _latest_context_event(cycle.name, execution.name, event_type)
    visible_code = unit.handling_unit_id if unit else boundary
    key = canonical_key("pphu-production-event", input_source, event_token)
    expected = {
        "event_type": event_type,
        "kanban_card": card.name,
        "kanban_cycle": cycle.name,
        "process_execution": execution.name,
        "handling_unit": unit.name if unit else None,
        "output_serial_boundary": boundary,
        "qty": flt(quantity),
    }
    existing = get_existing("CFG Kanban Event", key)
    if existing:
        _assert_idempotent_match(existing, expected)
        return _event_payload(existing)
    event = record(
        event_type,
        card=card.name,
        cycle=cycle.name,
        execution=execution.name,
        handling_unit=unit.name if unit else None,
        qty=flt(quantity),
        previous_state=_previous_visible_value(previous),
        new_state=visible_code,
        device_id=device_id,
        notes=_event_notes(event_type, unit, boundary),
        system_generated=True,
        operator=operator,
        operator_session=operator_session,
        terminal_user=terminal_user,
        observed_on=observed_on,
        input_source=input_source,
        source_event_id=source_event_id or event_token,
        idempotency_key=key,
        work_order=job_card.work_order if job_card else cycle.work_order,
        job_card=job_card.name if job_card else execution.job_card,
        operation=execution.operation,
        workstation=execution.workstation,
        material_item=unit.item_code if unit else None,
        material_batch=unit.batch_no if unit else None,
        output_serial_boundary=boundary,
        payload=payload,
    )
    _assert_idempotent_match(event, expected)
    return _event_payload(event)


def _validated_context(card_name, execution_name):
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if not card.active_cycle:
        frappe.throw(_("Scan an active production Card before recording a PPHU event"))
    cycle = frappe.get_doc("CFG Kanban Cycle", card.active_cycle)
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    if execution.kanban_cycle != cycle.name:
        frappe.throw(_("The selected operation does not belong to this Card Cycle"))
    if execution.status not in ACTIVE_EXECUTION_STATES:
        frappe.throw(
            _("Operation {0} is {1}; select an active operation").format(
                execution.operation, execution.status
            )
        )
    return card, cycle, execution


def _assert_idempotent_match(event, expected):
    mismatched = [
        fieldname for fieldname, value in expected.items()
        if (flt(event.get(fieldname)) if fieldname == "qty" else event.get(fieldname)) != value
    ]
    if mismatched:
        frappe.throw(
            _("This PPHU event token was already used for different event data; rescan to create a new event"),
            frappe.ValidationError,
        )


def _validated_unit(event_type, scan_value, cycle):
    if not scan_value:
        frappe.throw(_("Scan the physical Handling Unit first"))
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(_("The scan is not an activated Handling Unit"))
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if unit.identity_state != "Active":
        frappe.throw(_("Handling Unit {0} is {1}").format(
            unit.handling_unit_id, unit.identity_state
        ))
    if unit.quality_state not in (None, "", "Released"):
        frappe.throw(_("Handling Unit {0} is under quality state {1}").format(
            unit.handling_unit_id, unit.quality_state
        ))

    company = frappe.db.get_value("CFG Kanban Master", cycle.kanban_master, "company")
    if unit.inventory_company and company and unit.inventory_company != company:
        frappe.throw(_("Handling Unit {0} belongs to {1}, not {2}").format(
            unit.handling_unit_id, unit.inventory_company, company
        ))

    kind = EVENT_TYPES[event_type]["kind"]
    if kind == "hopper":
        if unit.tag_kind != "Reusable Container" or unit.handling_unit_type != "Hopper":
            frappe.throw(_("Scan an active reusable Handling Unit configured with type Hopper"))
        if not unit.inventory_company:
            frappe.throw(_("The scanned Hopper must be assigned to a Company"))
    if kind == "material":
        if unit.tag_kind == "Reusable Container":
            frappe.throw(_("Scan the material Stock Tag, not a reusable container"))
        if unit.quality_state != "Released":
            frappe.throw(_("The scanned material tag must be quality Released"))
        if not unit.item_code or not unit.batch_no:
            frappe.throw(_("The scanned material tag requires both Item and Batch"))
        if not unit.inventory_company or not unit.current_warehouse:
            frappe.throw(_("The scanned material tag requires Company and Warehouse custody"))
        if flt(unit.current_qty) <= 0:
            frappe.throw(_("The scanned material tag has no available physical quantity"))
    return unit


def _normalise_boundary(value):
    boundary = str(value or "").strip()
    if not boundary:
        frappe.throw(_("Scan the first output serial affected by this event"))
    if len(boundary) > 140 or re.search(r"[\x00-\x1f\x7f]", boundary):
        frappe.throw(_("Output serial boundary is invalid"))
    return boundary


def _latest_context_event(cycle_name, execution_name, event_type):
    return frappe.db.get_value(
        "CFG Kanban Event",
        {
            "kanban_cycle": cycle_name,
            "process_execution": execution_name,
            "event_type": event_type,
        },
        ["handling_unit", "new_state", "output_serial_boundary"],
        order_by="event_datetime desc, creation desc",
        as_dict=True,
    )


def _previous_visible_value(previous):
    if not previous:
        return None
    if previous.handling_unit:
        return frappe.db.get_value(
            "CFG Kanban Handling Unit", previous.handling_unit, "handling_unit_id"
        ) or previous.new_state
    return previous.new_state or previous.output_serial_boundary


def _event_notes(event_type, unit, boundary):
    identity = unit.handling_unit_id if unit else "serial context"
    return _("{0}: {1}; first affected output serial {2}").format(
        event_type, identity, boundary
    )


def _unit_payload(unit):
    return {
        "name": unit.name,
        "visible_code": unit.handling_unit_id,
        "handling_unit_type": unit.handling_unit_type,
        "item_code": unit.item_code,
        "batch_no": unit.batch_no,
        "company": unit.inventory_company,
        "warehouse": unit.current_warehouse,
    }


def _event_payload(event):
    return {
        "name": event.name,
        "event_type": event.event_type,
        "event_datetime": event.event_datetime,
        "input_source": event.input_source,
        "handling_unit": event.handling_unit,
        "material_item": event.material_item,
        "material_batch": event.material_batch,
        "output_serial_boundary": event.output_serial_boundary,
        "work_order": event.work_order,
        "job_card": event.job_card,
        "operation": event.operation,
        "workstation": event.workstation,
    }

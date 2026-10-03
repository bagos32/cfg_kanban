import json
import re

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.idempotency import canonical_key


TOLERANCE = 0.000001


def item_uses_serials(item_code):
    return bool(frappe.db.get_value("Item", item_code, "has_serial_no"))


def erp_row_serials(row):
    direct = _parse_serial_values(row.get("serial_no"))
    if direct:
        return direct
    bundle = row.get("serial_and_batch_bundle")
    if not bundle:
        return []
    values = frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": bundle, "parenttype": "Serial and Batch Bundle",
                 "serial_no": ["is", "set"]},
        pluck="serial_no",
        order_by="idx asc",
        limit_page_length=10000,
    )
    return list(dict.fromkeys(value for value in values if value))


def select_serials_for_tag(row, qty, requested=None, exclude=None):
    if not item_uses_serials(row.item_code):
        return []
    count = int(round(flt(qty)))
    if count <= 0 or abs(flt(qty) - count) > TOLERANCE:
        frappe.throw(_("Serial-controlled tag quantity must be a positive whole number"))
    erp_serials = erp_row_serials(row)
    if not erp_serials:
        frappe.throw(
            _("ERPNext row {0} has no Serial Numbers. Complete its Serial and Batch Bundle first.").format(
                row.idx
            )
        )
    excluded = set(exclude or [])
    available = [value for value in erp_serials if value not in excluded]
    selected = _parse_serial_values(requested)
    if not selected and len(available) == count:
        selected = available
    if len(selected) != count:
        frappe.throw(
            _("Select exactly {0} Serial Numbers for this {1}-unit Stock Tag").format(
                count, count
            )
        )
    unknown = [value for value in selected if value not in available]
    if unknown:
        frappe.throw(
            _("Serial Numbers are unavailable or do not belong to this ERP row: {0}").format(
                ", ".join(unknown)
            )
        )
    return selected


def active_serials_for_unit(handling_unit):
    return frappe.get_all(
        "CFG Kanban Handling Unit Serial",
        filters={"handling_unit": handling_unit, "state": "Active"},
        pluck="serial_no",
        order_by="serial_no asc",
        limit_page_length=10000,
    )


def assigned_serials_for_reference(reference_doctype, reference_name, reference_row):
    return frappe.get_all(
        "CFG Kanban Handling Unit Serial",
        filters={"assignment_reference_doctype": reference_doctype,
                 "assignment_reference_name": reference_name,
                 "assignment_reference_row": reference_row},
        pluck="serial_no",
        limit_page_length=10000,
    )


def assign_serials(unit, serial_numbers, reference_doctype, reference_name,
                   reference_row=None):
    serials = _parse_serial_values(serial_numbers)
    if not serials:
        return []
    if len(serials) != int(round(flt(unit.original_qty or unit.current_qty))):
        frappe.throw(_("Serial count must equal the complete Handling Unit quantity"))
    created = []
    for serial_no in serials:
        serial = frappe.db.get_value(
            "Serial No", serial_no, ["item_code", "batch_no"], as_dict=True
        )
        if not serial or serial.item_code != unit.item_code:
            frappe.throw(_("Serial No {0} does not belong to Item {1}").format(
                serial_no, unit.item_code
            ))
        if unit.batch_no and serial.batch_no and serial.batch_no != unit.batch_no:
            frappe.throw(_("Serial No {0} belongs to Batch {1}, not {2}").format(
                serial_no, serial.batch_no, unit.batch_no
            ))
        assignment_key = canonical_key(
            "handling-unit-serial", unit.name, serial_no,
            reference_doctype, reference_name, reference_row,
        )
        existing = frappe.db.get_value(
            "CFG Kanban Handling Unit Serial", {"assignment_key": assignment_key}, "name"
        )
        if existing:
            created.append(existing)
            continue
        doc = frappe.get_doc({
            "doctype": "CFG Kanban Handling Unit Serial",
            "state": "Active",
            "handling_unit": unit.name,
            "handling_unit_code": unit.handling_unit_id,
            "serial_no": serial_no,
            "item_code": unit.item_code,
            "batch_no": unit.batch_no or serial.batch_no,
            "company": unit.inventory_company,
            "warehouse_at_assignment": unit.current_warehouse,
            "assigned_on": now_datetime(),
            "assignment_reference_doctype": reference_doctype,
            "assignment_reference_name": reference_name,
            "assignment_reference_row": reference_row,
            "assignment_key": assignment_key,
        }).insert(ignore_permissions=True)
        created.append(doc.name)
    unit.db_set("serial_count", len(serials), update_modified=False)
    return created


def validate_unit_serials_for_row(unit, row, qty):
    if not item_uses_serials(row.item_code):
        return
    serials = active_serials_for_unit(unit.name)
    if not serials:
        frappe.throw(_("Handling Unit {0} has no exact Serial Number membership").format(
            unit.handling_unit_id
        ))
    if abs(flt(qty) - flt(unit.current_qty)) > TOLERANCE:
        frappe.throw(_("A serial-controlled Stock Tag must be allocated in full"))
    erp_serials = set(erp_row_serials(row))
    invalid = [value for value in serials if value not in erp_serials]
    if invalid:
        frappe.throw(_("Handling Unit serials do not match the ERP row: {0}").format(
            ", ".join(invalid)
        ))
    if len(serials) != int(round(flt(qty))):
        frappe.throw(_("Handling Unit serial count does not match its allocated quantity"))


def release_unit_serials(handling_unit, reason, reference_doctype, reference_name):
    rows = frappe.get_all(
        "CFG Kanban Handling Unit Serial",
        filters={"handling_unit": handling_unit, "state": "Active"},
        pluck="name",
        limit_page_length=10000,
    )
    now = now_datetime()
    for name in rows:
        frappe.db.set_value(
            "CFG Kanban Handling Unit Serial", name,
            {"state": "Released", "active_serial_key": None, "released_on": now,
             "release_reason": reason, "release_reference_doctype": reference_doctype,
             "release_reference_name": reference_name},
            update_modified=False,
        )
    frappe.db.set_value("CFG Kanban Handling Unit", handling_unit, "serial_count", 0,
                        update_modified=False)
    return len(rows)


def reactivate_unit_serials(handling_unit, reference_name):
    rows = frappe.get_all(
        "CFG Kanban Handling Unit Serial",
        filters={"handling_unit": handling_unit, "state": "Released",
                 "release_reference_name": reference_name},
        fields=["name", "serial_no"],
        limit_page_length=10000,
    )
    for row in rows:
        if frappe.db.exists(
            "CFG Kanban Handling Unit Serial",
            {"active_serial_key": row.serial_no, "name": ["!=", row.name]},
        ):
            frappe.throw(_("Serial No {0} is already active under another Stock Tag").format(
                row.serial_no
            ))
        frappe.db.set_value(
            "CFG Kanban Handling Unit Serial", row.name,
            {"state": "Active", "active_serial_key": row.serial_no, "released_on": None,
             "release_reason": None, "release_reference_doctype": None,
             "release_reference_name": None},
            update_modified=False,
        )
    frappe.db.set_value("CFG Kanban Handling Unit", handling_unit, "serial_count", len(rows),
                        update_modified=False)


def transfer_unit_serials(old_unit, new_unit, reason):
    serials = active_serials_for_unit(old_unit.name)
    if not serials:
        return
    release_unit_serials(old_unit.name, reason, "CFG Kanban Handling Unit", new_unit.name)
    assign_serials(
        new_unit, serials, "CFG Kanban Handling Unit", new_unit.name, old_unit.name
    )


def serial_history_for_units(handling_units):
    names = list(handling_units or [])
    if not names or not frappe.has_permission("CFG Kanban Handling Unit Serial", ptype="read"):
        return []
    return frappe.get_list(
        "CFG Kanban Handling Unit Serial",
        filters={"handling_unit": ["in", names]},
        fields=["name", "state", "handling_unit", "handling_unit_code", "serial_no",
                "item_code", "batch_no", "assigned_on", "released_on", "release_reason",
                "assignment_reference_doctype", "assignment_reference_name",
                "release_reference_doctype", "release_reference_name"],
        order_by="assigned_on desc",
        limit_page_length=500,
    )


def serials_to_json(serials):
    return json.dumps(_parse_serial_values(serials), separators=(",", ":"))


def serials_from_json(value):
    return _parse_serial_values(value)


def _parse_serial_values(value):
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        text = str(value).strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except (TypeError, ValueError):
                raw = re.split(r"[\n,]+", text)
        else:
            raw = re.split(r"[\n,]+", text)
    values = [str(item).strip() for item in raw if str(item).strip()]
    if len(values) != len(set(values)):
        frappe.throw(_("Duplicate Serial Numbers are not allowed"))
    return list(dict.fromkeys(values))

import frappe
from frappe.utils import cint, flt


FIELD_COLUMNS = [
    "field_key", "label", "field_type", "mandatory", "options", "default_value",
    "precision", "min_value", "max_value", "unit", "read_only", "validation_message",
    "definition_scope",
]


def definitions(master, capture_on, *, operation=None, process_task_key=None):
    filters = {
        "parent": master,
        "parenttype": "CFG Kanban Master",
        "capture_on": capture_on,
    }
    if process_task_key:
        filters.update({"definition_scope": "Process Task", "process_task_key": process_task_key})
    else:
        filters.update({"operation": operation})
    rows = frappe.get_all(
        "CFG Kanban Field Definition", filters=filters, fields=FIELD_COLUMNS,
        order_by="display_order asc, idx asc",
    )
    if not process_task_key:
        rows = [row for row in rows if (row.definition_scope or "Operation") == "Operation"]
    return rows


def standalone_definitions(schedule_name, capture_on):
    return frappe.get_all(
        "CFG Kanban Field Definition",
        filters={"parent": schedule_name, "parenttype": "CFG Kanban Task Schedule",
                 "definition_scope": "Standalone Task", "capture_on": capture_on},
        fields=FIELD_COLUMNS, order_by="display_order asc, idx asc",
    )


def validate_values(rows, supplied_values):
    supplied = {row.get("field_key"): row.get("value") for row in supplied_values or []}
    for definition in rows:
        value = supplied.get(definition.field_key)
        message = definition.validation_message or f"Invalid value for {definition.label}"
        if definition.mandatory and (value in (None, "") or
                                     (definition.field_type == "Check" and not cint(value))):
            frappe.throw(f"{definition.label} is required")
        if value in (None, ""):
            continue
        if definition.field_type in ("Int", "Float"):
            numeric = flt(value)
            if definition.min_value is not None and numeric < flt(definition.min_value):
                frappe.throw(message)
            if definition.max_value is not None and numeric > flt(definition.max_value):
                frappe.throw(message)
        if definition.field_type == "Select" and definition.options:
            if str(value) not in definition.options.splitlines():
                frappe.throw(message)


def normalized_values(rows, supplied_values):
    by_key = {row.get("field_key"): row.get("value") for row in supplied_values or []}
    return [{
        "field_key": row.field_key,
        "label": row.label,
        "field_type": row.field_type,
        "value": by_key.get(row.field_key, row.default_value),
        "unit": row.unit,
    } for row in rows if by_key.get(row.field_key, row.default_value) not in (None, "")]

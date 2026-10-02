import frappe
from frappe.utils import cint, flt

from cfg_kanban.services.field_conditions import (
    ConditionSyntaxError,
    evaluate_visible_condition,
    parse_visible_condition,
)


FIELD_COLUMNS = [
    "field_key", "label", "field_type", "mandatory", "options", "default_value",
    "precision", "min_value", "max_value", "unit", "read_only", "validation_message",
    "definition_scope", "operation", "process_task_key", "capture_on", "visible_condition",
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
    for definition in _visible_rows(rows, supplied):
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
        # CFG Kanban Execution Value.value is a Text field. Keeping numeric and
        # Check answers as Python integers makes Frappe Version formatting fail
        # on the next save (notably correction/resubmission). Persist one stable
        # string representation and convert with flt/cint only when evaluating.
        "value": _storage_value(by_key.get(row.field_key, row.default_value)),
        "unit": row.unit,
    } for row in _visible_rows(rows, by_key)
        if by_key.get(row.field_key, row.default_value) not in (None, "")]


def validate_condition_definitions(rows):
    rows = list(rows or [])
    by_key = {row.field_key: row for row in rows}
    dependencies = {}
    for row in rows:
        try:
            parsed = parse_visible_condition(row.visible_condition)
        except ConditionSyntaxError as exc:
            frappe.throw(f"Visible Condition for {row.label} is invalid: {exc}")
        if not parsed:
            continue
        dependency = parsed[0]
        parent = by_key.get(dependency)
        if not parent:
            frappe.throw(
                f"Visible Condition for {row.label} references unknown Field Key {dependency}"
            )
        if dependency == row.field_key:
            frappe.throw(f"Visible Condition for {row.label} cannot reference itself")
        if parent.capture_on != row.capture_on:
            frappe.throw(
                f"Visible Condition for {row.label} must reference a field captured on "
                f"the same stage ({row.capture_on})"
            )
        if _scope(parent) != _scope(row):
            frappe.throw(
                f"Visible Condition for {row.label} must reference a field in the same task "
                "or operation scope"
            )
        dependencies[row.field_key] = dependency
    _reject_cycles(dependencies, by_key)


def _visible_rows(rows, supplied):
    rows = list(rows or [])
    by_key = {row.field_key: row for row in rows}
    values = {row.field_key: row.default_value for row in rows}
    values.update(supplied)
    memo = {}

    def visible(field_key, trail=()):
        if field_key in memo:
            return memo[field_key]
        if field_key in trail:
            return False
        row = by_key[field_key]
        try:
            parsed = parse_visible_condition(row.visible_condition)
        except ConditionSyntaxError:
            return False
        if not parsed:
            memo[field_key] = True
            return True
        dependency = parsed[0]
        condition_values = dict(values)
        if dependency in by_key and not visible(dependency, trail + (field_key,)):
            condition_values[dependency] = None
        memo[field_key] = evaluate_visible_condition(row.visible_condition, condition_values)
        return memo[field_key]

    return [row for row in rows if visible(row.field_key)]


def _scope(row):
    return (
        row.definition_scope or "Operation",
        row.operation or "",
        row.process_task_key or "",
    )


def _reject_cycles(dependencies, by_key):
    def visit(field_key, trail):
        if field_key in trail:
            labels = [by_key[key].label for key in trail[trail.index(field_key):]]
            frappe.throw("Visible Conditions contain a dependency cycle: " + " → ".join(labels))
        dependency = dependencies.get(field_key)
        if dependency:
            visit(dependency, trail + [field_key])

    for field_key in dependencies:
        visit(field_key, [])


def _storage_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)

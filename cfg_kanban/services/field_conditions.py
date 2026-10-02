import ast
import re


_CONDITION = re.compile(
    r"^(?:doc\.)?(?P<field>[A-Za-z][A-Za-z0-9_]*)"
    r"(?:\s*(?P<operator>==|!=|=)\s*(?P<expected>.+))?$"
)


class ConditionSyntaxError(ValueError):
    pass


def parse_visible_condition(condition):
    expression = (condition or "").strip()
    if not expression:
        return None
    if expression.lower().startswith("eval:"):
        expression = expression[5:].strip()
    match = _CONDITION.fullmatch(expression)
    if not match:
        raise ConditionSyntaxError(
            "Use field_key, field_key == value, or field_key != value "
            "(an optional eval:doc. prefix is accepted)"
        )
    field_key = match.group("field")
    if field_key.startswith("dynamic_"):
        field_key = field_key[8:]
    operator = match.group("operator")
    if operator == "=":
        operator = "=="
    expected = _parse_literal(match.group("expected")) if operator else None
    return field_key, operator, expected


def evaluate_visible_condition(condition, values):
    parsed = parse_visible_condition(condition)
    if not parsed:
        return True
    field_key, operator, expected = parsed
    actual = values.get(field_key)
    if not operator:
        return _truthy(actual)
    equal = _equal(actual, expected)
    return equal if operator == "==" else not equal


def _parse_literal(value):
    value = (value or "").strip()
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def _truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none", "null"}


def _equal(actual, expected):
    if isinstance(expected, bool):
        return _truthy(actual) == expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    if expected is None:
        return actual in (None, "")
    return str(actual if actual is not None else "") == str(expected)

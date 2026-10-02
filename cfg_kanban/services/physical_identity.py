"""Helpers for physical codes printed before a Kanban transaction exists."""


MAX_TAG_RANGE_SIZE = 100000


def normalize_physical_code(value):
    """Remove scanner terminators/outer whitespace without changing the printed code."""
    code = str(value or "").strip()
    if not code:
        raise ValueError("A physical scan code is required")
    if any(ord(character) < 32 for character in code):
        raise ValueError("Physical scan codes cannot contain control characters")
    return code


def validate_tag_range_definition(prefix, start_number, end_number, number_width,
                                  child_separator, child_count):
    """Return normalized range controls or raise a user-readable validation error."""
    normalized_prefix = normalize_physical_code(prefix)
    if normalized_prefix != prefix:
        raise ValueError("Tag Prefix cannot contain outer whitespace")
    separator = str(child_separator or "-")
    if separator != separator.strip() or not separator:
        raise ValueError("Child Separator cannot be blank or contain outer whitespace")
    if len(separator) > 3 or any(character.isdigit() or ord(character) < 32
                                 for character in separator):
        raise ValueError("Child Separator must be one to three non-numeric characters")
    start = int(start_number or 0)
    end = int(end_number or 0)
    width = int(number_width or 0)
    children = int(child_count or 0)
    if start < 0 or end < start:
        raise ValueError("Ending Number must be greater than or equal to Starting Number")
    if width < 1 or width > 12:
        raise ValueError("Number Width must be between 1 and 12")
    if len(str(end)) > width:
        raise ValueError("Number Width is too small for the Ending Number")
    if end - start + 1 > MAX_TAG_RANGE_SIZE:
        raise ValueError(
            f"One Tag Range Registry cannot exceed {MAX_TAG_RANGE_SIZE:,} main tags"
        )
    if children < 0 or children > 20:
        raise ValueError("Detachable Child Count must be between 0 and 20")
    return {
        "prefix": normalized_prefix,
        "start_number": start,
        "end_number": end,
        "number_width": width,
        "child_separator": separator,
        "child_count": children,
    }


def format_tag_family_code(prefix, serial_number, number_width):
    return f"{prefix}{int(serial_number):0{int(number_width)}d}"


def parse_tag_range_code(code, registry):
    """Parse one exact main/child code against a registry-like mapping or object."""
    def value(fieldname, default=None):
        if isinstance(registry, dict):
            return registry.get(fieldname, default)
        return getattr(registry, fieldname, default)

    controls = validate_tag_range_definition(
        value("prefix"), value("start_number"), value("end_number"),
        value("number_width"), value("child_separator", "-"),
        value("child_count", 0),
    )
    visible_code = normalize_physical_code(code)
    prefix = controls["prefix"]
    if not visible_code.startswith(prefix):
        return None
    remainder = visible_code[len(prefix):]
    width = controls["number_width"]
    if len(remainder) < width:
        return None
    serial_text = remainder[:width]
    if (len(serial_text) != width or not serial_text.isascii()
            or not serial_text.isdigit()):
        return None
    serial_number = int(serial_text)
    if not controls["start_number"] <= serial_number <= controls["end_number"]:
        return None
    main_code = format_tag_family_code(prefix, serial_number, width)
    suffix = remainder[width:]
    if not suffix:
        tag_role = "Main"
        child_index = 0
    else:
        separator = controls["child_separator"]
        if not suffix.startswith(separator):
            return None
        child_text = suffix[len(separator):]
        if (not child_text.isascii() or not child_text.isdigit()
                or child_text != str(int(child_text))):
            return None
        child_index = int(child_text)
        if child_index < 1 or child_index > controls["child_count"]:
            return None
        tag_role = "Child"
    expected = main_code if tag_role == "Main" else (
        f"{main_code}{controls['child_separator']}{child_index}"
    )
    if visible_code != expected:
        return None
    return {
        "visible_code": visible_code,
        "main_code": main_code,
        "serial_number": serial_number,
        "tag_role": tag_role,
        "child_index": child_index,
        **controls,
    }

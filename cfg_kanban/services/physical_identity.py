"""Helpers for physical codes printed before a Kanban transaction exists."""


def normalize_physical_code(value):
    """Remove scanner terminators/outer whitespace without changing the printed code."""
    code = str(value or "").strip()
    if not code:
        raise ValueError("A physical scan code is required")
    if any(ord(character) < 32 for character in code):
        raise ValueError("Physical scan codes cannot contain control characters")
    return code

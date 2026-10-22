ACTIVE_PRESENCE_STATES = {"Active", "On Break"}

CREW_ROLES = {
    "Main Operator",
    "Supporting Operator",
    "Senior / Overseer",
    "Temporary Support",
}

WORK_CATEGORIES = {"Direct Participation", "Oversight Only"}

ALLOWED_TRANSITIONS = {
    "Active": {"Break", "Leave"},
    "On Break": {"Resume", "Leave"},
    "Left": set(),
}


def validate_membership_choice(crew_role, work_category):
    if crew_role not in CREW_ROLES:
        raise ValueError(f"Unsupported crew role: {crew_role}")
    if work_category not in WORK_CATEGORIES:
        raise ValueError(f"Unsupported work category: {work_category}")
    if crew_role == "Main Operator" and work_category != "Direct Participation":
        raise ValueError("The Main Operator must use Direct Participation")


def next_presence_state(current_state, event_type):
    if event_type not in ALLOWED_TRANSITIONS.get(current_state, set()):
        raise ValueError(f"Cannot apply {event_type} while membership is {current_state}")
    return {
        "Break": "On Break",
        "Resume": "Active",
        "Leave": "Left",
    }[event_type]


def active_coverage_members(memberships):
    return [row for row in memberships if row.get("status") == "Active"]


def expected_roster_match(expected_members, employee):
    for row in expected_members or []:
        if row.get("employee") == employee:
            return row
    return None

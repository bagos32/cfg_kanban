DIRECT_WORK = "Direct Participation"
OVERSIGHT_WORK = "Oversight Only"


def participation_kind(work_category):
    if work_category == DIRECT_WORK:
        return "Production Labour"
    if work_category == OVERSIGHT_WORK:
        return "Oversight"
    raise ValueError(f"Unsupported participation work category: {work_category}")


def segment_identity(participant):
    """Return the immutable identity of one participation segment.

    Role or work-category changes intentionally produce a new segment even when the
    Employee remains at the same Workstation.
    """
    source = participant.get("crew_membership") or participant.get("employee")
    return (
        source,
        participant.get("crew_role"),
        participant.get("work_category"),
        participant.get("participation_source"),
    )


def desired_participants(members, fallback_actor=None):
    participants = []
    for member in members or []:
        if member.get("status") != "Active":
            continue
        participants.append({
            "employee": member.get("employee"),
            "employee_name": member.get("employee_name"),
            "operator_profile": member.get("operator_profile"),
            "crew_session": member.get("crew_session"),
            "crew_membership": member.get("name"),
            "crew_role": member.get("crew_role"),
            "work_category": member.get("work_category"),
            "participation_kind": participation_kind(member.get("work_category")),
            "participation_source": "Crew Membership",
        })
    if participants or not fallback_actor or not fallback_actor.get("employee"):
        return participants
    return [{
        "employee": fallback_actor.get("employee"),
        "employee_name": fallback_actor.get("employee_name"),
        "operator_profile": fallback_actor.get("operator_profile"),
        "crew_session": None,
        "crew_membership": None,
        "crew_role": "Main Operator",
        "work_category": DIRECT_WORK,
        "participation_kind": "Production Labour",
        "participation_source": "Authenticated Operator Fallback",
    }]

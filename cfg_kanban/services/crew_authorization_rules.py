DIRECT_WORK = "Direct Participation"
ASSISTANT_ROLES = {"Supporting Operator", "Temporary Support"}
LEAD_ROLES = {"Main Operator", "Senior / Overseer"}
SUPERVISOR_ROLE = "Senior / Overseer"


def requirement_key(requirement):
    return f"{requirement.get('participation_role')}|{requirement.get('skill')}"


def evaluate_crew_authorization(
    policy,
    members,
    qualified_by_requirement=None,
    trainee_employees=None,
    concurrent_employees=None,
):
    """Pure P04 decision rule; database-specific evidence is assembled by the service."""
    policy = policy or {}
    if not policy.get("configured"):
        return {"allowed": True, "configured": False, "findings": []}

    active = [row for row in (members or []) if row.get("status") == "Active"]
    direct = [row for row in active if row.get("work_category") == DIRECT_WORK]
    assistants = [row for row in direct if row.get("crew_role") in ASSISTANT_ROLES]
    qualified_by_requirement = qualified_by_requirement or {}
    trainees = set(trainee_employees or [])
    concurrent = set(concurrent_employees or [])
    findings = []

    _minimum_finding(
        findings,
        "MINIMUM_DIRECT_WORKERS",
        len(direct),
        int(policy.get("minimum_direct_workers") or 1),
        "active direct worker(s)",
    )
    _minimum_finding(
        findings,
        "MINIMUM_ASSISTANTS",
        len(assistants),
        int(policy.get("minimum_assistants") or 0),
        "active assistant(s)",
    )

    supervisor_requirements = []
    supervisor_employees = set()
    for requirement in policy.get("skill_requirements") or []:
        key = requirement_key(requirement)
        qualified = set(qualified_by_requirement.get(key) or [])
        needed = int(requirement.get("minimum_people") or 1)
        if len(qualified) < needed:
            findings.append({
                "code": "SKILL_REQUIREMENT",
                "message": (
                    f"{requirement.get('participation_role')} requires {needed} active "
                    f"employee(s) with {requirement.get('skill')} at "
                    f"{requirement.get('minimum_level')}; found {len(qualified)}"
                ),
                "requirement": key,
            })
        if requirement.get("participation_role") == "Active Supervisor":
            supervisor_requirements.append(requirement)
            supervisor_employees.update(qualified)

    if not supervisor_requirements:
        supervisor_employees.update(
            row.get("employee") for row in active
            if row.get("crew_role") == SUPERVISOR_ROLE
        )

    trainee_policy = policy.get("trainee_policy") or "Permitted"
    supervision = policy.get("supervision_presence") or "Not Required"
    if trainee_policy == "Prohibited" and trainees:
        findings.append({
            "code": "TRAINEES_PROHIBITED",
            "message": "Trainees are not permitted: " + ", ".join(sorted(trainees)),
        })
    supervision_required = (
        supervision == "Always Required"
        or (supervision == "Required When Trainees Present" and trainees)
        or (trainee_policy == "Supervised Only" and trainees)
    )
    if supervision_required and not supervisor_employees:
        findings.append({
            "code": "SUPERVISOR_REQUIRED",
            "message": "An active, authorized supervisor is required for this crew",
        })
    ratio = int(policy.get("max_trainees_per_supervisor") or 0)
    if trainees and ratio > 0 and len(trainees) > len(supervisor_employees) * ratio:
        findings.append({
            "code": "TRAINEE_RATIO",
            "message": (
                f"{len(trainees)} trainee(s) exceed the permitted ratio of {ratio} per "
                f"active supervisor ({len(supervisor_employees)} present)"
            ),
        })
    if concurrent:
        findings.append({
            "code": "CONCURRENT_DIRECT_WORK",
            "message": (
                "Direct participants cannot cover multiple active Workstations: "
                + ", ".join(sorted(concurrent))
            ),
        })

    return {
        "allowed": not findings,
        "configured": True,
        "findings": findings,
        "active_direct_workers": len(direct),
        "active_assistants": len(assistants),
        "active_supervisors": len(supervisor_employees),
        "trainee_employees": sorted(trainees),
        "concurrent_employees": sorted(concurrent),
    }


def _minimum_finding(findings, code, actual, required, label):
    if actual < required:
        findings.append({
            "code": code,
            "message": f"Requires {required} {label}; found {actual}",
        })

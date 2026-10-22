TRAINEE_POLICY_RANK = {"Permitted": 0, "Supervised Only": 1, "Prohibited": 2}
SUPERVISION_RANK = {
    "Not Required": 0,
    "Required When Trainees Present": 1,
    "Always Required": 2,
}


def _as_int(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def merge_normalized_crew_policies(policies, sources=None):
    policies = list(policies or [])
    result = {
        "configured": bool(policies),
        "crew_modes": [],
        "minimum_direct_workers": 1,
        "minimum_assistants": 0,
        "trainee_policy": "Permitted",
        "supervision_presence": "Not Required",
        "max_trainees_per_supervisor": None,
        "skill_requirements": [],
        "sources": sources or [],
    }
    if not policies:
        return result

    trainee_policy = "Permitted"
    supervision = "Not Required"
    ratios = []
    skill_map = {}
    for policy in policies:
        mode = policy.get("crew_mode")
        if mode and mode not in result["crew_modes"]:
            result["crew_modes"].append(mode)
        result["minimum_direct_workers"] = max(
            result["minimum_direct_workers"],
            _as_int(policy.get("minimum_direct_workers")),
        )
        result["minimum_assistants"] = max(
            result["minimum_assistants"],
            _as_int(policy.get("minimum_assistants")),
        )
        candidate_trainee = policy.get("trainee_policy") or "Prohibited"
        if TRAINEE_POLICY_RANK[candidate_trainee] > TRAINEE_POLICY_RANK[trainee_policy]:
            trainee_policy = candidate_trainee
        candidate_supervision = policy.get("supervision_presence") or "Not Required"
        if SUPERVISION_RANK[candidate_supervision] > SUPERVISION_RANK[supervision]:
            supervision = candidate_supervision
        ratio = _as_int(policy.get("max_trainees_per_supervisor"))
        if ratio > 0:
            ratios.append(ratio)
        for requirement in policy.get("skill_requirements") or []:
            requirement = dict(requirement)
            key = (requirement["participation_role"], requirement["skill"])
            current = skill_map.get(key)
            if not current:
                skill_map[key] = requirement
                continue
            if _as_int(requirement.get("minimum_level_rank")) > _as_int(
                    current.get("minimum_level_rank")):
                current["minimum_level"] = requirement["minimum_level"]
                current["minimum_level_rank"] = requirement["minimum_level_rank"]
            current["minimum_people"] = max(
                _as_int(current.get("minimum_people")),
                _as_int(requirement.get("minimum_people")),
            )
            current["require_independent_authorization"] = bool(
                current.get("require_independent_authorization")
                or requirement.get("require_independent_authorization")
            )
            current["require_supervisor_authorization"] = bool(
                current.get("require_supervisor_authorization")
                or requirement.get("require_supervisor_authorization")
            )

    result["trainee_policy"] = trainee_policy
    result["supervision_presence"] = supervision
    result["max_trainees_per_supervisor"] = min(ratios) if ratios else None
    result["skill_requirements"] = sorted(
        skill_map.values(), key=lambda row: (row["participation_role"], row["skill"])
    )
    return result

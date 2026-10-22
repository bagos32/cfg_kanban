import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from cfg_kanban.services.competency import competency_level_code, competency_level_rank
from cfg_kanban.services.crew_policy_rules import merge_normalized_crew_policies


def assert_approved_crew_profile(profile_name, company=None):
    if not profile_name:
        frappe.throw(_("Crew Requirement Profile is required"))
    profile = frappe.get_cached_doc("CFG Kanban Crew Requirement Profile", profile_name)
    if cint(profile.docstatus) != 1 or not cint(profile.active):
        frappe.throw(
            _("Crew Requirement Profile {0} must be submitted and active").format(
                profile_name
            )
        )
    if company and profile.company and profile.company != company:
        frappe.throw(
            _("Crew Requirement Profile {0} belongs to {1}, not {2}").format(
                profile_name, profile.company, company
            )
        )
    return profile


def normalize_crew_profile(profile):
    profile = frappe._dict(profile.as_dict() if hasattr(profile, "as_dict") else profile)
    skills = []
    for row in profile.get("skill_requirements") or []:
        row = frappe._dict(row.as_dict() if hasattr(row, "as_dict") else row)
        skills.append({
            "participation_role": row.participation_role,
            "skill": row.skill,
            "minimum_level": competency_level_code(row.minimum_level),
            "minimum_level_rank": competency_level_rank(row.minimum_level),
            "minimum_people": max(cint(row.minimum_people), 1),
            "require_independent_authorization": bool(
                cint(row.require_independent_authorization)
            ),
            "require_supervisor_authorization": bool(
                cint(row.require_supervisor_authorization)
            ),
        })
    ratio = cint(profile.get("max_trainees_per_supervisor"))
    ratio_applies = (
        profile.trainee_policy == "Supervised Only"
        or profile.supervision_presence != "Not Required"
    )
    return {
        "normalized": True,
        "profile": profile.name,
        "requirement_name": profile.requirement_name,
        "revision": cint(profile.revision),
        "crew_mode": profile.crew_mode,
        "minimum_direct_workers": max(cint(profile.minimum_direct_workers), 1),
        "minimum_assistants": max(cint(profile.minimum_assistants), 0),
        "trainee_policy": profile.trainee_policy or "Prohibited",
        "supervision_presence": profile.supervision_presence or "Not Required",
        "max_trainees_per_supervisor": ratio if ratio_applies and ratio > 0 else None,
        "skill_requirements": skills,
        "external_policy_identifier": profile.get("external_policy_identifier"),
        "external_policy_revision_snapshot": profile.get(
            "external_policy_revision_snapshot"
        ),
    }


def merge_crew_policies(policies, sources=None):
    normalized = [
        normalize_crew_profile(policy)
        if not isinstance(policy, dict) or not policy.get("normalized")
        else policy
        for policy in policies
    ]
    return merge_normalized_crew_policies(normalized, sources=sources)


def get_effective_crew_policy(kanban_master, operation, workstation=None,
                              card_name=None, on_date=None):
    check_date = getdate(on_date or today())
    master = frappe.get_cached_doc("CFG Kanban Master", kanban_master)
    operation_row = next(
        (row for row in master.operation_profiles if row.operation == operation), None
    )
    if not operation_row:
        frappe.throw(
            _("Operation {0} is not configured in Kanban Master {1}").format(
                operation, master.name
            )
        )

    assignments = []
    if operation_row.get("crew_requirement_profile"):
        assignments.append({
            "scope": "Operation Profile",
            "reference": operation_row.name,
            "profile": operation_row.crew_requirement_profile,
        })

    if workstation:
        rules = frappe.get_all(
            "CFG Kanban Workstation Crew Requirement",
            filters={
                "company": master.company,
                "workstation": workstation,
                "active": 1,
                "docstatus": 1,
            },
            fields=[
                "name", "operation", "crew_requirement_profile",
                "effective_from", "effective_to",
            ],
            limit_page_length=0,
        )
        for rule in rules:
            if rule.operation and rule.operation != operation:
                continue
            if rule.effective_from and getdate(rule.effective_from) > check_date:
                continue
            if rule.effective_to and getdate(rule.effective_to) < check_date:
                continue
            assignments.append({
                "scope": "Workstation Restriction",
                "reference": rule.name,
                "profile": rule.crew_requirement_profile,
            })

    if card_name:
        card = frappe.get_cached_doc("CFG Kanban Card", card_name)
        if card.kanban_master != master.name:
            frappe.throw(_("Card does not belong to the selected Kanban Master"))
        if card.operation and card.operation != operation:
            frappe.throw(_("Card does not control the selected operation"))
        if card.get("crew_requirement_profile"):
            assignments.append({
                "scope": "Kanban Card",
                "reference": card.name,
                "profile": card.crew_requirement_profile,
            })

    policies = []
    for assignment in assignments:
        profile = assert_approved_crew_profile(
            assignment["profile"], company=master.company
        )
        policies.append(normalize_crew_profile(profile))
        assignment["profile_revision"] = cint(profile.revision)
        assignment["profile_name"] = profile.requirement_name
    return merge_crew_policies(policies, assignments)


@frappe.whitelist()
def preview_effective_crew_policy(kanban_master, operation, workstation=None,
                                  card_name=None, on_date=None):
    if not frappe.has_permission("CFG Kanban Crew Requirement Profile", "read"):
        frappe.throw(_("Not permitted to read crew requirements"), frappe.PermissionError)
    return get_effective_crew_policy(
        kanban_master, operation, workstation=workstation,
        card_name=card_name, on_date=on_date,
    )

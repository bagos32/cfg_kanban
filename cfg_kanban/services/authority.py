import frappe
from frappe.utils import cint, getdate, nowdate


CAPABILITIES = (
    "can_perform_work",
    "can_lead_crew",
    "can_supervise_trainees",
    "can_verify_work",
    "can_approve_progress",
    "can_close_on_behalf",
    "can_correct_records",
    "can_override_material",
    "can_cancel_or_bypass",
    "can_transfer_ownership",
)


LEGACY_CAPABILITIES = {
    "can_perform_work": lambda profile: bool(
        cint(profile.get("can_start")) or cint(profile.get("can_complete"))
    ),
    "can_lead_crew": lambda profile: profile.get("kanban_role") in (
        "Senior Operator", "Supervisor", "Development Proxy"
    ),
    "can_supervise_trainees": lambda profile: profile.get("kanban_role") in (
        "Supervisor", "Development Proxy"
    ),
    "can_verify_work": lambda profile: bool(
        cint(profile.get("can_verify_tasks"))
        or profile.get("kanban_role") in ("Supervisor", "Development Proxy")
    ),
    "can_approve_progress": lambda profile: bool(
        cint(profile.get("can_override"))
        or profile.get("kanban_role") in ("Supervisor", "Development Proxy")
    ),
    "can_close_on_behalf": lambda profile: bool(
        cint(profile.get("can_override"))
        or profile.get("kanban_role") in ("Supervisor", "Development Proxy")
    ),
    "can_correct_records": lambda profile: bool(cint(profile.get("can_override"))),
    "can_override_material": lambda profile: bool(cint(profile.get("can_override"))),
    "can_cancel_or_bypass": lambda profile: bool(
        cint(profile.get("can_override"))
        or profile.get("kanban_role") in ("Supervisor", "Development Proxy")
    ),
    "can_transfer_ownership": lambda profile: bool(
        cint(profile.get("can_override"))
        or profile.get("kanban_role") in ("Supervisor", "Development Proxy")
    ),
}


def resolve_authorities(profile, context=None, on_date=None, include_legacy=True):
    """Resolve additive multi-role authority without changing existing enforcement yet."""
    profile = _profile_doc(profile)
    context = frappe._dict(context or {})
    effective_date = getdate(on_date or nowdate())
    roles = []
    capabilities = set()

    for assignment in profile.get("authority_assignments") or []:
        if not _assignment_applies(assignment, context, effective_date):
            continue
        role = frappe.get_cached_doc(
            "CFG Kanban Authority Role", assignment.authority_role
        )
        if not role.active or not _role_company_applies(role, context):
            continue
        granted = [fieldname for fieldname in CAPABILITIES if cint(role.get(fieldname))]
        capabilities.update(granted)
        roles.append({
            "authority_role": role.name,
            "authority_name": role.authority_name,
            "company": assignment.company or role.company,
            "operation": assignment.operation,
            "workstation": assignment.workstation,
            "responsibility": assignment.responsibility,
            "effective_from": assignment.effective_from,
            "effective_until": assignment.effective_until,
            "capabilities": granted,
            "source": "Scoped Assignment",
        })

    legacy = []
    if include_legacy:
        legacy = [
            fieldname for fieldname, resolver in LEGACY_CAPABILITIES.items()
            if resolver(profile)
        ]
        capabilities.update(legacy)

    return {
        "operator_profile": profile.name,
        "employee": profile.employee,
        "context": dict(context),
        "roles": roles,
        "capabilities": sorted(capabilities),
        "legacy_capabilities": sorted(legacy),
        "legacy_fallback_active": bool(include_legacy),
    }


def has_authority(profile, capability, context=None, on_date=None, include_legacy=True):
    if capability not in CAPABILITIES:
        frappe.throw(f"Unsupported Kanban authority capability: {capability}")
    result = resolve_authorities(
        profile,
        context=context,
        on_date=on_date,
        include_legacy=include_legacy,
    )
    return capability in result["capabilities"]


def has_authority_role(profile, authority_role, context=None, on_date=None):
    """Match one explicit scoped role; the legacy dropdown cannot impersonate it."""
    if not authority_role:
        return True
    profile = _profile_doc(profile)
    context = frappe._dict(context or {})
    effective_date = getdate(on_date or nowdate())
    for assignment in profile.get("authority_assignments") or []:
        if assignment.authority_role != authority_role:
            continue
        if not _assignment_applies(assignment, context, effective_date):
            continue
        role = frappe.get_cached_doc("CFG Kanban Authority Role", authority_role)
        if role.active and _role_company_applies(role, context):
            return True
    return False


def _profile_doc(profile):
    if getattr(profile, "doctype", None) == "CFG Kanban Operator Profile":
        return profile
    if isinstance(profile, str):
        return frappe.get_doc("CFG Kanban Operator Profile", profile)
    return frappe._dict(profile)


def _assignment_applies(assignment, context, effective_date):
    if assignment.effective_from and getdate(assignment.effective_from) > effective_date:
        return False
    if assignment.effective_until and getdate(assignment.effective_until) < effective_date:
        return False
    for fieldname in ("company", "operation", "workstation", "responsibility"):
        assigned = assignment.get(fieldname)
        requested = context.get(fieldname)
        if assigned and assigned != requested:
            return False
    return True


def _role_company_applies(role, context):
    return not role.company or role.company == context.get("company")

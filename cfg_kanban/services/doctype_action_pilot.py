"""Explicit setup for the harmless Gate 1 DocType Action pilot targets.

Nothing in this module runs during migrate.  A maintenance administrator must
deliberately invoke the setup action from the Action Profile list.  This keeps
test allowlisting visible, reviewable and absent from sites that do not want the
pilot.
"""

import frappe

from cfg_kanban.services.doctype_actions import validate_profile_configuration


PILOT_PROFILES = (
    {
        "profile_name": "CFG Gate 1 Pilot - Draft",
        "target_doctype": "CFG Action Pilot Draft",
        "posting_policy": "Save Draft",
    },
    {
        "profile_name": "CFG Gate 1 Pilot - Submit",
        "target_doctype": "CFG Action Pilot Submission",
        "posting_policy": "Submit When Authorized",
    },
)


def install_pilot_configuration():
    """Create or restore the two fixed Gate 1 policies and profiles.

    The caller already passed the Action Engine maintenance-role check.  Normal
    document permissions are intentionally retained for every configuration
    write so this is not a hidden privileged installer.
    """
    created = []
    updated = []
    for definition in PILOT_PROFILES:
        target = definition["target_doctype"]
        _ensure_policy(target, definition["posting_policy"])
        profile, was_created = _ensure_profile(definition)
        result = validate_profile_configuration(profile)
        profile.db_set({
            "validation_status": "Valid",
            "last_validated_at": frappe.utils.now_datetime(),
            "metadata_fingerprint": result["metadata_fingerprint"],
        })
        profile.reload()
        profile.enabled = 1
        profile.save()
        (created if was_created else updated).append(profile.name)

    return {
        "created": created,
        "updated": updated,
        "draft_profile": PILOT_PROFILES[0]["profile_name"],
        "submit_profile": PILOT_PROFILES[1]["profile_name"],
        "message": (
            "Gate 1 pilot profiles are ready. Bind one profile at a time to a "
            "development Service Task Schedule and follow the pilot test guide."
        ),
    }


def _ensure_policy(target_doctype, posting_policy):
    allow_submit = posting_policy == "Submit When Authorized"
    if frappe.db.exists("CFG Kanban DocType Action Policy", target_doctype):
        policy = frappe.get_doc("CFG Kanban DocType Action Policy", target_doctype)
        policy.enabled = 1
        policy.risk_category = "Low"
        policy.allow_create = 1
        policy.allow_submit = int(allow_submit)
        policy.allow_currency_fields = 0
        policy.allow_exception_logged_failure = 0
        policy.notes = (
            "App-owned Gate 1 pilot target only. Do not use for operational records."
        )
        policy.save()
        return policy
    return frappe.get_doc({
        "doctype": "CFG Kanban DocType Action Policy",
        "target_doctype": target_doctype,
        "enabled": 1,
        "risk_category": "Low",
        "allow_create": 1,
        "allow_submit": int(allow_submit),
        "allow_currency_fields": 0,
        "allow_exception_logged_failure": 0,
        "notes": (
            "App-owned Gate 1 pilot target only. Do not use for operational records."
        ),
    }).insert()


def _ensure_profile(definition):
    name = definition["profile_name"]
    if frappe.db.exists("CFG Kanban DocType Action Profile", name):
        profile = frappe.get_doc("CFG Kanban DocType Action Profile", name)
        _apply_profile_definition(profile, definition)
        profile.save()
        return profile, False

    profile = frappe.get_doc({
        "doctype": "CFG Kanban DocType Action Profile",
        "profile_name": name,
        "description": (
            "Non-production Gate 1 pilot. Remove it from Task Schedules after acceptance."
        ),
        "target_doctype": definition["target_doctype"],
        "action_mode": "Create New",
        "posting_policy": definition["posting_policy"],
        "verification_policy": "No Additional Verification",
        "failure_policy": "Blocking",
        "form_title": name,
        "form_instructions": (
            "Pilot only: enter an outcome and at least one observation."
        ),
        "max_child_rows": 10,
        "enabled": 0,
    })
    _apply_mappings(profile)
    profile.insert()
    return profile, True


def _apply_profile_definition(profile, definition):
    profile.enabled = 0
    profile.description = (
        "Non-production Gate 1 pilot. Remove it from Task Schedules after acceptance."
    )
    profile.target_doctype = definition["target_doctype"]
    profile.action_mode = "Create New"
    profile.posting_policy = definition["posting_policy"]
    profile.verification_policy = "No Additional Verification"
    profile.failure_policy = "Blocking"
    profile.form_title = definition["profile_name"]
    profile.form_instructions = (
        "Pilot only: enter an outcome and at least one observation."
    )
    profile.max_child_rows = 10
    profile.set("parent_field_mappings", [])
    profile.set("child_table_configs", [])
    profile.set("child_column_mappings", [])
    _apply_mappings(profile)


def _apply_mappings(profile):
    parent = (
        ("task_reference", "Server Context", "task_name", "Service Task", 1, 1),
        ("performed_by", "Server Context", "employee", "Performed By", 1, 1),
        ("summary", "Operator Input", None, "Summary", 1, 0),
        ("outcome", "Operator Input", None, "Outcome", 1, 0),
        ("notes", "Operator Input", None, "Notes", 0, 0),
    )
    for order, (fieldname, source_type, source_key, label, required, read_only) in enumerate(
        parent, start=1
    ):
        profile.append("parent_field_mappings", {
            "target_fieldname": fieldname,
            "source_type": source_type,
            "source_key": source_key,
            "operator_label": label,
            "show_to_operator": 1,
            "required_in_kanban": required,
            "read_only": read_only,
            "display_order": order * 10,
        })

    profile.append("child_table_configs", {
        "table_fieldname": "observations",
        "operator_heading": "Pilot Observations",
        "rows_mode": "Repeatable",
        "min_rows": 1,
        "max_rows": 10,
        "allow_add_delete_rows": 1,
        "display_order": 10,
    })
    child = (
        ("check_item", "Check Item", 1),
        ("measured_value", "Measured Value", 1),
        ("accepted", "Accepted", 1),
        ("remarks", "Remarks", 0),
    )
    for order, (fieldname, label, required) in enumerate(child, start=1):
        profile.append("child_column_mappings", {
            "table_fieldname": "observations",
            "child_fieldname": fieldname,
            "source_type": "Operator Input",
            "operator_label": label,
            "required_in_kanban": required,
            "read_only": 0,
            "display_order": order * 10,
        })

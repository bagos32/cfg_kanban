import frappe

from cfg_kanban.services import doctype_actions


@frappe.whitelist()
def get_target_metadata(target_doctype):
    doctype_actions.require_configuration_role()
    return doctype_actions.target_metadata(target_doctype)


@frappe.whitelist()
def validate_configuration(profile_name):
    doctype_actions.require_configuration_role()
    profile = frappe.get_doc("CFG Kanban DocType Action Profile", profile_name)
    profile.check_permission("write")
    result = doctype_actions.validate_profile_configuration(profile)
    frappe.db.set_value(
        profile.doctype,
        profile.name,
        {
            "validation_status": "Valid",
            "last_validated_at": frappe.utils.now_datetime(),
            "metadata_fingerprint": result["metadata_fingerprint"],
        },
        update_modified=True,
    )
    result["validation_status"] = "Valid"
    return result


@frappe.whitelist()
def preview_operator_form(profile_name):
    doctype_actions.require_configuration_role()
    profile = frappe.get_doc("CFG Kanban DocType Action Profile", profile_name)
    profile.check_permission("read")
    return doctype_actions.profile_preview(profile)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def allowed_target_doctype_query(doctype, txt, searchfield, start, page_len, filters):
    return doctype_actions.allowed_target_query(
        doctype, txt, searchfield, start, page_len, filters
    )

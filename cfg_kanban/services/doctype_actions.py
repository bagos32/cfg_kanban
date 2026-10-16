"""Metadata and policy foundation for the controlled DocType Action Engine.

This module deliberately does not create target documents yet.  Gate 1 starts by
making target approval and profile validation explicit, default-deny, and based
on the effective Frappe metadata installed on the site.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate


MAINTAINER_ROLES = {"System Manager", "CFG Kanban System Maintenance"}
SUPPORTED_VALUE_FIELD_TYPES = {
    "Data", "Small Text", "Text", "Long Text", "Int", "Float", "Currency",
    "Check", "Select", "Date", "Datetime", "Link",
}
SYSTEM_FIELDNAMES = {
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "parent", "parentfield", "parenttype", "doctype", "workflow_state", "status",
    "naming_series", "series", "amended_from", "_user_tags", "_comments", "_assign",
    "_liked_by",
}
SERVER_CONTEXT_KEYS = {
    "employee", "task_name", "company", "location", "asset", "workstation",
    "server_timestamp",
}
SOURCE_TYPES = {"Operator Input", "Service Task Field", "Server Context", "Fixed Value"}
HARD_DENIED_TARGETS = {
    "Work Order", "Job Card", "Stock Entry", "Stock Entry Detail", "Batch", "BOM",
    "Production Plan", "Material Request", "Purchase Order", "Purchase Receipt",
    "Purchase Receipt Item", "Sales Order", "Delivery Note", "Delivery Note Item",
    "Pick List", "Stock Reconciliation", "Stock Ledger Entry", "Serial No",
    "Serial and Batch Bundle", "Subcontracting Order", "Subcontracting Receipt",
    "GL Entry", "Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice",
    "Payroll Entry", "Salary Slip", "Employee", "User", "Role", "DocPerm",
    "Custom DocPerm", "System Settings", "DocType", "Custom Field", "Property Setter",
    "Server Script", "Client Script", "Webhook", "OAuth Client", "API Access Log",
    "CFG ERP Command", "CFG Kanban Cycle", "CFG Kanban Signal",
}
HARD_DENIED_MODULES = {
    "Accounts", "Payments", "Payroll", "Users and Permissions", "Core", "CFG Kanban",
}
MAX_CHILD_ROWS = 50


def require_configuration_role():
    if frappe.session.user == "Administrator":
        return
    if not MAINTAINER_ROLES.intersection(frappe.get_roles()):
        frappe.throw(
            _("Only a System Manager or CFG Kanban System Maintenance user may configure DocType Actions."),
            frappe.PermissionError,
        )


def validate_target_policy(policy):
    meta = _target_meta(policy.target_doctype)
    _assert_not_hard_denied(meta)
    if not cint(policy.allow_create):
        frappe.throw(_("Enable Create / Save Draft for this target policy."))
    if cint(policy.allow_submit) and not cint(meta.is_submittable):
        frappe.throw(
            _("{0} is not submittable; its policy cannot allow Submit.").format(
                frappe.bold(policy.target_doctype)
            )
        )
    if cint(policy.allow_submit):
        _assert_no_active_workflow(meta)


def validate_profile_structure(profile):
    if not profile.target_doctype:
        return
    policy, meta = get_target_policy(profile.target_doctype, "create")
    if profile.posting_policy == "Submit When Authorized":
        _assert_policy_action(policy, meta, "submit")
    if (profile.failure_policy == "Exception Logged"
            and not cint(policy.allow_exception_logged_failure)):
        frappe.throw(_(
            "The approved target policy does not allow non-blocking Exception Logged failures."
        ))
    _validate_bounds(profile)
    _validate_condition(profile.trigger_condition, "Conditional Trigger")

    parent_fields = _field_map(meta)
    seen = set()
    for row in profile.parent_field_mappings or []:
        _validate_mapping_row(row, parent_fields, "Parent Field")
        _validate_policy_field(policy, parent_fields[row.target_fieldname])
        _validate_company_mapping(row, profile.company, "target_fieldname")
        if row.target_fieldname in seen:
            frappe.throw(_("Parent field {0} is mapped more than once.").format(
                frappe.bold(row.target_fieldname)
            ))
        seen.add(row.target_fieldname)

    table_fields = _table_map(meta)
    configured_tables = set()
    for row in profile.child_table_configs or []:
        field = table_fields.get(row.table_fieldname)
        if not field:
            frappe.throw(_("Unknown or unsupported target child table {0}.").format(
                frappe.bold(row.table_fieldname)
            ))
        if row.table_fieldname in configured_tables:
            frappe.throw(_("Child table {0} is configured more than once.").format(
                frappe.bold(row.table_fieldname)
            ))
        configured_tables.add(row.table_fieldname)
        row.child_doctype = field.options
        minimum, maximum = cint(row.min_rows), cint(row.max_rows)
        if minimum < 0 or maximum < 0 or minimum > maximum:
            frappe.throw(_("Invalid minimum/maximum rows for {0}.").format(
                frappe.bold(row.table_fieldname)
            ))
        if maximum > min(cint(profile.max_child_rows), MAX_CHILD_ROWS):
            frappe.throw(_("{0} exceeds the profile child-row safety limit.").format(
                frappe.bold(row.table_fieldname)
            ))

    child_seen = set()
    child_meta_cache = {}
    for row in profile.child_column_mappings or []:
        if row.table_fieldname not in configured_tables:
            frappe.throw(_("Child column {0} references an unconfigured table {1}.").format(
                frappe.bold(row.child_fieldname), frappe.bold(row.table_fieldname)
            ))
        table_field = table_fields[row.table_fieldname]
        child_meta = child_meta_cache.setdefault(
            table_field.options, frappe.get_meta(table_field.options)
        )
        _validate_mapping_row(row, _field_map(child_meta), "Child Column",
                              fieldname_attr="child_fieldname")
        _validate_policy_field(policy, _field_map(child_meta)[row.child_fieldname])
        _validate_company_mapping(row, profile.company, "child_fieldname")
        identity = (row.table_fieldname, row.child_fieldname)
        if identity in child_seen:
            frappe.throw(_("Child column {0}.{1} is mapped more than once.").format(
                row.table_fieldname, row.child_fieldname
            ))
        child_seen.add(identity)


def validate_profile_configuration(profile):
    validate_profile_structure(profile)
    if not profile.target_doctype:
        frappe.throw(_("Target DocType is required before validation."))
    meta = _target_meta(profile.target_doctype)
    mapped = {row.target_fieldname for row in profile.parent_field_mappings or []}
    missing = []
    for field in _eligible_value_fields(meta):
        if cint(field.reqd) and not field.default and not field.fetch_from and field.fieldname not in mapped:
            missing.append(f"{field.label} ({field.fieldname})")
    if missing:
        frappe.throw(_("Map all mandatory target fields before validation: {0}").format(
            ", ".join(missing)
        ))
    table_configs = {row.table_fieldname: row for row in profile.child_table_configs or []}
    child_mappings = {}
    for row in profile.child_column_mappings or []:
        child_mappings.setdefault(row.table_fieldname, set()).add(row.child_fieldname)
    child_missing = []
    for table_field in _eligible_table_fields(meta):
        config = table_configs.get(table_field.fieldname)
        if cint(table_field.reqd) and not config:
            child_missing.append(f"{table_field.label} ({table_field.fieldname}) table")
            continue
        if not config:
            continue
        if cint(table_field.reqd) and cint(config.min_rows) < 1:
            child_missing.append(f"{table_field.label} ({table_field.fieldname}) minimum row")
        mapped_columns = child_mappings.get(table_field.fieldname, set())
        child_meta = frappe.get_meta(table_field.options)
        for field in _eligible_value_fields(child_meta):
            if (cint(field.reqd) and not field.default and not field.fetch_from
                    and field.fieldname not in mapped_columns):
                child_missing.append(
                    f"{table_field.fieldname}.{field.label} ({field.fieldname})"
                )
    if child_missing:
        frappe.throw(_("Map all mandatory child-table requirements before validation: {0}").format(
            ", ".join(child_missing)
        ))
    fingerprint = metadata_fingerprint(meta)
    return {
        "target_doctype": profile.target_doctype,
        "metadata_fingerprint": fingerprint,
        "is_submittable": bool(meta.is_submittable),
        "parent_fields": len(profile.parent_field_mappings or []),
        "child_tables": len(profile.child_table_configs or []),
        "child_columns": len(profile.child_column_mappings or []),
    }


def profile_configuration_signature(profile):
    return _hash(profile_configuration_payload(profile))


def profile_configuration_payload(profile):
    return {
        "company": profile.company,
        "target_doctype": profile.target_doctype,
        "action_mode": profile.action_mode,
        "posting_policy": profile.posting_policy,
        "verification_policy": profile.verification_policy,
        "failure_policy": profile.failure_policy,
        "form_title": profile.form_title,
        "form_instructions": profile.form_instructions,
        "trigger_condition": _normalized_json(profile.trigger_condition),
        "max_child_rows": cint(profile.max_child_rows),
        "parent": [_mapping_snapshot(row, "target_fieldname")
                   for row in profile.parent_field_mappings or []],
        "tables": [{
            "table_fieldname": row.table_fieldname,
            "child_doctype": row.child_doctype,
            "operator_heading": row.operator_heading,
            "rows_mode": row.rows_mode,
            "min_rows": cint(row.min_rows),
            "max_rows": cint(row.max_rows),
            "allow_add_delete_rows": cint(row.allow_add_delete_rows),
            "display_order": cint(row.display_order),
        } for row in profile.child_table_configs or []],
        "columns": [_mapping_snapshot(row, "child_fieldname", row.table_fieldname)
                    for row in profile.child_column_mappings or []],
    }


def executable_profile_snapshot(profile_name):
    profile = frappe.get_doc("CFG Kanban DocType Action Profile", profile_name)
    if not cint(profile.enabled):
        frappe.throw(_("DocType Action Profile {0} is disabled.").format(
            frappe.bold(profile.name)
        ))
    if profile.validation_status != "Valid" or not profile.metadata_fingerprint:
        frappe.throw(_("DocType Action Profile {0} is not validated.").format(
            frappe.bold(profile.name)
        ))
    result = validate_profile_configuration(profile)
    if result["metadata_fingerprint"] != profile.metadata_fingerprint:
        frappe.throw(_(
            "Target metadata changed after this profile was validated. Disable and revalidate it."
        ))
    policy, _meta = get_target_policy(profile.target_doctype, "create")
    if profile.posting_policy == "Submit When Authorized":
        _assert_policy_action(policy, _meta, "submit")
    configuration = profile_configuration_payload(profile)
    snapshot = {
        "profile": profile.name,
        "profile_name": profile.profile_name,
        "configuration_revision": cint(profile.configuration_revision),
        "validation_status": profile.validation_status,
        "last_validated_at": str(profile.last_validated_at or ""),
        "metadata_fingerprint": profile.metadata_fingerprint,
        "configuration": configuration,
        "target_policy": {
            "name": policy.name,
            "target_doctype": policy.target_doctype,
            "risk_category": policy.risk_category,
            "allow_create": cint(policy.allow_create),
            "allow_submit": cint(policy.allow_submit),
            "allow_currency_fields": cint(policy.allow_currency_fields),
            "allow_exception_logged_failure": cint(
                policy.allow_exception_logged_failure
            ),
        },
    }
    return profile, snapshot, _hash(snapshot)


def metadata_fingerprint(meta):
    fields = []
    for field in meta.fields:
        fields.append({
            "fieldname": field.fieldname,
            "fieldtype": field.fieldtype,
            "options": field.options,
            "reqd": cint(field.reqd),
            "read_only": cint(field.read_only),
            "hidden": cint(field.hidden),
            "default": field.default,
            "fetch_from": field.fetch_from,
        })
    return _hash({
        "doctype": meta.name,
        "module": meta.module,
        "istable": cint(meta.istable),
        "issingle": cint(meta.issingle),
        "is_submittable": cint(meta.is_submittable),
        "fields": fields,
    })


def target_metadata(target_doctype):
    _policy, meta = get_target_policy(target_doctype, "create")
    parent_fields = [_field_payload(field) for field in _eligible_value_fields(meta)]
    tables = []
    for field in _eligible_table_fields(meta):
        child_meta = frappe.get_meta(field.options)
        tables.append({
            "fieldname": field.fieldname,
            "label": field.label,
            "child_doctype": field.options,
            "columns": [_field_payload(child) for child in _eligible_value_fields(child_meta)],
        })
    return {
        "target_doctype": target_doctype,
        "is_submittable": bool(meta.is_submittable),
        "metadata_fingerprint": metadata_fingerprint(meta),
        "parent_fields": parent_fields,
        "child_tables": tables,
    }


def profile_preview(profile):
    result = validate_profile_configuration(profile)
    metadata = target_metadata(profile.target_doctype)
    parent_by_name = {row["fieldname"]: row for row in metadata["parent_fields"]}
    table_by_name = {row["fieldname"]: row for row in metadata["child_tables"]}
    parents = []
    for row in sorted(profile.parent_field_mappings or [], key=lambda value: (cint(value.display_order), value.idx)):
        field = dict(parent_by_name[row.target_fieldname])
        field.update({
            "label": row.operator_label or field["label"],
            "source_type": row.source_type,
            "required": bool(row.required_in_kanban or field["required"]),
            "read_only": bool(row.read_only or row.source_type != "Operator Input"),
            "show_to_operator": bool(row.show_to_operator),
            "default_value": row.default_value,
            "visible_condition": _json_value(row.visible_condition),
        })
        parents.append(field)
    tables = []
    for config in sorted(profile.child_table_configs or [], key=lambda value: (cint(value.display_order), value.idx)):
        table_meta = table_by_name[config.table_fieldname]
        column_meta = {row["fieldname"]: row for row in table_meta["columns"]}
        columns = []
        for row in sorted(
            [value for value in profile.child_column_mappings or []
             if value.table_fieldname == config.table_fieldname],
            key=lambda value: (cint(value.display_order), value.idx),
        ):
            field = dict(column_meta[row.child_fieldname])
            field.update({
                "label": row.operator_label or field["label"],
                "source_type": row.source_type,
                "required": bool(row.required_in_kanban or field["required"]),
                "read_only": bool(row.read_only or row.source_type != "Operator Input"),
                "default_value": row.default_value,
                "visible_condition": _json_value(row.visible_condition),
            })
            columns.append(field)
        tables.append({
            "fieldname": config.table_fieldname,
            "label": config.operator_heading or table_meta["label"],
            "rows_mode": config.rows_mode,
            "min_rows": cint(config.min_rows),
            "max_rows": cint(config.max_rows),
            "allow_add_delete_rows": bool(config.allow_add_delete_rows),
            "columns": columns,
        })
    result.update({
        "profile_name": profile.profile_name,
        "form_title": profile.form_title or profile.profile_name,
        "form_instructions": profile.form_instructions,
        "posting_policy": profile.posting_policy,
        "parent_fields": parents,
        "child_tables": tables,
    })
    return result


def get_target_policy(target_doctype, action="create"):
    meta = _target_meta(target_doctype)
    _assert_not_hard_denied(meta)
    name = frappe.db.get_value(
        "CFG Kanban DocType Action Policy",
        {"target_doctype": target_doctype, "enabled": 1},
        "name",
    )
    if not name:
        frappe.throw(_("Target DocType {0} is not on the approved CFG Kanban allowlist.").format(
            frappe.bold(target_doctype)
        ), frappe.PermissionError)
    policy = frappe.get_doc("CFG Kanban DocType Action Policy", name)
    _assert_policy_action(policy, meta, action)
    return policy, meta


def allowed_target_query(doctype, txt, searchfield, start, page_len, filters):
    del doctype, searchfield, filters
    require_configuration_role()
    rows = frappe.get_all(
        "CFG Kanban DocType Action Policy",
        filters={"enabled": 1, "allow_create": 1, "target_doctype": ["like", f"%{txt}%"]},
        fields=["target_doctype"], order_by="target_doctype asc",
        start=cint(start), page_length=cint(page_len),
    )
    allowed = []
    for row in rows:
        try:
            meta = _target_meta(row.target_doctype)
            _assert_not_hard_denied(meta)
        except Exception:
            continue
        allowed.append([row.target_doctype])
    return allowed


def _assert_policy_action(policy, meta, action):
    fieldname = {"create": "allow_create", "submit": "allow_submit"}.get(action)
    if not fieldname or not cint(policy.get(fieldname)):
        frappe.throw(_("The approved policy does not allow {0} for {1}.").format(
            action, frappe.bold(meta.name)
        ), frappe.PermissionError)
    if action == "submit" and not cint(meta.is_submittable):
        frappe.throw(_("Target DocType {0} does not support submission.").format(
            frappe.bold(meta.name)
        ))
    if action == "submit":
        _assert_no_active_workflow(meta)


def _target_meta(target_doctype):
    if not target_doctype or not frappe.db.exists("DocType", target_doctype):
        frappe.throw(_("Target DocType {0} does not exist.").format(
            frappe.bold(target_doctype or "(empty)")
        ))
    meta = frappe.get_meta(target_doctype)
    if cint(meta.istable):
        frappe.throw(_("Child-table DocTypes cannot be direct DocType Action targets."))
    if cint(meta.issingle):
        frappe.throw(_("Single DocTypes cannot be direct DocType Action targets."))
    if cint(meta.get("is_virtual")) or cint(meta.get("is_tree")):
        frappe.throw(_("Virtual and tree DocTypes cannot be direct DocType Action targets."))
    return meta


def _assert_not_hard_denied(meta):
    if meta.name in HARD_DENIED_TARGETS or meta.module in HARD_DENIED_MODULES:
        frappe.throw(
            _("{0} is hard-denied for the generic DocType Action Engine. Use its dedicated controlled integration.").format(
                frappe.bold(meta.name)
            ),
            frappe.PermissionError,
        )


def _eligible_value_fields(meta):
    return [field for field in meta.fields if _is_eligible_value_field(field)]


def _eligible_table_fields(meta):
    return [field for field in meta.fields
            if field.fieldtype == "Table" and field.options and not cint(field.hidden)]


def _is_eligible_value_field(field):
    return (
        field.fieldtype in SUPPORTED_VALUE_FIELD_TYPES
        and field.fieldname not in SYSTEM_FIELDNAMES
        and not cint(field.hidden)
        and not cint(field.read_only)
    )


def _field_map(meta):
    return {field.fieldname: field for field in _eligible_value_fields(meta)}


def _table_map(meta):
    return {field.fieldname: field for field in _eligible_table_fields(meta)}


def _field_payload(field):
    return {
        "fieldname": field.fieldname,
        "label": field.label or field.fieldname,
        "fieldtype": field.fieldtype,
        "options": field.options,
        "required": bool(field.reqd),
        "default": field.default,
        "description": field.description,
    }


def _validate_mapping_row(row, fields, label, fieldname_attr="target_fieldname"):
    fieldname = row.get(fieldname_attr)
    field = fields.get(fieldname)
    if not field:
        frappe.throw(_("Unknown, read-only, hidden, or unsupported {0}: {1}").format(
            label, frappe.bold(fieldname)
        ))
    if row.source_type not in SOURCE_TYPES:
        frappe.throw(_("Invalid source type for {0}.").format(frappe.bold(fieldname)))
    if row.source_type == "Service Task Field" and not row.source_key:
        frappe.throw(_("Service Task Field mapping {0} requires a Source Key.").format(
            frappe.bold(fieldname)
        ))
    if row.source_type == "Server Context" and row.source_key not in SERVER_CONTEXT_KEYS:
        frappe.throw(_("Server Context mapping {0} must use an approved context key.").format(
            frappe.bold(fieldname)
        ))
    if row.source_type == "Fixed Value":
        if row.fixed_value in (None, "") and cint(field.reqd):
            frappe.throw(_("Fixed mapping {0} requires a value.").format(frappe.bold(fieldname)))
        _validate_typed_value(field, row.fixed_value)
    if row.source_type == "Operator Input":
        if row.get("show_to_operator") is not None and not cint(row.show_to_operator):
            if row.default_value in (None, ""):
                frappe.throw(_("Operator Input mapping {0} must be visible or have a default.").format(
                    frappe.bold(fieldname)
                ))
        if row.default_value not in (None, ""):
            _validate_typed_value(field, row.default_value)
    _validate_condition(row.visible_condition, f"Visible Condition for {fieldname}")


def _validate_company_mapping(row, profile_company, fieldname_attr):
    if row.get(fieldname_attr) != "company":
        return
    if row.source_type not in {"Server Context", "Fixed Value"}:
        frappe.throw(_("Company must come from Server Context or a protected Fixed Value."))
    if row.source_type == "Server Context" and row.source_key != "company":
        frappe.throw(_("Company Server Context mapping must use Source Key company."))
    if (row.source_type == "Fixed Value" and profile_company
            and row.fixed_value != profile_company):
        frappe.throw(_("Fixed Company must match the Action Profile Company."))


def _validate_policy_field(policy, field):
    if field.fieldtype == "Currency" and not cint(policy.allow_currency_fields):
        frappe.throw(_(
            "Currency field {0} requires Allow Currency Field Mapping on the target policy."
        ).format(frappe.bold(field.fieldname)))


def _assert_no_active_workflow(meta):
    if frappe.db.exists("Workflow", {"document_type": meta.name, "is_active": 1}):
        frappe.throw(_(
            "Generic DocType Action submission is disabled for {0} because it has an active "
            "Workflow. Use Save Draft or a dedicated reviewed integration."
        ).format(frappe.bold(meta.name)))


def _validate_typed_value(field, value):
    if value in (None, ""):
        return
    try:
        if field.fieldtype == "Int":
            int(value)
        elif field.fieldtype in {"Float", "Currency"}:
            float(value)
        elif field.fieldtype == "Check":
            if str(value).lower() not in {"0", "1", "true", "false", "yes", "no"}:
                raise ValueError
        elif field.fieldtype == "Date":
            getdate(value)
        elif field.fieldtype == "Datetime":
            get_datetime(value)
        elif field.fieldtype == "Select" and field.options:
            if str(value) not in str(field.options).splitlines():
                raise ValueError
        elif field.fieldtype == "Link" and value and not frappe.db.exists(field.options, value):
            frappe.throw(_("Fixed Link value {0} does not exist in {1}.").format(
                frappe.bold(value), frappe.bold(field.options)
            ))
    except (TypeError, ValueError):
        frappe.throw(_("Fixed value for {0} is not a valid {1}.").format(
            frappe.bold(field.label), field.fieldtype
        ))


def _validate_bounds(profile):
    maximum = cint(profile.max_child_rows)
    if maximum <= 0 or maximum > MAX_CHILD_ROWS:
        frappe.throw(_("Max Child Rows must be between 1 and {0}.").format(MAX_CHILD_ROWS))


def _validate_condition(value, label):
    if not value:
        return
    condition = _json_value(value)
    _validate_condition_node(condition, label, 0)


def _validate_condition_node(node, label, depth):
    if depth > 4 or not isinstance(node, dict):
        frappe.throw(_("{0} must be a safe structured JSON condition.").format(label))
    groups = [key for key in ("all", "any") if key in node]
    if groups:
        if len(groups) != 1 or set(node) != {groups[0]} or not isinstance(node[groups[0]], list):
            frappe.throw(_("{0} has an invalid condition group.").format(label))
        for child in node[groups[0]]:
            _validate_condition_node(child, label, depth + 1)
        return
    if set(node) - {"field", "operator", "value"}:
        frappe.throw(_("{0} contains unsupported keys.").format(label))
    if not node.get("field") or node.get("operator") not in {
        "equals", "not_equals", "in", "not_in", "greater_than", "less_than",
    }:
        frappe.throw(_("{0} contains an unsupported comparison.").format(label))


def _mapping_snapshot(row, fieldname_attr, table_fieldname=None):
    return {
        "table_fieldname": table_fieldname,
        "fieldname": row.get(fieldname_attr),
        "source_type": row.source_type,
        "source_key": row.source_key,
        "fixed_value": row.fixed_value,
        "operator_label": row.operator_label,
        "show_to_operator": cint(row.get("show_to_operator", 1)),
        "required_in_kanban": cint(row.required_in_kanban),
        "read_only": cint(row.read_only),
        "display_order": cint(row.display_order),
        "visible_condition": _normalized_json(row.visible_condition),
        "default_value": row.default_value,
    }


def _json_value(value):
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        frappe.throw(_("Condition must be valid JSON; Python or JavaScript expressions are not allowed."))


def _normalized_json(value):
    parsed = _json_value(value)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")) if parsed is not None else ""


def _hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


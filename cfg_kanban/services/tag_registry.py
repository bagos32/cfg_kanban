import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.physical_identity import parse_tag_range_code


RANGE_FIELDS = [
    "name", "registry_code", "active", "prefix", "start_number", "end_number",
    "number_width", "child_separator", "child_count", "issued_company",
]


def resolve_tag_range_candidate(scan_value, registry_name=None, include_inactive=False):
    """Resolve a range-backed printed identity without creating database records."""
    filters = {}
    if registry_name:
        filters["name"] = registry_name
    if not include_inactive:
        filters["active"] = 1
    registries = frappe.get_all(
        "CFG Kanban Tag Range Registry",
        filters=filters,
        fields=RANGE_FIELDS,
        order_by="prefix desc, number_width desc, start_number asc",
        limit_page_length=0,
    )
    candidates = []
    for registry in registries:
        parsed = parse_tag_range_code(scan_value, registry)
        if not parsed:
            continue
        candidates.append({
            "identity_type": "Tag Range Candidate",
            "name": parsed["visible_code"],
            "visible_code": parsed["visible_code"],
            "matched_by": "tag_range_registry",
            "range_registry": registry.name,
            "tag_family": parsed["main_code"],
            "tag_role": parsed["tag_role"],
            "child_index": parsed["child_index"],
            "serial_number": parsed["serial_number"],
            "state": "Unmaterialized",
            "issued_company": registry.issued_company,
            "child_count": registry.child_count,
            "child_separator": registry.child_separator,
        })
    if len(candidates) > 1:
        names = ", ".join(row["range_registry"] for row in candidates)
        frappe.throw(
            f"Physical code {scan_value} matches multiple Tag Range Registries ({names}). "
            "Deactivate and correct the overlapping registry definitions."
        )
    return candidates[0] if candidates else None


def materialize_tag_family_for_code(scan_value, expected_registry=None):
    """Create the exact family and child identities on first controlled activation."""
    candidate = resolve_tag_range_candidate(scan_value, expected_registry)
    if not candidate:
        if expected_registry:
            frappe.throw(
                f"Physical code {scan_value} is not valid in Tag Range Registry "
                f"{expected_registry}"
            )
        return None

    registry_name = candidate["range_registry"]
    frappe.db.sql(
        "select name from `tabCFG Kanban Tag Range Registry` where name=%s for update",
        registry_name,
    )
    registry = frappe.get_doc("CFG Kanban Tag Range Registry", registry_name)
    if not registry.active:
        frappe.throw(f"Tag Range Registry {registry.name} is inactive")
    candidate = resolve_tag_range_candidate(scan_value, registry.name)
    family_name = candidate["tag_family"]
    existing = frappe.db.exists("CFG Kanban Tag Family", family_name)
    if existing:
        family = frappe.get_doc("CFG Kanban Tag Family", existing)
        _validate_existing_family(family, registry)
        if not family.range_registry:
            family.db_set("range_registry", registry.name, update_modified=False)
            family.range_registry = registry.name
        _update_registry_usage(registry, family.name)
        return family

    family = frappe.get_doc({
        "doctype": "CFG Kanban Tag Family",
        "family_code": family_name,
        "active": 1,
        "range_registry": registry.name,
        "child_count": registry.child_count,
        "child_separator": registry.child_separator,
        "issued_company": registry.issued_company,
        "description": f"Lazily materialized from range {registry.name}",
    }).insert(ignore_permissions=True)
    _update_registry_usage(registry, family.name)
    return family


def _validate_existing_family(family, registry):
    if family.range_registry and family.range_registry != registry.name:
        frappe.throw(
            f"Tag Family {family.name} already belongs to Range Registry "
            f"{family.range_registry}"
        )
    expected = {
        "issued_company": registry.issued_company,
        "child_count": int(registry.child_count or 0),
        "child_separator": registry.child_separator or "-",
    }
    actual = {
        "issued_company": family.issued_company,
        "child_count": int(family.child_count or 0),
        "child_separator": family.child_separator or "-",
    }
    if actual != expected:
        frappe.throw(
            f"Existing Tag Family {family.name} conflicts with Range Registry {registry.name}. "
            "Issuing Company, child count, and child separator must match."
        )


def _update_registry_usage(registry, family_name):
    materialized_count = frappe.db.count(
        "CFG Kanban Tag Family", {"range_registry": registry.name}
    )
    frappe.db.set_value(
        "CFG Kanban Tag Range Registry",
        registry.name,
        {
            "materialized_count": materialized_count,
            "last_materialized_tag": family_name,
            "last_materialized_on": now_datetime(),
        },
        update_modified=False,
    )

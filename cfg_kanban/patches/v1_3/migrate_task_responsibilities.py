import frappe


def execute():
    """Preserve legacy ERP Role names as app-owned operational responsibilities."""
    names = set()
    for doctype in ("CFG Kanban Task Schedule", "CFG Kanban Task"):
        if not frappe.db.table_exists(doctype):
            continue
        names.update(frappe.get_all(
            doctype, filters={"responsible_role": ["is", "set"]},
            pluck="responsible_role", limit_page_length=0,
        ))
    for name in sorted(value for value in names if value):
        if frappe.db.exists("CFG Kanban Responsibility", name):
            continue
        frappe.get_doc({
            "doctype": "CFG Kanban Responsibility",
            "responsibility_name": name,
            "active": 1,
            "description": "Migrated from the legacy ERPNext Responsible Role value.",
        }).insert(ignore_permissions=True)

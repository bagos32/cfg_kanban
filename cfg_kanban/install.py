import frappe


def after_install():
    """Apply app-owned ERPNext traceability fields after schema installation."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    fields_by_doctype = _custom_fields()
    for fields in fields_by_doctype.values():
        for field in fields:
            field.setdefault("module", "CFG Kanban")
    create_custom_fields(fields_by_doctype, update=True)


def _custom_fields():
    common = [
        {"fieldname": "cfg_kanban_section", "label": "CFG Kanban", "fieldtype": "Section Break", "insert_after": "more_info"},
        {"fieldname": "cfg_kanban_controlled", "label": "Kanban Controlled", "fieldtype": "Check", "read_only": 1, "insert_after": "cfg_kanban_section"},
        {"fieldname": "cfg_kanban_cycle", "label": "Kanban Cycle", "fieldtype": "Link", "options": "CFG Kanban Cycle", "read_only": 1, "insert_after": "cfg_kanban_controlled"},
        {"fieldname": "cfg_kanban_signal", "label": "Kanban Signal", "fieldtype": "Link", "options": "CFG Kanban Signal", "read_only": 1, "insert_after": "cfg_kanban_cycle"},
    ]
    return {
        "Work Order": common + [{"fieldname": "cfg_production_origin", "label": "Production Origin", "fieldtype": "Select", "options": "KANBAN\nMANUAL\nPLANNING\nSALES ORDER\nREWORK\nTRIAL", "insert_after": "cfg_kanban_signal"}],
        "Job Card": common,
        "Stock Entry": common,
    }

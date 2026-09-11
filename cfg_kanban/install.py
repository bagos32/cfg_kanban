import frappe


def after_install():
    """Apply app-owned ERPNext traceability fields after schema installation."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    fields_by_doctype = _custom_fields()
    for fields in fields_by_doctype.values():
        for field in fields:
            field.setdefault("module", "CFG Kanban")
    create_custom_fields(fields_by_doctype, update=True)


def after_migrate():
    after_install()


def _custom_fields():
    common = [
        {"fieldname": "cfg_kanban_section", "label": "CFG Kanban", "fieldtype": "Section Break", "insert_after": "more_info"},
        {"fieldname": "cfg_kanban_controlled", "label": "Kanban Controlled", "fieldtype": "Check", "read_only": 1, "insert_after": "cfg_kanban_section"},
        {"fieldname": "cfg_kanban_cycle", "label": "Kanban Cycle", "fieldtype": "Link", "options": "CFG Kanban Cycle", "read_only": 1, "insert_after": "cfg_kanban_controlled"},
        {"fieldname": "cfg_kanban_signal", "label": "Kanban Signal", "fieldtype": "Link", "options": "CFG Kanban Signal", "read_only": 1, "insert_after": "cfg_kanban_cycle"},
    ]
    return {
        "Work Order": common + [{"fieldname": "cfg_production_origin", "label": "Production Origin", "fieldtype": "Select", "options": "KANBAN\nMANUAL\nPLANNING\nSALES ORDER\nREWORK\nTRIAL", "insert_after": "cfg_kanban_signal"}],
        "Sales Order": [
            {"fieldname": "cfg_kanban_demand_section", "label": "CFG Kanban Demand", "fieldtype": "Section Break", "insert_after": "terms", "module": "CFG Kanban", "collapsible": 1},
            {"fieldname": "cfg_production_line", "label": "Kanban Production Line", "fieldtype": "Data", "insert_after": "cfg_kanban_demand_section", "module": "CFG Kanban", "description": "Optional routing value used by Production Line demand scope."},
        ],
        "Job Card": common,
        "Stock Entry": common,
        "CFG Kanban Master": [
            {"fieldname": "cfg_sales_demand_section", "label": "Sales Demand Trigger", "fieldtype": "Section Break", "insert_after": "remarks", "module": "CFG Kanban"},
            {"fieldname": "enable_sales_order_trigger", "label": "Enable Sales Order Trigger", "fieldtype": "Check", "insert_after": "cfg_sales_demand_section", "module": "CFG Kanban"},
            {"fieldname": "sales_trigger_mode", "label": "Sales Trigger Mode", "fieldtype": "Select", "options": "Proposal Only\nApproval Required", "default": "Approval Required", "insert_after": "enable_sales_order_trigger", "module": "CFG Kanban"},
            {"fieldname": "threshold_source", "label": "Threshold Source", "fieldtype": "Select", "options": "ERPNext Warehouse Reorder Level\nKanban Override", "default": "ERPNext Warehouse Reorder Level", "reqd": 1, "insert_after": "sales_trigger_mode", "module": "CFG Kanban"},
            {"fieldname": "minimum_stock_override", "label": "Minimum Stock Override", "fieldtype": "Float", "depends_on": "eval:doc.threshold_source=='Kanban Override'", "mandatory_depends_on": "eval:doc.threshold_source=='Kanban Override'", "insert_after": "threshold_source", "module": "CFG Kanban"},
            {"fieldname": "demand_scope", "label": "Demand Scope", "fieldtype": "Select", "options": "General\nCustomer\nSales Territory\nProduction Line", "default": "General", "reqd": 1, "insert_after": "minimum_stock_override", "module": "CFG Kanban"},
            {"fieldname": "demand_scope_value", "label": "Demand Scope Value", "fieldtype": "Data", "depends_on": "eval:doc.demand_scope!='General'", "mandatory_depends_on": "eval:doc.demand_scope!='General'", "description": "Enter the exact Customer, Territory, or Sales Order Kanban Production Line value.", "insert_after": "demand_scope", "module": "CFG Kanban"},
            {"fieldname": "master_priority", "label": "Master Priority", "fieldtype": "Int", "default": "10", "description": "Higher number wins when scopes overlap.", "insert_after": "demand_scope_value", "module": "CFG Kanban"},
            {"fieldname": "sales_minimum_shortage_qty", "label": "Minimum Shortage to Propose", "fieldtype": "Float", "insert_after": "master_priority", "module": "CFG Kanban"},
            {"fieldname": "sales_safety_stock_qty", "label": "Legacy Sales Safety Stock Qty", "fieldtype": "Float", "read_only": 1, "hidden": 1, "insert_after": "sales_minimum_shortage_qty", "module": "CFG Kanban"},
            {"fieldname": "sales_max_cards_per_order", "label": "Maximum Cards per Sales Order", "fieldtype": "Int", "default": "10", "insert_after": "sales_minimum_shortage_qty", "module": "CFG Kanban"},
        ],
        "CFG Kanban Card": [
            {"fieldname": "reserved_for_demand", "label": "Reserved for Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "active_cycle", "module": "CFG Kanban"},
        ],
        "CFG Kanban Cycle": [
            {"fieldname": "sales_demand", "label": "Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "signal", "module": "CFG Kanban"},
        ],
        "CFG Kanban Signal": [
            {"fieldname": "sales_demand", "label": "Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "kanban_cycle", "module": "CFG Kanban"},
        ],
    }

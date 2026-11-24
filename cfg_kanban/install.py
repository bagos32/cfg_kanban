import frappe


def before_install():
    """Refresh discovery before native sync_for reads its in-process module map."""
    frappe.cache.delete_value("app_modules")
    frappe.setup_module_map(include_all_apps=True)
    expected = {frappe.scrub(name) for name in frappe.get_module_list("cfg_kanban")}
    actual = set(frappe.local.app_modules.get("cfg_kanban") or [])
    if not expected or actual != expected:
        frappe.throw("CFG Kanban module map could not be rebuilt; schema installation has not started")


def after_install():
    """Apply app-owned ERPNext traceability fields after schema installation."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    fields_by_doctype = _custom_fields()
    # The site's custom Credit Note app is optional; create no DocType or hard dependency.
    if frappe.db.exists("DocType", "Credit Note"):
        fields_by_doctype["Credit Note"] = [
            {"fieldname": "cfg_return_case", "label": "Customer Return Case", "fieldtype": "Link",
             "options": "CFG Kanban Return Case", "read_only": 1, "no_copy": 1, "insert_after": "return_against"},
            {"fieldname": "cfg_scan_event", "label": "Kanban Accounting Event Identity", "fieldtype": "Data",
             "read_only": 1, "no_copy": 1, "insert_after": "cfg_return_case"},
        ]
    _require_custom_field_schema(fields_by_doctype)
    for role_name in ("Kanban Terminal", "CFG Kanban System Maintenance"):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name,
                            "desk_access": 1}).insert(ignore_permissions=True)
    for fields in fields_by_doctype.values():
        for field in fields:
            field.setdefault("module", "CFG Kanban")
    create_custom_fields(fields_by_doctype, update=True)
    _ensure_logistics_audit_user_permissions()
    _ensure_responsibilities()


def after_migrate():
    after_install()
    # The native dimension adds Custom Fields to system ledgers with hidden,
    # mandatory keys. Frappe validates that metadata in its migration context.
    _ensure_process_certificate_inventory_dimension()


def _require_custom_field_schema(fields_by_doctype):
    required = {name for name in fields_by_doctype if name.startswith("CFG ")}
    required.add("CFG Process Certificate Set")
    for fields in fields_by_doctype.values():
        required.update(field["options"] for field in fields
            if field.get("fieldtype") in ("Link", "Table", "Table MultiSelect")
            and (field.get("options") or "").startswith("CFG "))
    missing = sorted(name for name in required if not frappe.db.exists("DocType", name))
    if missing:
        frappe.throw("CFG Kanban schema is incomplete. Missing DocTypes: " + ", ".join(missing)
            + ". Complete native CFG Kanban schema installation before creating ERP custom fields")


def _ensure_logistics_audit_user_permissions():
    """Keep attribution/counterparty Links from becoming extra ownership filters."""
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    for doctype in ("Delivery Note", "Purchase Receipt"):
        meta = frappe.get_meta(doctype)
        for fieldname, target in (("cfg_requested_operator", "Employee"),
                                  ("cfg_counterpart_company", "Company")):
            field = meta.get_field(fieldname)
            if not field or field.fieldtype != "Link" or field.options != target:
                frappe.throw(f"{doctype}: {fieldname} must remain a Link to {target}")
            if field.ignore_user_permissions:
                continue
            # A site's Property Setter can shadow the Custom Field definition.
            # Native Company/party/warehouse permissions remain unchanged.
            make_property_setter(doctype, field.fieldname, "ignore_user_permissions", 1, "Check")


def _ensure_process_certificate_inventory_dimension():
    """Expose certificate-qualified stock in native ERPNext inventory documents/reports."""
    if not frappe.flags.in_migrate:
        frappe.throw("Process Certificate Set Inventory Dimension setup requires native site migration")
    if not frappe.db.exists("DocType", "Inventory Dimension"):
        return
    if not frappe.db.table_exists("CFG Process Certificate Set"):
        return

    dimension_name = "Process Certificate Set"
    existing_name = frappe.db.get_value(
        "Inventory Dimension", {"dimension_name": dimension_name}, "name"
    )
    if existing_name:
        existing = frappe.db.get_value(
            "Inventory Dimension",
            existing_name,
            ["reference_document", "source_fieldname", "target_fieldname"],
            as_dict=True,
        )
        if existing.reference_document != "CFG Process Certificate Set":
            frappe.throw(
                "Inventory Dimension 'Process Certificate Set' already exists with a different "
                "Reference Document. Resolve the collision before migrating CFG Kanban."
            )
        expected_source = frappe.scrub(dimension_name)
        # ERPNext 15.65 derives the Stock Ledger Entry field from the Reference
        # Document, while later v15 releases derive it from the Dimension Name.
        # Both are framework-owned, valid fieldnames for this same dimension.
        accepted_targets = {
            expected_source,
            frappe.scrub(existing.reference_document),
        }
        if existing.source_fieldname != expected_source:
            frappe.throw(
                "Inventory Dimension 'Process Certificate Set' uses an unexpected source "
                "fieldname. Resolve the collision before migrating CFG Kanban."
            )
        if existing.target_fieldname not in accepted_targets:
            frappe.throw(
                "Inventory Dimension 'Process Certificate Set' uses an unexpected ledger "
                "fieldname. Resolve the collision before migrating CFG Kanban."
            )
        # A failed native on_update can commit the Dimension before all of its
        # fields exist. Its own adder skips existing fields and fills the gaps.
        frappe.get_doc("Inventory Dimension", existing_name).add_custom_fields()
        return

    frappe.get_doc({
        "doctype": "Inventory Dimension",
        "dimension_name": dimension_name,
        "reference_document": "CFG Process Certificate Set",
        "apply_to_all_doctypes": 1,
        "validate_negative_stock": 1,
        "reqd": 0,
    }).insert(ignore_permissions=True)


def _ensure_responsibilities():
    if not frappe.db.table_exists("CFG Kanban Responsibility"):
        return
    responsibilities = {
        "Logistics Dispatch": "Confirm approved stock dispatches.",
        "Logistics Receipt": "Confirm approved stock receipts.",
        "Supplier Receiving": (
            "Receive submitted purchase orders at an authorized warehouse location."
        ),
        "Vehicle Loading": "Load and unload company-specific vehicle warehouses.",
        "Internal Warehouse Transfer": (
            "Scan tagged stock against a same-company ERPNext Material Transfer."
        ),
        "Stock Withdrawal": (
            "Issue approved consumables and indirect materials from ERP stock without a Work Order."
        ),
        "Container Loading": (
            "Load and unload complete physical Stock Tags in reusable containers."
        ),
        "Stock Retagging": (
            "Split tagged quantity to an unused tag or transfer quantity between active tags "
            "inside the same Company and ERP warehouse."
        ),
        "Stock Adoption": (
            "Bind preprinted physical tags to verified, previously untagged ERPNext stock and "
            "optionally reserve a complete adopted tag for an eligible Kanban Cycle."
        ),
        "Customer Delivery": "Deliver stock to an identified Customer Site.",
        "Customer Return": (
            "Record a customer-site Temporary Return Note or wrong Delivery Note correction."
        ),
        "Customer Return QC": (
            "Receive, inspect, and disposition Customer Return Cases in non-stock custody."
        ),
        "Customer Invoice Trigger": "Trigger locked-price customer invoicing.",
        "Logistics Supervisor": "Approve logistics exceptions and controlled overrides.",
        "Intercompany Billing": "Prepare and reconcile intercompany billing batches.",
        "Logistics Reconciliation": "Reconcile tag, container, vehicle, and ERP stock balances.",
    }
    for name, description in responsibilities.items():
        if frappe.db.exists("CFG Kanban Responsibility", name):
            continue
        frappe.get_doc({
            "doctype": "CFG Kanban Responsibility",
            "responsibility_name": name,
            "active": 1,
            "description": description,
        }).insert(ignore_permissions=True)


def _custom_fields():
    common = [
        {"fieldname": "cfg_kanban_section", "label": "CFG Kanban", "fieldtype": "Section Break", "insert_after": "more_info"},
        {"fieldname": "cfg_kanban_controlled", "label": "Kanban Controlled", "fieldtype": "Check", "read_only": 1, "insert_after": "cfg_kanban_section"},
        {"fieldname": "cfg_kanban_cycle", "label": "Kanban Cycle", "fieldtype": "Link", "options": "CFG Kanban Cycle", "read_only": 1, "insert_after": "cfg_kanban_controlled"},
        {"fieldname": "cfg_kanban_signal", "label": "Kanban Signal", "fieldtype": "Link", "options": "CFG Kanban Signal", "read_only": 1, "insert_after": "cfg_kanban_cycle"},
    ]
    def purchase_common(insert_after):
        fields = [dict(field) for field in common]
        fields[0]["insert_after"] = insert_after
        return fields
    logistics_common = [
        {"fieldname": "cfg_logistics_route", "label": "Logistics Route", "fieldtype": "Link",
         "options": "CFG Kanban Logistics Route", "read_only": 1,
         "insert_after": "cfg_kanban_signal"},
        {"fieldname": "cfg_movement_manifest", "label": "Movement Manifest", "fieldtype": "Link",
         "options": "CFG Kanban Movement Manifest", "read_only": 1,
         "insert_after": "cfg_logistics_route"},
        {"fieldname": "cfg_delivery_session", "label": "Customer Delivery Session",
         "fieldtype": "Link", "options": "CFG Kanban Delivery Session", "read_only": 1,
         "insert_after": "cfg_movement_manifest"},
        {"fieldname": "cfg_return_case", "label": "Customer Return Case",
         "fieldtype": "Link", "options": "CFG Kanban Return Case", "read_only": 1,
         "insert_after": "cfg_delivery_session"},
        {"fieldname": "cfg_counterpart_company", "label": "Counterpart Company",
         "fieldtype": "Link", "options": "Company", "read_only": 1,
         "ignore_user_permissions": 1,
         "insert_after": "cfg_return_case"},
        {"fieldname": "cfg_counterpart_document", "label": "Counterpart ERP Document",
         "fieldtype": "Data", "read_only": 1, "insert_after": "cfg_counterpart_company"},
        {"fieldname": "cfg_requested_operator", "label": "Requested by Kanban Operator",
         "fieldtype": "Link", "options": "Employee", "read_only": 1,
         "ignore_user_permissions": 1,
         "insert_after": "cfg_counterpart_document"},
        {"fieldname": "cfg_scan_event", "label": "Kanban Scan Event Identity",
         "fieldtype": "Data", "read_only": 1, "insert_after": "cfg_requested_operator"},
    ]
    logistics_item_fields = [
        {"fieldname": "cfg_handling_unit", "label": "Kanban Handling Unit",
         "fieldtype": "Link", "options": "CFG Kanban Handling Unit", "read_only": 1,
         "insert_after": "batch_no", "module": "CFG Kanban"},
        {"fieldname": "cfg_manifest_line", "label": "Kanban Manifest Line",
         "fieldtype": "Data", "read_only": 1, "insert_after": "cfg_handling_unit",
         "module": "CFG Kanban"},
        {"fieldname": "cfg_delivery_allocation", "label": "Kanban Delivery Allocation",
         "fieldtype": "Link", "options": "CFG Kanban Delivery Allocation", "read_only": 1,
         "insert_after": "cfg_manifest_line", "module": "CFG Kanban"},
    ]
    return {
        "Work Order": common + [
            {"fieldname": "cfg_production_origin", "label": "Production Origin", "fieldtype": "Select", "options": "KANBAN\nMANUAL\nPLANNING\nSALES ORDER\nREWORK\nTRIAL", "insert_after": "cfg_kanban_signal"},
            {"fieldname": "cfg_sales_order", "label": "MTO Sales Order", "fieldtype": "Link", "options": "Sales Order", "read_only": 1, "insert_after": "cfg_production_origin"},
            {"fieldname": "cfg_planned_batch", "label": "MTO Planned Batch", "fieldtype": "Link", "options": "Batch", "read_only": 1, "insert_after": "cfg_sales_order"},
        ],
        "Sales Order": [
            {"fieldname": "cfg_delivery_route", "label": "Standard Delivery Route", "fieldtype": "Link", "options": "CFG Kanban Route Template", "insert_after": "delivery_date", "allow_on_submit": 1, "module": "CFG Kanban", "description": "Active Company route. Saved orders appear in its office inbox; the office assigns a dated Delivery Trip. Customer PO uses the standard Customer PO No field."},
            {"fieldname": "cfg_kanban_demand_section", "label": "CFG Kanban Demand", "fieldtype": "Section Break", "insert_after": "terms", "module": "CFG Kanban", "collapsible": 1},
            {"fieldname": "cfg_production_line", "label": "Kanban Production Line", "fieldtype": "Data", "insert_after": "cfg_kanban_demand_section", "module": "CFG Kanban", "description": "Optional routing value used by Production Line demand scope."},
            {"fieldname": "cfg_po_allows_extra_qty", "label": "Customer PO Allows Extra Quantity", "fieldtype": "Check", "insert_after": "cfg_production_line", "module": "CFG Kanban"},
            {"fieldname": "cfg_po_extra_tolerance_pct", "label": "Customer PO Extra Tolerance %", "fieldtype": "Percent", "depends_on": "cfg_po_allows_extra_qty", "mandatory_depends_on": "cfg_po_allows_extra_qty", "insert_after": "cfg_po_allows_extra_qty", "module": "CFG Kanban"},
            {"fieldname": "cfg_po_tolerance_reference", "label": "PO Tolerance Reference", "fieldtype": "Data", "depends_on": "cfg_po_allows_extra_qty", "mandatory_depends_on": "cfg_po_allows_extra_qty", "insert_after": "cfg_po_extra_tolerance_pct", "module": "CFG Kanban", "description": "Customer PO clause, amendment, or written acceptance reference."},
        ],
        "Batch": [
            {"fieldname":"cfg_rotation_section","label":"Kanban Batch Selection Isolation","fieldtype":"Section Break","insert_after":"description","module":"CFG Kanban"},
            {"fieldname":"cfg_rotation_excluded","label":"Exclude Batch from Automatic FEFO / FIFO","fieldtype":"Check","default":"0","insert_after":"cfg_rotation_section","module":"CFG Kanban","description":"All tags of this Batch are omitted from Kanban automatic rotation selection. An explicit scan remains allowed with all normal validity checks. Uncheck to return the Batch to automatic selection."},
            {"fieldname":"cfg_rotation_reason","label":"Isolation / Release Reason","fieldtype":"Small Text","insert_after":"cfg_rotation_excluded","module":"CFG Kanban"},
            {"fieldname": "cfg_mto_section", "label": "CFG Kanban MTO", "fieldtype": "Section Break", "insert_after": "description", "module": "CFG Kanban", "collapsible": 1},
            {"fieldname": "cfg_sales_demand", "label": "Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "unique": 1, "insert_after": "cfg_mto_section", "module": "CFG Kanban"},
            {"fieldname": "cfg_sales_order", "label": "Sales Order", "fieldtype": "Link", "options": "Sales Order", "read_only": 1, "insert_after": "cfg_sales_demand", "module": "CFG Kanban"},
        ],
        "Job Card": common,
        "Job Card Time Log": [
            {"fieldname":"cfg_hopper_carry_in","label":"Inherited Hopper WIP","fieldtype":"Link",
             "options":"CFG Kanban Hopper Carry In","read_only":1,"unique":1,"insert_after":"completed_qty","module":"CFG Kanban"},
            {"fieldname": "cfg_kanban_progress", "label": "Kanban Progress",
             "fieldtype": "Link", "options": "CFG Kanban Operation Progress",
             "read_only": 1, "unique": 1, "insert_after": "completed_qty", "module": "CFG Kanban"},
        ],
        "Stock Entry": common + [
            {"fieldname": "cfg_kanban_job_card", "label": "Kanban Material Job Card",
             "fieldtype": "Link", "options": "Job Card", "read_only": 1,
             "insert_after": "cfg_kanban_signal", "module": "CFG Kanban",
             "description": (
                 "CFG Kanban operation owner for Work Order-scoped material consumption. "
                 "ERPNext only permits its native Job Card field on material transfers."
             )},
            {"fieldname": "cfg_wip_bin_return_load", "label": "WIP Bin Return Load",
             "fieldtype": "Link", "options": "CFG Kanban WIP Bin Load", "read_only": 1,
             "insert_after": "cfg_kanban_job_card", "module": "CFG Kanban",
             "description": "Identifies the controlled return of unused material from a reusable WIP bin."},
            {"fieldname": "cfg_loose_wip_consolidated", "label": "Consolidated Loose WIP Consumption",
             "fieldtype": "Check", "read_only": 1,
             "insert_after": "cfg_wip_bin_return_load", "module": "CFG Kanban",
             "description": (
                 "Marks the Work Order-level consumption of immutable Loose WIP usage "
                 "reported by one or more operation-card cycles."
             )},
            {"fieldname": "cfg_logistics_route", "label": "Logistics Route",
             "fieldtype": "Link", "options": "CFG Kanban Logistics Route", "read_only": 1,
             "insert_after": "cfg_loose_wip_consolidated", "module": "CFG Kanban"},
            {"fieldname": "cfg_movement_manifest", "label": "Movement Manifest",
             "fieldtype": "Link", "options": "CFG Kanban Movement Manifest", "read_only": 1,
             "insert_after": "cfg_logistics_route", "module": "CFG Kanban"},
            {"fieldname": "cfg_transfer_stage", "label": "Internal Transfer Stage",
             "fieldtype": "Select", "options": "Direct\nOutward\nReceipt", "read_only": 1,
             "insert_after": "cfg_movement_manifest", "module": "CFG Kanban"},
            {"fieldname": "cfg_withdrawal_cycle", "label": "Kanban Withdrawal Cycle",
             "fieldtype": "Link", "options": "CFG Kanban Cycle", "read_only": 1,
             "insert_after": "cfg_transfer_stage", "module": "CFG Kanban"},
            {"fieldname": "cfg_return_case", "label": "Customer Return Case",
             "fieldtype": "Link", "options": "CFG Kanban Return Case", "read_only": 1,
             "insert_after": "cfg_withdrawal_cycle", "module": "CFG Kanban"},
            {"fieldname": "cfg_scan_event", "label": "Kanban Event Identity",
             "fieldtype": "Data", "read_only": 1, "insert_after": "cfg_return_case",
             "module": "CFG Kanban"},
        ],
        "Stock Entry Detail": [
            {"fieldname": "cfg_handling_unit", "label": "Kanban Handling Unit",
             "fieldtype": "Link", "options": "CFG Kanban Handling Unit", "read_only": 1,
             "insert_after": "batch_no", "module": "CFG Kanban"},
            {"fieldname": "cfg_manifest_line", "label": "Kanban Manifest Line",
             "fieldtype": "Data", "read_only": 1,
             "insert_after": "cfg_handling_unit", "module": "CFG Kanban"},
            {"fieldname": "cfg_withdrawal_allocation", "label": "Kanban Withdrawal Allocation",
             "fieldtype": "Data", "read_only": 1,
             "insert_after": "cfg_manifest_line", "module": "CFG Kanban"},
            {"fieldname": "cfg_return_disposition_line",
             "label": "Customer Return Disposition Row", "fieldtype": "Data",
             "read_only": 1, "insert_after": "cfg_withdrawal_allocation", "module": "CFG Kanban"},
        ],
        "Material Request": purchase_common("terms"),
        "Purchase Order": purchase_common("terms"),
        "Delivery Note": purchase_common("terms") + logistics_common,
        "Delivery Note Item": logistics_item_fields,
        "Sales Invoice": [
            {"fieldname": "cfg_return_case", "label": "Customer Return Case",
             "fieldtype": "Link", "options": "CFG Kanban Return Case", "read_only": 1,
             "insert_after": "return_against", "module": "CFG Kanban"},
            {"fieldname": "cfg_scan_event", "label": "Kanban Accounting Event Identity",
             "fieldtype": "Data", "read_only": 1, "insert_after": "cfg_return_case",
             "module": "CFG Kanban"},
        ],
        "Purchase Receipt": purchase_common("terms") + logistics_common,
        "Purchase Receipt Item": logistics_item_fields,
        "Warehouse": [
            {"fieldname": "cfg_vehicle_section", "label": "CFG Kanban Vehicle Stock",
             "fieldtype": "Section Break", "insert_after": "company", "module": "CFG Kanban",
             "collapsible": 1},
            {"fieldname": "cfg_is_vehicle_warehouse", "label": "Vehicle Warehouse",
             "fieldtype": "Check", "default": "0", "insert_after": "cfg_vehicle_section",
             "module": "CFG Kanban", "description": "Enable only for a Company-specific logical Warehouse representing stock physically carried by a vehicle."},
            {"fieldname": "cfg_vehicle_reference", "label": "Physical Vehicle Reference",
             "fieldtype": "Data", "insert_after": "cfg_is_vehicle_warehouse",
             "depends_on": "cfg_is_vehicle_warehouse",
             "mandatory_depends_on": "cfg_is_vehicle_warehouse", "module": "CFG Kanban",
             "description": "Shared physical vehicle identity, for example LORRY-01. Each Company uses its own Warehouse row with the same reference."},
        ],
        "CFG Kanban Master": [
            {"fieldname": "cfg_sales_demand_section", "label": "Sales Demand Trigger", "fieldtype": "Section Break", "insert_after": "remarks", "module": "CFG Kanban"},
            {"fieldname": "enable_sales_order_trigger", "label": "Enable Sales Order Trigger", "fieldtype": "Check", "insert_after": "cfg_sales_demand_section", "module": "CFG Kanban"},
            {"fieldname": "sales_trigger_mode", "label": "Sales Trigger Mode", "fieldtype": "Select", "options": "Proposal Only\nApproval Required", "default": "Approval Required", "insert_after": "enable_sales_order_trigger", "module": "CFG Kanban"},
            {"fieldname": "threshold_source", "label": "Threshold Source", "fieldtype": "Select", "options": "ERPNext Warehouse Reorder Level\nKanban Override", "default": "ERPNext Warehouse Reorder Level", "reqd": 1, "insert_after": "sales_trigger_mode", "module": "CFG Kanban"},
            {"fieldname": "minimum_stock_override", "label": "Minimum Stock Override", "fieldtype": "Float", "depends_on": "eval:doc.threshold_source=='Kanban Override'", "mandatory_depends_on": "eval:doc.threshold_source=='Kanban Override'", "insert_after": "threshold_source", "module": "CFG Kanban"},
            {"fieldname": "demand_scope", "label": "Demand Scope", "fieldtype": "Select", "options": "General\nCustomer\nSales Territory\nProduction Line", "default": "General", "reqd": 1, "insert_after": "minimum_stock_override", "module": "CFG Kanban"},
            {"fieldname": "demand_scope_value", "label": "Demand Scope Value", "fieldtype": "Data", "depends_on": "eval:doc.demand_scope!='General'", "mandatory_depends_on": "eval:doc.demand_scope!='General'", "description": "Enter the exact Customer, Territory, or Sales Order Kanban Production Line value.", "insert_after": "demand_scope", "module": "CFG Kanban"},
            {"fieldname": "master_priority", "label": "Master Priority", "fieldtype": "Int", "default": "10", "description": "Higher number wins when scopes overlap.", "insert_after": "demand_scope_value", "module": "CFG Kanban"},
            {"fieldname": "production_policy", "label": "Production Policy", "fieldtype": "Select", "options": "Stock Replenishment\nCustomer Make-to-Order", "default": "Stock Replenishment", "reqd": 1, "insert_after": "master_priority", "module": "CFG Kanban"},
            {"fieldname": "mto_extra_tolerance_pct", "label": "MTO Extra Production Tolerance %", "fieldtype": "Percent", "depends_on": "eval:doc.production_policy=='Customer Make-to-Order'", "insert_after": "production_policy", "module": "CFG Kanban"},
            {"fieldname": "mto_plan_to_maximum", "label": "Plan Work Order to Maximum Permitted Qty", "fieldtype": "Check", "default": "1", "depends_on": "eval:doc.production_policy=='Customer Make-to-Order'", "insert_after": "mto_extra_tolerance_pct", "module": "CFG Kanban"},
            {"fieldname": "mto_batch_policy", "label": "MTO Batch Policy", "fieldtype": "Select", "options": "One Batch per Sales Order Line", "default": "One Batch per Sales Order Line", "depends_on": "eval:doc.production_policy=='Customer Make-to-Order'", "insert_after": "mto_plan_to_maximum", "module": "CFG Kanban"},
            {"fieldname": "mto_existing_stock_usage", "label": "Existing Stock Usage", "fieldtype": "Select", "options": "Prohibited", "default": "Prohibited", "depends_on": "eval:doc.production_policy=='Customer Make-to-Order'", "insert_after": "mto_batch_policy", "module": "CFG Kanban"},
            {"fieldname": "mto_order_consolidation", "label": "Order Consolidation", "fieldtype": "Select", "options": "Prohibited", "default": "Prohibited", "depends_on": "eval:doc.production_policy=='Customer Make-to-Order'", "insert_after": "mto_existing_stock_usage", "module": "CFG Kanban"},
            {"fieldname": "sales_minimum_shortage_qty", "label": "Minimum Shortage to Propose", "fieldtype": "Float", "insert_after": "mto_order_consolidation", "module": "CFG Kanban"},
            {"fieldname": "sales_safety_stock_qty", "label": "Legacy Sales Safety Stock Qty", "fieldtype": "Float", "read_only": 1, "hidden": 1, "insert_after": "sales_minimum_shortage_qty", "module": "CFG Kanban"},
            {"fieldname": "sales_max_cards_per_order", "label": "Maximum Cards per Sales Order", "fieldtype": "Int", "default": "10", "insert_after": "sales_minimum_shortage_qty", "module": "CFG Kanban"},
        ],
        "CFG Kanban Cycle": [
            {"fieldname": "existing_stock_section", "label": "Existing ERP Stock Allocation",
             "fieldtype": "Section Break", "insert_after": "runtime_allocation",
             "module": "CFG Kanban", "collapsible": 1},
            {"fieldname": "existing_stock_allocated_qty",
             "label": "Existing Stock Allocated Qty", "fieldtype": "Float",
             "default": "0", "read_only": 1, "in_list_view": 1,
             "insert_after": "existing_stock_section", "module": "CFG Kanban"},
            {"fieldname": "existing_stock_allocation_status",
             "label": "Existing Stock Allocation Status", "fieldtype": "Select",
             "options": "\nPartially Allocated\nFully Allocated", "read_only": 1,
             "in_standard_filter": 1, "insert_after": "existing_stock_allocated_qty",
             "module": "CFG Kanban"},
        ],
        "CFG Kanban Card": [
            {"fieldname": "reserved_for_demand", "label": "Reserved for Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "active_cycle", "module": "CFG Kanban"},
        ],
        "CFG Kanban Cycle": [
            {"fieldname": "sales_demand", "label": "Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "signal", "module": "CFG Kanban"},
            {"fieldname": "production_policy", "label": "Production Policy", "fieldtype": "Data", "read_only": 1, "insert_after": "sales_demand", "module": "CFG Kanban"},
            {"fieldname": "sales_order", "label": "Sales Order", "fieldtype": "Link", "options": "Sales Order", "read_only": 1, "insert_after": "production_policy", "module": "CFG Kanban"},
            {"fieldname": "sales_order_item_row", "label": "Sales Order Item Row", "fieldtype": "Data", "read_only": 1, "insert_after": "sales_order", "module": "CFG Kanban"},
        ],
        "CFG Kanban Signal": [
            {"fieldname": "sales_demand", "label": "Sales Demand", "fieldtype": "Link", "options": "CFG Kanban Demand", "read_only": 1, "insert_after": "kanban_cycle", "module": "CFG Kanban"},
        ],
    }

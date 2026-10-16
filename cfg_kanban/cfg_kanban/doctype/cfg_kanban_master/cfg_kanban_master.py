import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from cfg_kanban.services.dynamic_forms import validate_condition_definitions
from cfg_kanban.services.hidden_items import get_hidden_item_policy
from cfg_kanban.services.purchase_uom import calculate_purchase_quantities
from cfg_kanban.services.uom_conversion import get_item_purchase_uom


class CFGKanbanMaster(Document):
    def validate(self):
        self._set_item_and_purchase_uom()
        if flt(self.replenishment_qty) <= 0 or cint(self.number_of_cards) <= 0:
            frappe.throw("Replenishment quantity and number of cards must be positive")
        if self.control_type == "Purchase Replenishment":
            if not self.default_supplier or not self.destination_warehouse:
                frappe.throw("Default Supplier and Destination Warehouse are required for Purchase Replenishment")
            if (self.purchase_execution_mode or "Material Request Only") != "Material Request Only" \
                    and not cint(self.auto_submit_material_request):
                frappe.throw(
                    "Submit Material Request on Approval is required when Purchase Execution Mode creates a Purchase Order"
                )
            for fieldname, label in (("supplier_pack_size", "Supplier Pack Size"),
                                     ("minimum_order_qty", "Minimum Order Qty"),
                                     ("purchase_order_multiple", "Purchase Order Multiple"),
                                     ("over_receipt_tolerance_pct", "Over-receipt Tolerance"),
                                     ("master_auto_submit_po_value_limit", "Master Auto-submit PO Value Limit")):
                # Frappe form payloads may carry Float/Percent values as strings
                # (for example, Percent zero arrives as "0"). Always normalize
                # before comparing so a valid purchase Master can be saved.
                if flt(self.get(fieldname)) < 0:
                    frappe.throw(f"{label} cannot be negative")
        if self.control_type == "Transfer":
            if not self.source_warehouse or not self.destination_warehouse or not self.logistics_route:
                frappe.throw(
                    "Source Warehouse, Destination Warehouse, and Internal Logistics Route "
                    "are required for Transfer control"
                )
            route = frappe.get_doc("CFG Kanban Logistics Route", self.logistics_route)
            if route.route_type != "Internal Warehouse Transfer":
                frappe.throw("Transfer Masters require an Internal Warehouse Transfer route")
            expected = (self.company, self.source_warehouse, self.company,
                        self.destination_warehouse)
            actual = (route.source_company, route.source_warehouse,
                      route.destination_company, route.destination_warehouse)
            if actual != expected:
                frappe.throw(
                    "The Internal Logistics Route Company and Warehouses must exactly match "
                    "the Kanban Master"
                )
        if self.control_type == "Withdrawal":
            if not self.source_warehouse or not (self.withdrawal_reason or "").strip():
                frappe.throw(
                    "Source Warehouse and Standard Withdrawal Reason are required for "
                    "Withdrawal control"
                )
            warehouse_company = frappe.db.get_value(
                "Warehouse", self.source_warehouse, "company"
            )
            if warehouse_company != self.company:
                frappe.throw(
                    f"Source Warehouse belongs to {warehouse_company}, not {self.company}"
                )
            self.destination_warehouse = None
            self.logistics_route = None
        sequences = [row.sequence for row in self.operation_profiles]
        if len(sequences) != len(set(sequences)):
            frappe.throw("Operation profile sequences must be unique")
        operations = {row.operation for row in self.operation_profiles}
        for row in self.operation_profiles:
            row.allow_parallel = row.execution_mode == "Parallel Workstations"
            if row.dependency_operation and row.dependency_operation not in operations:
                frappe.throw(f"Dependency operation {row.dependency_operation} is not in this route")
            if row.destination_operation and row.destination_operation not in operations:
                frappe.throw(f"Destination operation {row.destination_operation} is not in this route")
            if row.start_rule == "Minimum Qty Available" and flt(row.minimum_qty) <= 0:
                frappe.throw(f"Minimum Qty must be positive for operation {row.operation}")
            if row.start_rule == "Minimum Percentage Available" and not 0 < flt(row.minimum_percentage) <= 100:
                frappe.throw(f"Minimum Percentage must be between 0 and 100 for operation {row.operation}")
            if row.handoff_mode == "Digital Quantity Handoff" and flt(row.transfer_multiple) <= 0:
                frappe.throw(f"Transfer Multiple must be positive for operation {row.operation}")
        task_keys = [row.task_key for row in self.process_task_profiles]
        if len(task_keys) != len(set(task_keys)):
            frappe.throw("Process Task Profile keys must be unique")
        task_sequences = [row.sequence for row in self.process_task_profiles]
        if len(task_sequences) != len(set(task_sequences)):
            frappe.throw("Process Task Profile sequences must be unique")
        for row in self.process_task_profiles:
            if row.linked_operation and row.linked_operation not in operations:
                frappe.throw(f"Process Task {row.task_name} references an operation outside this route")
            if row.trigger_point in ("Before Operation Start", "After Operation Complete",
                                     "Before WIP Release") and not row.linked_operation:
                frappe.throw(f"Linked Operation is required for Process Task {row.task_name}")
            if row.reuse_while_valid and flt(row.validity_duration_hours) <= 0:
                frappe.throw(f"Validity Duration must be positive for Process Task {row.task_name}")
            if row.qc_controlled:
                if not row.test_method or not row.specification_reference:
                    frappe.throw(
                        f"Test Method and Specification Reference are required for controlled QC Process Task {row.task_name}"
                    )
                if row.reuse_while_valid:
                    frappe.throw(
                        f"Controlled QC Process Task {row.task_name} cannot reuse a result from another production cycle"
                    )
            if (row.enable_sample_traveller or row.allow_conditional_release) and not row.qc_controlled:
                frappe.throw(
                    f"Enable Controlled QC Task before configuring sample or conditional release for {row.task_name}"
                )
        keys = [row.field_key for row in self.operator_field_definitions]
        if len(keys) != len(set(keys)):
            frappe.throw("Dynamic operator Field Keys must be unique")
        unknown_fields = [row.operation for row in self.operator_field_definitions
                          if (row.definition_scope or "Operation") == "Operation"
                          and row.operation not in operations]
        if unknown_fields:
            frappe.throw(f"Dynamic operator fields reference operations outside this route: {', '.join(unknown_fields)}")
        unknown_tasks = [row.process_task_key for row in self.operator_field_definitions
                         if row.definition_scope == "Process Task"
                         and row.process_task_key not in task_keys]
        if unknown_tasks:
            frappe.throw("Dynamic operator fields reference unknown Process Tasks: "
                         + ", ".join(unknown_tasks))
        validate_condition_definitions(self.operator_field_definitions)
        self._protect_restricted_material_flow_rules()
        self._validate_production_material_flow()
        self._validate_sales_demand_configuration()
        self._validate_inventory_threshold_configuration()

    def _validate_production_material_flow(self):
        if self.control_type != "Production":
            return
        if not self.bom:
            frappe.throw("BOM is required for Production control")
        bom = frappe.get_doc("BOM", self.bom)
        hidden_policy = get_hidden_item_policy()
        restricted_items = (hidden_policy["items"]
                            if not hidden_policy["can_view"] else set())
        if bom.docstatus != 1 or not bom.is_active:
            frappe.throw("Production requires an active submitted BOM")
        if bom.item != self.item_code or bom.company != self.company:
            frappe.throw("BOM Item and Company must match the Kanban Master")

        mode = self.get("production_material_mode") or "Follow ERPNext BOM / Work Order"
        if mode == "Transfer to WIP by Job Card":
            if not bom.with_operations:
                frappe.throw("Job Card material transfer requires With Operations on the BOM")
            missing = [row.item_code for row in bom.items
                       if not row.operation and row.item_code not in restricted_items]
            restricted_missing = any(
                not row.operation and row.item_code in restricted_items for row in bom.items
            )
            if missing:
                frappe.throw(
                    "Every BOM component needs Item Operation for Job Card transfer: "
                    + ", ".join(missing)
                )
            if restricted_missing:
                frappe.throw(
                    "A restricted BOM component has no Item Operation. Ask an authorized "
                    "Hidden Item user to correct the ERPNext BOM."
                )
        if mode != "Skip WIP Transfer" and not self.wip_warehouse:
            frappe.throw("WIP Warehouse is required when materials transfer to WIP")
        if not self.destination_warehouse:
            frappe.throw("Destination Warehouse is required for manufactured output")

        bom_keys = {(row.item_code, row.operation or "") for row in bom.items}
        visible_bom_keys = {key for key in bom_keys if key[0] not in restricted_items}
        rule_keys = []
        for row in self.material_flow_rules:
            key = (row.item_code, row.operation or "")
            if row.item_code in restricted_items:
                # Existing restricted mappings remain server-side execution data. They are not
                # required in the filtered editor shown to an unauthorized user.
                continue
            rule_keys.append(key)
            if key not in bom_keys:
                frappe.throw(
                    f"Material Flow row {row.idx} ({row.item_code} / "
                    f"{row.operation or 'No Operation'}) is not in BOM {bom.name}"
                )
            _validate_warehouse_company(row.source_warehouse, self.company,
                                        f"Material Flow row {row.idx}")
            self._validate_wip_bin_rule(row, mode)
        if len(rule_keys) != len(set(rule_keys)):
            frappe.throw("BOM Component Material Flow cannot repeat the same Item and Operation")

        if rule_keys:
            missing_rules = visible_bom_keys - set(rule_keys)
            if missing_rules:
                detail = ", ".join(
                    f"{item} / {operation or 'No Operation'}"
                    for item, operation in sorted(missing_rules)
                )
                frappe.throw("Reload BOM Material Flow; missing component rows: " + detail)
        for warehouse, label in (
            (self.source_warehouse, "Source Warehouse"),
            (self.wip_warehouse, "WIP Warehouse"),
            (self.destination_warehouse, "Destination Warehouse"),
        ):
            if warehouse:
                _validate_warehouse_company(warehouse, self.company, label)

    def _protect_restricted_material_flow_rules(self):
        if self.control_type != "Production":
            return
        policy = get_hidden_item_policy()
        restricted_items = policy["items"] if not policy["can_view"] else set()
        if not restricted_items:
            return
        if self.is_new():
            # The filtered BOM preview never supplies these rows. Discard a manually injected
            # restricted row rather than accepting an unauthorized source-Warehouse override.
            self.set("material_flow_rules", [
                row for row in self.material_flow_rules
                if row.item_code not in restricted_items
            ])
            return

        stored_bom = frappe.db.get_value(self.doctype, self.name, "bom")
        if stored_bom != self.bom and (
                _bom_contains_items(stored_bom, restricted_items)
                or _bom_contains_items(self.bom, restricted_items)):
            frappe.throw(
                "This Master contains restricted BOM components. An authorized Hidden Item "
                "user must change or resynchronize its BOM."
            )
        stored_rows = frappe.get_all(
            "CFG Kanban Material Flow Rule",
            filters={"parent": self.name, "parenttype": self.doctype},
            fields=["name", "item_code", "operation", "source_warehouse",
                    "bom_qty", "stock_uom", "wip_presentation_method",
                    "wip_bin_pool", "standard_bin_qty", "idx"],
            order_by="idx asc",
        )
        protected_rows = [row for row in stored_rows
                          if row.item_code in restricted_items]
        visible_rows = [row.as_dict() for row in self.material_flow_rules
                        if row.item_code not in restricted_items]
        self.set("material_flow_rules", visible_rows + protected_rows)

    def _validate_wip_bin_rule(self, row, mode):
        presentation = row.wip_presentation_method or "Standard ERP / Tag Flow"
        if presentation != "Standard Quantity Reusable WIP Bin":
            row.wip_bin_pool = None
            row.standard_bin_qty = 0
            return
        if mode != "Transfer to WIP by Job Card":
            frappe.throw(
                f"Material Flow row {row.idx}: Standard Quantity Reusable WIP Bin "
                "requires Production Material Mode Transfer to WIP by Job Card"
            )
        if not row.operation:
            frappe.throw(
                f"Material Flow row {row.idx}: a WIP Bin component requires an Item Operation"
            )
        if frappe.db.get_value("Item", row.item_code, "has_serial_no"):
            frappe.throw(
                f"Material Flow row {row.idx}: serial-controlled Item {row.item_code} must "
                "use Standard ERP / Tag Flow so exact serial membership is preserved"
            )
        if not row.wip_bin_pool or flt(row.standard_bin_qty) <= 0:
            frappe.throw(
                f"Material Flow row {row.idx}: WIP Bin Pool and a positive Qty per Full Bin "
                "are required"
            )
        pool = frappe.db.get_value(
            "CFG Kanban WIP Bin Pool",
            row.wip_bin_pool,
            ["active", "company", "operation", "wip_warehouse"],
            as_dict=True,
        )
        if not pool or not pool.active:
            frappe.throw(f"Material Flow row {row.idx}: select an active WIP Bin Pool")
        if pool.company != self.company:
            frappe.throw(
                f"Material Flow row {row.idx}: WIP Bin Pool belongs to {pool.company}, "
                f"not {self.company}"
            )
        if pool.operation != row.operation:
            frappe.throw(
                f"Material Flow row {row.idx}: WIP Bin Pool operation {pool.operation} "
                f"does not match BOM Item Operation {row.operation}"
            )
        if not any(
            profile.operation == row.operation for profile in self.operation_profiles
        ):
            frappe.throw(
                f"Material Flow row {row.idx}: add an Operation Profile for {row.operation} "
                "before assigning a WIP Bin Pool"
            )
        if pool.wip_warehouse != self.wip_warehouse:
            frappe.throw(
                f"Material Flow row {row.idx}: WIP Bin Pool Warehouse {pool.wip_warehouse} "
                f"does not match Master WIP Warehouse {self.wip_warehouse}"
            )
        if not frappe.db.exists(
            "CFG Kanban WIP Bin Pool Entry",
            {"parent": row.wip_bin_pool, "parenttype": "CFG Kanban WIP Bin Pool", "active": 1},
        ):
            frappe.throw(
                f"Material Flow row {row.idx}: WIP Bin Pool has no active physical bins"
            )

    def _set_item_and_purchase_uom(self):
        if not self.item_code:
            return
        if self.control_type != "Purchase Replenishment":
            self.stock_uom = frappe.db.get_value("Item", self.item_code, "stock_uom")
            return
        uom = get_item_purchase_uom(self.item_code, self.get("purchase_uom"))
        self.stock_uom = uom["stock_uom"]
        self.purchase_uom = uom["purchase_uom"]
        self.purchase_uom_conversion_factor = uom["conversion_factor"]
        plan = calculate_purchase_quantities(
            self.replenishment_qty,
            uom["conversion_factor"],
            self.minimum_order_qty,
            self.purchase_order_multiple,
            self.supplier_pack_size,
        )
        self.purchase_replenishment_qty = plan["purchase_qty"]

    def _validate_sales_demand_configuration(self):
        if not self.get("enable_sales_order_trigger"):
            return
        scope = self.get("demand_scope") or "General"
        if scope != "General" and not self.get("demand_scope_value"):
            frappe.throw("Demand Scope Value is required for a non-General demand scope")
        if self.get("threshold_source") == "Kanban Override" and flt(self.get("minimum_stock_override")) <= 0:
            frappe.throw("Minimum Stock Override must be greater than zero")
        if self.get("production_policy") == "Customer Make-to-Order":
            if scope != "Customer":
                frappe.throw("Customer Make-to-Order Masters must use Customer demand scope")
            if flt(self.get("mto_extra_tolerance_pct")) < 0:
                frappe.throw("MTO Extra Production Tolerance cannot be negative")
        matches = frappe.get_all("CFG Kanban Master", filters={
            "active": 1, "enable_sales_order_trigger": 1, "item_code": self.item_code,
            "destination_warehouse": self.destination_warehouse,
        }, fields=["name", "demand_scope", "demand_scope_value"])
        duplicate = next((row.name for row in matches
            if row.name != self.name and (row.demand_scope or "General") == scope
            and (row.demand_scope_value or "") ==
            (self.get("demand_scope_value") or "")), None)
        if duplicate:
            frappe.throw(f"Sales demand configuration duplicates active Kanban Master {duplicate}")

    def _validate_inventory_threshold_configuration(self):
        if not self.get("enable_inventory_threshold_trigger"):
            return
        if self.control_type not in ("Production", "Purchase Replenishment", "Transfer"):
            frappe.throw(
                "Automatic inventory threshold triggering is available only for Production, "
                "Purchase Replenishment, and Transfer Masters"
            )
        if not self.destination_warehouse:
            frappe.throw("Destination Warehouse is required for automatic threshold triggering")
        warehouse_company = frappe.db.get_value(
            "Warehouse", self.destination_warehouse, "company"
        )
        if warehouse_company != self.company:
            frappe.throw(
                f"Destination Warehouse belongs to {warehouse_company}, not {self.company}"
            )
        if cint(self.get("inventory_max_cards_per_run")) <= 0:
            frappe.throw("Maximum Replenishment Quantities per Trigger must be positive")
        is_stock_item = cint(frappe.db.get_value("Item", self.item_code, "is_stock_item"))
        self.inventory_balance_source = (
            "ERPNext Projected Quantity" if is_stock_item
            else "Kanban Operational Inventory"
        )
        if not is_stock_item and self.control_type == "Production":
            frappe.throw(
                "A non-stock Item cannot use Production threshold replenishment. "
                "Use Purchase Replenishment or Transfer with Kanban Operational Inventory."
            )
        threshold_source = self.get("inventory_threshold_source") or "Kanban Master Override"
        if not is_stock_item and threshold_source != "Kanban Master Override":
            frappe.throw(
                "Non-stock Items must use Kanban Master Override because ERPNext does not "
                "maintain a Warehouse Bin or reorder level for them"
            )
        if threshold_source == "Kanban Master Override":
            reorder_point = flt(self.get("inventory_reorder_point_qty"))
            target = flt(self.get("inventory_target_qty"))
            if reorder_point < 0:
                frappe.throw("Inventory Reorder Point cannot be negative")
            if target <= reorder_point:
                frappe.throw("Replenish Up To quantity must be greater than the Reorder Point")
        else:
            reorder = frappe.db.get_value(
                "Item Reorder",
                {"parent": self.item_code, "warehouse": self.destination_warehouse},
                ["warehouse_reorder_level", "warehouse_reorder_qty"],
                as_dict=True,
            )
            if not reorder or flt(reorder.warehouse_reorder_level) <= 0:
                frappe.throw(
                    "An ERPNext Item Reorder row with a positive Warehouse Reorder Level is "
                    "required for the selected destination Warehouse"
                )
        duplicates = frappe.get_all("CFG Kanban Master", filters={
            "name": ["!=", self.name],
            "active": 1,
            "enable_inventory_threshold_trigger": 1,
            "company": self.company,
            "item_code": self.item_code,
            "destination_warehouse": self.destination_warehouse,
        }, pluck="name", limit_page_length=2)
        if duplicates:
            frappe.throw(
                "Automatic threshold control for this Company, Item, and destination "
                f"Warehouse is already owned by Kanban Master {duplicates[0]}"
            )


def _validate_warehouse_company(warehouse, company, label):
    if not warehouse:
        frappe.throw(f"{label}: Source Warehouse is required")
    details = frappe.db.get_value(
        "Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True
    )
    if not details:
        frappe.throw(f"{label}: Warehouse {warehouse} was not found")
    if details.company != company:
        frappe.throw(f"{label}: Warehouse belongs to {details.company}, not {company}")
    if details.is_group or details.disabled:
        frappe.throw(f"{label}: select an enabled non-group Warehouse")


def _bom_contains_items(bom, items):
    if not bom or not items:
        return False
    return bool(frappe.db.exists("BOM Item", {
        "parent": bom,
        "item_code": ["in", list(items)],
    }))


@frappe.whitelist()
def get_bom_material_flow_preview(bom, company, default_source_warehouse=None):
    """Return the exact BOM Item-operation map for the editable Master child table."""
    frappe.has_permission("CFG Kanban Master", ptype="write", throw=True)
    doc = frappe.get_doc("BOM", bom)
    if doc.docstatus != 1 or not doc.is_active:
        frappe.throw("Select an active submitted BOM")
    if doc.company != company:
        frappe.throw(f"BOM belongs to {doc.company}, not {company}")
    hidden_policy = get_hidden_item_policy()
    restricted_items = (hidden_policy["items"]
                        if not hidden_policy["can_view"] else set())
    rows_by_key = {}
    restricted_components_present = False
    for row in doc.items:
        if row.item_code in restricted_items:
            restricted_components_present = True
            continue
        source = row.get("source_warehouse") or default_source_warehouse
        key = (row.item_code, row.operation or "")
        if key in rows_by_key:
            rows_by_key[key]["bom_qty"] += flt(row.qty)
        else:
            rows_by_key[key] = {
                "item_code": row.item_code,
                "operation": row.operation,
                "source_warehouse": source,
                "bom_qty": flt(row.qty),
                "stock_uom": row.stock_uom,
            }
    return {
        "bom": doc.name,
        "transfer_material_against": doc.get("transfer_material_against"),
        "with_operations": bool(doc.with_operations),
        "rows": list(rows_by_key.values()),
        "restricted_components_present": restricted_components_present,
    }

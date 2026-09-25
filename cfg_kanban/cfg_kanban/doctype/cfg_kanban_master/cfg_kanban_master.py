import frappe
from frappe.model.document import Document


class CFGKanbanMaster(Document):
    def validate(self):
        if self.replenishment_qty <= 0 or self.number_of_cards <= 0:
            frappe.throw("Replenishment quantity and number of cards must be positive")
        if self.control_type == "Purchase Replenishment":
            if not self.default_supplier or not self.destination_warehouse:
                frappe.throw("Default Supplier and Destination Warehouse are required for Purchase Replenishment")
            for fieldname, label in (("supplier_pack_size", "Supplier Pack Size"),
                                     ("minimum_order_qty", "Minimum Order Qty"),
                                     ("purchase_order_multiple", "Purchase Order Multiple"),
                                     ("over_receipt_tolerance_pct", "Over-receipt Tolerance")):
                if (self.get(fieldname) or 0) < 0:
                    frappe.throw(f"{label} cannot be negative")
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
            if row.start_rule == "Minimum Qty Available" and (row.minimum_qty or 0) <= 0:
                frappe.throw(f"Minimum Qty must be positive for operation {row.operation}")
            if row.start_rule == "Minimum Percentage Available" and not 0 < (row.minimum_percentage or 0) <= 100:
                frappe.throw(f"Minimum Percentage must be between 0 and 100 for operation {row.operation}")
            if row.handoff_mode == "Digital Quantity Handoff" and (row.transfer_multiple or 0) <= 0:
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
            if row.reuse_while_valid and (row.validity_duration_hours or 0) <= 0:
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
        self._validate_sales_demand_configuration()

    def _validate_sales_demand_configuration(self):
        if not self.get("enable_sales_order_trigger"):
            return
        scope = self.get("demand_scope") or "General"
        if scope != "General" and not self.get("demand_scope_value"):
            frappe.throw("Demand Scope Value is required for a non-General demand scope")
        if self.get("threshold_source") == "Kanban Override" and (self.get("minimum_stock_override") or 0) <= 0:
            frappe.throw("Minimum Stock Override must be greater than zero")
        if self.get("production_policy") == "Customer Make-to-Order":
            if scope != "Customer":
                frappe.throw("Customer Make-to-Order Masters must use Customer demand scope")
            if (self.get("mto_extra_tolerance_pct") or 0) < 0:
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

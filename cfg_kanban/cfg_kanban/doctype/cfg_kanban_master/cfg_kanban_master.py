import frappe
from frappe.model.document import Document


class CFGKanbanMaster(Document):
    def validate(self):
        if self.replenishment_qty <= 0 or self.number_of_cards <= 0:
            frappe.throw("Replenishment quantity and number of cards must be positive")
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
        keys = [row.field_key for row in self.operator_field_definitions]
        if len(keys) != len(set(keys)):
            frappe.throw("Dynamic operator Field Keys must be unique")
        unknown_fields = [row.operation for row in self.operator_field_definitions
                          if row.operation not in operations]
        if unknown_fields:
            frappe.throw(f"Dynamic operator fields reference operations outside this route: {', '.join(unknown_fields)}")
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

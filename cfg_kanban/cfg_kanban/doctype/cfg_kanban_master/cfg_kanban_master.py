import frappe
from frappe.model.document import Document


class CFGKanbanMaster(Document):
    def validate(self):
        if self.replenishment_qty <= 0 or self.number_of_cards <= 0:
            frappe.throw("Replenishment quantity and number of cards must be positive")
        sequences = [row.sequence for row in self.operation_profiles]
        if len(sequences) != len(set(sequences)):
            frappe.throw("Operation profile sequences must be unique")
        self._validate_sales_demand_configuration()

    def _validate_sales_demand_configuration(self):
        if not self.get("enable_sales_order_trigger"):
            return
        scope = self.get("demand_scope") or "General"
        if scope != "General" and not self.get("demand_scope_value"):
            frappe.throw("Demand Scope Value is required for a non-General demand scope")
        if self.get("threshold_source") == "Kanban Override" and self.get("minimum_stock_override") <= 0:
            frappe.throw("Minimum Stock Override must be greater than zero")
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

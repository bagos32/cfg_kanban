import frappe
from frappe.model.document import Document


class CFGKanbanMaster(Document):
    def validate(self):
        if self.replenishment_qty <= 0 or self.number_of_cards <= 0:
            frappe.throw("Replenishment quantity and number of cards must be positive")
        sequences = [row.sequence for row in self.operation_profiles]
        if len(sequences) != len(set(sequences)):
            frappe.throw("Operation profile sequences must be unique")


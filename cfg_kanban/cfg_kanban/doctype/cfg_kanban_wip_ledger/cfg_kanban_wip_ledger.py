import frappe
from frappe.model.document import Document


class CFGKanbanWIPLedger(Document):
    def validate(self):
        if self.qty <= 0 and self.transaction_type != "Adjusted":
            frappe.throw("Ledger quantity must be positive; transaction type defines direction")

    def on_trash(self):
        frappe.throw("WIP ledger entries are immutable")


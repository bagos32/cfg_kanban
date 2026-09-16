import frappe
from frappe.model.document import Document


class CFGKanbanProcessTask(Document):
    def validate(self):
        if self.status == "Completed" and self.verification_required and not self.verified_on:
            frappe.throw("Supervisor verification is required before this Process Task is completed")

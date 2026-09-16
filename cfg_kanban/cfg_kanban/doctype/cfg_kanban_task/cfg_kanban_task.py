import frappe
from frappe.model.document import Document


class CFGKanbanTask(Document):
    def validate(self):
        if self.status == "Completed" and self.verification_required and not self.verified_on:
            frappe.throw("Supervisor verification is required before this Task is completed")
        if self.kanban_cycle or self.process_execution or self.work_order or self.job_card:
            frappe.throw("Standalone Kanban Tasks cannot own production or ERP manufacturing records")

import frappe
from frappe.model.document import Document


class CFGKanbanJobCode(Document):
    def validate(self):
        self.job_code = (self.job_code or "").strip().upper()
        self.job_title = (self.job_title or "").strip()
        if not self.job_code:
            frappe.throw("Job Code is required")
        if not self.job_title:
            frappe.throw("Job Title is required")


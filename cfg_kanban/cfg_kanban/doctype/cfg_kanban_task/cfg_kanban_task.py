import frappe
from frappe.model.document import Document


class CFGKanbanTask(Document):
    def validate(self):
        if self.status == "Completed" and self.verification_required and not self.verified_on:
            frappe.throw("Supervisor verification is required before this Task is completed")
        if self.status == "Completed" and self.verification_required:
            if self.verification_status != "Approved":
                frappe.throw("A verified Task must have an Approved verification result")
            if self.completed_by and self.completed_by == self.verified_by:
                frappe.throw("Task verification must be performed by a different operator")
        if self.status == "Awaiting Verification" and self.verification_status != "Pending":
            frappe.throw("A Task awaiting verification must have a Pending verification result")
        if self.status == "Correction Required" and self.verification_status != "Rejected":
            frappe.throw("A Task requiring correction must have a Rejected verification result")
        if self.kanban_cycle or self.process_execution or self.work_order or self.job_card:
            frappe.throw("Standalone Kanban Tasks cannot own production or ERP manufacturing records")

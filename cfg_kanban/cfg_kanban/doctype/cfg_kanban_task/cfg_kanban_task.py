import frappe
from frappe.model.document import Document


class CFGKanbanTask(Document):
    def before_validate(self):
        # Repair any in-memory legacy value before Frappe builds Version diffs.
        for row in self.execution_values:
            if row.value is not None and not isinstance(row.value, str):
                row.value = "1" if row.value is True else "0" if row.value is False else str(row.value)

    def validate(self):
        if not self.is_new():
            original = frappe.db.get_value(
                self.doctype,
                self.name,
                ["doctype_action_profile", "doctype_action_trigger",
                 "doctype_action_required"],
                as_dict=True,
            ) or {}
            changed = [
                fieldname for fieldname in (
                    "doctype_action_profile", "doctype_action_trigger",
                    "doctype_action_required",
                )
                if (original.get(fieldname) or None) != (self.get(fieldname) or None)
            ]
            if changed:
                frappe.throw(
                    "The effective DocType Action binding is immutable for a generated Task"
                )
        if self.doctype_action_required and not (
            self.doctype_action_profile and self.doctype_action_trigger
        ):
            frappe.throw("A required DocType Action needs an effective Profile and Trigger")
        if self.status == "Pending Document Posting":
            if not self.doctype_action_required or not self.doctype_action_run:
                frappe.throw("Pending Document Posting requires a linked, required DocType Action Run")
            if self.doctype_action_pending_status not in ("Completed", "Awaiting Verification"):
                frappe.throw("A pending document gate requires its intended next Task status")
        if self.doctype_action_required and self.status == "Completed":
            from cfg_kanban.services.doctype_action_tasks import action_is_satisfied
            if not action_is_satisfied(self.doctype_action_run):
                frappe.throw("The required DocType Action is not ready for Task completion")
        if (self.doctype_action_required
                and self.status == "Awaiting Verification"
                and self.doctype_action_trigger != "After Supervisor Verification"):
            from cfg_kanban.services.doctype_action_tasks import action_is_satisfied
            if not action_is_satisfied(self.doctype_action_run):
                frappe.throw("The required DocType Action must finish before verification")
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

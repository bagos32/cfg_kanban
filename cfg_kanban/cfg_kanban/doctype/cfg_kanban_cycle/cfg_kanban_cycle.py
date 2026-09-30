import frappe
from frappe.model.document import Document


class CFGKanbanCycle(Document):
    def validate(self):
        if not self.kanban_master:
            return
        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.company:
            if self.company != before.company:
                frappe.throw("Company Snapshot is immutable after the Cycle is created")
            self.company = before.company
            return
        master_company = frappe.db.get_value("CFG Kanban Master", self.kanban_master, "company")
        if self.company and self.company != master_company:
            frappe.throw(
                f"Cycle Company {self.company} does not match Kanban Master Company {master_company}"
            )
        self.company = master_company

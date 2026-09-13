import frappe
from frappe.model.document import Document


class CFGKanbanOperationSummary(Document):
    def before_insert(self):
        self.summary_key = self.summary_key or f"{self.kanban_cycle}::{self.operation}"

    def on_trash(self):
        if frappe.db.exists("CFG Kanban Process Execution", {"operation_summary": self.name}):
            frappe.throw("Operation summaries with executions cannot be deleted")

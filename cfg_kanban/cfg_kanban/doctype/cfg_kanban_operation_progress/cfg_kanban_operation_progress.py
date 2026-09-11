import frappe
from frappe.model.document import Document


class CFGKanbanOperationProgress(Document):
    def before_update_after_submit(self):
        frappe.throw("Progress records are immutable; create a correction entry")

    def on_trash(self):
        frappe.throw("Progress records are immutable")

import frappe
from frappe.model.document import Document


class CFGKanbanEvent(Document):
    def on_trash(self):
        frappe.throw("Kanban events are immutable")


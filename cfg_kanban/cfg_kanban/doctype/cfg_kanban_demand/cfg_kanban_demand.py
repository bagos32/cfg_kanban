import frappe
from frappe.model.document import Document


class CFGKanbanDemand(Document):
    def on_trash(self):
        if self.status not in ("No Action", "Cancelled"):
            frappe.throw("Active Kanban demand records cannot be deleted")


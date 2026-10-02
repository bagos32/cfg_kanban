import frappe
from frappe.model.document import Document


class CFGKanbanMaterialTrace(Document):
    def validate(self):
        if self.stock_entry:
            duplicate = frappe.db.get_value(
                "CFG Kanban Material Trace",
                {"stock_entry": self.stock_entry, "name": ["!=", self.name]},
                "name",
            )
            if duplicate:
                frappe.throw(
                    f"Material Trace {duplicate} already controls Stock Entry {self.stock_entry}"
                )


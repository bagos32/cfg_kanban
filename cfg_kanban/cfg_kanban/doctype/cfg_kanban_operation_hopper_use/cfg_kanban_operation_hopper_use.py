import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanOperationHopperUse(Document):
    def validate(self):
        if flt(self.qty) <= 0:
            frappe.throw("Operation Hopper use must be positive")
        if not self.is_new():
            frappe.throw("Operation Hopper consumption evidence is immutable")

    def on_trash(self):
        frappe.throw("Operation Hopper consumption evidence cannot be deleted")

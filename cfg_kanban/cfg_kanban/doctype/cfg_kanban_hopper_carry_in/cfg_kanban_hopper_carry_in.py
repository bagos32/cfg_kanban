import math
import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanHopperCarryIn(Document):
    def validate(self):
        if not math.isfinite(flt(self.qty)) or flt(self.qty) <= 0:
            frappe.throw("Carry-in quantity must be finite and positive")
        if not self.is_new():
            frappe.throw("Hopper carry-in evidence is immutable; use controlled reconciliation")

    def on_trash(self):
        frappe.throw("Hopper carry-in history cannot be deleted")

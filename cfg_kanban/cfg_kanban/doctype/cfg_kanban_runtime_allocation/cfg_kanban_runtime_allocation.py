import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanRuntimeAllocation(Document):
    def validate(self):
        if flt(self.effective_qty) <= 0:
            frappe.throw("Effective Cycle Qty must be positive")
        if flt(self.effective_qty) > flt(self.nominal_card_qty):
            frappe.throw("Effective Cycle Qty cannot exceed the permanent Card quantity")
        if flt(self.effective_qty) < flt(self.nominal_card_qty) and not self.short_cycle_reason:
            frappe.throw("A short-cycle reason is required")

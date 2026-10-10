import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanStockAdoption(Document):
    def validate(self):
        if flt(self.adopted_qty) <= 0:
            frappe.throw("Adopted quantity must be positive")
        if flt(self.tagged_qty_before) + flt(self.adopted_qty) > flt(self.erp_qty_at_adoption) + 0.000001:
            frappe.throw("Adopted quantity exceeds the ERP stock that was untagged at confirmation")
        if self.kanban_cycle and flt(self.cycle_allocated_qty) != flt(self.adopted_qty):
            frappe.throw("A Stock Tag must be allocated to a Kanban Cycle in full")
        if not self.is_new():
            before = self.get_doc_before_save()
            if before:
                immutable = (
                    "company", "warehouse", "item_code", "stock_uom", "batch_no",
                    "adopted_qty", "handling_unit", "visible_tag_code", "packed_on",
                    "expiry_date", "erp_qty_at_adoption", "tagged_qty_before",
                    "untagged_qty_before", "adoption_key", "adopted_by_operator",
                    "operator_session", "adopted_on",
                )
                for fieldname in immutable:
                    if before.get(fieldname) != self.get(fieldname):
                        frappe.throw(f"{self.meta.get_label(fieldname)} is immutable after adoption")

    def on_trash(self):
        if not getattr(frappe.flags, "in_uninstall", False):
            frappe.throw("Stock Adoption records are audit evidence and cannot be deleted")

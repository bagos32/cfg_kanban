import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanOperationHopperFill(Document):
    def validate(self):
        if self.status not in ("Filling", "Ready", "Empty", "Cancelled"):
            frappe.throw("Unsupported operation Hopper fill status")
        if min(flt(self.qty), flt(self.used_qty), flt(self.reserved_qty), flt(self.get("cleared_qty"))) < 0 or flt(self.used_qty) + flt(self.reserved_qty) + flt(self.get("cleared_qty")) > flt(self.qty) + 0.000001:
            frappe.throw("Operation Hopper quantity, use and reservations do not balance")
        if self.status in ("Filling", "Ready") and self.active_hopper_key != (self.get("current_handling_unit") or self.handling_unit):
            frappe.throw("An active operation fill requires its Hopper uniqueness key")
        if self.status in ("Empty", "Cancelled") and self.active_hopper_key:
            frappe.throw("A closed operation fill cannot retain the active Hopper key")
        if not self.is_new():
            before = self.get_doc_before_save()
            for name in ("handling_unit", "work_order", "company", "warehouse", "source_operation", "destination_operation", "source_execution", "source_material_run", "stock_uom", "opened_on"):
                if before and before.get(name) != self.get(name):
                    frappe.throw("Operation Hopper fill identity is immutable")

    def on_trash(self):
        frappe.throw("Operation Hopper fill history cannot be deleted")

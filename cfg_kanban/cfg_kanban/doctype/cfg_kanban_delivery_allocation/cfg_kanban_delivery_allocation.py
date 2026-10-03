import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanDeliveryAllocation(Document):
    def validate(self):
        if flt(self.allocated_qty) <= 0:
            frappe.throw("Allocated Qty must be positive")
        if flt(self.delivered_qty) < 0 or flt(self.delivered_qty) > flt(self.allocated_qty):
            frappe.throw("Delivered Qty must be between zero and Allocated Qty")
        if not self.is_new():
            before = self.get_doc_before_save()
            if before:
                for fieldname in (
                    "delivery_session", "handling_unit", "visible_code",
                    "container_handling_unit", "container_visible_code", "item_code",
                    "batch_no", "stock_uom", "allocated_qty", "source_warehouse",
                    "reserved_by_operator", "operator_session", "reserved_on",
                    "reservation_key",
                ):
                    if before.get(fieldname) != self.get(fieldname):
                        frappe.throw(
                            f"{self.meta.get_label(fieldname)} is immutable after allocation"
                        )

    def on_trash(self):
        frappe.throw("Delivery Allocations are audit records; release or cancel them instead")

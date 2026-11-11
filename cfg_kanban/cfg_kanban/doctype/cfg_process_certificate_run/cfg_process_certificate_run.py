import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGProcessCertificateRun(Document):
    def validate(self):
        if flt(self.selected_qty) < 0 or flt(self.good_qty) < 0 or flt(self.reject_qty) < 0:
            frappe.throw("Certificate Process quantities cannot be negative")
        if flt(self.good_qty) + flt(self.reject_qty) > flt(self.selected_qty) + 0.000001:
            frappe.throw("Good plus Reject quantity cannot exceed the selected quantity")
        if self.item_batch_controlled and self.source_handling_unit and not self.source_batch:
            frappe.throw("The selected source tag must carry the ERPNext Batch")
        if not self.item_batch_controlled and (self.source_batch or self.output_batch):
            frappe.throw("Batch values are not allowed because this Item is not Batch controlled")


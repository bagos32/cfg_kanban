import frappe
from frappe.model.document import Document


class CFGKanbanDeliveryOutcome(Document):
    def validate(self):
        if not self.flags.get('cfg_controlled_outcome'):
            frappe.throw('Delivery outcomes are controlled audit records; use the driver action')

    def on_trash(self):
        frappe.throw('Delivery outcomes are audit records and cannot be deleted')

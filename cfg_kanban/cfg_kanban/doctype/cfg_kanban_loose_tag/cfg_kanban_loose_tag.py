import frappe
from frappe.model.document import Document


class CFGKanbanLooseTag(Document):
    def validate(self):
        if not self.flags.get('cfg_loose_tag_controlled'):
            frappe.throw('Loose Tag contents and audit facts are controlled; use Pack / Cancel Loose Tag')

    def on_trash(self):
        frappe.throw('Loose Tag history must be retained; cancel an unused pack instead')

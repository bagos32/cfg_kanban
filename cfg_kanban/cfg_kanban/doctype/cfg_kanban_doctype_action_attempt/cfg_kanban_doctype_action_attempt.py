import frappe
from frappe.model.document import Document


class CFGKanbanDocTypeActionAttempt(Document):
    def before_insert(self):
        if not self.flags.get("doctype_action_engine_insert"):
            frappe.throw("DocType Action Attempts are created only by the controlled action engine")

    def validate(self):
        if not self.is_new():
            frappe.throw("DocType Action Attempts are immutable")


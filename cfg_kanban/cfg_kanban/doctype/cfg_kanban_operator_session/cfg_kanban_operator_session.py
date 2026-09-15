import frappe
from frappe.model.document import Document


class CFGKanbanOperatorSession(Document):
    def validate(self):
        if self.development_proxy:
            if self.terminal_user != "Administrator":
                frappe.throw("Development proxy sessions must belong to Administrator")
        elif not self.operator_profile:
            frappe.throw("Operator Profile is required for normal operator sessions")

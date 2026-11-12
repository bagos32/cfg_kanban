import frappe
from frappe.model.document import Document


class CFGKanbanWorkOrderYieldOverride(Document):
    def validate(self):
        if self.status not in ("Active", "Revoked") or not (self.reason or "").strip():
            frappe.throw("Work Order yield override requires a valid status and reason")
        if not self.is_new():
            frappe.throw("Work Order Yield Override evidence is immutable; use controlled revocation")

    def on_trash(self):
        frappe.throw("Work Order Yield Override audit records cannot be deleted")

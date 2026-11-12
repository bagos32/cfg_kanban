import frappe
from frappe.model.document import Document


class CFGKanbanMaterialRotationOverride(Document):
    def validate(self):
        if self.status not in ("Active", "Revoked") or not (self.reason or "").strip():
            frappe.throw("Work Order FEFO override requires a valid status and reason")
        if not self.is_new():
            frappe.throw("Material Rotation Override evidence is immutable; use controlled revocation")

    def on_trash(self):
        frappe.throw("Material Rotation Override audit records cannot be deleted")

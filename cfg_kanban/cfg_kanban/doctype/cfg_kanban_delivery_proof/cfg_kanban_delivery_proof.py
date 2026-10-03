import frappe
from frappe.model.document import Document


class CFGKanbanDeliveryProof(Document):
    def validate(self):
        before = None if self.is_new() else self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "delivery_session", "delivery_note", "site_code", "site_name",
            "selling_company", "customer", "customer_address", "source_warehouse",
            "proof_policy", "require_recipient_name", "require_signature",
            "require_photo", "require_gps", "unattended_reason_required",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable proof snapshot")
        if before.state == "Submitted" and self.has_value_changed("state"):
            frappe.throw("Submitted delivery proof cannot return to Draft")

    def on_trash(self):
        frappe.throw("Delivery Proof records are audit evidence and cannot be deleted")

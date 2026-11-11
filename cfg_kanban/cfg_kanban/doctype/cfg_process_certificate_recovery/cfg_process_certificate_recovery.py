import frappe
from frappe.model.document import Document


class CFGProcessCertificateRecovery(Document):
    """Immutable control record for reversing a Certificate Process Repack."""

    def validate(self):
        if not (self.reason or "").strip():
            frappe.throw("A controlled Certificate Process recovery reason is required")
        if self.is_new() or self.flags.get("controlled_update"):
            return
        previous = self.get_doc_before_save()
        if previous and previous.as_dict() != self.as_dict():
            frappe.throw(
                "Certificate Process Recovery records are system-controlled; use the "
                "recovery actions"
            )

    def on_trash(self):
        frappe.throw("Certificate Process Recovery records are audit evidence and cannot be deleted")

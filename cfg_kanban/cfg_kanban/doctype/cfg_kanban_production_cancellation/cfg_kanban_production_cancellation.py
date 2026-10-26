import frappe
from frappe.model.document import Document


class CFGKanbanProductionCancellation(Document):
    """System-controlled audit record for an in-flight production cancellation."""

    def validate(self):
        if not (self.reason or "").strip():
            frappe.throw("A production cancellation reason is required")
        if self.is_new():
            return
        if self.flags.get("controlled_update"):
            return
        previous = self.get_doc_before_save()
        if previous and previous.as_dict() != self.as_dict():
            frappe.throw(
                "Production Cancellation records are system-controlled; use the assessment "
                "and finalization actions"
            )

    def on_trash(self):
        frappe.throw("Production Cancellation records are audit evidence and cannot be deleted")

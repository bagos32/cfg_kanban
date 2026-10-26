import frappe
from frappe.model.document import Document


class CFGKanbanCorrectionRequest(Document):
    """Immutable request facts with service-controlled review and resolution fields."""

    def validate(self):
        if self.is_new():
            if self.status != "Open":
                frappe.throw("A Correction Request must begin Open")
            return
        previous = self.get_doc_before_save()
        if previous and previous.as_dict() != self.as_dict():
            frappe.throw(
                "Correction Requests are audit records; use the Workforce Supervisor Centre "
                "to review or resolve them"
            )

    def on_trash(self):
        frappe.throw("Correction Requests are immutable audit records and cannot be deleted")


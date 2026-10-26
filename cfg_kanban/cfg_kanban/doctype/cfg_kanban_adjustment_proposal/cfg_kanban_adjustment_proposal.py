import frappe
from frappe.model.document import Document


class CFGKanbanAdjustmentProposal(Document):
    """Immutable proposal whose controlled lifecycle is owned by the service layer."""

    def validate(self):
        if self.is_new():
            if self.status != "Prepared":
                frappe.throw("A Kanban Adjustment Proposal must begin Prepared")
            return
        previous = self.get_doc_before_save()
        if previous and previous.as_dict() != self.as_dict():
            frappe.throw(
                "Kanban Adjustment Proposals are audit records; use the Workforce "
                "Supervisor Centre to cancel them"
            )

    def on_trash(self):
        frappe.throw(
            "Kanban Adjustment Proposals are immutable audit records and cannot be deleted"
        )

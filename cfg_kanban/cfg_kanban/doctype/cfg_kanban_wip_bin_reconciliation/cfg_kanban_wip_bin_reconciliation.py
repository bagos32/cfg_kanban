import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanWIPBinReconciliation(Document):
    """Immutable supervisor decision after a submitted WIP-bin consumption is cancelled."""

    def validate(self):
        if flt(self.qty) <= 0:
            frappe.throw("WIP Bin reconciliation quantity must be positive")
        if self.is_new():
            if self.status != "Open" or self.decision:
                frappe.throw("A WIP Bin reconciliation must begin Open without a decision")
            return
        previous = self.get_doc_before_save()
        if previous and previous.as_dict() != self.as_dict():
            frappe.throw(
                "WIP Bin reconciliation records are system-controlled; use the Production "
                "Operator panel resolution action"
            )

    def on_trash(self):
        frappe.throw("WIP Bin reconciliation records are immutable and cannot be deleted")

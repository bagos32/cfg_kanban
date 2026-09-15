import frappe
from frappe.model.document import Document


class CFGKanbanSequenceChange(Document):
    """Append-only supervisor dispatch audit record."""

    def before_insert(self):
        self.changed_by = self.changed_by or frappe.session.user
        self.changed_on = self.changed_on or frappe.utils.now()

    def validate(self):
        if not (self.reason or "").strip():
            frappe.throw("A reason is required for every supervisor sequence change")

    def before_save(self):
        if not self.is_new():
            frappe.throw("Sequence Change records are immutable")

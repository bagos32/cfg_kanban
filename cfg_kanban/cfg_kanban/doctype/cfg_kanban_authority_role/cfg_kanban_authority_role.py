import frappe
from frappe.model.document import Document
from frappe.utils import cint


CAPABILITY_FIELDS = (
    "can_perform_work",
    "can_lead_crew",
    "can_supervise_trainees",
    "can_verify_work",
    "can_approve_progress",
    "can_close_on_behalf",
    "can_correct_records",
    "can_override_material",
    "can_cancel_or_bypass",
    "can_transfer_ownership",
)


class CFGKanbanAuthorityRole(Document):
    def validate(self):
        self.authority_code = (self.authority_code or "").strip().upper()
        if not self.authority_code:
            frappe.throw("Authority Code is required")
        if not any(cint(self.get(fieldname)) for fieldname in CAPABILITY_FIELDS):
            frappe.throw("Select at least one Kanban capability for this Authority Role")


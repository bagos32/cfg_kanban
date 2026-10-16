import frappe
from frappe import _
from frappe.model.document import Document


class CFGActionPilotDraft(Document):
    def validate(self):
        _validate_pilot(self)


def _validate_pilot(doc):
    if not doc.observations:
        frappe.throw(_("At least one pilot observation is required."))

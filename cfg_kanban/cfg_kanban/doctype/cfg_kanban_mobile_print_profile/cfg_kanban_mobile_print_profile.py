import frappe
from frappe.model.document import Document


class CFGKanbanMobilePrintProfile(Document):
    def validate(self):
        from cfg_kanban.services.mobile_printing import validate_profile
        validate_profile(self)

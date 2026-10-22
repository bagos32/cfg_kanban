import frappe
from frappe.model.document import Document
from frappe.utils import cint, getdate, now_datetime

from cfg_kanban.services.crew_policy import assert_approved_crew_profile


class CFGKanbanWorkstationCrewRequirement(Document):
    def validate(self):
        if self.effective_from and self.effective_to \
                and getdate(self.effective_to) < getdate(self.effective_from):
            frappe.throw("Effective To cannot be earlier than Effective From")
    def before_submit(self):
        if not cint(self.active):
            frappe.throw("An inactive Workstation Crew Requirement cannot be approved")
        assert_approved_crew_profile(self.crew_requirement_profile, self.company)
        self.approved_by = frappe.session.user
        self.approved_on = now_datetime()

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

    def before_update_after_submit(self):
        previous = self.get_doc_before_save()
        if not previous or cint(previous.active) == cint(self.active):
            return
        reason = (self.active_change_reason or "").strip()
        previous_reason = (previous.active_change_reason or "").strip()
        if not reason or reason == previous_reason:
            frappe.throw(
                "Enter a new Activation / Deactivation Reason before changing Active"
            )
        if cint(self.active):
            assert_approved_crew_profile(self.crew_requirement_profile, self.company)
        self.active_change_reason = reason
        self.active_changed_by = frappe.session.user
        self.active_changed_on = now_datetime()
        self._active_changed = True

    def on_update_after_submit(self):
        if not getattr(self, "_active_changed", False):
            return
        from cfg_kanban.services.crew_authorization import (
            reconcile_workstation_crew_compliance,
        )
        reconcile_workstation_crew_compliance(
            self.company,
            self.workstation,
            actor={"terminal_user": frappe.session.user},
        )

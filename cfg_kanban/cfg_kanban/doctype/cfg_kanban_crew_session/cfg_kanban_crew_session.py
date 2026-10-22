import frappe
from frappe.model.document import Document


class CFGKanbanCrewSession(Document):
    def validate(self):
        if self.status == "Active":
            existing = frappe.db.get_value(
                self.doctype,
                {
                    "company": self.company,
                    "workstation": self.workstation,
                    "status": "Active",
                    "name": ["!=", self.name],
                },
                "name",
            )
            if existing:
                frappe.throw(
                    f"Workstation {self.workstation} already has active Crew Session {existing}"
                )
        if self.status == "Active" and not self.started_on:
            frappe.throw("Started On is required for an active Crew Session")
        if self.status == "Closed" and not self.ended_on:
            frappe.throw("Ended On is required for a closed Crew Session")
        if self.main_membership:
            membership = frappe.db.get_value(
                "CFG Kanban Crew Membership",
                self.main_membership,
                ["crew_session", "employee", "crew_role"],
                as_dict=True,
            )
            if membership and membership.crew_session != self.name:
                frappe.throw("Main Membership belongs to another Crew Session")
            if membership and membership.employee != self.main_employee:
                frappe.throw("Main Employee must match Main Membership")
            if membership and membership.crew_role != "Main Operator":
                frappe.throw("Main Membership must use the Main Operator role")

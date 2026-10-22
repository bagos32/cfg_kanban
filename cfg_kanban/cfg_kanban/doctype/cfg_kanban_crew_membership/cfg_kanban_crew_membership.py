import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime


class CFGKanbanCrewMembership(Document):
    def validate(self):
        if self.crew_role == "Main Operator" and self.work_category != "Direct Participation":
            frappe.throw("The Main Operator must use Direct Participation")
        if self.status == "On Break" and not self.break_started_on:
            frappe.throw("Break Started On is required while a crew member is on break")
        if self.status == "Left" and not self.left_on:
            frappe.throw("Left On is required for a departed crew member")
        if self.left_on and self.joined_on:
            if get_datetime(self.left_on) < get_datetime(self.joined_on):
                frappe.throw("Left On cannot be earlier than Joined On")

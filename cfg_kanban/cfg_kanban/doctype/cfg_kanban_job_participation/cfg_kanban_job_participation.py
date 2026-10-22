import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_datetime


class CFGKanbanJobParticipation(Document):
    def validate(self):
        expected = {
            "Direct Participation": "Production Labour",
            "Oversight Only": "Oversight",
        }.get(self.work_category)
        if not expected or self.participation_kind != expected:
            frappe.throw("Participation Kind must match the selected Work Category")
        if self.ended_on and get_datetime(self.ended_on) < get_datetime(self.started_on):
            frappe.throw("Ended On cannot be earlier than Started On")
        if flt(self.duration_seconds) < 0 or flt(self.duration_hours) < 0:
            frappe.throw("Participation duration cannot be negative")
        if self.status == "Closed" and not self.ended_on:
            frappe.throw("Ended On is required for a closed participation interval")

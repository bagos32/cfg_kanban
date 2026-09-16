import frappe
from frappe.model.document import Document


class CFGKanbanTaskSchedule(Document):
    def validate(self):
        if self.trigger_type == "Time Interval" and (self.interval_value or 0) <= 0:
            frappe.throw("Interval Value must be positive for a Time Interval schedule")
        if self.trigger_type in ("Time Interval", "Calendar Schedule") and not self.next_due_on:
            frappe.throw("Next Due On is required for an automatic schedule")
        if self.trigger_type == "Calendar Schedule" and (self.calendar_repeat_days or 0) <= 0:
            frappe.throw("Calendar Repeat Days must be positive")
        keys = [row.field_key for row in self.task_field_definitions]
        if len(keys) != len(set(keys)):
            frappe.throw("Standalone Task dynamic Field Keys must be unique")
        wrong_scope = [row.field_key for row in self.task_field_definitions
                       if row.definition_scope != "Standalone Task"]
        if wrong_scope:
            frappe.throw("Task Schedule dynamic fields must use Applies To = Standalone Task")

import frappe
from frappe.model.document import Document


class CFGKanbanTaskSchedule(Document):
    def before_insert(self):
        if not self.name:
            self.set_new_name()
        self.service_point_code = f"CFG:SERVICE:SCHEDULE:{self.name}"

    def validate(self):
        if self.name and not self.service_point_code:
            self.service_point_code = f"CFG:SERVICE:SCHEDULE:{self.name}"
        if self.trigger_type == "Time Interval" and (self.interval_value or 0) <= 0:
            frappe.throw("Interval Value must be positive for a Time Interval schedule")
        if self.trigger_type in ("Time Interval", "Calendar Schedule") and not self.next_due_on:
            frappe.throw("Next Due On is required for an automatic schedule")
        if self.trigger_type == "Calendar Schedule" and (self.calendar_repeat_days or 0) <= 0:
            frappe.throw("Calendar Repeat Days must be positive")
        if self.service_point_enabled and not (self.location or self.asset or self.workstation):
            frappe.throw("A permanent Service Point requires a Location, Asset, or Workstation")
        keys = [row.field_key for row in self.task_field_definitions]
        if len(keys) != len(set(keys)):
            frappe.throw("Standalone Task dynamic Field Keys must be unique")
        wrong_scope = [row.field_key for row in self.task_field_definitions
                       if row.definition_scope != "Standalone Task"]
        if wrong_scope:
            frappe.throw("Task Schedule dynamic fields must use Applies To = Standalone Task")

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class CFGKanbanDashboardProfile(Document):
    def validate(self):
        if self.refresh_interval_seconds and self.refresh_interval_seconds < 10:
            frappe.throw("Refresh Interval must be at least 10 seconds")
        if self.queue_depth and self.queue_depth < 1:
            frappe.throw("Queue Depth must be at least 1")
        if self.column_count and cint(self.column_count) not in (1, 2, 3, 4):
            frappe.throw("Column Count must be between 1 and 4")
        enabled = [row for row in self.workstations if row.enabled]
        names = [row.workstation for row in enabled]
        if len(names) != len(set(names)):
            frappe.throw("A workstation can only appear once in a Dashboard Profile")
        station_views = ("Station Display", "Plant Queue", "Supervisor Sequence Control")
        if self.view_type in station_views and not enabled:
            frappe.throw(f"{self.view_type} requires at least one enabled workstation")

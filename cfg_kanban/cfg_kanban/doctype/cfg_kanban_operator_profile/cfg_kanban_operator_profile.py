import frappe
from frappe.model.document import Document


class CFGKanbanOperatorProfile(Document):
    def validate(self):
        duplicate = frappe.db.get_value(
            self.doctype, {"employee": self.employee, "name": ["!=", self.name]}, "name"
        )
        if duplicate:
            frappe.throw(f"Employee {self.employee} already has Kanban Operator Profile {duplicate}")
        if self.pin_required and not self.get_password("pin", raise_exception=False):
            frappe.throw("PIN is required when PIN Required is enabled")
        responsibilities = [row.responsibility for row in self.responsibilities]
        if len(responsibilities) != len(set(responsibilities)):
            frappe.throw("Responsible Roles must be unique")
        if self.view_all_responsibilities and self.kanban_role != "Supervisor":
            frappe.throw("View All Responsibilities is available only to a Supervisor")

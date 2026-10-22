import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class CFGKanbanCrewTemplate(Document):
    def validate(self):
        self.template_code = re.sub(
            r"[^A-Z0-9-]+", "-", (self.template_code or "").strip().upper()
        ).strip("-")
        if not self.template_code:
            frappe.throw("Template Code is required")
        if cint(self.revision) < 1:
            frappe.throw("Revision must be at least 1")
        self._validate_members()

    def before_submit(self):
        if not cint(self.active):
            frappe.throw("An inactive Crew Template cannot be approved")
        self._validate_members()
        self.approved_by = frappe.session.user
        self.approved_on = now_datetime()

    def _validate_members(self):
        if not self.members:
            frappe.throw("Add at least one expected crew member")
        employees = set()
        main_count = 0
        for row in self.members:
            if row.employee in employees:
                frappe.throw(f"Employee {row.employee} is duplicated in this Crew Template")
            employees.add(row.employee)
            employee = frappe.db.get_value(
                "Employee", row.employee, ["employee_name", "status", "company"], as_dict=True
            )
            if not employee:
                frappe.throw(f"Employee {row.employee} was not found")
            if employee.status and employee.status != "Active":
                frappe.throw(f"Employee {row.employee} is not active")
            if self.company and employee.company and employee.company != self.company:
                frappe.throw(f"Employee {row.employee} does not belong to Company {self.company}")
            profile = frappe.db.get_value(
                "CFG Kanban Operator Profile",
                {"employee": row.employee, "active": 1},
                "name",
            )
            if not profile:
                frappe.throw(f"Employee {row.employee} needs an active Kanban Operator Profile")
            row.employee_name = employee.employee_name
            row.operator_profile = profile
            if row.crew_role == "Main Operator":
                main_count += 1
                if row.work_category != "Direct Participation":
                    frappe.throw("The Main Operator must use Direct Participation")
        if main_count != 1:
            frappe.throw("A Crew Template must contain exactly one Main Operator")

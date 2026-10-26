import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class CFGKanbanOperatorProfile(Document):
    def validate(self):
        self.employee_name = (
            frappe.db.get_value("Employee", self.employee, "employee_name")
            if self.employee else None
        )
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
        job_codes = [row.job_code for row in (self.get("job_codes") or [])]
        if len(job_codes) != len(set(job_codes)):
            frappe.throw("Job Codes must be unique")
        employee_company = frappe.db.get_value("Employee", self.employee, "company")
        for job_code_name in job_codes:
            job_code = frappe.db.get_value(
                "CFG Kanban Job Code", job_code_name,
                ["active", "company"], as_dict=True,
            )
            if not job_code or not job_code.active:
                frappe.throw(f"Job Code {job_code_name} is not active")
            if job_code.company and employee_company and job_code.company != employee_company:
                frappe.throw(
                    f"Job Code {job_code_name} belongs to {job_code.company}, "
                    f"not employee company {employee_company}"
                )
        self._validate_authority_assignments()
        if self.view_all_responsibilities and self.kanban_role != "Supervisor":
            frappe.throw("View All Service Tasks is available only to a Supervisor")

    def _validate_authority_assignments(self):
        seen = set()
        for row in self.get("authority_assignments") or []:
            key = (
                row.authority_role,
                row.company,
                row.operation,
                row.workstation,
                row.responsibility,
                str(row.effective_from or ""),
                str(row.effective_until or ""),
            )
            if key in seen:
                frappe.throw(
                    f"Row {row.idx}: duplicate scoped Authority Assignment"
                )
            seen.add(key)
            role = frappe.db.get_value(
                "CFG Kanban Authority Role", row.authority_role,
                ["active", "company"], as_dict=True,
            )
            if not role or not role.active:
                frappe.throw(
                    f"Row {row.idx}: Authority Role {row.authority_role} is not active"
                )
            if role.company and row.company and role.company != row.company:
                frappe.throw(
                    f"Row {row.idx}: Authority Role {row.authority_role} belongs to "
                    f"{role.company}, not assignment company {row.company}"
                )
            if role.company and not row.company:
                row.company = role.company
            if (row.effective_from and row.effective_until
                    and getdate(row.effective_until) < getdate(row.effective_from)):
                frappe.throw(
                    f"Row {row.idx}: Effective Until cannot be before Effective From"
                )

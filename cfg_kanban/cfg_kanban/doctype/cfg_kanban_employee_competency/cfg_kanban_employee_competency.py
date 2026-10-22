import frappe
from frappe.model.document import Document
from frappe.utils import cint, getdate, now_datetime

from cfg_kanban.services.competency import competency_level_rank


class CFGKanbanEmployeeCompetency(Document):
    def validate(self):
        self._set_employee_and_skill_snapshots()
        self._validate_dates()
        self._validate_level_authorizations()
        self._validate_skill_requirements()

    def before_submit(self):
        self._validate_skill_requirements(force=True)
        self._validate_employee_and_skill_active()
        self._validate_no_overlapping_approval()
        self.status = "Active"
        self.approved_by = frappe.session.user
        self.approved_on = now_datetime()

    def before_update_after_submit(self):
        previous = self.get_doc_before_save()
        if not previous or previous.status == self.status:
            return
        if previous.status == "Revoked" and self.status != "Revoked":
            frappe.throw("A revoked competency cannot be reactivated; create a new approval")
        if self.status not in ("Active", "Suspended", "Revoked"):
            frappe.throw("A submitted competency may be Active, Suspended, or Revoked")
        if not self.status_reason:
            frappe.throw("Enter Status Change / Revocation Reason before changing authorization")
        self.status_changed_by = frappe.session.user
        self.status_changed_on = now_datetime()
        if self.status == "Revoked":
            self.revoked_by = frappe.session.user
            self.revoked_on = self.status_changed_on

    def before_cancel(self):
        if not self.status_reason:
            frappe.throw("Enter Status Change / Revocation Reason before cancelling competency")
        self.status = "Revoked"
        self.status_changed_by = frappe.session.user
        self.status_changed_on = now_datetime()
        self.revoked_by = frappe.session.user
        self.revoked_on = self.status_changed_on

    def _set_employee_and_skill_snapshots(self):
        employee = frappe.db.get_value(
            "Employee", self.employee, ["employee_name", "status"], as_dict=True
        )
        if not employee:
            frappe.throw(f"Employee {self.employee} was not found")
        self.employee_name = employee.employee_name
        profile = frappe.db.get_value(
            "CFG Kanban Operator Profile", {"employee": self.employee}, "name"
        )
        if not profile:
            frappe.throw(
                f"Employee {self.employee} must have a CFG Kanban Operator Profile before "
                "competency can be recorded"
            )
        self.operator_profile = profile
        skill = frappe.db.get_value(
            "CFG Kanban Skill", self.skill,
            ["skill_name", "active", "requires_certification", "requires_expiry_tracking"],
            as_dict=True,
        )
        if not skill:
            frappe.throw(f"Skill {self.skill} was not found")
        self.skill_name = skill.skill_name
        self._skill = skill
        self._employee_status = employee.status

    def _validate_dates(self):
        if self.valid_until and getdate(self.valid_until) < getdate(self.effective_from):
            frappe.throw("Valid Until cannot be earlier than Effective From")

    def _validate_level_authorizations(self):
        level = competency_level_rank(self.competency_level)
        if cint(self.can_work_independently) and level < 2:
            frappe.throw("Independent work authorization requires competency level L2 or higher")
        if cint(self.can_supervise_trainees) and level < 3:
            frappe.throw("Trainee supervision authorization requires competency level L3 or higher")

    def _validate_skill_requirements(self, force=False):
        if self.docstatus != 1 and not force:
            return
        if self._skill.requires_certification and not self.certification_reference:
            frappe.throw(f"Skill {self.skill} requires a Certification Reference")
        if self._skill.requires_expiry_tracking and not self.valid_until:
            frappe.throw(f"Skill {self.skill} requires a Valid Until date")

    def _validate_employee_and_skill_active(self):
        if self._employee_status and self._employee_status != "Active":
            frappe.throw(f"Employee {self.employee} is not active")
        if not cint(self._skill.active):
            frappe.throw(f"Skill {self.skill} is inactive")

    def _validate_no_overlapping_approval(self):
        candidates = frappe.get_all(
            self.doctype,
            filters={
                "employee": self.employee,
                "skill": self.skill,
                "docstatus": 1,
                "status": "Active",
                "name": ["!=", self.name],
            },
            fields=["name", "effective_from", "valid_until"],
        )
        start = getdate(self.effective_from)
        end = getdate(self.valid_until) if self.valid_until else None
        for row in candidates:
            other_start = getdate(row.effective_from)
            other_end = getdate(row.valid_until) if row.valid_until else None
            if (end is None or other_start <= end) and (other_end is None or start <= other_end):
                frappe.throw(
                    f"Competency {row.name} already authorizes {self.employee} for "
                    f"{self.skill} during an overlapping period"
                )

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from cfg_kanban.services.competency import competency_level_rank


class CFGKanbanCrewRequirementProfile(Document):
    def validate(self):
        self.requirement_code = re.sub(
            r"[^A-Z0-9-]+", "-", (self.requirement_code or "").strip().upper()
        ).strip("-")
        if not self.requirement_code:
            frappe.throw("Requirement Code is required")
        if cint(self.revision) < 1:
            frappe.throw("Revision must be at least 1")
        self._validate_crew_shape()
        self._validate_skill_requirements()

    def before_submit(self):
        if not cint(self.active):
            frappe.throw("An inactive Crew Requirement Profile cannot be approved")
        self.approved_by = frappe.session.user
        self.approved_on = now_datetime()

    def _validate_crew_shape(self):
        direct_workers = cint(self.minimum_direct_workers)
        assistants = cint(self.minimum_assistants)
        if direct_workers < 1:
            frappe.throw("Minimum Direct Workers must be at least 1")
        if assistants < 0:
            frappe.throw("Minimum Assistants cannot be negative")
        if self.crew_mode == "Single Operator" and direct_workers != 1:
            frappe.throw("Single Operator mode requires exactly one direct worker")
        if self.crew_mode == "Multiple Operators" and direct_workers < 2:
            frappe.throw("Multiple Operators mode requires at least two direct workers")
        if self.crew_mode == "Supervised Operation" \
                and self.supervision_presence == "Not Required":
            frappe.throw("Supervised Operation requires active supervisor presence")
        if self.crew_mode == "Qualified Lead + Assistants":
            if assistants < 1:
                frappe.throw("Qualified Lead + Assistants requires at least one assistant")
            if direct_workers < assistants + 1:
                frappe.throw(
                    "Minimum Direct Workers must include the qualified lead and all assistants"
                )
        if (self.trainee_policy == "Supervised Only"
                and self.supervision_presence == "Not Required"):
            frappe.throw("Supervised trainees require active supervisor presence")
        if (self.trainee_policy == "Supervised Only"
                or self.supervision_presence != "Not Required") \
                and cint(self.max_trainees_per_supervisor) < 1:
            frappe.throw("Maximum Trainees per Supervisor must be at least 1")

    def _validate_skill_requirements(self):
        if not self.skill_requirements:
            frappe.throw("Add at least one skill-specific crew requirement")
        seen = set()
        roles = set()
        for row in self.skill_requirements:
            key = (row.participation_role, row.skill)
            if key in seen:
                frappe.throw(
                    f"Skill {row.skill} is duplicated for crew role {row.participation_role}"
                )
            seen.add(key)
            roles.add(row.participation_role)
            if cint(row.minimum_people) < 1:
                frappe.throw(f"Minimum People must be positive for skill {row.skill}")
            competency_level_rank(row.minimum_level)
            if not frappe.db.get_value("CFG Kanban Skill", row.skill, "active"):
                frappe.throw(f"Skill {row.skill} is inactive")
            if row.participation_role == "Qualified Lead":
                row.require_independent_authorization = 1
            if row.participation_role == "Active Supervisor":
                row.require_supervisor_authorization = 1
        if self.crew_mode == "Qualified Lead + Assistants" and "Qualified Lead" not in roles:
            frappe.throw("Add a Qualified Lead skill requirement")
        if (self.supervision_presence != "Not Required"
                or self.trainee_policy == "Supervised Only") \
                and "Active Supervisor" not in roles:
            frappe.throw("Add an Active Supervisor skill requirement")

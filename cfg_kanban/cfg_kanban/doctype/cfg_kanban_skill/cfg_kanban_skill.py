import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, cstr


SKILL_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


class CFGKanbanSkill(Document):
    def validate(self):
        self.skill_code = cstr(self.skill_code).strip().upper()
        self.skill_name = cstr(self.skill_name).strip()
        self.skill_category = cstr(self.skill_category).strip()
        if not SKILL_CODE_PATTERN.fullmatch(self.skill_code or ""):
            frappe.throw(
                "Skill Code may contain only uppercase letters, numbers, hyphen, and underscore"
            )
        if cint(self.default_validity_days) < 0:
            frappe.throw("Default Validity (Days) cannot be negative")
        if not self.requires_expiry_tracking:
            self.default_validity_days = 0
        duplicate = frappe.db.get_value(
            self.doctype,
            {"skill_code": self.skill_code, "name": ["!=", self.name]},
            "name",
        )
        if duplicate:
            frappe.throw(f"Skill Code {self.skill_code} is already used by {duplicate}")

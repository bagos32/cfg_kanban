import uuid

import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import validate_physical_code_namespace
from cfg_kanban.services.physical_identity import normalize_physical_code


class CFGKanbanTagFamily(Document):
    def before_insert(self):
        try:
            normalized = normalize_physical_code(self.family_code)
        except ValueError as exc:
            frappe.throw(str(exc))
        if normalized != self.family_code:
            frappe.throw("Preprinted Main Tag Code cannot contain outer whitespace")
        self.child_count = int(self.child_count or 0)
        self.child_separator = self.child_separator or "-"
        self._build_identities()
        for identity in self.identities:
            validate_physical_code_namespace(identity.visible_code, "Registered Tag Identity")

    def validate(self):
        self.child_count = int(self.child_count or 0)
        self.child_separator = self.child_separator or "-"
        if self.child_count < 0 or self.child_count > 20:
            frappe.throw("Detachable Child Count must be between 0 and 20")
        if (len(self.child_separator) > 3 or self.child_separator != self.child_separator.strip()
                or any(character.isdigit() or ord(character) < 32
                       for character in self.child_separator)):
            frappe.throw("Child Separator must be one to three non-numeric characters")
        before = None if self.is_new() else self.get_doc_before_save()
        if before and int(before.child_count or 0) != self.child_count:
            frappe.throw("Detachable Child Count cannot change after the tag family is created")
        if before and before.issued_company != self.issued_company:
            frappe.throw("Issuing Company / Number Namespace cannot change after creation")
        if before and (before.child_separator or "-") != self.child_separator:
            frappe.throw("Child Separator cannot change after the tag family is created")
        if before and before.range_registry and before.range_registry != self.range_registry:
            frappe.throw("Source Tag Range Registry cannot change after creation")
        if before:
            previous = {
                row.visible_code: (row.child_index, row.tag_role, row.opaque_token)
                for row in before.identities
            }
            current = {
                row.visible_code: (row.child_index, row.tag_role, row.opaque_token)
                for row in self.identities
            }
            if previous != current:
                frappe.throw("Registered tag identity codes and tokens are immutable")
        self._validate_identities()

    def _build_identities(self):
        if self.identities:
            return
        self.append("identities", {
            "tag_role": "Main",
            "child_index": 0,
            "visible_code": self.family_code,
            "opaque_token": str(uuid.uuid4()),
            "state": "Unused",
        })
        for index in range(1, self.child_count + 1):
            self.append("identities", {
                "tag_role": "Child",
                "child_index": index,
                "visible_code": f"{self.family_code}{self.child_separator}{index}",
                "opaque_token": str(uuid.uuid4()),
                "state": "Unused",
            })

    def _validate_identities(self):
        expected = list(range(0, self.child_count + 1))
        actual = sorted(row.child_index for row in self.identities)
        if actual != expected:
            frappe.throw("Tag identities must contain the main tag and every configured child index")
        for row in self.identities:
            expected_code = (
                self.family_code
                if row.child_index == 0
                else f"{self.family_code}{self.child_separator}{row.child_index}"
            )
            expected_role = "Main" if row.child_index == 0 else "Child"
            if row.visible_code != expected_code or row.tag_role != expected_role or not row.opaque_token:
                frappe.throw("Tag identity codes, roles, and opaque tokens are system controlled")

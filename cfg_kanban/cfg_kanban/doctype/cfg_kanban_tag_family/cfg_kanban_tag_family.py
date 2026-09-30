import uuid

import frappe
from frappe.model.document import Document


class CFGKanbanTagFamily(Document):
    def before_insert(self):
        self.child_count = int(self.child_count or 0)
        self._build_identities()

    def validate(self):
        self.child_count = int(self.child_count or 0)
        if self.child_count < 0 or self.child_count > 20:
            frappe.throw("Detachable Child Count must be between 0 and 20")
        before = None if self.is_new() else self.get_doc_before_save()
        if before and int(before.child_count or 0) != self.child_count:
            frappe.throw("Detachable Child Count cannot change after the tag family is created")
        if before and before.issued_company != self.issued_company and any(
            row.handling_unit for row in before.identities
        ):
            frappe.throw("Issued Company cannot change after a tag identity is activated")
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
                "visible_code": f"{self.family_code}-{index}",
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
                else f"{self.family_code}-{row.child_index}"
            )
            expected_role = "Main" if row.child_index == 0 else "Child"
            if row.visible_code != expected_code or row.tag_role != expected_role or not row.opaque_token:
                frappe.throw("Tag identity codes, roles, and opaque tokens are system controlled")

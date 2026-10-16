import frappe
from frappe.model.document import Document
from frappe.utils import cint

from cfg_kanban.services.doctype_actions import (
    metadata_fingerprint,
    profile_configuration_signature,
    validate_profile_structure,
)


class CFGKanbanDocTypeActionProfile(Document):
    def before_validate(self):
        self.configuration_revision = max(cint(self.configuration_revision), 1)
        previous = self.get_doc_before_save()
        if not previous:
            return
        if profile_configuration_signature(previous) == profile_configuration_signature(self):
            return
        self.configuration_revision = max(cint(previous.configuration_revision) + 1, 1)
        self.validation_status = "Not Validated"
        self.last_validated_at = None
        self.metadata_fingerprint = None
        self.enabled = 0

    def validate(self):
        validate_profile_structure(self)
        if self.enabled:
            if self.validation_status != "Valid" or not self.metadata_fingerprint:
                frappe.throw("Validate Configuration before enabling this DocType Action Profile")
            current = metadata_fingerprint(frappe.get_meta(self.target_doctype))
            if current != self.metadata_fingerprint:
                frappe.throw(
                    "Target DocType metadata changed. Revalidate this profile before enabling it."
                )


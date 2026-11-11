import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class CFGProcessCertificateType(Document):
    def autoname(self):
        self.certificate_code = _normalise_code(self.certificate_code)
        self.revision = cint(self.revision or 1)
        self.name = f"{self.certificate_code}-R{self.revision:03d}"

    def validate(self):
        self.certificate_code = _normalise_code(self.certificate_code)
        self.certificate_name = (self.certificate_name or "").strip()
        self.description = (self.description or "").strip()
        self.revision = cint(self.revision or 1)
        self.validity_days = cint(self.validity_days)
        if self.revision < 1:
            frappe.throw("Certificate revision must be at least 1")
        if self.is_new():
            duplicate = frappe.db.exists(self.doctype, {
                "certificate_code": self.certificate_code,
                "revision": self.revision,
            })
            if duplicate:
                frappe.throw(
                    f"Certificate {self.certificate_code} revision {self.revision} already exists"
                )
        if self.validity_days < 0:
            frappe.throw("Default Validity cannot be negative")
        if self.item and self.item_group:
            frappe.throw("Select either an exact Item or an Item Group, not both")
        if self.expiry_required and not self.validity_days:
            frappe.throw("Default Validity is required when Expiry Date Required is enabled")
        self._audit_active_change()

    def before_submit(self):
        if not self.active:
            frappe.throw("An inactive Process Certificate Type cannot be approved")
        self.approved_by = frappe.session.user
        self.approved_on = now_datetime()

    def _audit_active_change(self):
        if self.is_new() or not self.has_value_changed("active"):
            return
        if not (self.active_change_reason or "").strip():
            frappe.throw("Active Status Change Reason is required")
        self.active_changed_by = frappe.session.user
        self.active_changed_on = now_datetime()


def _normalise_code(value):
    code = re.sub(r"[^A-Z0-9_-]+", "_", (value or "").strip().upper()).strip("_")
    if not code:
        frappe.throw("Certificate Code is required")
    if len(code) > 40:
        frappe.throw("Certificate Code cannot exceed 40 characters")
    return code

import hashlib
import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class CFGProcessCertificateSet(Document):
    def autoname(self):
        self._prepare_members()
        self.set_code = f"PCS-{self.signature_hash[:12].upper()}"
        self.name = self.set_code

    def before_insert(self):
        self.created_by = frappe.session.user
        self.created_on = now_datetime()

    def validate(self):
        self._prepare_members()
        if not self.set_code:
            self.set_code = self.name or f"PCS-{self.signature_hash[:12].upper()}"
        self._protect_membership()
        self._audit_deactivation()

    def _prepare_members(self):
        if not self.members:
            frappe.throw("Add at least one approved Process Certificate Type")
        snapshots = []
        seen = set()
        for row in self.members:
            if row.certificate_type in seen:
                frappe.throw(f"Certificate Type {row.certificate_type} is repeated")
            seen.add(row.certificate_type)
            certificate_type = frappe.get_doc(
                "CFG Process Certificate Type", row.certificate_type
            )
            if certificate_type.docstatus != 1 or not certificate_type.active:
                frappe.throw(
                    f"Certificate Type {row.certificate_type} must be approved and Active"
                )
            row.certificate_code_snapshot = certificate_type.certificate_code
            row.revision_snapshot = certificate_type.revision
            row.certificate_name_snapshot = certificate_type.certificate_name
            snapshots.append({
                "certificate_type": row.certificate_type,
                "code": row.certificate_code_snapshot,
                "revision": row.revision_snapshot,
                "name": row.certificate_name_snapshot,
            })
        snapshots.sort(key=lambda value: (value["code"], value["revision"]))
        self.set("members", sorted(
            self.members,
            key=lambda row: (row.certificate_code_snapshot, row.revision_snapshot),
        ))
        canonical = [
            [value["certificate_type"], value["revision"]] for value in snapshots
        ]
        self.signature_hash = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.member_codes = " + ".join(value["code"] for value in snapshots)
        if not (self.set_name or "").strip():
            self.set_name = self.member_codes

    def _protect_membership(self):
        if self.is_new():
            duplicate = frappe.db.get_value(
                self.doctype, {"signature_hash": self.signature_hash}, "name"
            )
            if duplicate:
                frappe.throw(
                    f"Certificate Set {duplicate} already represents this exact combination"
                )
            return
        before = self.get_doc_before_save()
        if not before:
            return
        before_members = sorted(
            (row.certificate_type, row.revision_snapshot) for row in before.members
        )
        after_members = sorted(
            (row.certificate_type, row.revision_snapshot) for row in self.members
        )
        if before_members != after_members or before.set_code != self.set_code:
            frappe.throw(
                "Certificate Set membership and code are immutable; create a new Set"
            )

    def _audit_deactivation(self):
        if self.is_new() or not self.has_value_changed("active"):
            return
        if self.active:
            self.deactivation_reason = None
            self.deactivated_by = None
            self.deactivated_on = None
            return
        if not (self.deactivation_reason or "").strip():
            frappe.throw("Deactivation Reason is required")
        self.deactivated_by = frappe.session.user
        self.deactivated_on = now_datetime()

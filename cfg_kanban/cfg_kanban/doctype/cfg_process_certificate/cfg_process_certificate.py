import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGProcessCertificate(Document):
    def validate(self):
        certificate_type = frappe.get_doc(
            "CFG Process Certificate Type", self.certificate_type
        )
        if certificate_type.docstatus != 1:
            frappe.throw("Process Certificate Type must be approved")
        certificate_set = frappe.get_doc(
            "CFG Process Certificate Set", self.certificate_set
        )
        if self.certificate_type not in {
            row.certificate_type for row in certificate_set.members
        }:
            frappe.throw("Resulting Certificate Set does not contain this Certificate Type")
        handling_unit = frappe.get_doc("CFG Kanban Handling Unit", self.handling_unit)
        expected = (
            handling_unit.item_code,
            handling_unit.stock_uom,
            handling_unit.inventory_company,
            handling_unit.current_warehouse,
            handling_unit.batch_no,
        )
        actual = (
            self.item_code,
            self.stock_uom,
            self.inventory_company,
            self.warehouse,
            self.batch_no,
        )
        if actual != expected:
            frappe.throw(
                "Certificate Item, UOM, Company, Warehouse, and Batch must match the Handling Unit"
            )
        if flt(self.certified_qty) <= 0 or flt(self.certified_qty) > flt(handling_unit.current_qty):
            frappe.throw("Certified Qty must be positive and cannot exceed the Handling Unit quantity")
        if self.valid_until and self.valid_from and self.valid_until < self.valid_from:
            frappe.throw("Valid Until cannot be earlier than Valid From")
        self.certificate_code_snapshot = certificate_type.certificate_code
        self.certificate_name_snapshot = certificate_type.certificate_name
        self.revision_snapshot = certificate_type.revision
        self._protect_issued_identity()

    def _protect_issued_identity(self):
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before:
            return
        mutable = {
            "status", "revoked_on", "revoked_by", "revocation_reason", "superseded_by",
            "modified", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by",
        }
        changed = [
            fieldname for fieldname in self.meta.get_valid_columns()
            if fieldname not in mutable and self.get(fieldname) != before.get(fieldname)
        ]
        if changed:
            frappe.throw(
                "Issued Process Certificate identity is immutable; revoke and issue a replacement"
            )

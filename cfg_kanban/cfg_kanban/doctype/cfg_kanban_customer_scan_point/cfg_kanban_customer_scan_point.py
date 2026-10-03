import uuid

import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import (
    validate_physical_code_namespace,
    validate_price_list_mode,
    validate_warehouse_company,
)
from cfg_kanban.services.physical_identity import normalize_physical_code


class CFGKanbanCustomerScanPoint(Document):
    def before_insert(self):
        try:
            normalized = normalize_physical_code(self.site_code)
        except ValueError as exc:
            frappe.throw(str(exc))
        if normalized != self.site_code:
            frappe.throw("Printed Customer Site Code cannot contain outer whitespace")
        validate_physical_code_namespace(self.site_code, "Customer Scan Point")
        self.opaque_token = self.opaque_token or str(uuid.uuid4())

    def validate(self):
        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.opaque_token != self.opaque_token:
            frappe.throw("Opaque Scan Token is immutable; replace the Customer Scan Point instead")
        validate_price_list_mode(self.default_price_list, "selling", "Default Price List")
        validate_warehouse_company(
            self.correction_return_warehouse, self.selling_company,
            "Delivery Correction Return Warehouse",
        )
        if self.customer_address and not frappe.db.exists(
            "Dynamic Link",
            {
                "parenttype": "Address",
                "parent": self.customer_address,
                "link_doctype": "Customer",
                "link_name": self.customer,
            },
        ):
            frappe.throw(
                f"Address {self.customer_address} is not linked to Customer {self.customer}"
            )
        self.unattended_reason_required = int(
            self.proof_policy == "Unattended Delivery Allowed"
        )

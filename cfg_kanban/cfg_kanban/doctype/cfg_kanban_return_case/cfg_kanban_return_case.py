import uuid

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from cfg_kanban.services.logistics_foundation import validate_warehouse_company


class CFGKanbanReturnCase(Document):
    def before_insert(self):
        self.scan_token = self.scan_token or str(uuid.uuid4())

    def validate(self):
        validate_warehouse_company(
            self.correction_return_warehouse, self.selling_company,
            "Correction Return Warehouse",
        )
        if flt(self.claimed_total_qty) <= 0:
            frappe.throw("Return Case claimed quantity must be greater than zero")
        if not self.lines:
            frappe.throw("Return Case requires at least one returned item")
        if self.return_flow == "Delivery Note Correction":
            if not self.original_delivery_note or not self.original_delivery_session:
                frappe.throw("Delivery Note Correction requires its original delivery")
            if not self.correction_return_warehouse:
                frappe.throw("Delivery Note Correction requires a Return Warehouse")
        elif self.return_flow == "Customer Return for QC" and not self.inspection_location:
            frappe.throw("Customer Return for QC requires an Inspection Custody Location")
        before = None if self.is_new() else self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "scan_token", "customer_scan_point", "original_delivery_session",
            "original_delivery_note", "delivery_proof", "selling_company", "customer",
            "customer_address", "site_code", "site_name", "return_flow",
            "inspection_location", "correction_return_warehouse", "claimed_on",
            "customer_return_reason", "customer_acknowledgement_name",
            "customer_acknowledged_on",
            "claimed_total_qty", "created_by_operator", "created_operator_session",
            "idempotency_key",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable intake snapshot")
        old_lines = [row.as_dict() for row in before.lines]
        new_lines = [row.as_dict() for row in self.lines]
        protected = (
            "original_delivery_allocation", "original_delivery_note_item",
            "original_handling_unit", "original_visible_code",
            "item_code", "batch_no", "expiry_date", "stock_uom", "delivered_qty",
            "claimed_qty", "condition", "details",
        )
        if len(old_lines) != len(new_lines) or any(
            old.get(field) != new.get(field)
            for old, new in zip(old_lines, new_lines)
            for field in protected
        ):
            frappe.throw("Return intake identity and claimed quantities are immutable")

    def on_trash(self):
        frappe.throw("Return Cases are audit records; use controlled cancellation instead")

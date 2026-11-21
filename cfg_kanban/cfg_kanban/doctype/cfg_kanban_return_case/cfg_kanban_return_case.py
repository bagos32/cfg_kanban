import uuid

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from cfg_kanban.services.logistics_foundation import validate_warehouse_company


class CFGKanbanReturnCase(Document):
    def before_insert(self):
        self.scan_token = self.scan_token or str(uuid.uuid4())

    def validate(self):
        method = self.get('intake_method') or 'Customer Site'
        if method not in ('Customer Site', 'Direct Customer'):
            frappe.throw('Select a valid return intake method')
        if method == 'Direct Customer':
            if (self.return_flow != 'Customer Return for QC' or self.customer_scan_point
                    or self.site_code or self.site_name
                    or self.original_delivery_session or self.original_delivery_note
                    or not self.selling_company or not self.customer):
                frappe.throw('Direct Customer intake requires Company/Customer QC custody without a Customer Site or delivery correction')
        elif not self.customer_scan_point or not self.site_code or not self.site_name:
            frappe.throw('Customer Site intake and delivery corrections require a Customer Scan Point and its Site snapshots')
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
            if self.get('stock_already_owned') and not self.flags.get('cfg_driver_return'):
                frappe.throw('Company-owned refusal cases are created only through the controlled driver outcome')
            return
        immutable = (
            "owned_stock_issue", "collected_by", "collected_on", "collection_key", "stock_already_owned", "driver_trip", "driver_stop_key", "collection_vehicle_warehouse", "reported_source_reference", "driver_delivery_outcome",
            "scan_token", "intake_method", "intake_payload_hash", "customer_scan_point", "original_delivery_session",
            "original_delivery_note", "delivery_proof", "selling_company", "customer",
            "customer_address", "site_code", "site_name", "return_flow",
            "inspection_location", "correction_return_warehouse", "claimed_on",
            "customer_return_reason", "customer_acknowledgement_name",
            "customer_acknowledged_on",
            "claimed_total_qty", "created_by_operator", "created_operator_session",
            "idempotency_key",
        )
        for fieldname in immutable:
            old, new = before.get(fieldname), self.get(fieldname)
            if fieldname == 'intake_method':
                old, new = old or 'Customer Site', new or 'Customer Site'
            if old != new:
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable intake snapshot")
        old_lines = [row.as_dict() for row in before.lines]
        new_lines = [row.as_dict() for row in self.lines]
        protected = (
            "driver_outcome_line", "original_delivery_allocation", "original_delivery_note_item",
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

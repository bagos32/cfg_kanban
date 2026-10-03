import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import validate_warehouse_company


class CFGKanbanDeliverySession(Document):
    def validate(self):
        validate_warehouse_company(
            self.source_warehouse, self.selling_company, "Lorry Warehouse"
        )
        if self.source_warehouse and frappe.get_meta("Warehouse").has_field(
            "cfg_is_vehicle_warehouse"
        ) and not frappe.db.get_value(
            "Warehouse", self.source_warehouse, "cfg_is_vehicle_warehouse"
        ):
            frappe.throw("Delivery Session source must be a configured Vehicle Warehouse")
        before = None if self.is_new() else self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "customer_scan_point", "site_code", "site_name", "selling_company",
            "customer", "customer_address", "territory", "route_reference",
            "source_warehouse", "vehicle_reference", "price_list", "proof_policy",
            "auto_submit_delivery_note",
            "require_recipient_name", "require_signature", "require_photo", "require_gps",
            "unattended_reason_required", "started_by_operator", "operator_session",
            "started_on", "idempotency_key",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable session snapshot")

    def on_trash(self):
        frappe.throw("Delivery Sessions are audit records; cancel an unused session instead")

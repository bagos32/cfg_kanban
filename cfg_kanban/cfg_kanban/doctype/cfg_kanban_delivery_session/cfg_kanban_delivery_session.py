import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import validate_warehouse_company


class CFGKanbanDeliverySession(Document):
    def validate(self):
        mode = self.get("fulfilment_mode") or "Vehicle Delivery"
        validate_warehouse_company(self.source_warehouse, self.selling_company, "Source Warehouse")
        if mode in ("Direct Warehouse Delivery", "Customer Pickup"):
            from cfg_kanban.services.warehouse_fulfilment import source_warehouse
            source_warehouse(self.source_warehouse, self.selling_company)
            plan = frappe.db.get_value("CFG Kanban Dispatch Plan", self.dispatch_plan,
                ["fulfilment_mode", "source_warehouse", "company", "customer_site"], as_dict=True) if self.dispatch_plan else None
            if (not plan or plan.fulfilment_mode != mode or plan.source_warehouse != self.source_warehouse
                    or plan.company != self.selling_company or plan.customer_site != self.customer_scan_point
                    or self.vehicle_reference or self.route_stop):
                frappe.throw("Warehouse Delivery Session requires its exact prepared customer Plan")
            if mode == "Customer Pickup" and self.proof_policy != "Required":
                frappe.throw("Customer Pickup requires attended acknowledgement")
        elif mode == "Vehicle Delivery":
            if self.source_warehouse and frappe.get_meta("Warehouse").has_field(
                    "cfg_is_vehicle_warehouse") and not frappe.db.get_value(
                    "Warehouse", self.source_warehouse, "cfg_is_vehicle_warehouse"):
                frappe.throw("Delivery Session source must be a configured Vehicle Warehouse")
        else:
            frappe.throw("Unsupported Delivery Session fulfilment mode")
        before = None if self.is_new() else self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "driver_delivery_outcome", "customer_scan_point", "site_code", "site_name", "selling_company",
            "customer", "customer_address", "territory", "route_reference",
            "source_warehouse", "vehicle_reference", "price_list", "proof_policy",
            "auto_submit_delivery_note", "require_delivery_product_scan",
            "require_recipient_name", "require_signature", "require_photo", "require_gps",
            "unattended_reason_required", "started_by_operator", "operator_session",
            "started_on", "idempotency_key", "dispatch_plan", "sales_order", "sales_order_context_json", "route_stop", "fulfilment_mode", "pickup_acknowledgement",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable session snapshot")

    def on_trash(self):
        frappe.throw("Delivery Sessions are audit records; cancel an unused session instead")

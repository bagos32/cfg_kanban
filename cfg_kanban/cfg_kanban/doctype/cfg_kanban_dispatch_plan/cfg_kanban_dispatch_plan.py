import hashlib
import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt


ACTIVE_STATES = {
    "Draft", "Awaiting Approval", "Approved", "Picking", "Ready for Vehicle",
    "Ready for Fulfilment", "Fulfilment In Progress", "Fulfilled",
    "Vehicle Claimed", "Loading", "Ready to Dispatch", "Dispatch Pending", "Loaded",
}


class CFGKanbanDispatchPlan(Document):
    """E2 business authorization and reservation header; never an ERP stock document."""

    def validate(self):
        before = None if self.is_new() else self.get_doc_before_save()
        if bool(self.get('has_loose_tags')) != bool(before.get('has_loose_tags') if before else False):
            frappe.throw('Loose Tag dispatch tracking is controlled by Pack Loose Tag')
        if (self.get('follow_on_trip') or None)!=((before.get('follow_on_trip') or None) if before else None) and not self.flags.get('cfg_follow_on'):
            frappe.throw('Existing-stock provenance is controlled by the follow-on action')
        for field in ('office_delivery_trip','office_stop_key','office_source_hash','existing_lorry_stock_only'):
            if (self.get(field) or None)!=((before.get(field) or None) if before else None) and not (getattr(self,'flags',None) or {}).get('cfg_office_dispatch'):
                frappe.throw('Office dispatch provenance is immutable; generate it from the Trip')
        if before and self.get('office_delivery_trip'):
            fields=('company','dispatch_profile','source_warehouse','plan_type','fulfilment_mode','customer_site','sales_order','required_date','trip_date')
            request=lambda doc:[(r.item_code,r.batch_no or '',r.stock_uom,flt(r.requested_qty),r.sales_order_item or '') for r in doc.lines]
            if any(self.get(f)!=before.get(f) for f in fields) or request(self)!=request(before):
                frappe.throw('Change generated dispatch quantities and sources on its office Delivery Trip before execution')
        if self.get('stop_cancellation') != (before.get('stop_cancellation') if before else None):
            frappe.throw('Customer stop cancellation is a controlled immutable execution reference')
        if self.get('driver_delivery_outcome') != (before.get('driver_delivery_outcome') if before else None):
            frappe.throw('Driver delivery outcome is a controlled immutable execution reference')
        if self.state not in ACTIVE_STATES | {"Cancelled", "Exception", "Reconciled"}:
            frappe.throw(f"Unsupported Dispatch Plan state {self.state}")
        if self.priority not in {"Low", "Normal", "High", "Urgent"}:
            frappe.throw("Priority must be Low, Normal, High or Urgent")
        if self.plan_type == "Customer Order" and not self.customer_site:
            frappe.throw("Customer Order Dispatch Plan requires a Customer Site")
        if self.plan_type == "Customer Order" and not self.required_date:
            frappe.throw("Customer Order Dispatch Plan requires a Required Date")
        if self.plan_type == "Open Route Stock" and not (self.logistics_route or self.territory):
            frappe.throw("Open Route Stock requires a Logistics Route or Territory")
        if self.plan_type == "Open Route Stock" and not self.trip_date:
            frappe.throw("Open Route Stock requires a Trip Date")
        if self.fulfilment_mode in ("Direct Warehouse Delivery", "Customer Pickup"):
            if self.plan_type != "Customer Order" or self.vehicle_warehouse or self.movement_manifest:
                frappe.throw("Warehouse fulfilment requires a Customer Order without a vehicle or loading Manifest")
        if not self.lines and not (self.get('existing_lorry_stock_only') and self.get('office_delivery_trip') and self.plan_type=='Open Route Stock'):
            frappe.throw("Dispatch Plan requires at least one Item line")
        seen = set()
        requested = 0
        for row in self.lines:
            if flt(row.requested_qty) <= 0:
                frappe.throw(f"Row {row.idx}: Requested Qty must be positive")
            key = (row.item_code, row.batch_no or "", row.sales_order_item if self.get("office_delivery_trip") else "")
            if key in seen:
                frappe.throw(
                    f"Row {row.idx}: combine duplicate Item/Batch {row.item_code} / "
                    f"{row.batch_no or 'No Batch'} into one line"
                )
            seen.add(key)
            requested += flt(row.requested_qty)
        self.total_requested_qty = requested
        if flt(self.total_reserved_qty) > requested + 0.000001:
            frappe.throw("Reserved quantity cannot exceed requested quantity")
        if flt(self.total_loaded_qty) > requested + 0.000001:
            frappe.throw("Loaded quantity cannot exceed requested quantity")
        if self.vehicle_warehouse:
            vehicle = frappe.db.get_value(
                "Warehouse", self.vehicle_warehouse,
                ["company", "disabled", "is_group", "cfg_is_vehicle_warehouse",
                 "cfg_vehicle_reference"], as_dict=True,
            )
            if (not vehicle or vehicle.disabled or vehicle.is_group
                    or not vehicle.cfg_is_vehicle_warehouse):
                frappe.throw("Claimed Lorry Warehouse must be an active vehicle Warehouse")
            if vehicle.company != self.company:
                frappe.throw("Claimed Lorry Warehouse must belong to the Dispatch Plan Company")
            if self.vehicle_reference != vehicle.cfg_vehicle_reference:
                frappe.throw("Physical Vehicle must match the claimed Lorry Warehouse")
        if self.movement_manifest:
            manifest_plan = frappe.db.get_value(
                "CFG Kanban Movement Manifest", self.movement_manifest, "dispatch_plan"
            )
            if manifest_plan and manifest_plan != self.name:
                frappe.throw("Movement Manifest belongs to a different Dispatch Plan")
        if not self.profile_snapshot_json or not self.profile_snapshot_hash:
            frappe.throw("Dispatch Profile snapshot is required")
        try:
            snapshot = json.loads(self.profile_snapshot_json)
        except (TypeError, ValueError):
            frappe.throw("Dispatch Profile snapshot is not valid JSON")
        if snapshot.get("name") != self.dispatch_profile:
            frappe.throw("Dispatch Profile snapshot does not match the selected Profile")
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
        if hashlib.sha256(canonical.encode()).hexdigest() != self.profile_snapshot_hash:
            frappe.throw("Dispatch Profile snapshot hash does not match its content")


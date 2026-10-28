import hashlib
import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt


ACTIVE_STATES = {"Draft", "Awaiting Approval", "Approved", "Picking", "Ready for Vehicle"}


class CFGKanbanDispatchPlan(Document):
    """E2 business authorization and reservation header; never an ERP stock document."""

    def validate(self):
        if self.state not in ACTIVE_STATES | {"Cancelled", "Exception"}:
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
        if not self.lines:
            frappe.throw("Dispatch Plan requires at least one Item line")
        seen = set()
        requested = 0
        for row in self.lines:
            if flt(row.requested_qty) <= 0:
                frappe.throw(f"Row {row.idx}: Requested Qty must be positive")
            key = (row.item_code, row.batch_no or "")
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


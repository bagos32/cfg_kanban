import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class CFGKanbanDeliveryAllocation(Document):
    def validate(self):
        kind = self.get("allocation_kind") or "Tagged Stock"
        if kind not in ("Tagged Stock", "Untagged ERP Stock"):
            frappe.throw("Unsupported customer delivery allocation kind")
        if kind == "Tagged Stock" and not self.handling_unit:
            frappe.throw("Tagged delivery allocation requires its physical Stock Tag")
        if kind == "Untagged ERP Stock" and (self.handling_unit or not (self.dispatch_allocation or
                (self.get("route_stop") and self.get("route_source_kind") == "Unassigned Lorry Stock"))):
            frappe.throw("Untagged delivery requires a prepared Dispatch Allocation without a Stock Tag")
        if flt(self.allocated_qty) <= 0:
            frappe.throw("Allocated Qty must be positive")
        if flt(self.delivered_qty) < 0 or flt(self.delivered_qty) > flt(self.allocated_qty):
            frappe.throw("Delivered Qty must be between zero and Allocated Qty")
        if self.is_new() and (cint(self.get("drop_scan_confirmed")) or self.get("drop_scan_evidence")):
            frappe.throw("Customer drop checks must use the controlled scan action")
        if not self.is_new():
            before = self.get_doc_before_save()
            if before:
                for fieldname in (
                    "delivery_session", "handling_unit", "visible_code",
                    "allocation_kind", "dispatch_allocation", "sales_order_item",
                    "route_stop", "route_source_kind", "route_request_key", "route_request_hash",
                    "container_handling_unit", "container_visible_code", "item_code",
                    "batch_no", "stock_uom", "allocated_qty", "source_warehouse",
                    "reserved_by_operator", "operator_session", "reserved_on",
                    "movement_state_before_reservation", "reservation_ledger",
                    "reservation_key", "drop_scan_confirmed", "drop_scan_evidence",
                ):
                    if before.get(fieldname) != self.get(fieldname):
                        frappe.throw(
                            f"{self.meta.get_label(fieldname)} is immutable after allocation"
                        )

    def on_trash(self):
        frappe.throw("Delivery Allocations are audit records; release or cancel them instead")

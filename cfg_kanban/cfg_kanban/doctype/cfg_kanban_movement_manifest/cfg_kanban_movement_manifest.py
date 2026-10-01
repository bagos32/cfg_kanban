import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanMovementManifest(Document):
    def before_insert(self):
        self.manifest_type = self.manifest_type or "Intercompany Handover"
        self.state = self.state or "Draft"
        self._copy_route_snapshot()

    def validate(self):
        self._validate_route_snapshot()
        self._validate_lines()
        self.total_quantity = sum(flt(row.dispatch_qty) for row in self.lines)
        self.total_received_quantity = sum(flt(row.received_qty) for row in self.lines)

    def on_trash(self):
        frappe.throw("Movement Manifests are audit records; cancel an unused Manifest instead")

    def _copy_route_snapshot(self):
        route = frappe.get_doc("CFG Kanban Logistics Route", self.logistics_route)
        if not route.active:
            frappe.throw(f"Logistics Route {route.name} is inactive")
        values = {
            "source_company": route.source_company,
            "source_warehouse": route.source_warehouse,
            "transit_warehouse": route.transit_warehouse,
            "destination_company": route.destination_company,
            "destination_warehouse": route.destination_warehouse,
            "internal_customer": route.internal_customer,
            "internal_supplier": route.internal_supplier,
            "selling_price_list": route.selling_price_list,
            "buying_price_list": route.buying_price_list,
            "handover_mode": route.handover_mode,
            "auto_submit_dispatch_dn": route.auto_submit_dispatch_dn,
            "auto_submit_receipt_pr": route.auto_submit_receipt_pr,
        }
        for fieldname, value in values.items():
            self.set(fieldname, value)

    def _validate_route_snapshot(self):
        if self.source_company == self.destination_company:
            frappe.throw("Manifest source and destination Companies must be different")
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "logistics_route", "source_company", "source_warehouse", "transit_warehouse",
            "destination_company", "destination_warehouse", "internal_customer",
            "internal_supplier", "selling_price_list", "buying_price_list", "handover_mode",
            "auto_submit_dispatch_dn", "auto_submit_receipt_pr",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is an immutable route snapshot")

    def _validate_lines(self):
        seen = set()
        for row in self.lines:
            if row.handling_unit in seen:
                frappe.throw(f"Handling Unit {row.handling_unit} appears more than once")
            seen.add(row.handling_unit)
            if flt(row.dispatch_qty) <= 0:
                frappe.throw(f"Row {row.idx}: Dispatch Qty must be positive")
            if flt(row.received_qty) < 0 or flt(row.received_qty) > flt(row.dispatch_qty):
                frappe.throw(f"Row {row.idx}: Received Qty must be between zero and Dispatch Qty")

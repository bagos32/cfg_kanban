import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from cfg_kanban.services.handling_unit_math import event_deltas


class CFGKanbanHandlingUnitQuantityLedger(Document):
    def before_insert(self):
        self.posting_datetime = self.posting_datetime or now_datetime()

    def validate(self):
        if flt(self.qty) <= 0 or flt(self.stock_qty) <= 0:
            frappe.throw("Ledger quantity and stock quantity must be positive")
        if not self.is_new():
            frappe.throw("Handling-unit quantity ledger entries are immutable")
        expected_stock_qty = flt(self.qty) * flt(self.conversion_factor or 1)
        if abs(flt(self.stock_qty) - expected_stock_qty) > 0.000001:
            frappe.throw("Stock Quantity must equal Transaction Quantity × Conversion Factor")
        try:
            expected = event_deltas(
                self.event_type,
                self.stock_qty,
                release_reserved=flt(self.source_reserved_delta) < 0,
            )
        except ValueError as exc:
            frappe.throw(str(exc))
        for fieldname, value in expected.items():
            if abs(flt(self.get(fieldname)) - float(value)) > 0.000001:
                frappe.throw(f"{self.meta.get_label(fieldname)} does not match the Event Type")
        if (expected["source_qty_delta"] or expected["source_reserved_delta"]) \
                and not self.source_handling_unit:
            frappe.throw("Source Handling Unit is required for this Event Type")
        if (expected["destination_qty_delta"] or expected["destination_reserved_delta"]) \
                and not self.destination_handling_unit:
            frappe.throw("Destination Handling Unit is required for this Event Type")
        if self.event_type in {
            "Location Transfer", "Return to Warehouse", "Quarantine", "Release"
        } and not self.source_handling_unit:
            frappe.throw("Source Handling Unit is required for this Event Type")
        if self.event_type in {
            "Split", "Replace", "Load into Container", "Unload from Container"
        } and self.source_handling_unit == self.destination_handling_unit:
            frappe.throw("Source and Destination Handling Units must be different")

    def on_trash(self):
        if not getattr(frappe.flags, "in_uninstall", False):
            frappe.throw("Handling-unit quantity ledger entries cannot be deleted")

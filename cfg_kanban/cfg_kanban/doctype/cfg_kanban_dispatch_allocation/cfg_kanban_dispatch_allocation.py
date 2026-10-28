import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanDispatchAllocation(Document):
    """Immutable reservation audit created only by the controlled E2 service."""

    def validate(self):
        if self.state not in {"Reserved", "Loaded", "Released", "Cancelled", "Exception"}:
            frappe.throw(f"Unsupported Dispatch Allocation state {self.state}")
        if self.allocation_kind not in {"Tagged Stock", "Untagged ERP Stock"}:
            frappe.throw(f"Unsupported Dispatch Allocation kind {self.allocation_kind}")
        if flt(self.allocated_qty) <= 0:
            frappe.throw("Dispatch Allocation quantity must be positive")
        if not self.reservation_key:
            frappe.throw("Dispatch Allocation reservation key is required")
        line = frappe.db.get_value(
            "CFG Kanban Dispatch Plan Line", self.dispatch_plan_line,
            ["parent", "item_code", "batch_no", "stock_uom"], as_dict=True,
        )
        if not line or line.parent != self.dispatch_plan:
            frappe.throw("Dispatch Plan Line does not belong to this Dispatch Plan")
        if line.item_code != self.item_code or line.stock_uom != self.stock_uom:
            frappe.throw("Dispatch Allocation Item/UOM does not match its Plan Line")
        if line.batch_no and line.batch_no != self.batch_no:
            frappe.throw("Dispatch Allocation Batch does not match its Plan Line")
        warehouse_company = frappe.db.get_value(
            "Warehouse", self.source_warehouse, "company"
        )
        if warehouse_company != self.source_company:
            frappe.throw("Dispatch Allocation source Warehouse and Company do not match")
        if self.allocation_kind == "Tagged Stock":
            if not self.handling_unit or self.active_handling_unit_key != self.handling_unit:
                frappe.throw("Tagged Allocation requires its exact active Handling Unit key")
        elif self.handling_unit or self.active_handling_unit_key:
            frappe.throw("Untagged ERP stock Allocation cannot carry a Handling Unit identity")
        if self.movement_manifest:
            manifest_plan = frappe.db.get_value(
                "CFG Kanban Movement Manifest", self.movement_manifest, "dispatch_plan"
            )
            if manifest_plan and manifest_plan != self.dispatch_plan:
                frappe.throw("Loading Manifest belongs to a different Dispatch Plan")
        if self.load_confirmed and not self.movement_manifest:
            frappe.throw("Loading confirmation requires a Movement Manifest")


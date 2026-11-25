import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_datetime


class CFGKanbanDispatchAllocation(Document):
    """Immutable reservation audit created only by the controlled E2 service."""

    def validate(self):
        before=None if self.is_new() else self.get_doc_before_save()
        controlled=('state','allocation_kind','dispatch_plan','dispatch_plan_line','handling_unit','visible_code',
            'item_code','batch_no','stock_uom','allocated_qty','source_company','source_warehouse',
            'movement_manifest','manifest_line','load_confirmed','loaded_by_operator','loaded_operator_session',
            'loaded_on','load_key','reserved_by_operator','operator_session','reserved_on','reservation_key',
            'active_handling_unit_key','reservation_ledger','movement_state_before_reservation',
            'released_by_operator','released_operator_session','released_on','release_reason','release_ledger','release_key')
        def normal(field,value):
            if value in (None,''):return None
            if field in ('loaded_on','reserved_on','released_on'):return get_datetime(value)
            if field=='allocated_qty':return flt(value)
            return value
        if before and any(normal(f,self.get(f))!=normal(f,before.get(f)) for f in controlled):
            frappe.throw('Dispatch allocations retain their controlled reservation/loading audit; use the existing actions')
        if self.state not in {"Reserved", "Loaded", "Released", "Cancelled", "Exception", "In Fulfilment", "Fulfilled"}:
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
            if not self.handling_unit or (self.state == "Reserved" and self.active_handling_unit_key != self.handling_unit):
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
            from cfg_kanban.services.trip_carry_in import validate_allocation
            validate_allocation(self)


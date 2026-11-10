import frappe
from frappe.model.document import Document
from frappe.utils import flt


IMMUTABLE_FIELDS = (
    "material_run", "kanban_cycle", "kanban_master", "process_execution", "work_order",
    "job_card", "operation", "workstation", "material_flow_rule_row", "item_code",
    "batch_no", "stock_uom", "source_warehouse", "source_handling_unit",
    "source_visible_code", "physical_container", "qty_per_output", "drawn_qty",
    "drawn_on", "drawn_by_operator", "operator_session", "terminal_user", "idempotency_key",
)


class CFGKanbanOperationMaterialDraw(Document):
    def validate(self):
        if self.status not in (
            "Open", "Partially Used", "Carry Forward", "Used", "Bound to ERP", "Cancelled"
        ):
            frappe.throw("Unsupported Operation Material Draw status")
        if flt(self.qty_per_output) <= 0 or flt(self.drawn_qty) <= 0:
            frappe.throw("Material draw quantities must be positive")
        if min(flt(self.used_qty), flt(self.remaining_qty)) < 0:
            frappe.throw("Material draw used and remaining quantities cannot be negative")
        if abs(
            flt(self.drawn_qty) - flt(self.used_qty) - flt(self.remaining_qty)
        ) > 0.000001:
            frappe.throw("Drawn quantity must equal used quantity plus remaining quantity")
        if not self.is_new():
            before = self.get_doc_before_save()
            changed = [
                fieldname for fieldname in IMMUTABLE_FIELDS
                if before and before.get(fieldname) != self.get(fieldname)
            ]
            if changed:
                frappe.throw(
                    "Operation Material Draw identity is immutable: " + ", ".join(changed)
                )

    def on_trash(self):
        frappe.throw(
            "Operation Material Draw records cannot be deleted; use controlled correction"
        )

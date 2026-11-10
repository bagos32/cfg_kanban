import frappe
from frappe.model.document import Document
from frappe.utils import flt


IMMUTABLE_CONTEXT_FIELDS = (
    "run_number", "kanban_cycle", "kanban_master", "process_execution",
    "runtime_allocation", "work_order", "job_card", "operation", "workstation",
    "output_serial_boundary", "opened_on", "opened_by_operator", "operator_session",
    "terminal_user", "material_draw_fingerprint", "idempotency_key",
)


class CFGKanbanOperationMaterialRun(Document):
    def validate(self):
        if self.status not in ("Open", "Progress Posted", "Settled", "Cancelled"):
            frappe.throw("Unsupported Material Run status")
        if self.status == "Open" and self.active_execution_key != self.process_execution:
            frappe.throw("An open Material Run requires its execution uniqueness key")
        if self.status != "Open" and self.active_execution_key:
            frappe.throw("A closed Material Run cannot retain an active execution key")
        if min(flt(self.drawn_qty), flt(self.used_qty), flt(self.carry_forward_qty)) < 0:
            frappe.throw("Material Run quantities cannot be negative")
        if flt(self.used_qty) > flt(self.drawn_qty) + 0.000001:
            frappe.throw("Material Run used quantity cannot exceed drawn quantity")
        if not self.is_new():
            before = self.get_doc_before_save()
            if before:
                changed = [
                    fieldname for fieldname in IMMUTABLE_CONTEXT_FIELDS
                    if before.get(fieldname) != self.get(fieldname)
                ]
                if changed:
                    frappe.throw(
                        "Material Run production context is immutable: " + ", ".join(changed)
                    )

    def on_trash(self):
        frappe.throw(
            "Material Run audit records cannot be deleted; use controlled cancellation"
        )

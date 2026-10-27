import frappe
from frappe.model.document import Document
from frappe.utils import flt


IMMUTABLE_FIELDS = (
    "reusable_bin", "wip_bin_load", "wip_bin_pool", "company", "item_code",
    "batch_no", "qty", "stock_uom", "kanban_master", "material_owner_cycle",
    "requesting_cycle", "work_order", "job_card", "process_execution", "operation",
    "workstation", "source_warehouse", "wip_warehouse", "idempotency_key",
    "reported_by_operator", "operator_session", "reported_on",
)


class CFGKanbanLooseWIPUsage(Document):
    def validate(self):
        if flt(self.qty) <= 0:
            frappe.throw("Loose WIP reported-use quantity must be positive")
        if self.status not in ("Recorded", "Consumption Draft", "Posted", "Reversed"):
            frappe.throw("Select a supported Loose WIP Usage status")
        if self.is_new():
            return
        previous = self.get_doc_before_save()
        if not previous:
            return
        changed = [field for field in IMMUTABLE_FIELDS
                   if previous.get(field) != self.get(field)]
        if changed:
            frappe.throw(
                "Loose WIP Usage evidence cannot change after creation: "
                + ", ".join(changed)
            )

    def on_trash(self):
        frappe.throw(
            "Loose WIP Usage records are immutable; use a controlled reversal record"
        )

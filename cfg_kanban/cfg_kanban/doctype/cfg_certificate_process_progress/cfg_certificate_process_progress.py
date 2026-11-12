import frappe
from frappe.model.document import Document
from frappe.utils import flt


IMMUTABLE_FIELDS = (
    "certificate_process_run", "kanban_cycle", "kanban_master", "kanban_card",
    "sequence", "company", "item_code", "stock_uom", "operation",
    "source_handling_unit", "output_tag_code", "output_handling_unit",
    "output_tag_mode", "good_qty", "reject_qty", "result_certificate_set",
    "output_batch", "printed_expiry", "first_output_serial", "last_output_serial",
    "recorded_on", "recorded_by_operator", "operator_session", "terminal_user",
    "idempotency_key", "request_fingerprint",
)


class CFGCertificateProcessProgress(Document):
    def validate(self):
        if self.status not in ("Recorded", "ERP Posted", "Cancelled"):
            frappe.throw("Unsupported Certificate Process Progress status")
        if flt(self.good_qty) <= 0 or flt(self.reject_qty) < 0:
            frappe.throw(
                "Certificate Process Progress requires positive Good and non-negative Reject quantity"
            )
        if not self.is_new():
            before = self.get_doc_before_save()
            changed = [
                field for field in IMMUTABLE_FIELDS
                if before and before.get(field) != self.get(field)
            ]
            if changed:
                frappe.throw(
                    "Certificate Process Progress evidence is immutable: "
                    + ", ".join(changed)
                )

    def on_trash(self):
        frappe.throw(
            "Certificate Process Progress cannot be deleted; use controlled cancellation"
        )

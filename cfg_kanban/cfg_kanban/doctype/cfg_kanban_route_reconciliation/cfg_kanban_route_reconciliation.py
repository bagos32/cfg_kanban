import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanRouteReconciliation(Document):
    def validate(self):
        self.expected_line_count = sum(
            1 for row in self.lines if abs(flt(row.expected_closing_qty)) > 0.000001
        )
        self.counted_line_count = sum(
            1 for row in self.lines if abs(flt(row.counted_qty)) > 0.000001
        )
        self.variance_line_count = sum(
            1 for row in self.lines if abs(flt(row.variance_qty)) > 0.000001
        )
        self._validate_unique_rows()
        self._protect_closed_record()

    def on_trash(self):
        frappe.throw(
            "Route Reconciliations are audit records; cancel an unused count instead"
        )

    def _validate_unique_rows(self):
        keys = set()
        for row in self.lines:
            key = (row.item_code, row.batch_no or "")
            if key in keys:
                frappe.throw(
                    f"Item {row.item_code} / Batch {row.batch_no or 'No Batch'} "
                    "appears more than once"
                )
            keys.add(key)
        scans = set()
        for row in self.scans:
            if row.handling_unit in scans:
                frappe.throw(f"Handling Unit {row.handling_unit} was counted more than once")
            scans.add(row.handling_unit)

    def _protect_closed_record(self):
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or before.state not in ("Closed", "Cancelled"):
            return
        protected = (
            "company", "vehicle_warehouse", "vehicle_reference", "period_start",
            "period_end", "opened_by_operator", "opened_operator_session",
            "closed_by_operator", "closed_operator_session", "closed_on",
            "state", "lines", "scans", "variance_exception",
        )
        for fieldname in protected:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw("A closed or cancelled Route Reconciliation is immutable")

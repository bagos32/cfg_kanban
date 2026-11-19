import frappe
from frappe.model.document import Document


class CFGKanbanRouteStop(Document):
    def validate(self):
        if self.state not in {"Planned", "In Progress", "Delivery Note Pending", "Delivered",
                              "Completed", "Cancelled", "Skipped", "Exception"}:
            frappe.throw("Invalid Route Stop state")
        before = None if self.is_new() else self.get_doc_before_save()
        if before:
            for field in ("dispatch_plan", "company", "customer_scan_point", "customer",
                          "customer_address", "planned_sequence", "idempotency_key", "retry_of_stop"):
                if before.get(field) != self.get(field):
                    frappe.throw("Route Stop planning snapshots are immutable; skip and create a new Stop")

    def on_trash(self):
        frappe.throw("Route Stops are audit records; skip or cancel through the controlled workflow")

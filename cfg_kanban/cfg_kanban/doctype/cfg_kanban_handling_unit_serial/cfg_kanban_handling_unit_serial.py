import frappe
from frappe.model.document import Document


class CFGKanbanHandlingUnitSerial(Document):
    def before_insert(self):
        self.active_serial_key = self.serial_no if self.state == "Active" else None
        if self.state == "Active" and frappe.db.exists(
            "CFG Kanban Handling Unit Serial",
            {"active_serial_key": self.serial_no},
        ):
            frappe.throw(f"Serial No {self.serial_no} is already assigned to an active Stock Tag")

    def validate(self):
        if not self.is_new():
            frappe.throw("Serial membership history is immutable; use controlled release or reversal")

    def on_trash(self):
        if not getattr(frappe.flags, "in_uninstall", False):
            frappe.throw("Serial membership history cannot be deleted")

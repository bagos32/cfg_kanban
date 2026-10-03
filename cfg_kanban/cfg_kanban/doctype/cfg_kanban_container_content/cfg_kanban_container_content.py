import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CFGKanbanContainerContent(Document):
    def before_insert(self):
        container_kind = frappe.db.get_value(
            "CFG Kanban Handling Unit", self.container_handling_unit, "tag_kind"
        )
        content_kind = frappe.db.get_value(
            "CFG Kanban Handling Unit", self.content_handling_unit, "tag_kind"
        )
        if container_kind != "Reusable Container":
            frappe.throw("Reusable Container must point to a reusable-container Handling Unit")
        if not content_kind or content_kind == "Reusable Container":
            frappe.throw("Contained Stock Tag must point to a physical Stock Tag")
        existing = frappe.db.get_value(
            "CFG Kanban Container Content",
            {"content_handling_unit": self.content_handling_unit, "state": "Loaded"},
            "container_visible_code",
        )
        if existing:
            frappe.throw(f"This Stock Tag is already loaded in container {existing}")

    def validate(self):
        if flt(self.qty) <= 0:
            frappe.throw("Complete Tag Quantity at Load must be positive")
        if self.container_handling_unit == self.content_handling_unit:
            frappe.throw("A reusable container cannot contain itself")
        if not self.is_new():
            frappe.throw("Container content episodes are immutable; unload through the scanner workflow")

    def on_trash(self):
        if not getattr(frappe.flags, "in_uninstall", False):
            frappe.throw("Container content history cannot be deleted")

import uuid

import frappe
from frappe.model.document import Document


class CFGKanbanHandlingUnit(Document):
    def before_insert(self):
        self.opaque_token = self.opaque_token or str(uuid.uuid4())
        if not self.handling_unit_id:
            self.handling_unit_id = self.name
        self._copy_cycle_context()

    def validate(self):
        if self.qty <= 0:
            frappe.throw("Handling-unit quantity must be positive")
        if self.sequence_no <= 0 or self.total_units <= 0 or self.sequence_no > self.total_units:
            frappe.throw("Handling-unit sequence must be between 1 and the total number of units")
        if self.kanban_card and self.opaque_token == frappe.db.get_value(
            "CFG Kanban Card", self.kanban_card, "uuid"
        ):
            frappe.throw("Handling-unit token must be different from the reusable card token")

    def _copy_cycle_context(self):
        cycle = frappe.get_doc("CFG Kanban Cycle", self.kanban_cycle)
        self.kanban_card = self.kanban_card or cycle.kanban_card
        self.item_code = self.item_code or cycle.item_code
        self.stock_uom = self.stock_uom or cycle.stock_uom
        self.batch_no = self.batch_no or cycle.batch_no
        self.work_order = self.work_order or cycle.work_order
        if not self.short_description and self.item_code:
            self.short_description = frappe.db.get_value("Item", self.item_code, "item_name")

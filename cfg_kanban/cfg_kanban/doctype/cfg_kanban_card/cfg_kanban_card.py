import uuid

import frappe
from frappe.model.document import Document


class CFGKanbanCard(Document):
    def before_insert(self):
        self.uuid = self.uuid or str(uuid.uuid4())
        self.qr_code = self.qr_code or self.uuid

    def validate(self):
        production_types = ("Physical Unit Card", "Physical Batch Card",
                            "Process Kanban", "Station Kanban")
        behaviour = {
            "Physical Unit Card": "TRAVELLING_CARD",
            "Physical Batch Card": "TRAVELLING_CARD",
            "Process Kanban": "STATION_CARD",
            "Station Kanban": "STATION_CARD",
            "Asset Card": "ASSET_CARD",
            "Location Card": "LOCATION_CARD",
            "Task Card": "TASK_CARD",
        }
        self.card_behavior = behaviour.get(self.card_type)
        if self.card_type in production_types and not self.kanban_master:
            frappe.throw("Kanban Master is required for a production card")
        self._copy_master_context()
        if self.card_type in production_types and self.kanban_qty <= 0:
            frappe.throw("Kanban quantity must be positive")
        if self.card_type in ("Process Kanban", "Station Kanban") and not self.operation:
            frappe.throw("Controlled Operation is required for Process and Station Kanban cards")
        if self.card_type == "Station Kanban" and not self.workstation:
            frappe.throw("Eligible Workstation is required for a Station Kanban card")
        if self.card_type == "Asset Card" and not self.asset:
            frappe.throw("Asset is required for an Asset Card")
        if self.card_type == "Location Card" and not self.location_reference:
            frappe.throw("Location Reference is required for a Location Card")
        if self.card_type == "Task Card" and not self.task_schedule:
            frappe.throw("Task Schedule is required for a Task Card")

    def _copy_master_context(self):
        if not self.kanban_master:
            self.item_code = None
            self.stock_uom = None
            self.source_warehouse = None
            self.destination_warehouse = None
            self.operation = None
            self.workstation = None
            self.handoff_mode = None
            return
        master = frappe.get_cached_doc("CFG Kanban Master", self.kanban_master)
        self.item_code = master.item_code
        self.stock_uom = master.stock_uom
        self.source_warehouse = master.source_warehouse
        self.destination_warehouse = master.destination_warehouse
        self.current_warehouse = self.current_warehouse or master.destination_warehouse
        if not self.kanban_qty:
            self.kanban_qty = master.replenishment_qty
        if not self.operation:
            self.workstation = None
            self.handoff_mode = None
            return
        profile = next((row for row in master.operation_profiles if row.operation == self.operation), None)
        if not profile:
            frappe.throw(f"Operation {self.operation} is not configured in Kanban Master {master.name}")
        if self.card_type == "Station Kanban":
            self.workstation = self.workstation or profile.workstation
            self.current_station = self.current_station or self.workstation
        else:
            self.workstation = None
            self.current_station = None
        self.handoff_mode = profile.handoff_mode

import frappe
from frappe.model.document import Document

from cfg_kanban.services.delivery_trips import validate_trip


class CFGKanbanDeliveryTrip(Document):
    def validate(self):
        validate_trip(self)

    def on_trash(self):
        frappe.throw('Delivery Trip planning records retain their audit history; close or cancel instead')

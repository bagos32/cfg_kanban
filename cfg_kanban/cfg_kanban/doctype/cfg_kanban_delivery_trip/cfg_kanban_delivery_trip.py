import frappe
from frappe.model.document import Document

from cfg_kanban.services.delivery_trips import validate_trip


class CFGKanbanDeliveryTrip(Document):
    def onload(self):
        from cfg_kanban.services.driver_routes import trip_driver_display
        self.driver_display=trip_driver_display(self)

    def validate(self):
        validate_trip(self)

    def on_update(self):
        if self.flags.get('cfg_office_team_previous') is not None:
            from cfg_kanban.services.trip_team import record_office_team
            record_office_team(self)

    def on_trash(self):
        frappe.throw('Delivery Trip planning records retain their audit history; close or cancel instead')

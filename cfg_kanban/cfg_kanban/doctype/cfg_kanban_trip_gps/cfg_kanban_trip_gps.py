import frappe
from frappe.model.document import Document

class CFGKanbanTripGPS(Document):
    def validate(self):
        if not self.flags.get('cfg_trip_gps'):
            frappe.throw('Trip GPS is controlled by its sharing device and Supervisor map')

    def on_trash(self):
        frappe.throw('Trip GPS sharing records retain their source audit references')

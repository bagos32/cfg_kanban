import frappe
from frappe.model.document import Document


class CFGKanbanRouteChangeRequest(Document):
    def validate(self):
        if not self.flags.get('cfg_trip_route_change'):
            frappe.throw('Route change requests are controlled; use Driver Route or the Supervisor Action Centre')

    def on_trash(self):
        frappe.throw('Route change requests retain their decision history')

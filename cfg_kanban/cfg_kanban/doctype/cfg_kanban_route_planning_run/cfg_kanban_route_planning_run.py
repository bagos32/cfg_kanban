import frappe
from frappe.model.document import Document


class CFGKanbanRoutePlanningRun(Document):
    def validate(self):
        if not self.flags.get('cfg_route_planner'):
            frappe.throw('Planning Runs are controlled; use Mock Route Planner on the Delivery Trip')

    def on_trash(self):
        frappe.throw('Route Planning Runs retain proposal, attempt and decision history')

import frappe
from frappe.model.document import Document

from cfg_kanban.services.doctype_action_runs import ACTION_RUN_STATES


class CFGKanbanDocTypeActionRun(Document):
    def before_insert(self):
        if not self.flags.get("doctype_action_engine_insert"):
            frappe.throw("DocType Action Runs are created only by the controlled action engine")

    def validate(self):
        if self.state not in ACTION_RUN_STATES:
            frappe.throw(f"Unsupported DocType Action Run state: {self.state}")
        if not self.is_new() and not self.flags.get("doctype_action_engine_update"):
            frappe.throw("DocType Action Runs cannot be edited manually")


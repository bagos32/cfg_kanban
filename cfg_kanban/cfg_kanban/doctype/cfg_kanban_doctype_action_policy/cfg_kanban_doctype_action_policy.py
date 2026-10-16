from frappe.model.document import Document

from cfg_kanban.services.doctype_actions import validate_target_policy


class CFGKanbanDocTypeActionPolicy(Document):
    def validate(self):
        validate_target_policy(self)


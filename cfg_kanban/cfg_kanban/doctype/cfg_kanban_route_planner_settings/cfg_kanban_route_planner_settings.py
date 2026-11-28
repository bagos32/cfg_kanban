from frappe.model.document import Document

from cfg_kanban.services.route_planner import validate_settings


class CFGKanbanRoutePlannerSettings(Document):
    def validate(self):
        validate_settings(self)

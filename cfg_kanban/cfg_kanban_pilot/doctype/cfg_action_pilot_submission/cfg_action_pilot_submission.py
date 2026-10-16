from frappe.model.document import Document

from cfg_kanban.cfg_kanban_pilot.doctype.cfg_action_pilot_draft.cfg_action_pilot_draft import (
    _validate_pilot,
)


class CFGActionPilotSubmission(Document):
    def validate(self):
        _validate_pilot(self)

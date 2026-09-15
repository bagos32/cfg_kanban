from frappe.model.document import Document


class CFGKanbanDispatchQueue(Document):
    """Persistent dispatch projection for one Process Execution."""

    def validate(self):
        if self.queue_position is not None and self.queue_position < 0:
            self.queue_position = 0


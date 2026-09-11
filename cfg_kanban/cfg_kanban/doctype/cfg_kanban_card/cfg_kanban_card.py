import uuid
from frappe.model.document import Document


class CFGKanbanCard(Document):
    def before_insert(self):
        self.uuid = self.uuid or str(uuid.uuid4())
        self.qr_code = self.qr_code or self.uuid

    def validate(self):
        if self.kanban_qty <= 0:
            raise ValueError("Kanban quantity must be positive")


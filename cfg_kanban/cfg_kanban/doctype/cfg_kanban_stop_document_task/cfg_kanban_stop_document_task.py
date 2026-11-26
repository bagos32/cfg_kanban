from frappe.model.document import Document
from cfg_kanban.services.stop_documents import controlled, no_delete


class CFGKanbanStopDocumentTask(Document):
    def validate(self):
        controlled(self)

    def on_trash(self):
        no_delete()

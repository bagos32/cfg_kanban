from frappe.model.document import Document


class CFGKanbanReturnCustodyLabel(Document):
    def validate(self):
        from cfg_kanban.services.mobile_printing import controlled_document
        controlled_document(self)

    def on_trash(self):
        from cfg_kanban.services.mobile_printing import no_delete
        no_delete()

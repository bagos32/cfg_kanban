from frappe.model.document import Document


class CFGKanbanPrintBrowser(Document):
    def validate(self):
        from cfg_kanban.services.label_bridge_pairing import controlled_registration
        controlled_registration(self)

    def on_trash(self):
        from cfg_kanban.services.label_bridge_pairing import no_delete
        no_delete(self)

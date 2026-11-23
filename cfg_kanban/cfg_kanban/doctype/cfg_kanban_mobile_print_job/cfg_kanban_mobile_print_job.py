from frappe.model.document import Document


class CFGKanbanMobilePrintJob(Document):
    def onload(self):
        from cfg_kanban.services.mobile_printing import can_close_mobile_print_job
        self.set_onload('can_close_mobile_print_job', can_close_mobile_print_job(self))

    def validate(self):
        from cfg_kanban.services.mobile_printing import controlled_document
        controlled_document(self)

    def on_trash(self):
        from cfg_kanban.services.mobile_printing import no_delete
        no_delete()

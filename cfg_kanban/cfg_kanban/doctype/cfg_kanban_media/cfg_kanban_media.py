import frappe
from frappe.model.document import Document


class CFGKanbanMedia(Document):
    def validate(self):
        if not self.is_new():
            before = self.get_doc_before_save()
            for fieldname in (
                "media_id", "app_id", "environment", "bucket", "object_key",
                "media_class", "reference_doctype", "reference_name",
            ):
                if before and before.get(fieldname) != self.get(fieldname):
                    frappe.throw(f"{self.meta.get_label(fieldname)} is immutable")

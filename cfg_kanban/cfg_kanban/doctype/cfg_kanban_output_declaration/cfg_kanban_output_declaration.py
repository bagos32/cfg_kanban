import frappe
from frappe.model.document import Document


class CFGKanbanOutputDeclaration(Document):
    def validate(self):
        if not getattr(self.flags, 'controlled_output_declaration', False):
            frappe.throw('Use the controlled station output declaration actions')

    def on_trash(self):
        if not getattr(frappe.flags, 'in_uninstall', False):
            frappe.throw('Output declaration history cannot be deleted')

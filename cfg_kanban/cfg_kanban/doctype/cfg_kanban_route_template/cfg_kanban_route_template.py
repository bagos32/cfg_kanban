import frappe
from frappe.model.document import Document
from frappe.utils import cint

class CFGKanbanRouteTemplate(Document):
    def validate(self):
        if not self.company or not self.stops:
            frappe.throw('Route Template requires Company and at least one Customer Site')
        for row in self.stops:
            site = frappe.get_doc('CFG Kanban Customer Scan Point',row.customer_scan_point)
            site.check_permission('read')
            if not site.active or site.selling_company!=self.company:
                frappe.throw('Every template Site must be active and belong to the template Company')
            row.site_name,row.customer,row.customer_address = site.site_name,site.customer,site.customer_address
        before = None if self.is_new() else self.get_doc_before_save()
        def signature(doc):
            return (doc.company,doc.active,doc.notes,[(r.customer_scan_point,r.instructions) for r in doc.stops])
        self.revision = (cint(before.revision)+1 if before and signature(before)!=signature(self)
                         else cint(before.revision) if before else 1)

import frappe
from frappe.model.document import Document

class CFGKanbanRouteSheet(Document):
    def validate(self):
        if self.scope=='Per Dispatch Plan' and not self.dispatch_plan:
            frappe.throw('A per-Plan Route Sheet requires its Dispatch Plan')
        if self.scope=='Combined Lorry Trip' and not self.vehicle_warehouse:
            frappe.throw('A combined Route Sheet requires its lorry Warehouse')
        before = None if self.is_new() else self.get_doc_before_save()
        if before:
            for name in ('scope','company','dispatch_plan','vehicle_warehouse','vehicle_reference','created_by_operator','created_on'):
                if before.get(name)!=self.get(name):
                    frappe.throw('Route Sheet identity is immutable')
            protected=('row_key','dispatch_plan','customer_scan_point','site_name','customer',
                       'customer_address','address_display','instructions','source_route_stop',
                       'delivery_session','state','actual_sequence')
            def sequence(doc):
                return [tuple(row.get(field) for field in protected) for row in doc.stops]
            if before.state!='Draft' and sequence(before)!=sequence(self):
                frappe.throw('An approved Route Sheet cannot be reordered; preserve its visit history')
    def on_trash(self):
        frappe.throw('Route Sheets are audit records; use controlled cancellation or closure')

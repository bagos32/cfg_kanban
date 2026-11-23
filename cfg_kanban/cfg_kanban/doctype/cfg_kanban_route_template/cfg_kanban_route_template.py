import frappe
from frappe.model.document import Document
from frappe.utils import cint

from cfg_kanban.services.delivery_trips import _company, validate_stops


class CFGKanbanRouteTemplate(Document):
    def validate(self):
        _company(self.company)
        from cfg_kanban.services.trip_gps_math import publish_interval
        try:self.gps_publish_interval_seconds=str(publish_interval(self.get('gps_publish_interval_seconds')))
        except ValueError as exc:frappe.throw(str(exc))
        self.sequence_policy = self.get('sequence_policy') or 'Flexible Order'
        if self.sequence_policy not in ('Flexible Order', 'Planned Order'):
            frappe.throw('Select Flexible Order or Planned Order')
        validate_stops(self, assign_keys=False)
        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.company != self.company:
            if (frappe.db.exists('Sales Order', {'cfg_delivery_route': self.name})
                    or frappe.db.exists('CFG Kanban Delivery Trip', {'route_template': self.name})):
                frappe.throw('Company cannot change after a Standard Route is used by Sales Orders or Delivery Trips')

        def signature(doc):
            return (doc.company, doc.active, doc.notes, doc.get('region'), doc.get('direction'),
                    doc.get('sequence_policy') or 'Flexible Order',cint(doc.get('auto_generate_dispatch')),
                    doc.get('dispatch_profile'),doc.get('open_route_profile'),
                    cint(doc.get('gps_auto_start')),publish_interval(doc.get('gps_publish_interval_seconds')),
                    [(row.get('stop_purpose') or 'Delivery', row.customer_scan_point,
                      row.customer, row.customer_address, row.instructions) for row in doc.stops])

        self.revision = (cint(before.revision) + int(signature(self) != signature(before))) if before else 1

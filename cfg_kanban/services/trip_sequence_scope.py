"""Lazy Trip lookup shared by native delivery entry points; no Frappe import."""
def sequence_trip(frappe,plan):
    name=plan.get('office_delivery_trip')
    if not name:
        names=frappe.get_all('CFG Kanban Delivery Trip Plan',filters={'dispatch_plan':plan.name,
            'parenttype':'CFG Kanban Delivery Trip','parentfield':'dispatch_plans'},pluck='parent',limit_page_length=0)
        if len(set(names))>1:frappe.throw('Dispatch Plan belongs to multiple office Trips')
        name=names[0] if names else None
    if name and frappe.db.get_value('CFG Kanban Delivery Trip',name,'route_sequence_revision') is not None:
        return name
    return None

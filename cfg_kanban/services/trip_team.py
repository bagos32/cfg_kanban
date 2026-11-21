"""Audited assistants on one Delivery Trip; membership grants scope, never operator authority."""
import frappe
from frappe.utils import cint, now_datetime
from cfg_kanban.services.events import record

TRIP = 'CFG Kanban Delivery Trip'
ASSISTANT = 'CFG Kanban Trip Assistant'
AUDIT_FIELDS = ('employee_name','assigned_on','assigned_by','assigned_by_user','assignment_source')


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def _employee(name):
    if not str(name or '').strip():frappe.throw('Select an Assistant Driver Employee')
    employee = _read('Employee', name)
    if employee.status != 'Active':frappe.throw('Assistant Driver Employee must be active')
    profile_name = frappe.db.get_value('CFG Kanban Operator Profile', {'employee':name,'active':1}, 'name')
    if not profile_name:frappe.throw('Assistant Driver needs an active Kanban Operator Profile')
    profile = frappe.get_doc('CFG Kanban Operator Profile', profile_name)
    if not any(r.responsibility == 'Customer Delivery' for r in profile.get('responsibilities') or []):
        frappe.throw('Assistant Driver needs Customer Delivery responsibility on their Operator Profile')
    return employee


def _members(doc):
    members = [str(row.employee or '').strip() for row in doc.get('assistant_drivers') or []]
    if any(not name for name in members):frappe.throw('Select an Assistant Driver Employee for every row')
    return sorted(members)


def _event(doc, before, actor=None, session=None):
    record('Delivery Trip Assistants Changed', reference_doctype=TRIP, reference_name=doc.name,
        operator=actor.employee if actor else None, operator_session=session.name if session else None,
        terminal_user=frappe.session.user, payload=dict(driver=doc.driver,
            previous_assistants=before, assistants=_members(doc), team_revision=cint(doc.team_revision)))


def validate_office_team(doc, before):
    previous = {r.employee:r for r in before.get('assistant_drivers') or []} if before else {}
    members = _members(doc)
    if len(members) != len(set(members)):frappe.throw('Select each Assistant Driver only once')
    if members and (not doc.driver or doc.driver in members):
        frappe.throw('Select a lead Assigned Driver and distinct Assistant Drivers')
    changed = members != sorted(previous)
    if changed and before and (before.state in ('Closed','Cancelled') or
            before.get('driver_route_state') not in (None,'','Not Started')):
        frappe.throw('Started Trips retain their assigned team; the lead driver can add assistants through Driver Route')
    for row in doc.get('assistant_drivers') or []:
        old = previous.get(row.employee)
        if old:
            for field in AUDIT_FIELDS:row.set(field,old.get(field))
        else:
            employee = _employee(row.employee)
            row.update(dict(employee_name=employee.employee_name,assigned_on=now_datetime(),assigned_by=None,
                assigned_by_user=frappe.session.user,assignment_source='Office'))
    doc.team_revision = (cint(before.get('team_revision')) if before else 0) + int(changed)
    # Event has a Dynamic Link to the Trip. On first insert, wait until parent and
    # child rows exist; on_update remains inside the same native transaction.
    doc.flags.cfg_office_team_previous = sorted(previous) if changed else None


def record_office_team(doc):
    previous = doc.flags.pop('cfg_office_team_previous',None)
    if previous is not None:_event(doc,previous)


def assert_lead(doc, operator):
    if not doc.driver or doc.driver != operator.employee:
        frappe.throw('Only the Assigned Driver can add assistants from Driver Route',frappe.PermissionError)
    if doc.state != 'Planned' or doc.get('driver_route_state') not in (None,'','Not Started','In Progress'):
        frappe.throw('Add assistants before or during an active Planned Trip')


def add_assistant(doc, employee, operator, session):
    """Caller holds the Trip lock and checks the original durable action/revision first."""
    assert_lead(doc,operator)
    if employee == doc.driver:frappe.throw('The Assigned Driver is already part of this Trip')
    previous = _members(doc)
    if employee in previous:return dict(assistant_added=False,employee=employee)
    selected = _employee(employee)
    row = doc.append('assistant_drivers',dict(employee=selected.name,employee_name=selected.employee_name,
        assigned_on=now_datetime(),assigned_by=operator.employee,assigned_by_user=frappe.session.user,
        assignment_source='Assigned Driver'))
    row.insert(ignore_permissions=True)
    doc.db_set('team_revision',cint(doc.get('team_revision'))+1,update_modified=True)
    _event(doc,previous,operator,session)
    return dict(assistant_added=True,employee=selected.name)


def can_access_delivery(operator, delivery):
    """Additional access to an exact team delivery; unrelated native Sessions keep their owner rule."""
    plan = _read('CFG Kanban Dispatch Plan',delivery.dispatch_plan)
    if plan.get('office_delivery_trip'):
        names = [plan.office_delivery_trip]
    else:
        names = frappe.get_all('CFG Kanban Delivery Trip Plan',filters={'dispatch_plan':plan.name,
            'parenttype':TRIP,'parentfield':'dispatch_plans'},pluck='parent',limit_page_length=0)
    if len(set(names)) != 1:return False
    trip = _read(TRIP,names[0])
    if not (operator.employee == trip.driver or operator.employee in _members(trip)):
        return False
    if trip.get('driver_route_state') not in ('In Progress','Completed','Closed Incomplete'):
        return False
    if (delivery.selling_company != trip.company or plan.company != trip.company or
            delivery.source_warehouse != plan.vehicle_warehouse):return False
    _read('Company',trip.company)
    if not any(r.responsibility == 'Customer Delivery' for r in operator.get('responsibilities') or []):return False
    from cfg_kanban.services.dispatch_planning import _assert_plan_authorized
    _assert_plan_authorized(plan,operator)
    if delivery.get('route_stop'):
        if trip.get('open_route_plan') != plan.name:return False
        source = _read('CFG Kanban Route Stop',delivery.route_stop)
        if source.dispatch_plan != plan.name or source.delivery_session != delivery.name:return False
        key = source.office_stop_key
    else:
        links = [r for r in trip.dispatch_plans if r.dispatch_plan == plan.name]
        if len(links) != 1:return False
        key = links[0].stop_key
    stop = next((r for r in trip.stops if r.stop_key == key),None)
    return bool(stop and stop.customer == delivery.customer and
        stop.customer_scan_point == delivery.customer_scan_point and stop.customer_address == delivery.customer_address)

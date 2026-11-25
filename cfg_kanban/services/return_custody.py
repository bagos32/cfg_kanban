"""Whole-case transport handover; original collection and QC facts remain immutable."""
import json
import frappe
from frappe.utils import cint, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

CASE='CFG Kanban Return Case'
TRIP='CFG Kanban Delivery Trip'


def current_trip(case):
    return case.get('custody_trip') or case.driver_trip


def cases(trip,history=True,current=False,native=True):
    # A middle Trip keeps its confirmed incoming Cases even after a second takeover.
    saved=json.loads(trip.get('follow_on_snapshot_json') or '{}')
    historical=saved.get('returns',[]) if history and trip.get('follow_on_of') else []
    if native:
        names=frappe.get_list(CASE,filters={'selling_company':trip.company},
            or_filters={'driver_trip':trip.name,'custody_trip':trip.name},pluck='name',order_by='name',limit_page_length=0)
        if historical:
            names+=frappe.get_list(CASE,filters={'selling_company':trip.company,'name':['in',historical]},
                pluck='name',order_by='name',limit_page_length=0)
    else:
        names=([r.name for r in frappe.db.get_values(CASE,{'driver_trip':trip.name},['name'],as_dict=True,for_update=current)]+
            [r.name for r in frappe.db.get_values(CASE,{'custody_trip':trip.name},['name'],as_dict=True,for_update=current)])
    names=sorted(set(names))
    result=[]
    for name in names:
        doc=frappe.get_doc(CASE,name,**({'for_update':True} if current else {}))
        if native:doc.check_permission('read')
        if doc.selling_company!=trip.company:
            frappe.throw('Return custody belongs to another Company')
        if history or current_trip(doc)==trip.name:result.append(doc)
    return result


def pending(case):
    return bool(not cint(case.get('stock_already_owned')) and case.return_flow=='Customer Return for QC'
        and case.state not in ('Closed','Cancelled') and not case.received_on)


def assert_received(trip):
    # Hidden Cases still prevent abandonment of current transport custody.
    if any(pending(case) for case in cases(trip,history=False,current=True,native=False)):
        frappe.throw('Collected returns still await QC receipt or a confirmed follow-on custody handover')


def transfer(source,target,names,operator,session,reason):
    wanted=set(names)
    if len(wanted)!=len(names):frappe.throw('Select each return Case only once')
    existing={case.name:case for case in cases(source,history=False,current=True,native=False) if pending(case)}
    if wanted!=set(existing):
        frappe.throw('Confirm QC receipt or include every unreceived customer return before ending the original Trip')
    if target.company!=source.company or not target.vehicle_warehouse:
        frappe.throw('Return handover requires a Company-specific receiving lorry')
    for name in sorted(wanted):
        case=existing[name];case.check_permission('read')
        if not case.collected_on or case.state!='Awaiting QC Receipt':
            frappe.throw('Only collected old returns awaiting QC receipt can change transport custody')
        history=json.loads(case.get('custody_handover_json') or '[]')
        entry=dict(from_trip=source.name,to_trip=target.name,
            from_warehouse=case.get('custody_vehicle_warehouse') or case.collection_vehicle_warehouse,
            to_warehouse=target.vehicle_warehouse,receiver=target.driver,
            operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user,
            confirmed_on=str(now_datetime()),reason=reason)
        history.append(entry)
        case.db_set(dict(custody_trip=target.name,custody_vehicle_warehouse=target.vehicle_warehouse,
            custody_handover_json=json.dumps(history,sort_keys=True)),update_modified=True)
        record('Customer Return Transport Custody Handed Over',return_case=case.name,
            reference_doctype=TRIP,reference_name=target.name,operator=operator.employee,
            operator_session=session.name,terminal_user=session.terminal_user,
            idempotency_key=canonical_key('return-custody-handover',case.name,target.name),payload=entry)

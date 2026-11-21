"""Trip-bound old customer return collection through the existing custody/QC intake."""
import frappe
import json
from frappe.utils import now_datetime
from cfg_kanban.services import direct_customer_returns as intake
from cfg_kanban.services.events import record


def context(trip, stop, operator):
    intake._returns()._require_intake(operator)
    intake._returns()._assert_enabled()
    if trip.state != 'Planned' or trip.get('driver_route_state') not in ('In Progress', 'Completed'):
        frappe.throw('Start the route before collecting an old customer return')
    site = frappe.get_doc('CFG Kanban Customer Scan Point', stop.customer_scan_point) if stop.customer_scan_point else None
    if site:
        site.check_permission('read')
    snapshot=json.loads(trip.driver_route_snapshot_json or '{}')
    vehicle=snapshot.get('vehicle')
    if vehicle:
        warehouse=frappe.get_doc('Warehouse',vehicle);warehouse.check_permission('read')
        if warehouse.company!=trip.company:frappe.throw('Collection lorry belongs to another Company')
    return dict(company=trip.company, customer=stop.customer, customer_address=stop.customer_address,
        inspection_location=site.return_inspection_location if site else None,
        vehicle_warehouse=vehicle,
        conditions=list(intake._returns().CONDITIONS))


def preview(trip, stop, values, operator, token):
    source = context(trip, stop, operator)
    if values.get('existing_return_case'):
        case=_existing(values['existing_return_case'],source,current=False)
        return dict(company=case.selling_company,customer=case.customer,customer_name=case.customer,inspection_location=case.inspection_location,lines=[r.as_dict() for r in case.lines],existing_return_case=case.name)
    return intake.preview_direct_customer_return(company=source['company'],customer=source['customer'],
        customer_address=source['customer_address'],inspection_location=values.get('inspection_location'),
        customer_return_reason=values.get('customer_return_reason'),lines=values.get('lines'),
        customer_acknowledgement_name=values.get('customer_acknowledgement_name'),operator_session_token=token)


def collect(trip, stop, values, operator, session, token, event_token):
    source = context(trip, stop, operator)
    if values.get('existing_return_case'):
        case=_existing(values['existing_return_case'],source,current=True)
        if case.get('collection_key') and case.collection_key!=event_token:
            frappe.throw('This Return Note was already collected; open its recorded trip instead of collecting it twice')
        case.db_set(dict(driver_trip=trip.name,driver_stop_key=stop.stop_key,collection_vehicle_warehouse=source['vehicle_warehouse'],collected_by=operator.employee,collected_on=now_datetime(),collection_key=event_token),update_modified=True)
        record('Existing Customer Return Collected on Driver Trip',return_case=case.name,reference_doctype=trip.doctype,reference_name=trip.name,operator=operator.employee,operator_session=session.name,terminal_user=session.terminal_user)
        return dict(return_case=case.name)
    result = intake.create_direct_customer_return(company=source['company'],customer=source['customer'],
        customer_address=source['customer_address'],inspection_location=values.get('inspection_location'),
        customer_return_reason=values.get('customer_return_reason'),lines=values.get('lines'),
        customer_acknowledgement_name=values.get('customer_acknowledgement_name'),operator_session_token=token,
        event_token=event_token)
    case = frappe.get_doc('CFG Kanban Return Case', result['return_case']['name'],for_update=True)
    if case.get('driver_trip') and (case.driver_trip!=trip.name or case.driver_stop_key!=stop.stop_key):
        frappe.throw('This return intake belongs to another original trip/stop')
    case.db_set(dict(driver_trip=trip.name,driver_stop_key=stop.stop_key,
        collection_vehicle_warehouse=source['vehicle_warehouse'],collected_by=operator.employee,collected_on=now_datetime(),collection_key=event_token,reported_source_reference=str(values.get('reported_source_reference') or '').strip()),update_modified=True)
    record('Old Customer Return Collected on Driver Trip',return_case=case.name,
        reference_doctype=trip.doctype,reference_name=trip.name,operator=operator.employee,
        operator_session=session.name,terminal_user=session.terminal_user,
        notes='Collected into temporary custody; awaiting physical QC receipt. No stock or accounting posting.')
    return dict(return_case=case.name)


def summaries(trip_name):
    # The parent Trip read check is mandatory before calling this projection.
    names = frappe.get_all('CFG Kanban Return Case',filters={'driver_trip':trip_name},pluck='name',
        order_by='claimed_on, name',limit_page_length=0)
    rows=[]
    for name in names:
        case=frappe.get_doc('CFG Kanban Return Case',name);case.check_permission('read')
        rows.append(dict(name=case.name,stop_key=case.driver_stop_key,state=case.state,
            stock_already_owned=bool(case.stock_already_owned),claimed_total_qty=case.claimed_total_qty,
            qc_started_on=case.qc_started_on,qc_completed_on=case.qc_completed_on,
            inspection_location=case.inspection_location,vehicle_warehouse=case.collection_vehicle_warehouse,
            accounting_status=case.accounting_status,disposition_status=case.disposition_status))
    return rows


def _existing(value,source,current=False):
    name=str(value or '').strip()
    if not frappe.db.exists('CFG Kanban Return Case',name):
        name=frappe.db.get_value('CFG Kanban Return Case',{'scan_token':name},'name')
    if not name:frappe.throw('Existing Temporary Return Note was not found')
    case=frappe.get_doc('CFG Kanban Return Case',name,**({'for_update':True} if current else {}));case.check_permission('read')
    if (case.selling_company!=source['company'] or case.customer!=source['customer'] or case.return_flow!='Customer Return for QC' or case.stock_already_owned):
        frappe.throw('Return Note does not match this Company/customer or is company-owned refused stock')
    if case.state!='Awaiting QC Receipt':frappe.throw('Only an unreceived Temporary Return Note can be collected')
    if case.get('driver_trip') or case.get('collection_key'):frappe.throw('This Return Note was already collected or assigned to a collection trip')
    return case

"""One explicit GPS publisher per active Trip; fixes never grant delivery permissions."""
import hmac,json,re,secrets,time

import frappe
from frappe.utils import add_to_date,cint,now_datetime
from cfg_kanban.services.operator_auth import require_operator,credential_hash
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.events import record
from cfg_kanban.services.trip_gps_math import position,sequence,fix_age,PUBLISH_SECONDS,STALE_SECONDS,LEASE_HOURS

TRIP='CFG Kanban Delivery Trip'
GPS='CFG Kanban Trip GPS'
MANAGERS=('Stock Manager','Manufacturing Manager','System Manager')

class GPSLeaseEnded(frappe.PermissionError):
    """No more device publishing is permitted for this source."""


def _actions():
    from cfg_kanban.services import driver_route_actions
    return driver_route_actions


def _views():
    from cfg_kanban.services import driver_routes
    return driver_routes


def _now_ms():return int(time.time()*1000)


def _source(doc,current=False):
    name=frappe.db.get_value(GPS,doc.name,'name',**({'for_update':True} if current else {}))
    row=frappe.get_doc(GPS,name,**({'for_update':True} if current else {})) if name else None
    if row and (row.delivery_trip!=doc.name or row.company!=doc.company):frappe.throw('GPS source does not match this Trip Company')
    return row


def _vehicle(doc):
    if doc.state!='Planned' or doc.driver_route_state!='In Progress':frappe.throw('Start this active Delivery Trip before sharing GPS')
    try:saved=json.loads(doc.driver_route_snapshot_json or '{}')
    except (ValueError,TypeError):frappe.throw('Reconcile the active Trip lorry snapshot before sharing GPS')
    if saved.get('scope_hash')!=_actions()._core(doc) or not saved.get('vehicle') or not doc.driver_active_vehicle_key:
        frappe.throw('Reconcile the active Trip lorry before sharing GPS')
    vehicle=frappe.get_doc('Warehouse',saved['vehicle']);vehicle.check_permission('read')
    if vehicle.company!=doc.company or not vehicle.cfg_is_vehicle_warehouse or vehicle.disabled or vehicle.is_group:
        frappe.throw('GPS requires the active Trip Company lorry Warehouse')
    return vehicle


def _publisher(row,doc):
    """A scoped GPS lease may outlive inactivity, but never an explicit switch/logout/revocation."""
    session=frappe.get_doc('CFG Kanban Operator Session',row.operator_session)
    if session.employee!=row.source_employee or session.terminal_user!=row.terminal_user or session.operator_profile!=row.operator_profile:
        frappe.throw('GPS publisher identity changed',GPSLeaseEnded)
    if not session.active:
        if session.end_reason!='Inactive Timeout':frappe.throw('GPS operator switched or logged out',GPSLeaseEnded)
        # An already timed-out session is not closed again by a later login. Respect the
        # native login's station/global switch scope without touching its activity timer.
        newer=frappe.get_all('CFG Kanban Operator Session',filters={'terminal_user':row.terminal_user,
            'employee':['!=',row.source_employee],'started_on':['>',session.started_on]},fields=['station'],limit_page_length=0)
        if any(not other.station or other.station==session.station for other in newer):
            frappe.throw('Another operator signed in after this GPS session',GPSLeaseEnded)
    if session.development_proxy:
        if row.terminal_user!='Administrator' or not cint(frappe.db.get_single_value('CFG Kanban Settings','enable_administrator_operator_bypass')):
            frappe.throw('GPS development operator is no longer authorized',GPSLeaseEnded)
        from cfg_kanban.services.operator_auth import _development_proxy_profile
        profile=_development_proxy_profile(session.employee)
    else:
        profile=frappe.get_doc('CFG Kanban Operator Profile',row.operator_profile)
    if not profile.active or profile.employee!=row.source_employee or not profile.can_start or not _views().assigned(doc,profile):
        frappe.throw('GPS publisher is no longer assigned or authorized',GPSLeaseEnded)
    _views()._delivery()._require_customer_delivery(profile)
    if frappe.db.get_value('Employee',profile.employee,'status')!='Active':frappe.throw('GPS Employee is inactive',GPSLeaseEnded)
    return profile


def _lease_live(row,doc):
    if doc.state!='Planned' or doc.driver_route_state!='In Progress' or not row or row.state=='Stopped' or _now_ms()>=cint(row.lease_until_ms):return False
    try:
        _publisher(row,doc)
        if _vehicle(doc).name!=row.vehicle_warehouse:return False
    except (frappe.PermissionError,frappe.DoesNotExistError,frappe.ValidationError):return False
    return True


def _secret(value):
    value=str(value or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',value):frappe.throw('A secure device GPS token is required')
    return value


def start(doc,values,operator,session):
    """The existing durable Driver Action owns root lock, start authorization and receipt."""
    if not _views().assigned(doc,operator):frappe.throw('Only an assigned driver or assistant may publish this Trip GPS',frappe.PermissionError)
    if frappe.db.get_value('Employee',operator.employee,'status')!='Active':frappe.throw('GPS Employee must be active')
    vehicle=_vehicle(doc);secret=_secret(values.get('publish_token'));device=str(values.get('device_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',device):frappe.throw('Identify this GPS browser device')
    row=_source(doc,True)
    if _lease_live(row,doc):frappe.throw('GPS is already shared for this Trip; stop the current device or ask a Supervisor to release it')
    if not row:
        row=frappe.get_doc(dict(doctype=GPS,name=doc.name,delivery_trip=doc.name,company=doc.company))
        row.flags.cfg_trip_gps=True;row.insert(ignore_permissions=True)
    epoch=secrets.token_urlsafe(18);until=_now_ms()+LEASE_HOURS*3600000
    row.db_set(dict(state='Sharing',vehicle_warehouse=vehicle.name,vehicle_reference=vehicle.cfg_vehicle_reference,
        source_employee=operator.employee,operator_profile=session.operator_profile,operator_session=session.name,terminal_user=frappe.session.user,
        device_id=device,lease_id=epoch,publish_token_hash=credential_hash(secret),lease_until_ms=until,
        lease_until=add_to_date(now_datetime(),hours=LEASE_HOURS),started_on=now_datetime(),stopped_on=None,stop_reason=None,
        last_sequence=0,last_payload_hash=None,pause_sequence=0),update_modified=True)
    return dict(lease_id=epoch,lease_until_ms=until,vehicle_warehouse=vehicle.name,vehicle_reference=vehicle.cfg_vehicle_reference,
        publisher_employee=operator.employee,publish_interval_seconds=PUBLISH_SECONDS,stale_after_seconds=STALE_SECONDS)


def summary(doc,row=None):
    row=row if row is not None else _source(doc)
    if not row:return dict(state='Not Shared',position=None,vehicle_warehouse=None,live=False,age_seconds=None)
    vehicle=frappe.get_doc('Warehouse',row.vehicle_warehouse);vehicle.check_permission('read')
    if vehicle.company!=doc.company:frappe.throw('GPS source lorry belongs to another Company',frappe.PermissionError)
    fix=json.loads(row.last_fix_json or 'null');age=fix_age(fix,row.last_received_ms or 0,_now_ms())
    active=doc.state=='Planned' and doc.driver_route_state=='In Progress'
    state=('Trip Ended' if not active else 'Stopped' if row.state=='Stopped' else 'Expired' if _now_ms()>=cint(row.lease_until_ms) else
        'Revoked' if not _lease_live(row,doc) else 'Paused' if row.state=='Paused' else
        'Waiting for GPS' if not fix or fix.get('lease_id')!=row.lease_id else 'Stale' if age>STALE_SECONDS else
        'Low Accuracy' if fix['accuracy']>100 else 'Live')
    return dict(state=state,live=state in ('Live','Low Accuracy'),position=({key:fix[key] for key in ('latitude','longitude','accuracy','captured_ms')} if fix else None),
        age_seconds=age,received_on=row.last_received_on,vehicle_warehouse=row.vehicle_warehouse,vehicle_reference=row.vehicle_reference,
        publisher_employee=row.source_employee,lease_id=row.lease_id,lease_until_ms=row.lease_until_ms,last_sequence=cint(row.last_sequence),
        stale_after_seconds=STALE_SECONDS,publish_interval_seconds=PUBLISH_SECONDS,stop_reason=row.stop_reason)


def _device(trip_name,lease_id,publish_token,current=True):
    doc=_actions()._root(trip_name);row=_source(doc,current)
    digest=credential_hash(_secret(publish_token))
    if (not row or row.lease_id!=lease_id or row.terminal_user!=frappe.session.user or
            not hmac.compare_digest(row.publish_token_hash or '',digest)):
        frappe.throw('This GPS source was replaced or belongs to another device',GPSLeaseEnded)
    return doc,row


@frappe.whitelist()
def source_status(trip_name,lease_id,publish_token):
    doc,row=_device(trip_name,lease_id,publish_token,False)
    return summary(doc,row)


@frappe.whitelist()
def publish_position(trip_name,lease_id,publish_token,position_data,sequence_no):
    doc,row=_device(trip_name,lease_id,publish_token)
    if not _lease_live(row,doc):frappe.throw('GPS sharing ended or expired; identify the driver and start it again',GPSLeaseEnded)
    vehicle=_vehicle(doc)
    if vehicle.name!=row.vehicle_warehouse:frappe.throw('The GPS lorry changed; restart sharing for the current Trip',GPSLeaseEnded)
    value=json.loads(position_data) if isinstance(position_data,str) else position_data
    try:fix=position(value,_now_ms());number=sequence(sequence_no)
    except ValueError as exc:frappe.throw(str(exc))
    digest=canonical_key('trip-gps-fix',lease_id,number,fix)
    if number<=cint(row.last_sequence):
        if number==cint(row.last_sequence) and row.last_payload_hash!=digest:frappe.throw('This GPS sequence belongs to different original coordinates')
        return dict(status='Ignored',gps=summary(doc,row))
    if number<=cint(row.get('pause_sequence')):return dict(status='Ignored',gps=summary(doc,row))
    old=json.loads(row.last_fix_json or 'null')
    changes=dict(last_sequence=number,last_payload_hash=digest)
    if old and old.get('lease_id')==lease_id and fix['captured_ms']<=old['captured_ms']:
        row.db_set(changes,update_modified=False)
        return dict(status='Ignored',gps=summary(doc,row))
    changes.update(state='Sharing',last_fix_json=frappe.as_json(dict(fix,lease_id=lease_id)),last_received_ms=_now_ms(),last_received_on=now_datetime())
    row.db_set(changes,update_modified=True)
    return dict(status='Recorded',gps=summary(doc,row))


@frappe.whitelist()
def pause_source(trip_name,lease_id,publish_token,sequence_no=0):
    doc,row=_device(trip_name,lease_id,publish_token)
    try:number=0 if type(sequence_no) is int and sequence_no==0 or sequence_no=='0' else sequence(sequence_no)
    except ValueError as exc:frappe.throw(str(exc))
    if row.state!='Stopped' and number>=cint(row.last_sequence):
        row.db_set(dict(state='Paused',pause_sequence=max(number,cint(row.get('pause_sequence')))),update_modified=True)
    return summary(doc,row)


@frappe.whitelist()
def stop_source(trip_name,lease_id,publish_token):
    doc,row=_device(trip_name,lease_id,publish_token)
    if row.state!='Stopped':
        row.db_set(dict(state='Stopped',stopped_on=now_datetime(),stop_reason='Stopped by GPS device'),update_modified=True)
        record('Trip GPS Source Stopped',reference_doctype=TRIP,reference_name=doc.name,operator=row.source_employee,
            operator_session=row.operator_session,terminal_user=frappe.session.user,payload=dict(lease_id=lease_id,vehicle=row.vehicle_warehouse))
    return summary(doc,row)


@frappe.whitelist()
def driver_context(trip_name,operator_session_token):
    operator,_session=require_operator(operator_session_token,touch_activity=False)
    _views()._delivery()._require_customer_delivery(operator);doc=_views()._trip(trip_name,operator)
    return dict(gps=summary(doc),can_share=bool(_views().assigned(doc,operator) and operator.can_start and doc.state=='Planned' and doc.driver_route_state=='In Progress'))


def _supervisor(token,interactive=0,override=False):
    frappe.only_for(MANAGERS)
    operator,session=require_operator(token,'override' if override else None,touch_activity=bool(cint(interactive)))
    if not _views()._all(operator):frappe.throw('A Supervisor with View All Responsibilities is required for the live map',frappe.PermissionError)
    _views()._delivery()._require_customer_delivery(operator)
    return operator,session


@frappe.whitelist()
def supervisor_fleet(operator_session_token,company=None,include_closed=0,start=0,interactive=0):
    operator,_session=_supervisor(operator_session_token,interactive)
    if company:frappe.get_doc('Company',company).check_permission('read')
    filters={'driver_route_state':['in',['In Progress','Completed','Closed Incomplete'] if cint(include_closed) else ['In Progress']]}
    if company:filters['company']=company
    if not cint(include_closed):filters['state']='Planned'
    offset=max(0,cint(start));names=frappe.get_list(TRIP,filters=filters,pluck='name',order_by='driver_route_started_on desc, name desc',limit_start=offset,limit_page_length=21)
    rows=[]
    for name in names[:20]:
        doc=_views()._trip(name,operator);rows.append(dict(trip=_views()._header(doc),gps=summary(doc)))
    return dict(trips=rows,has_more=len(names)>20,start=offset,operator=dict(employee=operator.employee,kanban_role=operator.kanban_role,can_override=bool(operator.can_override)),server_ms=_now_ms())


@frappe.whitelist()
def supervisor_trip(trip_name,operator_session_token,interactive=0):
    operator,_session=_supervisor(operator_session_token,interactive)
    doc=_views()._trip(trip_name,operator)
    result=_views().get_driver_trip(trip_name,operator_session_token,interactive=0)
    return dict(detail=result,gps=summary(doc),server_ms=_now_ms())


def release(doc,values,operator,session):
    """The existing Driver Action receipt fences duplicate or late release requests."""
    frappe.only_for(MANAGERS)
    if not (_views()._all(operator) and operator.can_override):frappe.throw('A Supervisor with View All and Override must release this GPS source',frappe.PermissionError)
    reason=str(values.get('reason') or '').strip()
    if not reason:frappe.throw('Enter the Supervisor GPS release reason')
    row=_source(doc,True)
    if not row or row.lease_id!=values.get('lease_id'):frappe.throw('GPS source changed; refresh before releasing it')
    row.db_set(dict(state='Stopped',stopped_on=now_datetime(),stop_reason=reason),update_modified=True)
    return dict(lease_id=row.lease_id,gps_released=True)

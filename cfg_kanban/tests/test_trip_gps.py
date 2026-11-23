"""Real GPS control flow with offline native-document doubles, not live GPS acceptance."""
import datetime
import hmac
import json
import re
import secrets
import sys
import time
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests import test_driver_route_actions as actions
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests.test_vehicle_overview import Row,load,ROOT
from cfg_kanban.services import trip_gps_math as math


class GPSDoc(office.Doc):
    def insert(self,**kwargs):
        self.name=self.delivery_trip
        if self.name in self._data.setdefault(self.doctype,{}):raise ValueError('Duplicate GPS root')
        self._data[self.doctype][self.name]=self
        return self


class TestGPSMath(unittest.TestCase):
    now=1795305600000
    def fix(self,**kw):return dict(latitude=3.139,longitude=101.6869,accuracy=8,captured_ms=self.now,**kw)
    def test_coordinates_zero_finite_ranges_and_exact_payload(self):
        fix=self.fix();fix.update(latitude=0,longitude=0);self.assertEqual(math.position(fix,self.now)['latitude'],0)
        for key,bad in [('latitude',91),('longitude',181),('accuracy',-1),('captured_ms',float('inf')),('latitude',True),('longitude','3')]:
            with self.subTest(key=key,bad=bad):
                value=self.fix();value[key]=bad
                with self.assertRaises(ValueError):math.position(value,self.now)
        for value in [None,[],dict(self.fix(),operator='FORGED')]:
            with self.assertRaises(ValueError):math.position(value,self.now)
    def test_stale_future_and_age_do_not_use_site_timezone(self):
        for delta in [-120001,30001]:
            fix=self.fix();fix['captured_ms']+=delta
            with self.assertRaises(ValueError):math.position(fix,self.now)
        fix=self.fix();fix['captured_ms']+=20000
        self.assertEqual(math.fix_age(fix,self.now,self.now+95000),95)
        fix['captured_ms']=self.now-5000;self.assertEqual(math.fix_age(fix,self.now,self.now+95000),100)
    def test_monotonic_sequence_accepts_http_digits_and_rejects_coercions(self):
        self.assertEqual(math.sequence('42'),42)
        for value in [True,0,-1,1.2,'1.0',' 1','١',None,2147483648]:
            with self.assertRaises(ValueError):math.sequence(value)
    def test_publish_presets_and_freshness_window_preserve_legacy_default(self):
        for value in (None,'',0):self.assertEqual(math.publish_interval(value),15)
        for value in (15,30,60,120,300):
            self.assertEqual(math.publish_interval(str(value)),value)
            self.assertEqual(math.stale_after(value),max(90,3*value))
        for value in (True,False,1,-1,14,61,15.1,'60 seconds',[],float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):math.publish_interval(value)


class TestTripGPS(unittest.TestCase):
    def setUp(self):
        self.a=actions.TestDriverRouteActions();self.a.setUp();self.a.start()
        self.f=self.a.b.frappe;self.data=self.a.data;self.trip=self.a.trip;self.op=self.a.operator
        self.clock=1795305600000;self.receipts=[];self.auth_calls=[]
        self.session=office.Doc(name='GPSSESSION',active=1,employee=self.op.employee,operator_profile='PROFILE',terminal_user='terminal@example.com',development_proxy=0,station='PHONE',started_on=datetime.datetime(2026,11,22,8))
        self.op.update(active=1,name='PROFILE');self.f.session.user='terminal@example.com'
        self.data['CFG Kanban Operator Session']={self.session.name:self.session}
        self.data['CFG Kanban Operator Profile']={'PROFILE':self.op}
        self.f.DoesNotExistError=KeyError
        previous_all=self.f.get_all
        def get_all(doctype,filters=None,fields=None,**kwargs):
            if doctype!='CFG Kanban Operator Session':return previous_all(doctype,filters=filters,fields=fields,**kwargs)
            return [Row(station=r.station) for r in self.data[doctype].values() if r.terminal_user==filters['terminal_user']
                and r.employee!=filters['employee'][1] and r.started_on>filters['started_on'][1]]
        self.f.get_all=get_all
        previous=self.f.get_doc
        def get_doc(doctype,name=None,**kw):
            if isinstance(doctype,dict):return GPSDoc(dict(doctype,_data=self.data,flags=Row()))
            return previous(doctype,name,**kw)
        self.f.get_doc=get_doc
        def get_value(dt,name,field,**kw):
            rows=self.data.get(dt,{})
            row=next((r for r in rows.values() if self.a.b.matches(r,name)),None) if isinstance(name,dict) else rows.get(name)
            if not row:return None
            return Row({k:row.get(k) for k in field}) if isinstance(field,list) else row.get(field)
        self.f.db.get_value=get_value
        self.mod=types.ModuleType('cfg_kanban.services.trip_gps');self.ns=self.mod.__dict__
        self.ns.update(frappe=self.f,hmac=hmac,json=json,re=re,secrets=secrets,time=time,
            add_to_date=lambda d,hours:d+datetime.timedelta(hours=hours),cint=lambda value:int(value or 0),
            now_datetime=lambda:datetime.datetime(2026,11,22,8),require_operator=self.auth,
            credential_hash=lambda value:actions.canonical('secret',value),canonical_key=actions.canonical,
            record=lambda event,**kw:self.receipts.append((event,kw)),position=math.position,sequence=math.sequence,
            fix_age=math.fix_age,PUBLISH_SECONDS=math.PUBLISH_SECONDS,STALE_SECONDS=math.STALE_SECONDS,LEASE_HOURS=math.LEASE_HOURS)
        load('services/trip_gps.py',self.ns)
        self.ns.update(_actions=lambda:Row(**self.a.ns),_views=lambda:Row(**self.a.v.ns),_now_ms=lambda:self.clock)
        p=patch.dict(sys.modules,{self.mod.__name__:self.mod});p.start();self.addCleanup(p.stop)
        self.a.ns['require_operator']=self.auth
        self.secret='original_secret_'+'x'*48;self.device='device_'+'y'*32;self.n=0
    def auth(self,token,action=None,**kwargs):
        self.auth_calls.append((token,action,kwargs))
        if token!='TOKEN':raise PermissionError('Operator session is not active')
        if not self.session.active:raise PermissionError('Operator session is not active')
        if action and not self.op.get('can_'+action):raise PermissionError('Action flag required')
        return self.op,self.session
    def context(self,operation='Start GPS'):return self.a.ns['driver_action_context'](self.trip.name,'TOKEN',operation=operation)
    def test_legacy_lorry_sync_preserves_active_gps_binding(self):
        self.trip.vehicle_warehouse=None
        saved=json.loads(self.trip.driver_route_snapshot_json);saved['scope_hash']=self.a.ns['_core'](self.trip)
        self.trip.driver_route_snapshot_json=json.dumps(saved)
        result=self.ns['start'](self.trip,dict(device_id=self.device,publish_token=self.secret),self.op,self.session)
        self.a.sync_lorry()
        self.assertEqual(self.ns['_vehicle'](self.trip).name,'LORRY')
        self.assertEqual(self.ns['summary'](self.trip)['vehicle_warehouse'],'LORRY')
        self.assertEqual(result['vehicle_warehouse'],'LORRY')
        self.lease=result['lease_id'];self.fix()

    def request(self,action='Start GPS',**payload):
        c=self.context(action);self.n+=1
        if action=='Start GPS':payload=dict(device_id=self.device,publish_token=self.secret,**payload)
        return dict(trip_name=self.trip.name,action=action,event_token='GPS-'+str(self.n),operator_session_token='TOKEN',
            expected_revision=c['revision'],scope_hash=c['scope_hash'],payload=payload)
    def share(self):
        self.last_request=self.request();result=self.a.perform(self.last_request);self.lease=result['result']['lease_id'];return result
    def row(self):return self.data[self.ns['GPS']][self.trip.name]
    def args(self):return dict(trip_name=self.trip.name,lease_id=self.lease,publish_token=self.secret)
    def fix(self,number=1,**extra):
        value=dict(latitude=3.139,longitude=101.6869,accuracy=8,captured_ms=self.clock);value.update(extra)
        return self.ns['publish_position'](**self.args(),position_data=value,sequence_no=number)
    def summary(self):return self.ns['summary'](self.trip)
    def test_saved_interval_controls_source_replies_and_does_not_prematurely_mark_stale(self):
        self.trip.gps_publish_interval_seconds='60';self.data['Employee']['EMP'].employee_name='Ali'
        result=self.share()['result'];self.assertEqual(result['publish_interval_seconds'],60)
        self.assertEqual(result['publisher_name'],'Ali');self.fix();self.clock+=100000
        summary=self.summary();self.assertEqual(summary['state'],'Live');self.assertEqual(summary['stale_after_seconds'],180)
        self.clock+=81000;self.assertEqual(self.summary()['state'],'Stale')
        self.trip.gps_publish_interval_seconds='300'
        self.assertEqual(self.ns['source_status'](**self.args())['publish_interval_seconds'],300)
        self.assertEqual(self.summary()['stale_after_seconds'],900)
    def supervisor(self):self.op.update(kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
    def test_start_receipt_survives_mutable_trip_end_and_never_changes_delivery_revision(self):
        revision=self.trip.driver_route_revision;result=self.share();row=self.row()
        self.assertEqual(self.trip.driver_route_revision,revision);self.assertEqual(row.name,self.trip.name)
        self.assertNotEqual(row.publish_token_hash,self.secret);self.assertNotIn(self.secret,json.dumps(self.a.events,default=str))
        self.trip.driver_route_state='Completed';self.assertEqual(self.a.perform(self.last_request),result)
        self.assertEqual(len(self.data[self.ns['GPS']]),1)
        changed=dict(self.last_request,payload=dict(device_id=self.device,publish_token='changed_'+'z'*48))
        with self.assertRaisesRegex(ValueError,'different original'):self.a.perform(changed)
    def test_concurrent_source_rejected_then_supervisor_release_fences_old_device(self):
        self.share();old=self.args();revision=self.trip.driver_route_revision
        with self.assertRaisesRegex(ValueError,'already shared'):self.a.perform(self.request())
        self.supervisor();request=self.request('Release GPS',lease_id=self.lease,reason='Device battery empty')
        result=self.a.perform(request);self.assertTrue(result['result']['gps_released']);self.assertEqual(self.trip.driver_route_revision,revision)
        self.share();self.assertNotEqual(self.lease,old['lease_id']);self.assertEqual(self.a.perform(request),result)
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.ns['stop_source'](**old)
        self.assertEqual(self.row().state,'Sharing')
    def test_assistant_can_share_but_unassigned_supervisor_cannot_publish(self):
        self.trip.driver='OTHER';self.trip.assistant_drivers=[office.Doc(employee=self.op.employee)]
        self.trip.driver_route_snapshot_json=json.dumps(dict(json.loads(self.trip.driver_route_snapshot_json),scope_hash=self.a.ns['_core'](self.trip)))
        self.share();self.ns['stop_source'](**self.args());self.supervisor();self.trip.assistant_drivers=[]
        with self.assertRaisesRegex(PermissionError,'assigned driver'):self.a.perform(self.request())
    def test_start_requires_start_flag_active_employee_and_live_reconciled_lorry(self):
        self.op.can_start=0
        with self.assertRaises(PermissionError):self.share()
        self.op.can_start=1;self.data['Employee'][self.op.employee].status='Left'
        with self.assertRaisesRegex(ValueError,'active'):self.share()
        self.data['Employee'][self.op.employee].status='Active';self.trip.driver_route_state='Not Started'
        with self.assertRaisesRegex(ValueError,'Start this'):self.share()
        self.trip.driver_route_state='In Progress';self.data['Warehouse']['LORRY'].company='B'
        with self.assertRaisesRegex(ValueError,'Company lorry'):self.share()
    def test_stop_is_idempotent_and_blocks_late_fixes(self):
        self.share();self.fix();one=self.ns['stop_source'](**self.args());two=self.ns['stop_source'](**self.args())
        self.assertEqual(one,two);self.assertEqual(len(self.receipts),1)
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix(2)
        self.assertFalse(self.summary()['live']);self.assertIsNotNone(self.summary()['position'])
    def test_duplicate_sequence_does_not_refresh_age_and_changed_original_is_rejected(self):
        self.share();self.fix();received=self.row().last_received_ms;captured=self.clock;self.clock+=10000
        result=self.fix(1,captured_ms=captured);self.assertEqual(result['status'],'Ignored');self.assertEqual(self.row().last_received_ms,received)
        with self.assertRaisesRegex(ValueError,'different original'):self.fix(1,latitude=4,captured_ms=captured)
        self.assertEqual(self.summary()['age_seconds'],10)
    def test_older_capture_or_sequence_never_rewinds_a_newer_position(self):
        self.share();self.fix(2);original=self.row().last_fix_json;received=self.row().last_received_ms
        self.clock+=10000;self.assertEqual(self.fix(1,latitude=4)['status'],'Ignored')
        self.assertEqual(self.fix(3,latitude=5,captured_ms=self.clock-15000)['status'],'Ignored')
        self.assertEqual(self.row().last_fix_json,original);self.assertEqual(self.row().last_received_ms,received)
        self.assertEqual(self.row().last_sequence,3)
    def test_pause_sequence_fences_pre_hide_requests_and_late_pause_cannot_suspend_newer_fix(self):
        self.share();self.fix(1);self.ns['pause_source'](**self.args(),sequence_no=2)
        self.clock+=1000;self.assertEqual(self.fix(2)['status'],'Ignored');self.assertEqual(self.summary()['state'],'Paused')
        self.clock+=1000;self.fix(3);self.ns['pause_source'](**self.args(),sequence_no=2)
        self.assertEqual(self.summary()['state'],'Live')
    def test_ages_low_accuracy_and_old_source_are_explicit(self):
        self.share();self.assertEqual(self.summary()['state'],'Waiting for GPS');self.fix(accuracy=200)
        self.assertEqual(self.summary()['state'],'Low Accuracy');self.clock+=91000
        self.assertEqual(self.summary()['state'],'Stale');self.assertFalse(self.summary()['live'])
        self.ns['stop_source'](**self.args());self.share();self.assertEqual(self.summary()['state'],'Waiting for GPS');self.assertIsNotNone(self.summary()['position'])
    def test_inactivity_can_publish_without_renewing_operator_action_permission(self):
        self.share();count=len(self.auth_calls);self.session.update(active=0,end_reason='Inactive Timeout')
        self.fix();self.assertEqual(len(self.auth_calls),count)
        with self.assertRaises(PermissionError):self.context()
    def test_switch_logout_profile_employee_and_assignment_revoke_source(self):
        for change in ['switch','logout','profile','employee','assignment','responsibility']:
            with self.subTest(change=change):
                self.setUp();self.share()
                if change in ('switch','logout'):self.session.update(active=0,end_reason='Operator Switched' if change=='switch' else 'Logout')
                if change=='profile':self.op.active=0
                if change=='employee':self.data['Employee'][self.op.employee].status='Left'
                if change=='assignment':self.trip.driver='OTHER'
                if change=='responsibility':self.op.responsibilities=[]
                with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix()
                self.assertEqual(self.summary()['state'],'Revoked')
    def test_expiry_and_trip_closure_stop_publishing_even_with_valid_secret(self):
        self.share();self.clock=self.row().lease_until_ms
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix()
        self.assertEqual(self.summary()['state'],'Expired');self.clock-=1;self.trip.driver_route_state='Completed'
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix()
        self.assertEqual(self.summary()['state'],'Trip Ended')
    def test_scoped_token_native_terminal_and_company_read_are_all_required(self):
        self.share()
        for field,value in [('publish_token','invalid_'+'x'*48),('lease_id','OLD')]:
            with self.assertRaises(self.ns['GPSLeaseEnded']):self.ns['source_status'](**dict(self.args(),**{field:value}))
        self.f.session.user='other@example.com'
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.ns['source_status'](**self.args())
        self.f.session.user='terminal@example.com';self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.fix()
    def test_supervisor_requires_native_manager_supervisor_view_all_and_customer_delivery(self):
        self.share()
        with self.assertRaises(PermissionError):self.ns['supervisor_fleet']('TOKEN')
        self.supervisor();self.a.b.roles=['Stock User']
        with self.assertRaises(PermissionError):self.ns['supervisor_fleet']('TOKEN')
        self.a.b.roles=['Stock Manager'];self.op.responsibilities=[]
        with self.assertRaises(PermissionError):self.ns['supervisor_fleet']('TOKEN')
    def test_fleet_is_permission_company_scoped_multi_day_and_passive(self):
        self.share();self.supervisor();self.trip.trip_date='2026-11-18';self.trip.expected_return_date='2026-11-23'
        result=self.ns['supervisor_fleet']('TOKEN',company='A');self.assertEqual(result['trips'][0]['trip']['name'],self.trip.name)
        self.assertEqual(self.auth_calls[-1][2],dict(touch_activity=False));self.assertFalse(self.ns['supervisor_fleet']('TOKEN',company='B')['trips'])
        self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.ns['supervisor_fleet']('TOKEN',company='A')
    def test_closed_history_and_detail_reuse_real_delivery_projection(self):
        self.share();self.fix();self.supervisor();self.trip.driver_route_state='Completed'
        self.assertFalse(self.ns['supervisor_fleet']('TOKEN')['trips'])
        history=self.ns['supervisor_fleet']('TOKEN',include_closed=1)['trips'];self.assertEqual(history[0]['gps']['state'],'Trip Ended')
        result=self.ns['supervisor_trip'](self.trip.name,'TOKEN');self.assertEqual(result['detail']['stops'][0]['items'][0]['planned_qty'],4)
        self.assertEqual(result['gps']['state'],'Trip Ended')
    def test_release_needs_override_reason_matching_source_and_existing_receipt(self):
        self.share();self.supervisor();self.op.can_override=0
        request=self.request('Release GPS',lease_id=self.lease,reason='Empty battery')
        with self.assertRaises(PermissionError):self.a.perform(request)
        self.op.can_override=1
        for lease,reason in [(self.lease,''),('OLD','Wrong source')]:
            with self.assertRaises(ValueError):self.a.perform(self.request('Release GPS',lease_id=lease,reason=reason))
        self.assertEqual(self.row().state,'Sharing')
    def test_projection_has_no_publish_credentials_session_or_device_identity(self):
        self.share();self.fix();result=self.summary();raw=json.dumps(result,default=str)
        for key in ('publish_token','publish_token_hash','device_id','operator_session','terminal_user'):self.assertNotIn(key,result)
        self.assertNotIn(self.secret,raw);self.assertNotIn(self.device,raw)
    def test_timed_out_original_is_revoked_by_a_later_operator_login_in_native_switch_scope(self):
        self.share();self.session.update(active=0,end_reason='Inactive Timeout')
        other=office.Doc(name='LATER',terminal_user=self.session.terminal_user,employee='OTHER',station='OTHER-STATION',started_on=self.session.started_on+datetime.timedelta(minutes=30))
        self.data['CFG Kanban Operator Session']['LATER']=other
        self.fix();other.station='PHONE'
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix(2)
        self.assertEqual(self.summary()['state'],'Revoked')
        other.station=None
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix(2)
    def test_lorry_reconciliation_or_disabled_vehicle_revokes_and_native_warehouse_denial_hides_the_view(self):
        self.share();self.fix();self.data['Warehouse']['LORRY'].disabled=1
        self.assertEqual(self.summary()['state'],'Revoked')
        with self.assertRaises(self.ns['GPSLeaseEnded']):self.fix(2)
        self.data['Warehouse']['LORRY'].disabled=0;self.data['Warehouse']['LORRY']._denied=True
        with self.assertRaises(PermissionError):self.summary()
    def test_readonly_gps_record_rejects_normal_edit_and_deletion(self):
        ns=load('cfg_kanban/doctype/cfg_kanban_trip_gps/cfg_kanban_trip_gps.py',dict(frappe=self.f,Document=Row))
        doc=ns['CFGKanbanTripGPS'](flags=Row())
        with self.assertRaisesRegex(ValueError,'controlled'):doc.validate()
        doc.flags.cfg_trip_gps=True;doc.validate()
        with self.assertRaisesRegex(ValueError,'retain'):doc.on_trash()
    def test_current_trip_lock_precedes_source_and_schema_uses_64_bit_epochs(self):
        self.share();self.a.b.reads.clear();self.fix();reads=[r for r in self.a.b.reads if r[2].get('for_update')]
        self.assertEqual(reads[0][0],office.TRIP)
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_trip_gps/cfg_kanban_trip_gps.json').read_text());fields={r['fieldname']:r for r in schema['fields']}
        self.assertEqual(fields['lease_until_ms']['fieldtype'],'Long Int');self.assertEqual(fields['last_received_ms']['fieldtype'],'Long Int');self.assertFalse(schema['track_changes'])
        self.assertTrue(all(not p.get('write') and not p.get('create') and not p.get('delete') for p in schema['permissions']))

if __name__=='__main__':unittest.main()

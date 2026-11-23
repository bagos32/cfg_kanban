"""Actual driver orchestration with offline native-service/document doubles.

Native stock posting, transaction rollback, unique indexes and media need site acceptance.
"""
import copy
import datetime
import hashlib
import json
import unittest
from unittest.mock import Mock
from cfg_kanban.tests import test_driver_routes as views
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests.test_vehicle_overview import Row, load, ROOT


def canonical(namespace, *parts):
    return hashlib.sha256(json.dumps([namespace, *parts], sort_keys=True, default=str).encode()).hexdigest()


class TestDriverRouteActions(unittest.TestCase):
    def setUp(self):
        self.v = views.TestDriverRoutes(); self.v.setUp()
        self.b = self.v.b; self.data = self.v.data; self.trip = self.v.trip
        self.operator = self.v.operator; self.operator.update(can_start=1, can_complete=1, can_override=0)
        self.trip.state = 'Planned'; self.trip.driver_route_state = 'Not Started'; self.trip.driver_route_revision = 0
        self.events = {}; self.counter = 0; self.calls = []
        self.b.frappe.ValidationError = ValueError
        self.b.frappe.UniqueValidationError = type('UniqueValidationError', (Exception,), {})
        self.b.frappe.db.sql = self.sql
        self.engine = Row(**self.v.engine)
        self.engine.update(get_delivery_session=self.get_session,
            confirm_delivery_allocations=Mock(side_effect=self.confirm),
            get_customer_delivery_requirements=Mock(side_effect=self.requirements),
            create_customer_delivery_document=Mock(side_effect=self.create_note),
            _resolve_customer_site=self.site)
        get_value = self.b.frappe.db.get_value
        def native_value(doctype, name, field, **kwargs):
            if isinstance(field, list):
                row=self.data.get(doctype,{}).get(name)
                return office.Doc({key:row.get(key) for key in field}) if row else None
            return get_value(doctype,name,field)
        self.b.frappe.db.get_value=native_value
        self.native_prepared=load('services/dispatch_fulfilment.py',dict(frappe=self.b.frappe))
        vehicle_ns=load('services/dispatch_planning.py',dict(frappe=self.b.frappe))
        self.vehicle_check=vehicle_ns['_vehicle_warehouse']
        self.prepared = Row(start_prepared_delivery=Mock(side_effect=self.begin),
            validate_prepared_loading=self.native_prepared['validate_prepared_loading'],
            _loaded_allocations=lambda plan:[r for r in self.data.get('CFG Kanban Dispatch Allocation',{}).values() if r.dispatch_plan==plan.name])
        for n,plan in enumerate((self.v.p1,self.v.p2),1):
            self.data['CFG Kanban Movement Manifest']['MAN'+str(n)].update(
                dispatch_plan=plan.name,state='Received',source_warehouse=plan.source_warehouse,destination_company='A')
        self.sheets = Row(QR='Require Customer Site QR', SELECT='Allow Assigned Stop Selection',
            verification=lambda plan: plan.get('test_verification') or 'Require Customer Site QR',
            start_route_sheet_stop=Mock(side_effect=self.begin_sheet))
        self.proof = Row(get_or_create_delivery_proof=Mock(side_effect=self.open_proof),
            get_delivery_proof=lambda name, token:self.data['CFG Kanban Delivery Proof'][name].as_dict(),
            submit_delivery_proof=Mock(side_effect=self.submit_proof))
        self.ns = load('services/driver_route_actions.py', dict(frappe=self.b.frappe, json=json,
            cint=lambda v:int(v or 0), flt=lambda v:float(v or 0), canonical_key=canonical,
            get_datetime=lambda v:datetime.datetime.fromisoformat(str(v)),
            now_datetime=lambda:datetime.datetime(2026,11,21,17), require_operator=self.auth, record=self.record))
        self.ns.update(_views=lambda:Row(**self.v.ns), _delivery=lambda:self.engine,
            _prepared=lambda:self.prepared, _sheets=lambda:self.sheets, _proof=lambda:self.proof,
            _planning=lambda:Row(_assert_plan_authorized=self.authorized,_vehicle_warehouse=self.vehicle_check),
            _core=lambda doc:self.ns['_scope_hash'](doc,self.b.ns['_business'](doc)))
        self.v.ns['_delivery'] = lambda:self.engine
        for n in (1,2):self.data['CFG Kanban Customer Scan Point']['SITE'+str(n)].site_code='QR'+str(n)
        self.auto_submit = True; self.proof_policy = 'Required'; self.required_fields = []

    def auth(self, token, action=None):
        if token != 'TOKEN':raise ValueError('Operator session is not active')
        if action and not self.operator.get('can_'+action):raise PermissionError('Action flag required')
        return self.operator, office.Doc(name='OPSESSION',terminal_user='terminal@example.com')
    def authorized(self, plan, operator):
        if plan.get('_operator_denied'):raise PermissionError('Dispatch responsibility required')
    def record(self, event, **kw):
        self.events[kw['idempotency_key']] = dict(event=event, **kw)
    def sql(self, query, values=None, **kw):
        if 'tabCFG Kanban Event' in query:
            event=self.events.get(values[0]); return [Row(payload_json=json.dumps(event['payload'],default=str))] if event else []
        return self.b.sql(query, values, **kw)
    def context(self, n=1):
        return self.ns['driver_action_context'](self.trip.name, 'TOKEN', self.v.keys[n-1])
    def request(self, action=None, n=1, **payload):
        c=self.context(n); self.counter+=1
        return dict(trip_name=self.trip.name, action=action or c['next_step'], event_token='EVENT'+str(self.counter),
            operator_session_token='TOKEN', expected_revision=c['revision'],scope_hash=c['scope_hash'],
            stop_key=c['stop_key'],dispatch_plan=c['dispatch_plan'],payload=payload)
    def perform(self, request):return self.ns['perform_driver_action'](**request)
    def act(self, action=None,n=1,**payload):return self.perform(self.request(action,n,**payload))
    def start(self):return self.act('Start Route')
    def begin_stop(self,n=1):return self.act(n=n,customer_scan='QR'+str(n))
    def site(self, code):
        return next(row for row in self.data['CFG Kanban Customer Scan Point'].values() if code in (row.name,row.site_code))
    def begin_sheet(self,sheet_name,row_key,key,token,scan):
        sheet=self.data['CFG Kanban Route Sheet'][sheet_name]
        row=next(row for row in sheet.stops if row.row_key==row_key)
        if sheet.verification_policy==self.sheets.QR and not scan:raise ValueError('Site QR required')
        sheet.state='In Progress';return self.begin(row.dispatch_plan,scan or row.customer_scan_point,key,token)
    def begin(self, plan_name, scan, key, token):
        plan=self.data[office.PLAN][plan_name]
        if self.site(scan).name!=plan.customer_site:raise ValueError('Customer Site scan does not match')
        if plan.delivery_session:return self.get_session(plan.delivery_session,token)
        self.calls.append(('begin',plan_name,scan)); name='DEL-'+plan_name
        self.b.add(views.SESSION,name,dispatch_plan=plan_name,selling_company='A',customer=plan.customer,
            customer_scan_point=plan.customer_site,state='Allocating Stock',started_by_operator=self.operator.employee,
            delivery_note=None,delivery_proof=None,auto_submit_delivery_note=int(self.auto_submit),proof_policy=self.proof_policy)
        plan.delivery_session=name;plan.fulfilment_status='In Progress';return self.get_session(name,token)
    def get_session(self,name,token):return self.data[views.SESSION][name].as_dict()
    def confirm(self,name,key,token):
        self.calls.append(('confirm',name));self.data[views.SESSION][name].state='Awaiting Confirmation'
    def requirements(self,name,token):
        session=self.data[views.SESSION][name]
        return dict(fields=self.required_fields,**({'existing_draft':session.delivery_note} if session.delivery_note else {}))
    def create_note(self,name,key,token,inputs):
        self.calls.append(('note',name,json.loads(inputs)));session=self.data[views.SESSION][name]
        note='DN-'+session.dispatch_plan;session.delivery_note=note
        self.b.add(views.NOTE,note,company='A',customer=session.customer,docstatus=1 if self.auto_submit else 0,is_return=0)
        if self.auto_submit:self.post(name)
        else:session.state='ERP Document Pending'
    def post(self,name):
        session=self.data[views.SESSION][name];plan=self.data[office.PLAN][session.dispatch_plan]
        self.data[views.NOTE][session.delivery_note].docstatus=1
        session.state='Closed' if session.proof_policy=='No Proof Required' else 'Delivered'
        plan.fulfilment_status='Completed' if session.state=='Closed' else 'Delivered'
        for alloc in self.data['CFG Kanban Dispatch Allocation'].values():
            if alloc.dispatch_plan==plan.name:
                alloc.state='Fulfilled';self.b.add(views.DA,'USE-'+alloc.name,delivery_session=name,
                    dispatch_allocation=alloc.name,state='Delivered',delivered_qty=alloc.allocated_qty)
    def open_proof(self,name,token):
        session=self.data[views.SESSION][name]; proof_name='POD-'+name;session.delivery_proof=proof_name
        proof=self.b.add('CFG Kanban Delivery Proof',proof_name,state='Draft',delivery_session=name,
            delivery_note=session.delivery_note,proof_policy=session.proof_policy,allowed_dispositions=['Attended'],media=[])
        return proof.as_dict()
    def submit_proof(self,proof_name,disposition,event_token,operator_session_token,**kwargs):
        proof=self.data['CFG Kanban Delivery Proof'][proof_name];proof.state='Submitted'
        session=self.data[views.SESSION][proof.delivery_session];session.state='Closed'
        self.data[office.PLAN][session.dispatch_plan].fulfilment_status='Completed'
    def deliver_to_proof(self,n=1):
        self.begin_stop(n);self.act(n=n);self.act(n=n,required_erp_inputs={'parent':{},'tables':{}});self.act(n=n)
    def proof_submit(self,n=1):
        return self.act(n=n,proof_name=self.context(n)['proof']['name'],disposition='Attended',recipient_name='Recipient')

    def test_start_only_records_departure_and_keeps_native_delivery_untouched(self):
        r=self.start();self.assertEqual(r['status'],'Recorded');self.assertTrue(r['result']['route_started'])
        self.assertEqual(self.trip.driver_route_state,'In Progress');self.assertEqual(self.trip.driver_route_revision,1)
        self.assertEqual(self.calls,[]);self.assertFalse(self.data.get(views.SESSION));self.assertFalse(self.data.get(views.NOTE))
        self.assertEqual(self.context()['next_step'],'Begin Delivery');self.assertTrue(self.trip.driver_active_vehicle_key)
    def test_opted_in_departure_records_auto_gps_intent_without_creating_a_source_on_server(self):
        self.trip.gps_auto_start=1;result=self.start()
        self.assertTrue(result['result']['gps_auto_start'])
        self.assertFalse(self.data.get('CFG Kanban Trip GPS'))
        self.assertEqual(self.trip.driver_route_state,'In Progress')

    def legacy_departure(self,empty=None):
        self.trip.vehicle_warehouse=empty;self.start()
        saved=json.loads(self.trip.driver_route_snapshot_json)
        # Model the previous release: real lorry saved, original empty planning scope.
        self.trip.vehicle_warehouse=empty
        saved['scope_hash']=self.ns['_core'](self.trip)
        self.trip.driver_route_snapshot_json=json.dumps(saved)
        return self.trip.driver_route_snapshot_json
    def sync_lorry(self,**changes):
        args=dict(trip_name=self.trip.name,expected_modified=self.trip.modified)
        args.update(changes);return self.ns['sync_trip_lorry'](**args)

    def test_departure_persists_late_selected_lorry_and_next_delivery_remains_valid(self):
        self.trip.vehicle_warehouse=None;request=self.request('Start Route');self.perform(request)
        self.assertEqual(self.trip.vehicle_warehouse,'LORRY')
        self.assertEqual(json.loads(self.trip.driver_route_snapshot_json)['scope_hash'],self.ns['_core'](self.trip))
        self.assertEqual(self.v.queue()['trips'][0]['vehicle_warehouse'],'LORRY')
        self.begin_stop();self.assertEqual(len(self.calls),1)
        self.assertEqual(self.perform(request)['result']['route_started'],True)

    def test_failed_departure_does_not_fill_header_when_lorries_disagree(self):
        self.b.add('Warehouse','OTHER',company='A',cfg_is_vehicle_warehouse=1,cfg_vehicle_reference='OTHER',is_group=0,disabled=0)
        self.trip.vehicle_warehouse=None;self.v.p2.vehicle_warehouse='OTHER'
        with self.assertRaises(ValueError):self.start()
        self.assertIsNone(self.trip.vehicle_warehouse);self.assertEqual(self.trip.driver_route_state,'Not Started')
        self.assertFalse(self.events)

    def test_legacy_sync_preserves_exact_snapshot_revision_key_and_pending_delivery_scope(self):
        frozen=self.legacy_departure();pending=self.request('Begin Delivery',customer_scan='QR1')
        revision=self.trip.driver_route_revision;active=self.trip.driver_active_vehicle_key
        result=self.sync_lorry()
        self.assertTrue(result['changed']);self.assertEqual(self.trip.vehicle_warehouse,'LORRY')
        self.assertEqual(self.trip.driver_route_snapshot_json,frozen)
        self.assertEqual(self.trip.driver_route_revision,revision);self.assertEqual(self.trip.driver_active_vehicle_key,active)
        self.assertEqual(self.ns['_core'](self.trip),json.loads(frozen)['scope_hash'])
        self.perform(pending);self.assertEqual(len(self.calls),1)
        self.assertEqual(len([e for e in self.events.values() if e['event']=='Delivery Trip Departure Lorry Linked']),1)
        self.assertFalse(self.sync_lorry()['changed'])

    def test_empty_string_legacy_header_and_completed_trip_can_be_synced(self):
        frozen=self.legacy_departure('');self.trip.driver_route_state='Completed'
        self.assertTrue(self.sync_lorry()['changed']);self.assertEqual(self.trip.driver_route_snapshot_json,frozen)
        self.assertEqual(self.ns['_core'](self.trip),json.loads(frozen)['scope_hash'])

    def test_legacy_hash_compatibility_does_not_accept_other_planning_changes(self):
        self.legacy_departure();self.sync_lorry();saved=json.loads(self.trip.driver_route_snapshot_json)
        self.trip.orders[0].planned_qty+=1
        self.assertNotEqual(self.ns['_core'](self.trip),saved['scope_hash'])
        with self.assertRaisesRegex(ValueError,'reconciliation'):self.sync_lorry()
        self.trip.orders[0].planned_qty-=1;self.trip.vehicle_warehouse='WRONG'
        self.assertNotEqual(self.ns['_core'](self.trip),saved['scope_hash'])
        with self.assertRaises(ValueError):self.sync_lorry()

    def test_sync_requires_office_write_company_lorry_permissions_and_current_revision(self):
        self.legacy_departure();self.b.roles=[]
        with self.assertRaises(PermissionError):self.sync_lorry()
        self.b.roles=['Stock Manager']
        with self.assertRaisesRegex(ValueError,'changed'):self.sync_lorry(expected_modified='2000-01-01 00:00:00')
        for target in (self.trip,self.data['Company']['A'],self.data['Warehouse']['LORRY']):
            target._denied=True
            with self.subTest(target=target.name),self.assertRaises(PermissionError):self.sync_lorry()
            target._denied=False
        self.data['Warehouse']['LORRY'].company='B'
        with self.assertRaises(ValueError):self.sync_lorry()
        self.assertIsNone(self.trip.vehicle_warehouse)

    def test_sync_never_guesses_from_current_dispatch_when_departure_is_missing_or_invalid(self):
        self.trip.vehicle_warehouse=None
        with self.assertRaisesRegex(ValueError,'Start the route'):self.sync_lorry()
        self.legacy_departure()
        for value in ('','[]','not JSON',json.dumps(dict(vehicle='LORRY',scope_hash='WRONG'))):
            self.trip.driver_route_snapshot_json=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'reconciliation'):self.sync_lorry()
        self.assertIsNone(self.trip.vehicle_warehouse)
    def test_unplanned_or_unassigned_trip_and_native_permissions_reject_departure(self):
        req=self.request('Start Route');self.trip.state='Draft'
        with self.assertRaisesRegex(ValueError,'planning or execution'):self.perform(req)
        self.trip.state='Planned';self.trip.driver='OTHER'
        with self.assertRaises(PermissionError):self.perform(req)
        self.trip.driver='EMP';self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.perform(req)
        self.assertFalse(self.events)
    def test_start_flags_and_dispatch_responsibility_are_native_gates(self):
        req=self.request('Start Route');self.operator.can_start=0
        with self.assertRaises(PermissionError):self.perform(req)
        self.operator.can_start=1;self.v.p1._operator_denied=True
        with self.assertRaises(PermissionError):self.perform(req)
        self.assertFalse(self.events)
    def test_partial_or_unsubmitted_loading_blocks_start(self):
        req=self.request('Start Route');self.data['Stock Entry']['SE1'].docstatus=0
        with self.assertRaisesRegex(ValueError,'completed lorry loading'):self.perform(req)
        self.data['Stock Entry']['SE1'].docstatus=1;self.trip.orders[0].planned_qty=5;req=self.request('Start Route')
        with self.assertRaisesRegex(ValueError,'completed lorry loading'):self.perform(req)
        self.assertFalse(self.events)
    def test_departure_reuses_actual_native_completed_manifest_gate(self):
        req=self.request('Start Route');manifest=self.data['CFG Kanban Movement Manifest']['MAN1']
        for field,value in [('state','Prepared'),('dispatch_plan','OTHER'),('source_warehouse','OTHER'),('destination_company','B')]:
            old=manifest[field];manifest[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'completed loading Manifest'):self.perform(req)
            manifest[field]=old
        self.assertFalse(self.events);self.assertEqual(self.trip.driver_route_state,'Not Started')

    def test_departure_uses_native_lorry_warehouse_eligibility(self):
        req=self.request('Start Route');vehicle=self.data['Warehouse']['LORRY'];vehicle.disabled=1
        with self.assertRaisesRegex(ValueError,'active Company-specific lorry'):self.perform(req)
        self.assertFalse(self.events)

    def test_every_delivery_stop_needs_preparation(self):
        self.trip.dispatch_plans.pop();req=self.request('Start Route')
        with self.assertRaisesRegex(ValueError,'Prepare every Delivery stop'):self.perform(req)
    def test_route_approval_and_exact_mappings_are_required(self):
        self.v.p1.route_approval_required=1;req=self.request('Start Route')
        with self.assertRaisesRegex(ValueError,'Supervisor must approve'):self.perform(req)
        sheet=self.v.sheet();sheet.revision=1
        for i,row in enumerate(sheet.stops):row.row_key='RK'+str(i)
        sheet.state='Draft'
        with self.assertRaisesRegex(ValueError,'must be approved'):self.perform(req)
        sheet.state='Approved';sheet.stops.append(office.Doc(dispatch_plan='OUTSIDE',customer_scan_point='SITE1'))
        with self.assertRaisesRegex(ValueError,'map exactly'):self.perform(req)
    def test_start_retry_uses_receipt_before_mutable_gates_and_cannot_duplicate(self):
        req=self.request('Start Route');first=self.perform(req);self.trip.driver='OTHER';self.trip.state='Closed';self.operator.can_start=0
        self.assertEqual(self.perform(req),first);self.assertEqual(len(self.events),1)
        self.assertEqual(self.trip.driver_route_revision,1)
    def test_token_details_are_immutable_and_void_fences_late_requests(self):
        req=self.request('Start Route');self.perform(req);changed={**req,'stop_key':'OTHER'}
        with self.assertRaises(self.ns['DriverActionConflict']):self.perform(changed)
        self.operator.update(kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
        req=self.request('Begin Delivery',customer_scan='QR1')
        r=self.ns['reconcile_driver_action'](**req,void_reason='Terminal never submitted')
        self.assertEqual(r['status'],'Voided')
        with self.assertRaises(self.ns['DriverActionConflict']):self.perform(req)
        self.assertFalse(self.calls)
    def test_missing_result_readback_does_not_void_or_mutate(self):
        req=self.request('Start Route');r=self.ns['reconcile_driver_action'](**req)
        self.assertEqual(r,dict(status='Not Recorded'));self.assertFalse(self.events)
        with self.assertRaises(ValueError):self.ns['reconcile_driver_action'](**req,void_reason='driver bypass')
        self.assertEqual(self.trip.driver_route_state,'Not Started')
    def test_supervisor_can_reconcile_original_actor_without_reusing_their_session(self):
        req=self.request('Start Route');recorded=self.perform(req)
        self.operator.update(employee='SUP',kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
        self.assertEqual(self.ns['reconcile_driver_action'](**req,request_actor='EMP'),recorded)
        self.operator.can_override=0
        with self.assertRaises(PermissionError):self.ns['reconcile_driver_action'](**req,request_actor='EMP')
    def test_revision_scope_payload_and_action_token_checks(self):
        req=self.request('Start Route')
        for changes in ({'expected_revision':9},{'scope_hash':'changed'},{'event_token':None},{'payload':{'qty':1}},{'action':'Post Stock'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.perform({**req,**changes})
        self.assertFalse(self.events)
    def test_same_lorry_cannot_depart_on_two_active_driver_trips(self):
        other=office.document(self.trip.as_dict());other.name='OTHER';other.driver_active_vehicle_key=canonical('driver-active-lorry','A','LORRY')
        self.data[office.TRIP][other.name]=other
        with self.assertRaisesRegex(ValueError,'already has an active'):self.start()
    def test_strict_stop_order_and_physical_site_scan_remain_required(self):
        self.start();req=self.request('Begin Delivery',customer_scan='QR1');req['stop_key']=self.v.keys[1];req['dispatch_plan']='PLAN2'
        with self.assertRaisesRegex(ValueError,'next stop'):self.perform(req)
        with self.assertRaisesRegex(ValueError,'Scan the assigned'):self.act('Begin Delivery')
        with self.assertRaisesRegex(ValueError,'does not match'):self.act('Begin Delivery',customer_scan='QR2')
        self.begin_stop();self.assertEqual(self.prepared.start_prepared_delivery.call_args.args[1],'QR1')
    def test_flexible_selection_can_use_saved_stop_only_when_policy_allows(self):
        self.trip.sequence_policy='Flexible'
        for plan in (self.v.p1,self.v.p2):plan.test_verification=self.sheets.SELECT
        self.start();req=self.request(n=1,customer_scan='QR1')
        self.act(n=2);self.assertEqual(self.calls[0],('begin','PLAN2','QR2'))
        req['expected_revision']=self.trip.driver_route_revision
        with self.assertRaisesRegex(ValueError,'current customer stop'):self.perform(req)
    def test_approved_sheet_visit_uses_existing_sheet_engine_and_approved_sequence(self):
        sheet=self.v.sheet();sheet.revision=2
        for i,row in enumerate(sheet.stops):row.row_key='ROW'+str(i)
        self.start();self.begin_stop(2)
        args=self.sheets.start_route_sheet_stop.call_args.args
        self.assertEqual((args[0],args[1],args[4]),('SHEET','ROW0','QR2'))
        self.assertFalse(self.prepared.start_prepared_delivery.called)
    def test_departure_snapshot_detects_later_route_revision_and_source_changes(self):
        sheet=self.v.sheet(order=(1,2));sheet.revision=1
        for i,row in enumerate(sheet.stops):row.row_key='ROW'+str(i)
        self.start();sheet.revision+=1
        with self.assertRaisesRegex(ValueError,'execution route changed'):self.begin_stop()
        self.assertFalse(self.calls)
    def test_native_confirm_then_dn_and_proof_are_the_only_delivery_writers(self):
        self.start();self.deliver_to_proof();self.assertEqual(self.context()['next_step'],'Submit Proof')
        self.assertFalse(self.trip.stops[0].driver_completed_on)
        self.assertEqual([row[0] for row in self.calls],['begin','confirm','note'])
        self.proof_submit();self.assertTrue(self.trip.stops[0].driver_completed_on)
        self.assertEqual(self.context()['next_step'],'Done');self.assertEqual(self.context(2)['next_step'],'Begin Delivery')
    def test_draft_policy_holds_stop_until_native_submission_and_required_proof(self):
        self.auto_submit=False;self.start();self.begin_stop();self.act();self.act(required_erp_inputs={'parent':{'project':'P'},'tables':{}})
        c=self.context();self.assertEqual(c['next_step'],'Await ERP');self.assertFalse(self.trip.stops[0].driver_completed_on)
        req=self.request('Complete Stop');req['dispatch_plan']=None
        with self.assertRaisesRegex(ValueError,'every Delivery Note'):self.perform(req)
        self.post('DEL-PLAN1');self.assertEqual(self.context()['next_step'],'Open Proof')
        self.act();self.proof_submit();self.assertTrue(self.trip.stops[0].driver_completed_on)
    def test_no_proof_policy_closes_only_from_submitted_native_feedback(self):
        self.proof_policy='No Proof Required';self.start();self.begin_stop();self.act();r=self.act(required_erp_inputs={'parent':{},'tables':{}})
        self.assertTrue(r['result']['stop_completed']);self.assertFalse(self.proof.get_or_create_delivery_proof.called)
    def test_legacy_delivery_completed_outside_driver_page_can_be_confirmed_without_reposting(self):
        self.proof_policy='No Proof Required';self.start();self.begin_stop();self.act();self.create_note('DEL-PLAN1','KEY','TOKEN','{}')
        self.assertEqual(self.context()['next_step'],'Complete Stop');r=self.act()
        self.assertTrue(r['result']['stop_completed']);self.assertEqual(len([r for r in self.calls if r[0]=='note']),1)
    def test_missing_or_failed_proof_does_not_complete_stop_or_create_driver_receipt(self):
        self.start();self.deliver_to_proof();before=len(self.events)
        req=self.request(proof_name='WRONG',disposition='Attended')
        with self.assertRaisesRegex(ValueError,'exact Delivery Session'):self.perform(req)
        self.proof.submit_delivery_proof.side_effect=ValueError('Recipient signature is required')
        with self.assertRaisesRegex(ValueError,'signature'):self.proof_submit()
        self.assertEqual(len(self.events),before);self.assertFalse(self.trip.stops[0].driver_completed_on)
    def test_duplicate_dn_proof_retry_returns_receipt_without_reposting(self):
        self.start();self.begin_stop();self.act();req=self.request(required_erp_inputs={'parent':{},'tables':{}})
        first=self.perform(req);self.assertEqual(self.perform(req),first)
        self.assertEqual(self.engine.create_customer_delivery_document.call_count,1)
        self.act();req=self.request(proof_name=self.context()['proof']['name'],disposition='Attended')
        first=self.perform(req);self.assertEqual(self.perform(req),first)
        self.assertEqual(self.proof.submit_delivery_proof.call_count,1)
    def test_complete_flag_and_session_ownership_apply_after_start(self):
        self.start();self.begin_stop();self.operator.can_complete=0
        with self.assertRaises(PermissionError):self.act('Confirm Allocations')
        self.operator.can_complete=1;self.data[views.SESSION]['DEL-PLAN1'].started_by_operator='OTHER'
        with self.assertRaises(PermissionError):self.act('Confirm Allocations')
    def test_last_completed_stop_releases_lorry_without_running_e5(self):
        self.proof_policy='No Proof Required';self.start()
        for n in (1,2):self.begin_stop(n);self.act(n=n);self.act(n=n,required_erp_inputs={'parent':{},'tables':{}})
        self.assertEqual(self.trip.driver_route_state,'Completed');self.assertIsNone(self.trip.driver_active_vehicle_key)
        self.assertTrue(self.trip.driver_route_completed_on);self.assertEqual(self.context()['next_step'],'Done')
        self.assertEqual(self.v.p1.state,'Loaded','Driver completion must not fabricate E5 reconciliation')
    def test_visit_only_stop_records_information_without_stock_dn_or_proof(self):
        self.trip.stops=self.trip.stops[:1];self.trip.stops[0].stop_purpose='Visit Only'
        self.trip.orders=[];self.trip.dispatch_plans=[];self.trip.vehicle_warehouse=None
        self.start();self.assertEqual(self.context()['next_step'],'Complete Stop');self.act(notes='Customer needs more stock next week')
        self.assertEqual(self.trip.driver_route_state,'Completed');self.assertEqual(self.trip.stops[0].driver_visit_notes,'Customer needs more stock next week')
        self.assertFalse(self.calls);self.assertEqual(self.v.read()['completed_stops'],1)
    def test_multi_order_stop_finishes_only_after_both_native_notes_and_proofs(self):
        stop=self.v.keys[0];self.trip.sequence_policy='Flexible';self.trip.stops=self.trip.stops[:1]
        self.trip.orders[1].stop_key=stop;self.trip.dispatch_plans[1].stop_key=stop
        self.v.p2.update(customer_site='SITE1',customer='C1')
        self.data['Sales Order']['SO2'].customer='C1'
        self.start();self.deliver_to_proof();self.proof_submit()
        self.assertFalse(self.trip.stops[0].driver_completed_on);self.assertEqual(self.context()['dispatch_plan'],'PLAN2')
        self.act(customer_scan='QR1');self.act();self.act(required_erp_inputs={'parent':{},'tables':{}});self.act();self.proof_submit()
        self.assertEqual(self.trip.driver_route_state,'Completed');self.assertEqual(len(self.data[views.NOTE]),2)
    def test_current_trip_row_is_locked_before_native_delivery_session(self):
        self.start();self.begin_stop();self.b.reads.clear();self.act()
        reads=[row for row in self.b.reads if row[2].get('for_update')]
        self.assertEqual(reads[0][0],office.TRIP)
        self.assertTrue(any(row[0]==views.SESSION for row in reads))
    def test_office_form_cannot_forge_execution_or_rewrite_started_visit_only_itinerary(self):
        self.trip.stops=self.trip.stops[:1];self.trip.stops[0].stop_purpose='Visit Only';self.trip.orders=[];self.trip.dispatch_plans=[]
        self.start();before=office.document(self.trip.as_dict());doc=office.document(before.as_dict())
        doc.driver_route_state='Completed';doc.driver_active_vehicle_key=None;doc.stops[0].driver_completed_on='FORGED'
        self.b.ns['_protect_driver_execution'](doc,before)
        self.assertEqual(doc.driver_route_state,'In Progress');self.assertIsNone(doc.stops[0].driver_completed_on)
        doc.stops[0].instructions='Changed'
        with self.assertRaisesRegex(ValueError,'retain their itinerary'):self.b.ns['_protect_driver_execution'](doc,before)
    def test_existing_office_closure_releases_incomplete_route_only_after_native_e5(self):
        self.start();before=office.document(self.trip.as_dict());doc=office.document(before.as_dict());doc._before=before
        doc.state='Closed';doc.closure_reason='Route ended and stock reconciled'
        with self.assertRaisesRegex(ValueError,'Settle or cancel'):self.b.ns['validate_trip'](doc)
        for plan in (self.v.p1,self.v.p2):plan.state='Reconciled'
        self.b.ns['validate_trip'](doc)
        self.assertEqual(doc.driver_route_state,'Closed Incomplete');self.assertIsNone(doc.driver_active_vehicle_key)
        self.assertFalse(any(row.driver_completed_on for row in doc.stops))
    def test_supervisor_recovery_control_uses_operator_flag_not_a_missing_public_field(self):
        self.operator.update(kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
        self.assertTrue(self.v.queue()['operator']['can_override'])

    def test_schema_adds_readonly_audit_and_unique_active_lorry_fields(self):
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.json').read_text())
        fields={row['fieldname']:row for row in schema['fields']}
        self.assertEqual(fields['driver_active_vehicle_key']['unique'],1)
        self.assertTrue(fields['driver_route_snapshot_json']['read_only'])
        self.assertIn('Closed Incomplete',fields['driver_route_state']['options'])

if __name__=='__main__':unittest.main()

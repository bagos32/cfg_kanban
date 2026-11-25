"""E5B3 orchestration with real builders/validators and offline record/service doubles.

No native MariaDB transaction, ERP posting, QR device or live-site acceptance is implied.
"""
import copy
import datetime as dt
import hashlib
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests import test_trip_dispatch as generation
from cfg_kanban.tests.test_office_delivery_trip import Doc,document,TRIP,PLAN
from cfg_kanban.tests.test_vehicle_overview import load,Row,ROOT

CASE='CFG Kanban Return Case'
ALLOC='CFG Kanban Dispatch Allocation'

def canonical(*parts):return hashlib.sha256(json.dumps(parts,sort_keys=True,default=str).encode()).hexdigest()

class FollowOnFixture:
    def setUp(self):
        self.g=generation.TestTripDispatch();self.g.setUp();self.addCleanup(self.g.doCleanups)
        self.b=self.g.b;self.data=self.g.data;self.g.generated_draft();self.g.customer.tag_policy=self.g.open.tag_policy='Mixed'
        source=self.g.trip
        source.update(driver='DRIVER',driver_route_state='In Progress',driver_route_started_on='2026-11-24 10:00:00',auto_generate_dispatch=0)
        source.orders[0].name='ORIGINAL-ROW';self.source=source
        for plan in self.g.plans():plan.update(state='Reconciled',dispatch_review_state='Settled')
        for name in ('DRIVER','RELIEF','HELPER'):self.b.add('Employee',name,status='Active',employee_name=name.title())
        self.op=Doc(employee='SUP',employee_name='Supervisor',kanban_role='Supervisor',can_start=1,can_complete=1,can_override=1,view_all_responsibilities=1)
        self.session=Doc(name='SESSION',terminal_user=self.b.frappe.session.user)
        self.events=[];self.reserve_calls=[];self.quantity_events=[];self.checkpoints={};self.transaction_calls=[]
        f=self.b.frappe;f.db.savepoint=self.savepoint;f.db.rollback=self.rollback;f.PermissionError=PermissionError;f._dict=Doc;f.throw=lambda message,kind=ValueError:(_ for _ in ()).throw(kind(message))
        def get_list(doctype,filters=None,pluck=None,fields=None,or_filters=None,**kw):
            rows=[r for r in self.data.get(doctype,{}).values() if self.b.matches(r,filters) and not r.get('_hidden') and (not or_filters or any(r.get(k)==v for k,v in or_filters.items()))]
            rows=sorted(rows,key=lambda r:r.name)
            start=kw.get('limit_start',0);length=kw.get('limit_page_length',0);rows=rows[start:start+length] if length else rows[start:]
            return [r.get(pluck) for r in rows] if pluck else [Doc({k:r.get(k) for k in fields}) for r in rows] if fields else rows
        f.get_list=f.get_all=get_list
        f.db.get_values=lambda dt,filters,fields,**kw:[Doc({k:r.get(k) for k in fields}) for r in sorted(self.data.get(dt,{}).values(),key=lambda r:r.name) if self.b.matches(r,filters)]
        f.db.exists=lambda dt,filters:any(self.b.matches(r,filters) if isinstance(filters,dict) else r.name==filters for r in self.data.get(dt,{}).values())
        f.db.get_value=self.g.value
        self.g.planning._assert_plan_authorized=lambda plan,operator:None if operator.view_all_responsibilities else f.throw('Responsibility required',PermissionError)
        self.g.planning._require_event_token=lambda value:None if value else f.throw('Stable event token required')
        self.g.planning._vehicle_warehouse_from_scan=lambda scan,company:self.data['Warehouse']['LORRY'] if scan=='LORRY-CARD' else f.throw('Scan the physical lorry')
        self.g.planning.resolve_logistics_scan=lambda value:{'identity_type':'Handling Unit','name':'HU'}
        self.g.planning.assert_erp_stock=Mock();self.g.planning._lock_erp_bin=Mock();self.g.planning._untagged_available=lambda *a,**kw:20
        self.g.planning.reserve_dispatch_tag=lambda p,l,s,q,e,t:self.reserve(p,l,q,'Tagged Stock',s)
        self.g.planning.reserve_dispatch_untagged=lambda p,l,q,b,e,t:self.reserve(p,l,q,'Untagged ERP Stock',batch=b)
        self.g.planning.post_quantity_event=lambda **kw:self.quantity_events.append(kw)
        self.g.planning.approve_dispatch_plan=lambda name,*args:self.data[PLAN][name].db_set('state','Approved')
        common=dict(frappe=f,json=json,math=math,cint=lambda n:int(n or 0),flt=lambda n:float(n or 0),getdate=lambda n:dt.date.fromisoformat(str(n)[:10]),today=lambda:'2026-11-25',now_datetime=lambda:dt.datetime(2026,11,25,10),record=self.record,canonical_key=canonical,require_operator=lambda token,*a:self.auth(token))
        self.ns=load('services/trip_continuation.py',dict(common));self.ns['_office']=lambda:self.g.office;self.ns['_planning']=lambda:self.g.planning
        self.carry=types.ModuleType('cfg_kanban.services.trip_carry_in');self.carry.__dict__.update(load('services/trip_carry_in.py',dict(common)));self.carry._planning=lambda:self.g.planning
        self.custody=types.ModuleType('cfg_kanban.services.return_custody');self.custody.__dict__.update(load('services/return_custody.py',dict(common)))
        self.continuation=types.ModuleType('cfg_kanban.services.trip_continuation');self.continuation.__dict__.update(self.ns)
        self.g.office.validate_trip.__globals__['frappe']=f
        self.handover=types.ModuleType('cfg_kanban.services.trip_handover');self.handover._supervisor=lambda op:op.kanban_role=='Supervisor' and op.can_override
        self.sheets=types.ModuleType('cfg_kanban.services.route_sheets');self.sheets.save_route_sheet=Mock(return_value={'sheet':{'state':'Completed'}});self.sheets._sheet_scope=lambda doc:'SCOPE'
        self.revisions=types.ModuleType('cfg_kanban.services.trip_stock_revision');self.revisions.__dict__.update(load('services/trip_stock_revision.py',dict(common)))
        self.team=types.ModuleType('cfg_kanban.services.trip_team');self.team.__dict__.update(load('services/trip_team.py',dict(common)))
        self.b.add('CFG Kanban Operator Profile','HELPER-PROFILE',employee='HELPER',active=1,responsibilities=[Doc(responsibility='Customer Delivery')])
        self.modules={m.__name__:m for m in (self.carry,self.custody,self.continuation,self.handover,self.sheets,self.team,self.revisions)}
        p=patch.dict(sys.modules,self.modules);p.start();self.addCleanup(p.stop)
        outer=self
        class TripDoc(Doc):
            def clean(doc):return document({k:v for k,v in dict(doc).items() if k not in ('_before','flags','_data','meta')})
            def is_new(doc):return not doc.name
            def insert(doc,**kw):
                outer.g.office.validate_trip(doc)
                doc.name='FOLLOW-'+str(len(outer.data[TRIP])+1)
                outer.identities(doc);outer.data[TRIP][doc.name]=doc;doc._before=doc.clean();return doc
            def save(doc,**kw):
                outer.g.office.validate_trip(doc)
                outer.identities(doc);outer.data[TRIP][doc.name]=doc;doc._before=doc.clean();return doc
        original=f.get_doc
        def get_doc(doctype,name=None,**kw):
            if isinstance(doctype,dict) and doctype['doctype']==TRIP:return TripDoc(document(doctype),flags=Doc())
            return original(doctype,name,**kw)
        f.get_doc=get_doc
        self.source=TripDoc(source.clean() if hasattr(source,'clean') and source.clean else {k:v for k,v in source.items() if k not in ('_before','flags')})
        self.source.flags=Doc();self.source._before=self.source.clean();self.data[TRIP][self.source.name]=self.source
        self.stock=Doc(kind='Tagged Stock',scan_value='TAG',handling_unit='HU',item_code='ITEM1',batch_no=None,stock_uom='Nos',available_qty=4,source_hash='PHYSICAL')
        self.ns['_stock_info']=lambda *a,**kw:dict(self.stock)
        self.b.add('CFG Kanban Handling Unit','HU',item_code='ITEM1',batch_no=None,current_qty=4,current_warehouse='LORRY',inventory_company='A',movement_state='Received')
    def savepoint(self,name):
        self.transaction_calls.append(('savepoint',name))
        self.checkpoints[name]=(copy.deepcopy(self.data),copy.deepcopy(self.events),copy.deepcopy(self.quantity_events))
    def rollback(self,save_point=None):
        self.transaction_calls.append(('rollback',save_point))
        data,events,quantity=self.checkpoints[save_point or next(iter(self.checkpoints))]
        self.data.clear();self.data.update(copy.deepcopy(data));self.events[:]=events;self.quantity_events[:]=quantity
        self.source=self.data[TRIP][self.source.name]
    def auth(self,token):
        if token!='TOKEN':raise ValueError('Operator session is not active')
        return self.op,self.session
    def identities(self,doc):
        for field in ('orders','stops','dispatch_plans'):
            for i,row in enumerate(doc.get(field) or []):row.name=row.name or doc.name+'-'+field+str(i)
    def record(self,event,**kw):
        self.events.append(dict(event=event,**kw))
        if kw.get('idempotency_key'):self.b.add('CFG Kanban Event',kw['idempotency_key'],idempotency_key=kw['idempotency_key'],operator=kw.get('operator'),user=kw.get('terminal_user'),payload_json=json.dumps(kw.get('payload') or {},default=str))
    def reserve(self,plan,line,qty,kind,scan=None,batch=None):
        self.reserve_calls.append((plan,line,qty,kind));p=self.data[PLAN][plan]
        row=self.b.add(ALLOC,'ALLOCATION-'+str(len(self.reserve_calls)),dispatch_plan=plan,dispatch_plan_line=line,
            source_company='A',source_warehouse='LORRY',reservation_key='KEY-'+str(len(self.reserve_calls)),allocation_kind=kind,allocated_qty=qty,handling_unit='HU' if scan else None,batch_no=batch,item_code='ITEM1',stock_uom='Nos',state='Reserved',movement_state_before_reservation='Received')
        p.reload=lambda:p
        for r in p.lines:r.db_set=lambda values,**kw:r.update(values)
        return row
    def context(self):return self.ns['get_follow_on_context'](self.source.name,'TOKEN','LORRY')
    def payload(self,**changes):
        p=dict(warehouse='LORRY',lorry_scan='LORRY-CARD',driver='RELIEF',assistants=['HELPER'],trip_date='2026-11-25',expected_return_date='2026-11-27',orders=[dict(source_row='ORIGINAL-ROW',qty=4)],visits=[],stock=[dict(source_row='ORIGINAL-ROW',kind='Tagged Stock',scan_value='TAG',item_code='ITEM1',batch_no=None,qty=4,source_hash='PHYSICAL')],returns=[],confirmed_returns=[],reason='Relief takeover',context_hash=self.context()['context_hash'])
        p.update(changes);return p
    def create(self,payload=None,token='EVENT'):return self.ns['create_follow_on_trip'](self.source.name,payload or self.payload(),token,'TOKEN')
    def case(self,**kw):
        fields=dict(selling_company='A',driver_trip=self.source.name,driver_stop_key=self.source.stops[0].stop_key,customer='C1',return_flow='Customer Return for QC',state='Awaiting QC Receipt',collected_on='2026-11-24 12:00:00',collection_vehicle_warehouse='LORRY',received_on=None,lines=[Doc(item_code='ITEM1',claimed_qty=2,stock_uom='Nos')]);fields.update(kw)
        return self.b.add(CASE,'RETURN',**fields)

class TestFollowOn(FollowOnFixture,unittest.TestCase):
    def test_same_lorry_creates_linked_trip_with_normal_existing_stock_allocations(self):
        result=self.create();child=self.data[TRIP][result['trip']];plan=self.data[PLAN][child.dispatch_plans[0].dispatch_plan]
        self.assertEqual(child.follow_on_of,self.source.name);self.assertEqual(self.source.follow_on_trip,child.name)
        self.assertEqual(self.source.state,'Closed');self.assertEqual(child.state,'Draft')
        self.assertEqual(child.driver,'RELIEF');self.assertEqual(child.assistant_drivers[0].employee,'HELPER')
        self.assertEqual(plan.state,'Loaded');self.assertEqual(plan.source_warehouse,'LORRY');self.assertEqual(plan.vehicle_warehouse,'LORRY')
        self.assertFalse(plan.movement_manifest);self.assertFalse(self.data.get('Stock Entry'));self.assertEqual(len(self.reserve_calls),1)
        self.assertEqual([e['event_type'] for e in self.quantity_events],['Unreserve']);self.carry.validate_loading(plan)
        child.flags=Doc();child.state='Planned';child.save();self.assertEqual(child.state,'Planned')
        with self.assertRaisesRegex(ValueError,'another warehouse withdrawal'):self.g.mod._specs(child)
    def test_returns_keep_original_case_collection_and_qc_then_block_new_trip_until_receipt(self):
        case=self.case();original=copy.deepcopy(case.as_dict());result=self.create(self.payload(returns=['RETURN'],confirmed_returns=['RETURN']))
        child=self.data[TRIP][result['trip']]
        for field in ('driver_trip','driver_stop_key','collection_vehicle_warehouse','state','collected_on','lines','received_on'):self.assertEqual(case.get(field),original.get(field))
        self.assertEqual(case.custody_trip,child.name);self.assertEqual(case.custody_vehicle_warehouse,'LORRY')
        self.assertEqual(json.loads(case.custody_handover_json)[0]['to_trip'],child.name)
        self.custody.assert_received(self.source)
        with self.assertRaisesRegex(ValueError,'await QC receipt'):self.custody.assert_received(child)
        case.received_on='2026-11-25 12:00:00';case.state='QC In Progress';self.custody.assert_received(child)
    def test_unknown_response_replays_before_mutable_stock_state_checks(self):
        p=self.payload();result=self.create(p);self.ns['_stock_info']=Mock(side_effect=AssertionError('Replay must precede mutable stock checks'))
        self.assertEqual(self.create(p),result);self.assertEqual(len(self.reserve_calls),1)
        p['reason']='CHANGED'
        with self.assertRaisesRegex(self.ns['FollowOnReplayError'],'different details'):self.create(p)
    def test_pending_context_and_readback_do_not_depend_on_current_template_or_stock(self):
        payload=self.payload();result=self.create(payload);self.b.template.active=0
        context=self.ns['get_follow_on_context'](self.source.name,'TOKEN',reconciliation_only=1)
        self.assertEqual(context['operator']['employee'],'SUP')
        self.assertEqual(self.ns['reconcile_follow_on'](self.source.name,payload,'EVENT','TOKEN'),result)

    def test_readback_resolves_existing_receipt_and_void_prevents_late_execution(self):
        p=self.payload();answer=self.ns['reconcile_follow_on'](self.source.name,p,'EVENT','TOKEN',void_reason='No record; correct quantities')
        self.assertTrue(answer['voided']);self.assertFalse(answer['recorded'])
        with self.assertRaisesRegex(self.ns['FollowOnReplayError'],'voided'):self.create(p)
        self.assertFalse(self.reserve_calls)
    def test_changed_source_hash_and_wrong_vehicle_scan_fail_before_insert(self):
        for delta in ({'context_hash':'STALE'},{'lorry_scan':'WRONG'}):
            with self.subTest(delta=delta),self.assertRaises(ValueError):self.create(self.payload(**delta))
        self.assertEqual(len(self.data[TRIP]),1);self.assertFalse(self.reserve_calls)
    def test_unsettled_source_plan_and_pending_delivery_block(self):
        plan=self.g.plans()[0];plan.state='Loaded'
        with self.assertRaisesRegex(ValueError,'Settle Plan'):self.create()
        plan.state='Reconciled';self.b.add('CFG Kanban Delivery Session','OPEN',dispatch_plan=plan.name,state='Delivered')
        with self.assertRaisesRegex(ValueError,'proof first'):self.create()
    def test_pending_returns_must_be_selected_and_physically_confirmed(self):
        self.case()
        for p in (self.payload(),self.payload(returns=['RETURN'],confirmed_returns=[])):
            with self.assertRaisesRegex(ValueError,'every unreceived|Scan/confirm'):self.create(p)
        self.assertEqual(len(self.data[TRIP]),1)
    def test_partial_delivery_and_other_trip_claims_reduce_exact_so_balance(self):
        self.b.fulfilled.append(Doc(trip=self.source.name,sales_order='SO1',sales_order_item='ROW1',delivery_note_item='DN-L',stock_qty=2))
        self.assertEqual(self.context()['lines'][0]['max_qty'],2)
        with self.assertRaisesRegex(ValueError,'still-required'):self.create(self.payload())
    def test_already_completed_refused_stops_are_explicit_candidates_never_automatically_selected(self):
        self.source.stops[0].driver_completed_on='2026-11-24 13:00:00'
        self.assertTrue(self.context()['lines'][0]['already_completed'])
        self.source.stops[0].cancellation_request='CANCEL-STOP';self.assertEqual(self.context()['lines'],[])
    def test_tag_is_whole_unique_and_changed_source_cannot_be_reused(self):
        for stock in ([dict(self.payload()['stock'][0],qty=2)],[dict(self.payload()['stock'][0],source_hash='STALE')],self.payload()['stock']*2):
            with self.subTest(stock=stock),self.assertRaises(ValueError):self.create(self.payload(stock=stock))
        self.assertFalse(self.reserve_calls)
    def test_payload_rejects_nonfinite_booleans_missing_dates_and_unknown_fields(self):
        cases=[{'trip_date':''},{'extra':'BAD'}]+[{'orders':[dict(source_row='ORIGINAL-ROW',qty=q)]} for q in (True,0,-2,float('nan'),float('inf'))]
        for delta in cases:
            with self.subTest(delta=delta),self.assertRaises(ValueError):self.ns['_payload'](self.payload(**delta))
    def test_native_permissions_and_operator_scope_precede_receipt_reads(self):
        self.b.roles=[]
        with self.assertRaises(PermissionError):self.context()
        self.b.roles=['Stock Manager'];self.op.can_override=0
        with self.assertRaisesRegex(PermissionError,'Supervisor'):self.context()
    def test_loading_receipt_detects_mutation_but_retains_historical_release(self):
        result=self.create();child=self.data[TRIP][result['trip']];plan=self.data[PLAN][child.dispatch_plans[0].dispatch_plan]
        allocation=next(iter(self.data[ALLOC].values()));allocation.state='Released';self.carry.validate_loading(plan)
        allocation.allocated_qty=3
        with self.assertRaisesRegex(ValueError,'immutable physical confirmation'):self.carry.validate_loading(plan)
    def test_return_only_takeover_creates_no_dispatch_or_stock_receipt(self):
        self.case();result=self.create(self.payload(orders=[],stock=[],returns=['RETURN'],confirmed_returns=['RETURN']))
        child=self.data[TRIP][result['trip']];self.assertEqual(child.stops,[]);self.assertEqual(child.dispatch_plans,[])
        self.assertTrue(json.loads(child.follow_on_snapshot_json)['return_only']);self.assertFalse(self.reserve_calls)
    def test_native_form_cannot_forge_or_move_confirmed_custody_vehicle(self):
        result=self.create();child=self.data[TRIP][result['trip']];child.flags=Doc();child.vehicle_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'retain their Trip snapshot'):child.save()

    def test_selected_visits_create_one_shared_pool_without_new_stock_draw(self):
        visit=self.source.stops[1].stop_key
        result=self.create(self.payload(orders=[],stock=[],visits=[visit]));child=self.data[TRIP][result['trip']]
        pool=self.data[PLAN][child.open_route_plan]
        self.assertEqual(pool.plan_type,'Open Route Stock');self.assertEqual(pool.state,'Ready for Fulfilment')
        self.assertTrue(pool.existing_lorry_stock_only);self.assertFalse(pool.lines);self.assertFalse(self.reserve_calls)
        self.assertEqual(len(self.data['CFG Kanban Route Stop']),2) # original visit and new linked visit
    def test_mixed_tagged_and_loose_stock_is_confirmed_without_transfer_entry(self):
        self.stock.update(kind='Untagged ERP Stock',scan_value='ITEM1',handling_unit=None,available_qty=20)
        row=dict(self.payload()['stock'][0],kind='Untagged ERP Stock',scan_value='ITEM1')
        result=self.create(self.payload(stock=[row]));child=self.data[TRIP][result['trip']]
        plan=self.data[PLAN][child.dispatch_plans[0].dispatch_plan];self.carry.validate_loading(plan)
        self.assertEqual(self.reserve_calls[0][-1],'Untagged ERP Stock');self.assertFalse(self.quantity_events)
    def test_replacement_lorry_receives_original_return_case_and_new_sources(self):
        self.b.add('Warehouse','RELIEF-LORRY',company='A',cfg_is_vehicle_warehouse=1,cfg_vehicle_reference='TRUCK2',disabled=0,is_group=0)
        self.g.planning._vehicle_warehouse_from_scan=lambda scan,company:self.data['Warehouse']['RELIEF-LORRY']
        self.case();context=self.ns['get_follow_on_context'](self.source.name,'TOKEN','RELIEF-LORRY')
        result=self.create(self.payload(warehouse='RELIEF-LORRY',lorry_scan='RELIEF-CARD',context_hash=context['context_hash'],returns=['RETURN'],confirmed_returns=['RETURN']))
        child=self.data[TRIP][result['trip']];case=self.data[CASE]['RETURN']
        self.assertEqual(child.vehicle_warehouse,'RELIEF-LORRY');self.assertEqual(case.collection_vehicle_warehouse,'LORRY')
        self.assertEqual(case.custody_vehicle_warehouse,'RELIEF-LORRY');self.assertFalse(self.data.get('Stock Entry'))
    def test_exact_case_and_custody_label_scan_require_current_owning_trip(self):
        self.case();self.b.add('CFG Kanban Return Custody Label','LABEL',return_case='RETURN')
        self.assertEqual(self.ns['resolve_follow_on_return'](self.source.name,'CFG:RETURN-CUSTODY:LABEL','TOKEN'),{'name':'RETURN'})
        self.data[CASE]['RETURN'].custody_trip='OTHER'
        with self.assertRaisesRegex(ValueError,'not pending custody'):self.ns['resolve_follow_on_return'](self.source.name,'RETURN','TOKEN')
    def test_stocked_open_route_pool_uses_the_same_immutable_loading_receipt(self):
        visit=self.source.stops[1].stop_key;row=dict(self.payload()['stock'][0],source_row='ROUTE')
        result=self.create(self.payload(orders=[],visits=[visit],stock=[row]));child=self.data[TRIP][result['trip']];pool=self.data[PLAN][child.open_route_plan]
        self.assertEqual(pool.state,'Loaded');self.assertFalse(pool.existing_lorry_stock_only);self.carry.validate_loading(pool)
        route=load('services/route_delivery.py',dict(frappe=self.b.frappe,flt=lambda n:float(n or 0)))
        route.update(_engine=lambda:Row(_vehicle_warehouse=self.g.planning._vehicle_warehouse),_route_sources=lambda p:[],_planning=lambda:self.g.planning)
        route['_validate_loaded_route'](pool)
    def test_new_stock_totals_use_native_erp_balance_gate_before_any_insert(self):
        self.g.planning.assert_erp_stock.side_effect=ValueError('Combined quantity exceeds ERP stock')
        with self.assertRaisesRegex(ValueError,'Combined quantity'):self.create()
        self.assertEqual(len(self.data[TRIP]),1);self.assertFalse(self.reserve_calls)
    def test_second_takeover_retains_middle_trip_incoming_return_history(self):
        case=self.case();result=self.create(self.payload(returns=['RETURN'],confirmed_returns=['RETURN']));child=self.data[TRIP][result['trip']]
        case.custody_trip='THIRD'
        self.assertEqual([row.name for row in self.custody.cases(child)],['RETURN'])
        self.assertEqual(self.custody.cases(child,history=False),[])

    def test_native_prepared_loading_gate_accepts_only_confirmed_carry_in(self):
        result=self.create();child=self.data[TRIP][result['trip']];plan=self.data[PLAN][child.dispatch_plans[0].dispatch_plan]
        gate=load('services/dispatch_fulfilment.py',dict(frappe=self.b.frappe))['validate_prepared_loading']
        self.assertEqual(gate(plan).name,child.name)
        plan.vehicle_warehouse='CHANGED'
        with self.assertRaisesRegex(ValueError,'provenance'):gate(plan)
    def test_return_history_retains_origin_and_current_owner_without_exposing_hidden_case(self):
        self.case();result=self.create(self.payload(returns=['RETURN'],confirmed_returns=['RETURN']));child=self.data[TRIP][result['trip']]
        self.assertEqual([c.name for c in self.custody.cases(child)],['RETURN'])
        self.assertEqual(self.custody.cases(self.source,history=False),[])
        self.data[CASE]['RETURN']._hidden=1
        self.assertEqual(self.custody.cases(child),[])
        with self.assertRaises(ValueError):self.custody.assert_received(child)

class TestPhysicalFollowOn(FollowOnFixture,unittest.TestCase):
    """Exercise physical preview guards separately from orchestration's stock doubles."""
    def physical(self):
        common=self.ns
        real=load('services/trip_continuation.py',dict(common))['_stock_info'];self.ns['_stock_info']=real
        p=self.g.planning;p.resolve_logistics_scan=lambda value:{'identity_type':'Handling Unit','name':'HU'} if value=='TAG' else None
        p._assert_not_in_open_manifest=Mock();p.assert_erp_stock=Mock()
        unit=self.data['CFG Kanban Handling Unit']['HU'];unit.update(handling_unit_id='TAG',tag_kind='Stock Tag',stock_uom='Nos',identity_state='Active',quality_state='Released',available_qty=4,reserved_qty=0)
        prepared=types.ModuleType('cfg_kanban.services.dispatch_fulfilment')
        prepared.assert_prepared_tag_scope=Mock();prepared.assert_delivery_tag_expiry=Mock();prepared._assert_untagged_batch_expiry=Mock()
        identity=types.ModuleType('cfg_kanban.services.logistics_stock_identity')
        identity.identity_snapshot=lambda u:dict(item_code=u.item_code,process_certificate_set=u.get('process_certificate_set'),expiry=u.get('expiry_date'),serials=u.get('serial_nos'))
        identity._line_identity=Mock()
        patcher=patch.dict(sys.modules,{prepared.__name__:prepared,identity.__name__:identity});patcher.start();self.addCleanup(patcher.stop)
        return unit,prepared,identity
    def preview(self,**kw):return self.ns['preview_follow_on_stock'](self.source.name,'LORRY','ORIGINAL-ROW','Tagged Stock','TOKEN',scan_value='TAG',**kw)
    def test_native_tag_validation_rejects_wrong_company_location_reserved_quality_or_uom(self):
        unit,prepared,identity=self.physical()
        for field,value in [('inventory_company','B'),('current_warehouse','SOURCE'),('reserved_qty',1),('quality_state','Quarantine'),('stock_uom','Kg')]:
            old=unit.get(field);unit[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.preview()
            unit[field]=old
        self.preview();prepared.assert_prepared_tag_scope.assert_called();prepared.assert_delivery_tag_expiry.assert_called();self.g.planning.assert_erp_stock.assert_called()
    def test_certificate_expiry_serial_snapshot_changes_require_new_physical_review(self):
        unit,prepared,identity=self.physical();first=self.preview()
        for field in ('process_certificate_set','expiry_date','serial_nos'):
            unit[field]='NEW-IDENTITY';self.assertNotEqual(first['source_hash'],self.preview()['source_hash']);unit[field]=None
        prepared.assert_delivery_tag_expiry.side_effect=ValueError('Expired tag')
        with self.assertRaisesRegex(ValueError,'Expired'):self.preview()
    def test_loose_serial_batch_and_certificate_ambiguity_cannot_skip_native_services(self):
        unit,prepared,identity=self.physical();item=self.data['Item']['ITEM1']
        args=(self.source.name,'LORRY','ORIGINAL-ROW','Untagged ERP Stock','TOKEN')
        item.has_serial_no=1
        with self.assertRaisesRegex(ValueError,'Serialized'):self.ns['preview_follow_on_stock'](*args,item_code='ITEM1')
        item.has_serial_no=0;identity._line_identity.side_effect=ValueError('Certified stock requires exact tag')
        with self.assertRaisesRegex(ValueError,'Certified'):self.ns['preview_follow_on_stock'](*args,item_code='ITEM1')

"""Actual Trip orchestration + existing Open Route allocation/DN/ledger offline; no native-site claims."""
import datetime,json,math,sys,types,unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests import test_route_delivery as native
from cfg_kanban.tests.test_vehicle_overview import load
from cfg_kanban.tests import test_dispatch_fulfilment as e4

TRIP='CFG Kanban Delivery Trip'
class TestTripSales(unittest.TestCase):
    def setUp(self):
        self.r=native.TestRouteDelivery();self.r.setUp();self.addCleanup(self.r.doCleanups)
        self.b=self.r.b;self.b.frappe.ValidationError=ValueError;self.b.frappe.UniqueValidationError=type('UniqueValidationError',(Exception,),{});self.data=self.b.data;self.operator=self.r.operator;self.operator.update(can_start=1,can_complete=1,can_override=0)
        for n,site in enumerate([self.b.site,self.r.other],1):
            self.r.add('SITE-QR' if n==1 else 'OTHER-SITE','SEED'+str(n))
        visits=list(self.data[native.STOP].values())
        self.b.add('Company','B');self.b.add('Item','ITEM',item_name='Product',stock_uom='Nos',is_stock_item=1)
        self.plan=self.r.plan;self.plan.update(office_delivery_trip='TRIP',office_source_hash='SPEC',existing_lorry_stock_only=0,
            profile_snapshot_hash='POLICY',profile_snapshot_json=json.dumps({'auto_submit_delivery_note':1,'customer_verification':'Allow Assigned Stop Selection'}))
        stops=[]
        for n,(visit,site) in enumerate(zip(visits,[self.b.site,self.r.other]),1):
            self.b.add('Customer',site.customer,customer_name=site.customer,disabled=0)
            self.b.add('Address',site.customer_address,links=[e4.Row(link_doctype='Customer',link_name=site.customer)])
            key='STOP000'+str(n);visit.update(office_delivery_trip='TRIP',office_stop_key=key)
            stops.append(e4.Record(stop_key=key,stop_purpose='Visit Only',customer_scan_point=site.name,
                customer=site.customer,customer_address=site.customer_address,site_name=site.site_name,driver_completed_on=None))
        self.trip=self.b.add(TRIP,'TRIP',company='B',state='Planned',driver=self.operator.employee,driver_route_state='Not Started',
            driver_route_revision=0,route_template='ROUTE',trip_date='2026-11-21',sequence_policy='Planned Order',
            vehicle_warehouse='LORRY1',source_warehouse='SOURCE',open_route_plan=self.plan.name,stops=stops,orders=[],dispatch_plans=[])
        p=patch.object(e4.Doc,'check_permission',lambda d,p:(_ for _ in ()).throw(PermissionError('Denied')) if d.get('_denied') else None,create=True);p.start();self.addCleanup(p.stop)
        self.b.frappe.get_list=self.b.frappe.get_all
        common=dict(frappe=self.b.frappe,math=math,json=json,cint=lambda x:int(x or 0),flt=lambda x:float(x or 0),canonical_key=self.b.bridge.canonical_key,
            now_datetime=lambda:datetime.datetime(2026,11,21,16),require_operator=self.auth,record=self.b.e3.events)
        self.office=types.ModuleType('cfg_kanban.services.delivery_trips');self.office.__dict__.update(common);load('services/delivery_trips.py',self.office.__dict__)
        self.gen=types.ModuleType('cfg_kanban.services.trip_dispatch');self.gen.__dict__.update(common);load('services/trip_dispatch.py',self.gen.__dict__)
        self.sales=types.ModuleType('cfg_kanban.services.trip_sales');self.sales.__dict__.update(common);load('services/trip_sales.py',self.sales.__dict__)
        self.act=types.ModuleType('cfg_kanban.services.driver_route_actions');self.act.__dict__.update(common);load('services/driver_route_actions.py',self.act.__dict__)
        documents=types.SimpleNamespace(**load('services/stop_documents.py',dict(common)))
        self.act._documents=lambda:documents
        self.sheets=types.ModuleType('cfg_kanban.services.route_sheets');self.sheets.__dict__.update(common);load('services/route_sheets.py',self.sheets.__dict__)
        self.views=types.ModuleType('cfg_kanban.services.driver_routes');self.views.__dict__.update(common);load('services/driver_routes.py',self.views.__dict__)
        self.actual_view=self.views.get_driver_trip;self.views._trip=self.owned_trip;self.views.get_driver_trip=self.view;self.views._delivery=lambda:self.b.engine
        self.act._views=lambda:self.views;self.act._planning=lambda:self.b.planning;self.act._delivery=lambda:self.b.engine
        self.act._prepared=lambda:self.b.bridge;self.act._sheets=lambda:self.sheets
        self.sales._office=lambda:self.office;self.sales._actions=lambda:self.act;self.sales._routes=lambda:self.r.route;self.sales._sheets=lambda:self.sheets
        self.gen._office=lambda:self.office;self.gen._planning=lambda:self.b.planning
        self.sheets._delivery=lambda:self.b.engine
        self.b.planning._vehicle_warehouse=lambda name,company=None:self.data['Warehouse'][name]
        self.proof=types.ModuleType('cfg_kanban.services.delivery_proof')
        modules={m.__name__:m for m in (self.office,self.gen,self.sales,self.act,self.sheets,self.views,self.proof)}
        p=patch.dict(sys.modules,modules);p.start();self.addCleanup(p.stop)
        previous_sql=self.r.sql
        def sql(query,values=None,**kwargs):
            if 'SELECT payload_json FROM `tabCFG Kanban Event`' in query:
                event=next((r for r in self.data.get('CFG Kanban Event',{}).values() if r.idempotency_key==values[0]),None)
                return [e4.Row(payload_json=json.dumps(event.payload,default=str))] if event else []
            return previous_sql(query,values,**kwargs)
        self.b.frappe.db.sql=sql
        self.b.engine.create_customer_delivery_document=self.post
        self.b.engine.get_customer_delivery_requirements=lambda *a:dict(fields=[])
        self.counter=0
    def auth(self,token,action=None,**kwargs):
        if token!='TOKEN':raise ValueError('Inactive operator')
        if action and not self.operator.get('can_'+action):raise PermissionError('Action flag')
        return self.operator,self.b.e3.session
    def owned_trip(self,name,operator):
        self.trip.check_permission('read')
        if name!=self.trip.name or self.trip.driver!=operator.employee:raise PermissionError('Other driver')
        return self.trip
    def view(self,name,token):
        return dict(sequence_source='Office plan',stops=[dict(stop_key=r.stop_key,purpose='Visit Only',items=[],sources=[]) for r in self.trip.stops])
    def request(self,action=None,n=1,operation=None,**payload):
        c=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[n-1].stop_key,operation)
        self.counter+=1
        return dict(trip_name='TRIP',action=action or c['next_step'],event_token='ACTION'+str(self.counter),operator_session_token='TOKEN',
            expected_revision=c['revision'],scope_hash=c['scope_hash'],stop_key=c['stop_key'],dispatch_plan=c['dispatch_plan'],payload=payload)
    def run_action(self,action=None,n=1,operation=None,**payload):return self.act.perform_driver_action(**self.request(action,n,operation,**payload))
    def start(self):return self.run_action('Start Route')
    def begin(self,n=1,**payload):return self.run_action(n=n,operation='Sell from Lorry',**payload)
    def delivery(self):return self.r.delivery()
    def post(self,name,event,token,inputs):
        delivery=self.data[e4.SESSION][name]
        note=self.b.gateway['build_customer_delivery_note'](delivery,self.b.engine._customer_delivery_payload(delivery))
        note.name='DN'+str(len(self.data.get('Delivery Note',{}))+1);note.docstatus=1
        self.data.setdefault('Delivery Note',{})[note.name]=note
        self.b.erp_balance-=sum(float(r.stock_qty) for r in note.items)
        self.b.feedback._on_customer_delivery_submit(note,delivery.name)
        return delivery.as_dict()
    def existing_only(self):
        self.plan.update(existing_lorry_stock_only=1,state='Approved',lines=[],movement_manifest=None,vehicle_warehouse=None)
        self.data[e4.ALLOC]={}
    def test_newly_identified_optional_sale_offers_goods_selection_in_the_same_session(self):
        self.start();self.begin(customer_scan='SITE-QR')
        session=self.delivery();self.assertEqual(session.state,'Customer Identified')
        before=(len(self.data[e4.SESSION]),len(self.b.posted))
        context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key,'Sell from Lorry')
        self.assertEqual(context['next_step'],'Select Route Stock')
        self.assertEqual(context['delivery_session'],session.name)
        self.assertEqual(context['selected_stock'],[])
        again=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key,'Sell from Lorry')
        self.assertEqual(again['delivery_session'],session.name)
        self.assertEqual((len(self.data[e4.SESSION]),len(self.b.posted)),before)

    def test_identified_session_resumes_through_selection_dn_and_feedback_once(self):
        self.start();self.begin(customer_scan='SITE-QR')
        session=self.delivery();self.assertEqual(session.state,'Customer Identified')
        self.assertEqual(self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)['next_step'],'Select Route Stock')
        self.r.allocate(2)
        context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)
        self.assertEqual(context['next_step'],'Select Route Stock')
        self.assertEqual(context['selected_stock'][0]['allocated_qty'],2)
        request=self.request('Confirm Allocations');self.act.perform_driver_action(**request);self.act.perform_driver_action(**request)
        request=self.request('Create Delivery Note');self.act.perform_driver_action(**request);self.act.perform_driver_action(**request)
        self.assertEqual(len(self.data[e4.SESSION]),1);self.assertEqual(len(self.data['Delivery Note']),1)
        self.assertEqual(self.r.unit.current_qty,3);self.assertEqual(self.r.unit.reserved_qty,0)
        self.assertTrue(self.trip.stops[0].driver_completed_on)

    def test_customer_product_check_in_open_sale_follows_selection_and_keeps_existing_posting_flow(self):
        from cfg_kanban.tests.test_delivery_product_scans import install
        service,events,container=install(self,self.b)
        self.b.site.require_delivery_product_scan=1
        self.start();self.begin(customer_scan='SITE-QR')
        key=self.trip.stops[0].stop_key
        self.assertEqual(self.act.driver_action_context('TRIP','TOKEN',key)['next_step'],'Select Route Stock')
        self.r.allocate(2)
        context=self.act.driver_action_context('TRIP','TOKEN',key)
        self.assertEqual(context['next_step'],'Verify Delivery Goods')
        before=len(self.b.posted)
        self.run_action('Verify Delivery Goods',scan_value=self.r.unit.handling_unit_id)
        self.assertEqual(len(self.b.posted),before)
        self.assertTrue(service.context(self.delivery())['ready'])
        self.assertEqual(self.act.driver_action_context('TRIP','TOKEN',key)['next_step'],'Select Route Stock')
        self.run_action('Confirm Allocations');self.run_action('Create Delivery Note')
        self.assertEqual(len(self.data['Delivery Note']),1)
        self.assertTrue(self.trip.stops[0].driver_completed_on)

    def test_identified_resume_retains_operator_scope(self):
        self.start();self.begin();self.operator.employee='ANOTHER'
        with self.assertRaises(PermissionError):
            self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)

    def test_genuine_exception_is_visible_without_resetting_stock_or_status(self):
        self.start();self.begin();session=self.delivery();session.state='Exception';session.exception='EXCEPTION-1'
        before=(len(self.b.posted),len(self.data[e4.SESSION]),self.r.unit.current_qty)
        context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)
        self.assertEqual(context['next_step'],'Blocked')
        self.assertEqual(context['session_state'],'Exception');self.assertEqual(context['exception'],'EXCEPTION-1')
        self.assertIn(session.name,context['message']);self.assertIn('Kanban Logistics',context['message'])
        self.assertEqual(session.state,'Exception');self.assertEqual((len(self.b.posted),len(self.data[e4.SESSION]),self.r.unit.current_qty),before)

    def test_draft_or_submitted_note_does_not_reopen_goods_selection(self):
        self.start();self.begin();session=self.delivery()
        for status in (0,1):
            name='DN-'+str(status);self.b.add('Delivery Note',name,docstatus=status,status='Draft' if status==0 else 'To Bill')
            session.state='Exception';session.delivery_note=name
            context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)
            self.assertEqual(context['next_step'],'Blocked');self.assertEqual(context['delivery_note'],name)
            self.assertEqual(context['delivery_note_status'],status)
            self.assertIn('Draft' if status==0 else 'submitted',context['message'])
            self.assertFalse(self.data.get(e4.DA))

    def test_frozen_pack_session_still_requires_its_native_allocation_state(self):
        self.start();self.begin();self.plan.has_loose_tags=1
        module=types.ModuleType('cfg_kanban.services.loose_tags');module.is_pack_delivery=lambda d:True
        with patch.dict(sys.modules,{module.__name__:module}):
            context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)
            self.assertEqual(context['next_step'],'Blocked')
            self.delivery().state='Allocating Stock'
            context=self.act.driver_action_context('TRIP','TOKEN',self.trip.stops[0].stop_key)
            self.assertEqual(context['next_step'],'Confirm Allocations')

    def test_shared_prepared_pool_sells_native_quantity_and_completes_only_that_visit(self):
        self.start();self.begin();self.r.allocate(2)
        self.run_action('Confirm Allocations');self.run_action('Create Delivery Note')
        self.assertEqual(self.r.unit.current_qty,3);self.assertEqual(self.r.unit.reserved_qty,0)
        self.assertTrue(self.trip.stops[0].driver_completed_on);self.assertFalse(self.trip.stops[1].driver_completed_on)
        self.assertEqual(self.trip.driver_route_state,'In Progress');self.assertEqual(len(self.data['Delivery Note']),1)
    def test_existing_lorry_pool_creates_no_loading_entry_and_can_sell_unassigned_tag(self):
        self.existing_only();entries=len(self.data.get('Stock Entry',{}));self.start()
        self.assertEqual(self.plan.state,'Ready for Fulfilment');self.assertFalse(self.plan.movement_manifest)
        self.begin();choice=self.r.context(scan='TAG1')['choices'][0];self.assertEqual(choice['source_kind'],'Unassigned Lorry Stock')
        self.r.allocate(2,source='unassigned');self.run_action('Confirm Allocations');self.run_action('Create Delivery Note')
        self.assertEqual(self.r.unit.current_qty,3);self.assertEqual(entries,len(self.data.get('Stock Entry',{})))
    def test_existing_pool_unassigned_untagged_uses_native_erp_stock_and_receipt(self):
        self.existing_only();self.start();self.begin()
        choices=self.r.context(item='ITEM')['choices'];self.assertEqual({r['source_key'] for r in choices},{'unassigned-tag:TAG','unassigned'})
        self.r.allocate(2,source='unassigned',scan=None,item='ITEM');self.run_action('Confirm Allocations');self.run_action('Create Delivery Note')
        note=next(iter(self.data['Delivery Note'].values()));self.assertEqual(note.items[0].stock_qty,2)
        self.assertEqual(self.r.unit.current_qty,5)
    def test_zero_sale_visit_closes_without_dn_and_releases_native_sequence(self):
        self.start();self.run_action('Complete Stop',notes='No order today')
        native=self.sales.visit(self.trip,self.trip.stops[0]);self.assertEqual(native.state,'Skipped')
        self.assertFalse(self.data.get('Delivery Note'));self.begin(n=2)
        self.assertEqual(self.delivery().customer,'CUSTOMER2')
    def test_strict_order_and_required_site_qr_apply_to_optional_sale(self):
        self.plan.profile_snapshot_json=json.dumps({'auto_submit_delivery_note':1,'customer_verification':'Require Customer Site QR'})
        self.start()
        with self.assertRaisesRegex(ValueError,'next stop'):self.begin(n=2)
        with self.assertRaisesRegex(ValueError,'Scan the assigned'):self.begin()
        with self.assertRaisesRegex(ValueError,'does not match'):self.begin(customer_scan='OTHER-SITE')
        self.begin(customer_scan='SITE-QR');self.assertEqual(self.delivery().customer,'CUSTOMER')
    def test_direct_logistics_visit_cannot_bypass_trip_start_or_strict_order(self):
        first=self.sales.visit(self.trip,self.trip.stops[0]);second=self.sales.visit(self.trip,self.trip.stops[1])
        with self.assertRaisesRegex(ValueError,'Start this exact'):self.r.route.start_route_stop(self.plan.name,'SITE-QR','DIRECT','TOKEN',first.name)
        self.start()
        with self.assertRaisesRegex(ValueError,'next stop'):self.r.route.start_route_stop(self.plan.name,'OTHER-SITE','DIRECT2','TOKEN',second.name)
        self.assertFalse(self.data.get(e4.SESSION))
    def test_known_stock_custody_hold_and_identity_gates_are_not_bypassed(self):
        self.existing_only();self.start();self.begin();self.r.unit.reserved_qty=5;self.r.unit.available_qty=0
        with self.assertRaises(ValueError):self.r.context(scan='TAG1')
        self.assertFalse(self.data.get(e4.DA));self.assertFalse(self.data.get('Delivery Note'))
    def test_pending_or_missing_load_and_unapproved_existing_pool_block_departure(self):
        self.plan.state='Approved'
        with self.assertRaisesRegex(ValueError,'Prepare'):self.start()
        self.existing_only();self.plan.state='Awaiting Approval'
        with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.trip.driver_route_state,'Not Started')
    def test_open_customer_proof_prevents_visit_completion(self):
        self.start();self.begin();self.r.allocate(2);delivery=self.delivery()
        delivery.state='Delivered';delivery.proof_policy='Required'
        request=self.request();request.update(action='Complete Stop',dispatch_plan=None,payload={})
        with self.assertRaisesRegex(ValueError,'every Delivery Note'):self.act.perform_driver_action(**request)
        self.assertFalse(self.trip.stops[0].driver_completed_on)
    def test_duplicate_begin_and_stock_retry_preserve_one_session_and_reservation(self):
        self.start();request=self.request(operation='Sell from Lorry');first=self.act.perform_driver_action(**request);self.act.perform_driver_action(**request)
        self.assertEqual(len(self.data[e4.SESSION]),1);self.r.allocate(2,token='SAME');self.r.allocate(2,token='SAME')
        self.assertEqual(self.r.unit.reserved_qty,2);self.assertEqual(len(self.data[e4.DA]),1)
    def test_projection_exposes_optional_sale_and_exact_session_to_driver(self):
        self.start();targets={r.stop_key:{} for r in self.trip.stops};result=self.sales.projection(self.trip,targets,self.operator)
        self.assertEqual(result['name'],self.plan.name);self.assertTrue(targets['STOP0001']['can_open_sale'])
        self.begin();self.sales.projection(self.trip,targets,self.operator)
        self.assertEqual(targets['STOP0001']['open_sale']['delivery_session'],self.delivery().name)
    def test_completed_first_stop_leaves_no_sale_second_stop_and_final_e5_separate(self):
        self.start();self.run_action('Complete Stop');self.run_action('Complete Stop',n=2)
        self.assertEqual(self.trip.driver_route_state,'Completed');self.assertEqual(self.plan.state,'Loaded')
        self.assertFalse(self.data.get('Stock Entry',{}).get('NEW'));self.assertFalse(self.data.get('Delivery Note'))


    def test_actual_driver_projection_lists_shared_stock_and_delivered_tags(self):
        self.start();self.begin();self.r.allocate(2)
        result=self.actual_view('TRIP','TOKEN')
        first=result['stops'][0]
        self.assertEqual(first['open_sale']['allocations'][0]['visible_code'],'TAG1')
        self.assertEqual(first['open_sale']['allocations'][0]['allocated_qty'],2)
        self.assertEqual(result['next_stop_key'],'STOP0001')
        self.run_action('Confirm Allocations');self.run_action('Create Delivery Note')
        result=self.actual_view('TRIP','TOKEN')
        self.assertEqual(result['stops'][0]['open_sale']['allocations'][0]['delivered_qty'],2)
        self.assertEqual(result['next_stop_key'],'STOP0002')
    def test_native_delivery_lock_precedes_session_lock_for_shared_trip(self):
        self.start();self.begin();events=[];get_doc=self.b.frappe.get_doc;root=self.act._root
        def current(dt,name=None,**kwargs):
            if kwargs.get('for_update'):events.append(dt)
            return get_doc(dt,name,**kwargs)
        def trip_root(name):events.append('Trip Root');return root(name)
        self.b.frappe.get_doc=current;self.act._root=trip_root
        self.b.engine._delivery_for_operator(self.delivery().name,self.operator)
        self.assertLess(events.index('Trip Root'),events.index('CFG Kanban Delivery Session'))

if __name__=='__main__':unittest.main()

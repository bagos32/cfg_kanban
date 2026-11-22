"""Actual Trip decisions, receipts and native order gates offline; site acceptance is separate."""
import datetime,json,sys,types,unittest
from unittest.mock import patch
from cfg_kanban.tests import test_driver_route_actions as fixture
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests import test_trip_sales as shared
from cfg_kanban.tests.test_vehicle_overview import Row,load
REQUEST='CFG Kanban Route Change Request';TRIP=office.TRIP

def install(case,frappe,act,views,record):
    mod=types.ModuleType('cfg_kanban.services.trip_sequence')
    mod.__dict__.update(frappe=frappe,json=json,cint=lambda x:int(x or 0),now_datetime=lambda:datetime.datetime(2026,11,22,12),canonical_key=fixture.canonical,record=record)
    load('services/trip_sequence.py',mod.__dict__);mod._actions=lambda:act;mod._views=lambda:views
    p=patch.dict(sys.modules,{mod.__name__:mod});p.start();case.addCleanup(p.stop)
    old=frappe.get_doc
    def get_doc(dt,name=None,**kw):
        if isinstance(dt,dict) and dt.get('doctype')==REQUEST:
            doc=office.Doc(dt);doc._data=case.data;doc.flags=Row();return doc
        return old(dt,**kw) if isinstance(dt,dict) else old(dt,name,**kw)
    frappe.get_doc=get_doc
    return mod

class TestTripSequence(unittest.TestCase):
    def setUp(self):
        self.a=fixture.TestDriverRouteActions();self.a.setUp();self.addCleanup(self.a.doCleanups)
        self.trip=self.a.trip;self.data=self.a.data;self.op=self.a.operator;self.b=self.a.b;self.trip.route_sequence_revision=0
        self.trip.stops.append(office.Doc(stop_key='THIRD',customer='C1',customer_scan_point='SITE1',customer_address='A1',site_name='Third Visit',stop_purpose='Visit Only',delivery_sequence=3))
        for plan in (self.a.v.p1,self.a.v.p2):plan.allow_supervisor_override=1
        self.keys=[s.stop_key for s in self.trip.stops];self.n=0
        self.seq=install(self,self.b.frappe,Row(**self.a.ns),Row(**self.a.v.ns),self.a.record)
    def context(self,operation='Change Route Order',name=None):return self.a.ns['driver_action_context'](self.trip.name,'TOKEN',operation=operation,outcome_name=name)
    def request(self,action,payload,c=None):
        c=c or self.context();self.n+=1
        return dict(trip_name=self.trip.name,action=action,event_token='SEQ'+str(self.n),operator_session_token='TOKEN',expected_revision=c['revision'],scope_hash=c['scope_hash'],payload=payload)
    def execute(self,action,payload,c=None):return self.a.perform(self.request(action,payload,c))
    def start(self,flexible=False):
        if flexible:self.trip.sequence_policy='Flexible Order'
        self.a.start()
    def submit(self):
        self.execute('Request Route Change',dict(order=list(reversed(self.keys)),reason='Customer closes early'))
        return self.data[REQUEST][self.trip.route_change_request]
    def supervisor(self):self.op.update(employee='SUP',kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
    def decide(self,row,mode='Next Customer Only',decision='Approve'):
        return self.execute('Decide Route Change',dict(request_name=row.name,decision=decision,approval_mode=mode,reason='Reviewed customer availability'),self.context('Review Route Change',row.name))
    def test_flexible_order_changes_display_without_mutating_office_source_or_stock(self):
        self.start(True);before=self.a.ns['_core'](self.trip);saved=self.trip.driver_route_snapshot_json
        self.execute('Change Route Order',dict(order=list(reversed(self.keys))))
        view=self.a.v.read();self.assertEqual([r['stop_key'] for r in view['stops']],list(reversed(self.keys)))
        self.assertEqual(view['source_stop_order'],self.keys);self.assertEqual(view['next_stop_key'],self.keys[2])
        self.assertEqual(self.a.ns['_core'](self.trip),before);self.assertEqual(self.trip.driver_route_snapshot_json,saved)
        self.assertEqual(self.a.calls,[]);self.assertFalse(self.data.get(fixture.views.NOTE))
        self.assertEqual(fixture.canonical('snapshot',self.a.ns['_execution'](self.trip,self.op,view)),fixture.canonical('snapshot',json.loads(saved)))
    def test_next_customer_only_then_resumes_remaining_prior_order(self):
        self.start();row=self.submit();self.supervisor();self.decide(row)
        self.assertEqual(self.seq.pending(self.trip),[self.keys[2],self.keys[0],self.keys[1]])
        self.a.ns['_finish'](self.trip,self.trip.stops[2],self.op,'TOKEN','Visited')
        self.assertEqual(self.seq.pending(self.trip),self.keys[:2]);self.assertEqual(row.approval_mode,self.seq.NEXT)
    def test_full_order_and_both_approval_modes(self):
        self.start();row=self.submit();self.supervisor();c=self.context('Review Route Change',row.name)
        self.assertEqual(c['setup']['modes'],[self.seq.NEXT,self.seq.FULL]);self.assertTrue(c['setup']['approvable'])
        self.decide(row,self.seq.FULL);self.assertEqual(self.seq.pending(self.trip),list(reversed(self.keys)))
        self.assertEqual(row.state,'Approved');self.assertIsNone(row.pending_trip_key);self.assertEqual(row.decided_by,'SUP')
    def test_pending_request_does_not_authorize_out_of_order_visit(self):
        self.start();row=self.submit();self.assertEqual(row.state,'Pending');self.assertEqual(self.seq.order(self.trip),self.keys)
        with self.assertRaisesRegex(ValueError,'next stop'):self.a.ns['_target'](self.trip,dict(stop_key=self.keys[2]),json.loads(self.trip.driver_route_snapshot_json))
    def test_enforced_trip_rejects_direct_resequence(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'enforces'):self.execute('Change Route Order',dict(order=list(reversed(self.keys))))
        self.assertFalse(self.trip.driver_stop_order_json)
    def test_native_plan_policy_alone_enforces_visit_only_and_order_edit(self):
        self.trip.sequence_policy='Flexible Order';self.a.v.p1.stop_sequence_policy='Planned Order';self.start()
        self.assertTrue(self.context()['setup']['enforced'])
        with self.assertRaisesRegex(ValueError,'next stop'):self.a.ns['_target'](self.trip,dict(stop_key=self.keys[2]),json.loads(self.trip.driver_route_snapshot_json))
    def test_completed_positions_fixed_and_every_unfinished_stop_required_once(self):
        self.start(True);self.trip.stops[1].driver_completed_on='2026-11-22 09:00:00'
        for invalid in ([self.keys[2]],[self.keys[2],self.keys[2]],list(reversed(self.keys))):
            with self.assertRaisesRegex(ValueError,'every unfinished'):self.execute('Change Route Order',dict(order=invalid))
        self.execute('Change Route Order',dict(order=[self.keys[2],self.keys[0]]));self.assertEqual(self.seq.order(self.trip),[self.keys[2],self.keys[1],self.keys[0]])
    def test_current_stop_and_unfinished_native_proof_block_edits(self):
        self.start(True);self.trip.driver_active_stop_key=self.keys[0]
        with self.assertRaisesRegex(ValueError,'proof'):self.context()
        self.trip.driver_active_stop_key=None;self.b.add(fixture.views.SESSION,'ACTIVE',dispatch_plan='PLAN1',state='Delivered')
        with self.assertRaisesRegex(ValueError,'every active'):self.context()
    def test_changed_loading_source_blocks_actions(self):
        self.start(True);self.data['Stock Entry']['SE1'].docstatus=0
        with self.assertRaisesRegex(ValueError,'completed lorry loading'):self.context()
    def test_wrong_company_unassigned_driver_and_missing_start_flag_denied(self):
        self.start(True);c=self.context();self.op.employee='OTHER'
        with self.assertRaises(PermissionError):self.execute('Change Route Order',dict(order=list(reversed(self.keys))),c)
        self.op.employee='EMP';self.op.can_start=0
        with self.assertRaises(PermissionError):self.execute('Change Route Order',dict(order=list(reversed(self.keys))),c)
        self.op.can_start=1;self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.context()
    def test_assistant_can_request_but_cannot_approve(self):
        self.start();self.trip.assistant_drivers=[Row(employee='HELP')];self.op.employee='HELP';row=self.submit();self.assertEqual(row.requested_by,'HELP')
        with self.assertRaises(PermissionError):self.context('Review Route Change',row.name)
    def test_supervisor_role_view_all_override_and_complete_all_required(self):
        self.start();row=self.submit();self.supervisor()
        for field,value in [('can_override',0),('view_all_responsibilities',0),('can_complete',0),('kanban_role','Operator')]:
            old=self.op[field];self.op[field]=value
            with self.assertRaises(PermissionError):self.context('Review Route Change',row.name)
            self.op[field]=old
    def test_full_scope_requires_every_affected_plan_override_permission(self):
        self.start();row=self.submit();self.supervisor();self.a.v.p2.allow_supervisor_override=0
        with self.assertRaisesRegex(ValueError,'Profile'):self.decide(row,self.seq.FULL)
        self.assertEqual(row.state,'Pending');self.decide(row,self.seq.NEXT)
    def test_request_target_requires_captured_override_policy(self):
        self.start();self.a.v.p2.allow_supervisor_override=0
        with self.assertRaisesRegex(ValueError,'Profile'):self.execute('Request Route Change',dict(order=[self.keys[1],self.keys[0],self.keys[2]],reason='Traffic'))
        self.assertFalse(self.data.get(REQUEST))
    def test_stale_request_cannot_be_approved_but_can_be_rejected(self):
        self.start();row=self.submit();self.trip.stops[0].driver_completed_on='2026-11-22 09:00:00';self.supervisor()
        self.assertFalse(self.context('Review Route Change',row.name)['setup']['approvable'])
        with self.assertRaisesRegex(ValueError,'progressed'):self.decide(row)
        self.decide(row,decision='Reject');self.assertEqual(row.state,'Rejected')
    def test_closed_trip_request_can_be_rejected_without_live_loading_projection(self):
        self.start();row=self.submit();self.trip.state='Closed';self.trip.driver_route_state='Closed Incomplete';self.data['Stock Entry']['SE1'].docstatus=2
        self.supervisor();self.decide(row,decision='Reject');self.assertEqual(row.state,'Rejected')
    def test_requester_or_lead_can_cancel_but_other_assistant_cannot(self):
        self.start();self.trip.assistant_drivers=[Row(employee='HELP'),Row(employee='OTHER')];self.op.employee='HELP';row=self.submit();self.op.employee='OTHER'
        with self.assertRaises(PermissionError):self.execute('Cancel Route Change',dict(request_name=row.name,reason='Cancel'))
        self.op.employee='EMP';self.execute('Cancel Route Change',dict(request_name=row.name,reason='Office called'))
        self.assertEqual(row.state,'Cancelled');self.assertEqual(self.seq.order(self.trip),self.keys)
    def test_duplicate_pending_cannot_replace_details_but_progressed_request_can_be_superseded(self):
        self.start();old=self.submit()
        with self.assertRaisesRegex(ValueError,'waiting'):self.submit()
        self.trip.stops[0].driver_completed_on='2026-11-22 09:00:00'
        self.execute('Request Route Change',dict(order=[self.keys[2],self.keys[1]],reason='Road closed'))
        self.assertEqual(old.state,'Superseded');self.assertIsNone(old.pending_trip_key);self.assertNotEqual(self.trip.route_change_request,old.name)
    def test_request_and_decision_replay_before_stale_revision_without_duplicate_change(self):
        self.start();req=self.request('Request Route Change',dict(order=list(reversed(self.keys)),reason='Traffic'));r=self.a.perform(req);self.a.perform(req)
        self.assertEqual(len(self.data[REQUEST]),1);self.supervisor();row=self.data[REQUEST][r['result']['route_change_request']]
        decision=self.request('Decide Route Change',dict(request_name=row.name,decision='Approve',approval_mode=self.seq.NEXT,reason='Checked'),self.context('Review Route Change',row.name))
        first=self.a.perform(decision);rev=self.trip.route_sequence_revision;self.assertEqual(self.a.perform(decision),first);self.assertEqual(self.trip.route_sequence_revision,rev)
        decision['payload']['approval_mode']=self.seq.FULL
        with self.assertRaises(self.a.ns['DriverActionConflict']):self.a.perform(decision)
    def test_reason_and_valid_approval_mode_required(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'reason'):self.execute('Request Route Change',dict(order=list(reversed(self.keys))))
        row=self.submit();self.supervisor()
        with self.assertRaisesRegex(ValueError,'Choose Next'):self.decide(row,'Other')
        self.assertEqual(row.state,'Pending')
    def test_exact_native_customer_and_current_runtime_target_gate(self):
        self.start();self.seq._trip_name=lambda p:self.trip.name;row=self.submit();self.supervisor();self.decide(row,self.seq.FULL)
        with self.assertRaisesRegex(ValueError,'next stop'):self.seq.native_target(self.a.v.p1,'SITE1',operator=self.op)
        self.trip.stops[2].driver_completed_on='2026-11-22 10:00:00';self.assertTrue(self.seq.native_order_permitted(self.a.v.p2,'SITE2'))
        self.a.v.p2.allow_supervisor_override=0;self.assertFalse(self.seq.native_order_permitted(self.a.v.p2,'SITE2'))
        with self.assertRaisesRegex(ValueError,'exact runtime'):self.seq.native_target(self.a.v.p2,'SITE1',operator=self.op)
    def test_native_entry_rejects_other_driver_and_completed_stop(self):
        self.start(True);self.seq._trip_name=lambda p:self.trip.name;self.execute('Change Route Order',dict(order=list(reversed(self.keys))));self.op.employee='OTHER'
        with self.assertRaises(PermissionError):self.seq.native_target(self.a.v.p1,'SITE1',operator=self.op)
        self.op.employee='EMP';self.trip.stops[0].driver_completed_on='2026-11-22 09:00:00'
        with self.assertRaisesRegex(ValueError,'already completed'):self.seq.native_target(self.a.v.p1,'SITE1',operator=self.op)
    def test_form_save_restores_protected_runtime_fields(self):
        self.start(True);self.execute('Change Route Order',dict(order=list(reversed(self.keys))))
        before=office.document(self.trip.as_dict());changed=office.document(before.as_dict());changed.update(driver_stop_order_json='[]',route_sequence_revision=99,route_order_source='Injected',route_change_request='OTHER')
        self.b.ns['_protect_driver_execution'](changed,before)
        for name in ('driver_stop_order_json','route_sequence_revision','route_order_source','route_change_request'):self.assertEqual(changed.get(name),before.get(name))
    def test_supervisor_queue_respects_native_company_and_trip_permissions(self):
        self.start();self.submit();self.b.frappe.has_permission=lambda *a:True;self.b.frappe.get_list=self.a.v.get_all;self.assertEqual(len(self.seq.supervisor_requests()),1)
        self.data['Company']['A']._denied=True;self.assertEqual(self.seq.supervisor_requests(),[])
    def test_request_form_rejects_uncontrolled_writes_and_deletion(self):
        ns=load('cfg_kanban/doctype/cfg_kanban_route_change_request/cfg_kanban_route_change_request.py',dict(frappe=self.b.frappe,Document=object));doc=ns['CFGKanbanRouteChangeRequest']();doc.flags=Row()
        with self.assertRaisesRegex(ValueError,'controlled'):doc.validate()
        doc.flags.cfg_trip_route_change=True;doc.validate()
        with self.assertRaisesRegex(ValueError,'history'):doc.on_trash()

    def install_sheet(self):
        sheet=self.a.v.sheet(order=(1,2));sheet.update(revision=1,scope='Combined Lorry Trip',active_scope_key='V:LORRY')
        for n,row in enumerate(sheet.stops,1):row.update(name='SROW'+str(n),row_key='R'+str(n),state='Planned',customer='C'+str(n),customer_address='A'+str(n))
        for plan in (self.a.v.p1,self.a.v.p2):plan.update(office_delivery_trip=self.trip.name,route_sequence_scope='Combined Lorry Trip',customer_address='A'+str(1 if plan.name=='PLAN1' else 2))
        mod=types.ModuleType('cfg_kanban.services.route_sheets');mod.__dict__.update(frappe=self.b.frappe,json=json,cint=lambda x:int(x or 0),canonical_key=fixture.canonical,now_datetime=lambda:datetime.datetime(2026,11,22,12),require_operator=self.a.auth,record=self.a.record)
        load('services/route_sheets.py',mod.__dict__)
        old_value=self.b.frappe.db.get_value
        def value(dt,name,fields,**kw):
            if isinstance(name,dict):
                row=next((r for r in self.data.get(dt,{}).values() if self.b.matches(r,name)),None)
                return Row({k:row.get(k) for k in fields}) if row and isinstance(fields,list) else row.get(fields) if row else None
            return old_value(dt,name,fields,**kw)
        self.b.frappe.db.get_value=value
        mod._plans=lambda:Row(_assert_plan_authorized=self.a.authorized,_require_event_token=lambda v:None)
        self.a.engine._customer_delivery_allowed=lambda op:True
        mod._delivery=lambda:self.a.engine;mod._fulfilment=lambda:self.a.prepared
        self.a.ns['_sheets']=lambda:mod
        patcher=patch.dict(sys.modules,{mod.__name__:mod});patcher.start();self.addCleanup(patcher.stop)
        return sheet,mod
    def test_known_customer_sheet_gate_accepts_only_current_supervisor_approved_target(self):
        sheet,mod=self.install_sheet();self.start()
        with self.assertRaisesRegex(ValueError,'next (customer|stop)'):mod.assert_visit_allowed(self.a.v.p2,'SITE2')
        self.execute('Request Route Change',dict(order=[self.keys[1],self.keys[2],self.keys[0]],reason='Traffic'));row=self.data[REQUEST][self.trip.route_change_request];self.supervisor();self.decide(row)
        self.assertEqual(mod.assert_visit_allowed(self.a.v.p2,'SITE2')[1].row_key,'R2')
        self.assertEqual([r.row_key for r in sheet.stops],['R1','R2']);self.assertEqual(sheet.revision,1)
        with self.assertRaisesRegex(ValueError,'next stop'):self.seq.native_target(self.a.v.p1,'SITE1',operator=self.op)
    def test_approval_does_not_bypass_required_site_qr_on_native_sheet_entry(self):
        sheet,mod=self.install_sheet();self.start();self.execute('Request Route Change',dict(order=[self.keys[1],self.keys[2],self.keys[0]],reason='Traffic'));row=self.data[REQUEST][self.trip.route_change_request];self.supervisor();self.decide(row)
        with self.assertRaisesRegex(ValueError,'Customer Site QR'):mod.start_route_sheet_stop(sheet.name,'R2','VISIT','TOKEN')
        with self.assertRaisesRegex(ValueError,'does not match'):mod.start_route_sheet_stop(sheet.name,'R2','VISIT','TOKEN','QR1')
        self.assertEqual(self.a.calls,[])
        result=mod.start_route_sheet_stop(sheet.name,'R2','VISIT','TOKEN','QR2');self.assertEqual(result['dispatch_plan'],'PLAN2');self.assertEqual(len(self.a.calls),1)
    def test_changed_sheet_revision_cannot_reuse_a_pending_approval(self):
        sheet,mod=self.install_sheet();self.start();self.execute('Request Route Change',dict(order=[self.keys[1],self.keys[2],self.keys[0]],reason='Traffic'));row=self.data[REQUEST][self.trip.route_change_request];self.supervisor();sheet.revision+=1
        with self.assertRaisesRegex(ValueError,'sources or approved route changed'):self.decide(row)
        self.assertEqual(row.state,'Pending')

class TestTripSequenceNativeOpen(unittest.TestCase):
    def setUp(self):
        self.s=shared.TestTripSales();self.s.setUp();self.addCleanup(self.s.doCleanups);self.trip=self.s.trip;self.data=self.s.data;self.op=self.s.operator;self.trip.route_sequence_revision=0
        self.s.views._all=lambda op:bool(op.kanban_role=='Supervisor' and op.view_all_responsibilities)
        self.s.views._trip=lambda name,op:self.s.act._root(name)
        self.seq=install(self,self.s.b.frappe,self.s.act,self.s.views,self.s.b.e3.events);self.s.plan.allow_supervisor_override=1
        self.s.views.get_driver_trip=self.s.actual_view;self.s.start()
    def approve(self,mode='Next Customer Only'):
        c=self.s.act.driver_action_context('TRIP','TOKEN',operation='Change Route Order')
        values=dict(trip_name='TRIP',action='Request Route Change',event_token='REQUEST',operator_session_token='TOKEN',expected_revision=c['revision'],scope_hash=c['scope_hash'],payload=dict(order=['STOP0002','STOP0001'],reason='Customer available'))
        self.s.act.perform_driver_action(**values);self.op.update(employee='SUP',kanban_role='Supervisor',view_all_responsibilities=1,can_override=1)
        c=self.s.act.driver_action_context('TRIP','TOKEN',operation='Review Route Change',outcome_name=self.trip.route_change_request)
        values.update(action='Decide Route Change',event_token='DECISION',expected_revision=c['revision'],payload=dict(request_name=self.trip.route_change_request,decision='Approve',approval_mode=mode,reason='Checked'))
        self.s.act.perform_driver_action(**values);self.op.update(employee=self.trip.driver,kanban_role='Operator',view_all_responsibilities=0,can_override=0)
    def test_approved_out_of_order_sale_uses_native_stock_dn_then_resumes_order(self):
        self.approve();self.s.begin(n=2);self.s.r.allocate(2);self.s.run_action('Confirm Allocations',n=2);self.s.run_action('Create Delivery Note',n=2)
        self.assertEqual(len(self.data['Delivery Note']),1);self.assertEqual(self.s.r.unit.current_qty,3);self.assertTrue(self.trip.stops[1].driver_completed_on);self.assertFalse(self.trip.stops[0].driver_completed_on)
        self.s.begin();self.assertEqual(self.s.delivery().customer,'CUSTOMER')
    def test_direct_native_open_api_cannot_bypass_unapproved_or_runtime_order(self):
        second=self.s.sales.visit(self.trip,self.trip.stops[1])
        with self.assertRaisesRegex(ValueError,'next stop'):self.s.r.route.start_route_stop(self.s.plan.name,'OTHER-SITE','EARLY','TOKEN',second.name)
        self.approve();first=self.s.sales.visit(self.trip,self.trip.stops[0])
        with self.assertRaisesRegex(ValueError,'next stop'):self.s.r.route.start_route_stop(self.s.plan.name,'SITE-QR','WRONG','TOKEN',first.name)
        self.assertFalse(self.data.get(shared.e4.SESSION))
    def test_trip_lock_precedes_native_plan_lock(self):
        self.approve();events=[];root=self.s.act._root;get_doc=self.s.b.frappe.get_doc
        def locked(name):events.append('ROOT');return root(name)
        def read(dt,name=None,**kw):
            if kw.get('for_update'):events.append(dt)
            return get_doc(dt,name,**kw)
        self.s.act._root=locked;self.s.b.frappe.get_doc=read;self.s.begin(n=2)
        self.assertLess(events.index('ROOT'),events.index('CFG Kanban Dispatch Plan'))

class TestTripSequenceNativePrepared(unittest.TestCase):
    def setUp(self):
        from cfg_kanban.tests import test_dispatch_fulfilment as native
        self.b=native.TestDispatchFulfilment();self.b.setUp();self.addCleanup(self.b.doCleanups);self.data=self.b.data;self.op=self.b.operator;self.plan=self.b.plan
        p=patch.object(native.Doc,'check_permission',lambda d,p:None,create=True);p.start();self.addCleanup(p.stop)
        self.b.add('Company','B')
        self.plan.update(office_delivery_trip='TRIP',allow_supervisor_override=1)
        self.trip=self.b.add(TRIP,'TRIP',company='B',state='Planned',driver=self.op.employee,driver_route_state='In Progress',route_sequence_revision=1,driver_stop_order_json=json.dumps(['DEL','INFO']),route_order_source='Supervisor approved next customer',stops=[native.Record(stop_key='INFO',customer_scan_point='SITE',stop_purpose='Visit Only'),native.Record(stop_key='DEL',customer_scan_point='SITE',stop_purpose='Delivery')],dispatch_plans=[native.Record(dispatch_plan=self.plan.name,stop_key='DEL')])
        self.saved=dict(scope_hash='SOURCE',stop_order=['INFO','DEL'],strict=True);self.trip.driver_route_snapshot_json=json.dumps(self.saved)
        self.b.frappe.ValidationError=ValueError
        self.act=types.ModuleType('cfg_kanban.services.driver_route_actions');self.act.__dict__.update(frappe=self.b.frappe,json=json);load('services/driver_route_actions.py',self.act.__dict__)
        self.views=Row(_all=lambda op:False,get_driver_trip=lambda *a:{})
        self.act._core=lambda doc:'SOURCE';self.act._views=lambda:self.views;self.act._delivery=lambda:self.b.engine;self.act._execution=lambda *a:self.saved
        self.seq=install(self,self.b.frappe,self.act,self.views,self.b.e3.events)
    def start(self,key='START'):return self.b.bridge.start_prepared_delivery(self.plan.name,'SITE-QR',key,'TOKEN')
    def test_native_prepared_delivery_accepts_exact_approved_stop_once(self):
        first=self.start();second=self.start();self.assertEqual(first['name'],second['name']);self.assertEqual(len(self.data[shared.e4.SESSION]),1);self.assertEqual(self.trip.driver_active_stop_key,'DEL')
        self.assertEqual(self.b.unit.reserved_qty,5)
    def test_native_prepared_start_cannot_skip_runtime_order(self):
        self.trip.driver_stop_order_json=json.dumps(['INFO','DEL'])
        with self.assertRaisesRegex(ValueError,'next stop'):self.start()
        self.assertFalse(self.data.get(shared.e4.SESSION));self.assertEqual(self.b.unit.reserved_qty,0)
    def test_pending_known_trip_cannot_bypass_original_order_before_any_approval(self):
        self.trip.driver_stop_order_json=None;self.trip.route_order_source=None
        with self.assertRaisesRegex(ValueError,'next stop'):self.start()
        self.assertFalse(self.data.get(shared.e4.SESSION))
    def test_linked_known_trip_requires_departure_before_native_delivery(self):
        self.trip.driver_route_state='Not Started';self.trip.driver_stop_order_json=None
        with self.assertRaisesRegex(ValueError,'Start this exact Delivery Trip'):self.start()
        self.assertFalse(self.data.get(shared.e4.SESSION))
    def test_native_prepared_start_rejects_changed_frozen_sources(self):
        self.act._execution=lambda *a:dict(self.saved,scope_hash='CHANGED')
        with self.assertRaisesRegex(ValueError,'Saved Trip sources'):self.start()
        self.assertFalse(self.data.get(shared.e4.SESSION));self.assertEqual(self.b.unit.reserved_qty,0)
    def test_prepared_replay_precedes_changed_runtime_order_and_source_checks(self):
        first=self.start();self.trip.driver_stop_order_json=json.dumps(['INFO','DEL']);self.act._execution=lambda *a:dict(self.saved,scope_hash='CHANGED')
        self.assertEqual(self.start()['name'],first['name']);self.assertEqual(len(self.data[shared.e4.SESSION]),1)

if __name__=='__main__':unittest.main()

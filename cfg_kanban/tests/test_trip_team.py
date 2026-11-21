"""Cooperative Trip scope through actual office, driver action and native access functions offline."""
import copy,datetime,json,math,sys,types,unittest
from unittest.mock import patch
from cfg_kanban.tests import test_driver_route_actions as actions
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests import test_dispatch_fulfilment as native
from cfg_kanban.tests import test_trip_sales as shared
from cfg_kanban.tests.test_vehicle_overview import Row,load

TRIP='CFG Kanban Delivery Trip';CHILD='CFG Kanban Trip Assistant';LINK='CFG Kanban Delivery Trip Plan'

class TestTripTeam(unittest.TestCase):
    def setUp(self):
        self.a=actions.TestDriverRouteActions();self.a.setUp();self.addCleanup(self.a.doCleanups)
        self.b=self.a.b;self.data=self.b.data;self.trip=self.a.trip;self.operator=self.a.operator;self.trip.flags=Row();self.operator.responsibilities.append(Row(responsibility='Dispatch'))
        self.b.frappe.PermissionError=PermissionError;self.b.frappe.get_all=self.a.v.get_all
        self.team=self.install(self.b.frappe,self.a.record,self.trip,self.data)
        planning=types.ModuleType('cfg_kanban.services.dispatch_planning')
        planning.__dict__.update(load('services/dispatch_planning.py',dict(frappe=self.b.frappe)))
        p=patch.dict(sys.modules,{planning.__name__:planning});p.start();self.addCleanup(p.stop)
        self.a.engine._can_view_delivery=self.native_access(self.b.frappe)
        for n,plan in enumerate((self.a.v.p1,self.a.v.p2),1):
            plan.dispatch_responsibility='Dispatch';plan.customer_address=self.trip.stops[n-1].customer_address
            self.b.add(LINK,'LINK'+str(n),parent=self.trip.name,parenttype=TRIP,parentfield='dispatch_plans',dispatch_plan=plan.name)
        self.employee('HELP1');self.employee('HELP2')
        original=self.a.prepared.start_prepared_delivery.side_effect
        def begin(*args):
            result=original(*args);doc=self.data[actions.views.SESSION][result['name']]
            doc.customer_address=self.data[office.PLAN][doc.dispatch_plan].customer_address
            doc.source_warehouse='LORRY';return doc.as_dict()
        self.a.prepared.start_prepared_delivery.side_effect=begin
    def install(self,frappe,record,trip,data):
        module=types.ModuleType('cfg_kanban.services.trip_team')
        def audit(kind,**kw):
            kw.setdefault('idempotency_key','AUDIT-'+str(len(data))+str(len(getattr(self.a,'events',{}))))
            return record(kind,**kw)
        module.__dict__.update(frappe=frappe,cint=lambda v:int(v or 0),record=audit,now_datetime=lambda:datetime.datetime(2026,11,21,18))
        load('services/trip_team.py',module.__dict__)
        p=patch.dict(sys.modules,{module.__name__:module});p.start();self.addCleanup(p.stop)
        class Child(office.Doc):
            def insert(row,**kwargs):
                row.name='ASST'+str(len(data.setdefault(CHILD,{}))+1);data[CHILD][row.name]=row;return row
        def append(doc,field,value):
            row=Child(doctype=CHILD,parent=doc.name,parenttype=TRIP,parentfield=field,idx=len(doc.get(field) or [])+1,**value)
            doc.setdefault(field,[]).append(row);return row
        p=patch.object(type(trip),'append',append,create=True);p.start();self.addCleanup(p.stop)
        old_value=frappe.db.get_value
        def value(dt,name,field,**kwargs):
            if isinstance(name,dict):
                row=next((r for r in data.get(dt,{}).values() if all(r.get(k)==v for k,v in name.items())),None)
                if not row:return None
                return Row({k:row.get(k) for k in field}) if isinstance(field,list) else row.get(field)
            return old_value(dt,name,field,**kwargs)
        frappe.db.get_value=value
        return module
    def native_access(self,frappe):
        ns=dict(frappe=frappe);native.extract('services/customer_delivery.py',ns,{'_can_view_delivery','_can_view_all'})
        return ns['_can_view_delivery']
    def employee(self,name):
        self.b.add('Employee',name,status='Active',employee_name='Name '+name)
        return self.b.add('CFG Kanban Operator Profile',name,employee=name,active=1,responsibilities=[Row(responsibility='Customer Delivery')])
    def add_request(self,employee='HELP1'):
        c=self.a.ns['driver_action_context'](self.trip.name,'TOKEN',operation='Add Assistant');self.a.counter+=1
        return dict(trip_name=self.trip.name,action='Add Assistant',event_token='TEAM'+str(self.a.counter),operator_session_token='TOKEN',
            expected_revision=c['revision'],scope_hash=c['scope_hash'],stop_key=None,dispatch_plan=None,payload={'employee':employee})
    def add(self,employee='HELP1'):return self.a.perform(self.add_request(employee))
    def office_rows(self,*names):self.trip.assistant_drivers=[office.Doc(employee=n) for n in names]
    def office_team(self,before=None):self.team.validate_office_team(self.trip,before)
    def test_office_presets_several_assistants_and_audits_actual_office_user(self):
        self.office_rows('HELP1','HELP2');self.office_team()
        self.assertEqual(self.trip.team_revision,1);self.assertEqual(len(self.trip.assistant_drivers),2)
        row=self.trip.assistant_drivers[0];self.assertEqual(row.assignment_source,'Office');self.assertIsNone(row.assigned_by)
        self.assertEqual(row.assigned_by_user,'planner@example.com')
        before=office.document(self.trip.as_dict());row.assigned_by='FORGED';row.assignment_source='Forged';self.office_team(before)
        self.assertEqual(row.assignment_source,'Office');self.assertIsNone(row.assigned_by);self.assertEqual(self.trip.team_revision,1)
    def test_native_office_validation_enforces_team_without_changing_route_scope(self):
        before=office.document(self.trip.as_dict());self.trip._before=before;scope=self.a.ns['_core'](self.trip)
        self.office_rows('HELP1');self.b.ns['validate_trip'](self.trip)
        self.assertEqual(self.trip.team_revision,1);self.assertEqual(self.a.ns['_core'](self.trip),scope)
    def test_office_rejects_duplicates_primary_inactive_or_unqualified_assistants(self):
        for members in [('HELP1','HELP1'),('EMP',),('MISSING',),(None,'HELP1')]:
            self.office_rows(*members)
            with self.assertRaises((ValueError,KeyError)):self.office_team()
        self.office_rows('HELP1');self.data['Employee']['HELP1'].status='Left'
        with self.assertRaisesRegex(ValueError,'active'):self.office_team()
        self.data['Employee']['HELP1'].status='Active';self.data['CFG Kanban Operator Profile']['HELP1'].active=0
        with self.assertRaisesRegex(ValueError,'active Kanban'):self.office_team()
        self.data['CFG Kanban Operator Profile']['HELP1'].active=1;self.data['CFG Kanban Operator Profile']['HELP1'].responsibilities=[]
        with self.assertRaisesRegex(ValueError,'Customer Delivery'):self.office_team()
    def test_started_or_closed_team_cannot_be_rewritten_by_office_save(self):
        self.office_rows('HELP1');self.office_team();before=office.document(self.trip.as_dict())
        for state in ('In Progress','Completed','Closed Incomplete'):
            before.driver_route_state=state;self.office_rows('HELP2')
            with self.assertRaisesRegex(ValueError,'Started Trips'):self.office_team(before)
    def test_lead_can_add_before_loading_and_retry_records_one_child_and_original_actor(self):
        self.a.v.p1.state='Picking';request=self.add_request();first=self.a.perform(request);again=self.a.perform(request)
        self.assertEqual(first,again);self.assertEqual(len(self.data[CHILD]),1);self.assertEqual(self.trip.team_revision,1)
        row=self.trip.assistant_drivers[0];self.assertEqual(row.assigned_by,'EMP');self.assertEqual(row.assignment_source,'Assigned Driver')
        self.assertEqual(self.trip.driver_route_state,'Not Started');self.assertFalse(self.data.get(actions.views.SESSION))
        self.assertEqual(first['request_actor'],'EMP')
    def test_lead_add_during_delivery_preserves_frozen_execution_and_avoids_duplicates(self):
        self.a.start();self.a.begin_stop();snapshot=self.trip.driver_route_snapshot_json;core=self.a.ns['_core'](self.trip)
        self.add();self.add();self.add('HELP2')
        self.assertEqual(len(self.data[CHILD]),2);self.assertEqual(self.trip.team_revision,2)
        self.assertEqual(self.trip.driver_route_snapshot_json,snapshot);self.assertEqual(self.a.ns['_core'](self.trip),core)
    def test_assistant_cannot_add_another_assistant_or_impersonate_the_lead(self):
        self.add();self.operator.employee='HELP1'
        with self.assertRaisesRegex(PermissionError,'Only the Assigned Driver'):self.add_request('HELP2')
        request=dict(trip_name=self.trip.name,action='Add Assistant',event_token='FORGED',operator_session_token='TOKEN',expected_revision=self.trip.driver_route_revision,
            scope_hash=self.a.ns['_core'](self.trip),payload={'employee':'HELP2'})
        with self.assertRaisesRegex(PermissionError,'Only the Assigned Driver'):self.a.perform(request)
        self.assertEqual(len(self.data[CHILD]),1)
    def test_stale_or_conflicting_add_and_missing_start_permission_create_nothing(self):
        request=self.add_request();self.trip.driver_route_revision=1
        with self.assertRaisesRegex(ValueError,'changed'):self.a.perform(request)
        self.trip.driver_route_revision=0;self.operator.can_start=0
        with self.assertRaises(PermissionError):self.a.perform(request)
        self.assertFalse(self.data.get(CHILD));self.operator.can_start=1;self.a.perform(request)
        request['payload']={'employee':'HELP2'}
        with self.assertRaises(self.a.ns['DriverActionConflict']):self.a.perform(request)
        self.assertEqual(len(self.data[CHILD]),1)
    def test_assistant_trip_queue_uses_native_permission_filtered_or_condition(self):
        self.add();self.operator.employee='HELP1';original=self.b.frappe.get_list;calls=[]
        def visible(dt,filters=None,**kw):
            calls.append(kw)
            rows=original(dt,filters=filters,**{k:v for k,v in kw.items() if k!='or_filters'})
            if kw.get('or_filters'):
                allowed=kw['or_filters']['name'][1]
                rows=[n for n in rows if n in allowed or self.data[TRIP][n].driver==self.operator.employee]
            return rows
        self.b.frappe.get_list=visible
        result=self.a.v.ns['get_driver_trips']('TOKEN');self.assertEqual([r['name'] for r in result['trips']],[self.trip.name])
        self.assertEqual(calls[0]['or_filters']['name'][1],[self.trip.name])
        self.trip._hidden=True;self.assertEqual(self.a.v.ns['get_driver_trips']('TOKEN')['trips'],[])
    def test_assistant_can_open_trip_but_outsider_and_native_company_denial_cannot(self):
        self.add();self.operator.employee='HELP1';self.assertEqual(self.a.v.read()['trip']['name'],self.trip.name)
        self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.a.v.read()
        self.data['Company']['A']._denied=False;self.operator.employee='HELP2'
        with self.assertRaises(PermissionError):self.a.v.read()
    def test_assistant_continues_known_session_and_proof_without_changing_its_creator(self):
        self.a.start();self.a.deliver_to_proof();delivery=self.data[actions.views.SESSION][self.a.v.p1.delivery_session]
        self.add();self.operator.employee='HELP1';self.a.proof_submit()
        self.assertEqual(delivery.started_by_operator,'EMP');self.assertEqual(delivery.state,'Closed')
        self.assertEqual(self.trip.stops[0].driver_completed_by,'HELP1')
        event=next(v for v in self.a.events.values() if v['event']=='Driver Route Submit Proof')
        self.assertEqual(event['operator'],'HELP1')
    def test_teammate_access_is_exact_to_company_site_plan_and_native_permissions(self):
        self.a.start();self.a.begin_stop();self.add();self.operator.employee='HELP1'
        delivery=self.data[actions.views.SESSION][self.a.v.p1.delivery_session]
        self.assertTrue(self.a.engine._can_view_delivery(self.operator,delivery))
        for field,value in [('selling_company','B'),('customer_scan_point','SITE2'),('customer_address','OTHER'),('source_warehouse','SOURCE')]:
            old=delivery[field];delivery[field]=value;self.assertFalse(self.a.engine._can_view_delivery(self.operator,delivery));delivery[field]=old
        self.a.v.p1._denied=True
        self.assertFalse(self.a.engine._can_view_delivery(self.operator,delivery))
        self.a.v.p1._denied=False;self.operator.responsibilities=[]
        self.assertFalse(self.a.engine._can_view_delivery(self.operator,delivery))
    def test_team_membership_never_grants_complete_or_supervisor_permissions(self):
        self.a.start();self.a.begin_stop();self.add();self.operator.employee='HELP1';request=self.a.request('Confirm Allocations')
        self.operator.can_complete=0
        with self.assertRaises(PermissionError):self.a.perform(request)
        self.operator.can_complete=1;self.operator.can_override=0
        with self.assertRaises(PermissionError):self.a.ns['driver_action_context'](self.trip.name,'TOKEN',self.a.v.keys[0],operation='Release Refused Stock',outcome_name='FORGED')
    def test_two_operators_cannot_apply_the_same_stale_route_revision(self):
        self.a.start();self.add();request=self.a.request('Begin Delivery',customer_scan='QR1')
        self.operator.employee='HELP1';other=self.a.request('Begin Delivery',customer_scan='QR1')
        self.operator.employee='EMP';self.a.perform(request);self.operator.employee='HELP1'
        with self.assertRaisesRegex(ValueError,'changed'):self.a.perform(other)
        self.assertEqual(len(self.data[actions.views.SESSION]),1)
    def test_completed_trip_rejects_new_team_and_assistant_cannot_reconcile_another_actor(self):
        self.add();request=self.add_request('HELP2');self.trip.driver_route_state='Completed'
        with self.assertRaisesRegex(ValueError,'active Planned'):self.a.perform(request)
        self.operator.employee='HELP1';request.update(request_actor='EMP')
        with self.assertRaisesRegex(PermissionError,'Supervisor'):self.a.ns['reconcile_driver_action'](**request)
    def test_native_session_without_a_trip_keeps_the_original_owner_rule(self):
        delivery=office.Doc(name='UNRELATED',dispatch_plan=None,started_by_operator='EMP')
        self.operator.employee='HELP1';self.assertFalse(self.a.engine._can_view_delivery(self.operator,delivery))
        self.operator.employee='EMP';self.assertTrue(self.a.engine._can_view_delivery(self.operator,delivery))

    def test_shared_pool_stock_and_native_dn_can_be_completed_by_an_assistant(self):
        x=shared.TestTripSales();x.setUp();self.addCleanup(x.doCleanups);x.b.frappe.session=Row(user='terminal@example.com')
        team=self.install(x.b.frappe,x.b.e3.events,x.trip,x.data)
        x.b.add('Employee','HELP1',status='Active',employee_name='Assistant')
        x.b.add('CFG Kanban Operator Profile','HELP1',employee='HELP1',active=1,responsibilities=[Row(responsibility='Customer Delivery')])
        real=load('services/driver_routes.py',dict(frappe=x.b.frappe))
        x.views._trip=real['_trip'];x.views.get_driver_trip=x.actual_view
        x.start();x.begin();delivery=x.delivery()
        x.run_action(operation='Add Assistant',employee='HELP1')
        x.operator.employee='HELP1';x.r.allocate(2);x.run_action('Confirm Allocations');x.run_action('Create Delivery Note')
        self.assertEqual(delivery.started_by_operator,'EMP');self.assertEqual(delivery.state,'Closed')
        self.assertEqual(x.r.unit.current_qty,3);self.assertEqual(x.r.unit.reserved_qty,0)
        self.assertEqual(x.trip.stops[0].driver_completed_by,'HELP1');self.assertEqual(len(x.data['Delivery Note']),1)

    def test_office_assistant_can_start_route_and_is_recorded_as_departure_actor(self):
        self.office_rows('HELP1');self.office_team();self.operator.employee='HELP1'
        self.a.start();self.assertEqual(self.trip.driver_route_started_by,'HELP1')
        self.assertEqual(self.trip.driver,'EMP');self.assertFalse(self.data.get('Delivery Note'))
        self.assertFalse(self.a.v.read()['can_add_assistant'])

    def test_assistant_old_return_action_keeps_actual_collector_and_one_receipt(self):
        from unittest.mock import Mock
        self.a.start();self.add();self.operator.employee='HELP1'
        module=types.ModuleType('cfg_kanban.services.driver_collections')
        module.context=Mock(return_value={'company':'A','customer':'C1'})
        module.collect=Mock(return_value={'return_case':'RET1'})
        with patch.dict(sys.modules,{module.__name__:module}):
            c=self.a.ns['driver_action_context'](self.trip.name,'TOKEN',self.a.v.keys[0],operation='Collect Old Return')
            request=dict(trip_name=self.trip.name,action='Collect Old Return',event_token='RETURN',operator_session_token='TOKEN',
                expected_revision=c['revision'],scope_hash=c['scope_hash'],stop_key=c['stop_key'],payload={'lines':[{'item_code':'ITEM','claimed_qty':1}]})
            result=self.a.perform(request);self.a.perform(request)
        module.collect.assert_called_once();self.assertEqual(module.collect.call_args.args[3].employee,'HELP1')
        self.assertEqual(result['request_actor'],'HELP1');self.assertEqual(result['result']['return_case'],'RET1')

    def test_team_delivery_access_still_requires_dispatch_responsibility(self):
        self.a.start();self.a.begin_stop();self.add();self.operator.employee='HELP1'
        self.operator.responsibilities=[Row(responsibility='Customer Delivery')]
        delivery=self.data[actions.views.SESSION][self.a.v.p1.delivery_session]
        self.assertFalse(self.a.engine._can_view_delivery(self.operator,delivery))

    def test_office_event_waits_for_saved_parent_and_records_once_in_on_update(self):
        self.office_rows('HELP1');self.office_team()
        self.assertFalse([v for v in self.a.events.values() if v['event']=='Delivery Trip Assistants Changed'])
        controller=load('cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.py',dict(Document=office.Doc))['CFGKanbanDeliveryTrip']
        controller.on_update(self.trip);controller.on_update(self.trip)
        events=[v for v in self.a.events.values() if v['event']=='Delivery Trip Assistants Changed']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['reference_name'],self.trip.name)

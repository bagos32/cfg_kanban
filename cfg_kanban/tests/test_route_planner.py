"""Request -> worker -> office accept with real normal Trip validation/LIFO and DB doubles.

Transaction restoration here models the Frappe POST rollback boundary; real MariaDB/Redis
concurrency, after-commit queueing and native permissions remain site acceptance.
"""
import copy
import datetime as dt
import json
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.services import route_planner_model as model
from cfg_kanban.services.customer_locations import delivery_pin, pin_geojson
from cfg_kanban.tests import test_office_delivery_trip as base
from cfg_kanban.tests.test_vehicle_overview import Row, load


class TestRoutePlanner(unittest.TestCase):
    def setUp(self):
        self.b=base.TestOfficeDeliveryTrip();self.b.setUp();self.data=self.b.data
        self.jobs=[];self.commits=[];self.events=Mock();self.saved=[];self.clock=dt.datetime(2026,11,21,10)
        self.frappe=self.b.frappe
        self.frappe.update(PermissionError=PermissionError,session=Row(user='planner@example.com'),
            get_all=self.get_list,get_list=self.get_list,get_doc=self.get_doc,enqueue=self.enqueue,throw=self.throw)
        self.frappe.db.update(get_value=self.value,commit=lambda:self.commits.append('commit'))
        self.office=types.SimpleNamespace(**self.b.ns)
        self.ns=load('services/route_planner.py',dict(frappe=self.frappe,office=self.office,model=model,
            copy=copy,dt=dt,json=json,time=time,delivery_pin=delivery_pin,record=self.events,
            cint=lambda value:int(value or 0),get_datetime=lambda value:dt.datetime.fromisoformat(str(value)),
            now_datetime=lambda:self.clock))
        self.module=types.ModuleType('cfg_kanban.services.route_planner');self.module.__dict__.update(self.ns)
        p=patch.dict(sys.modules,{self.module.__name__:self.module});p.start();self.addCleanup(p.stop)
        outer=self
        class StoredDoc(base.Doc):
            def check_permission(doc,kind):
                if doc.get('_denied') or (kind=='write' and doc.get('_deny_write')):raise PermissionError('Access denied')
            def as_dict(doc):return {k:v for k,v in super().as_dict().items() if k!='flags'}
            def insert(doc,**kwargs):
                doc.assert_controlled()
                doc.name='RPR-'+str(len(outer.data.setdefault(outer.ns['RUN'],{}))+1)
                doc.creation=doc.modified=str(outer.clock)
                outer.data[doc.doctype][doc.name]=base.document(doc.as_dict());outer.saved.append(('insert',doc.doctype))
                return doc
            def save(doc,**kwargs):
                before=base.document(outer.data[doc.doctype][doc.name].as_dict());doc._before=before
                if doc.doctype==base.TRIP:
                    outer.trip_controller.validate(doc)
                    doc.modified=str(outer.clock+dt.timedelta(seconds=len(outer.saved)+1))
                else:doc.assert_controlled()
                outer.data[doc.doctype][doc.name]=base.document(doc.as_dict());outer.saved.append(('save',doc.doctype))
                return doc
            def assert_controlled(doc):
                outer.run_controller.validate(doc)
        self.Doc=StoredDoc
        self.run_controller=load('cfg_kanban/doctype/cfg_kanban_route_planning_run/cfg_kanban_route_planning_run.py',
            dict(frappe=self.frappe,Document=self.Doc))['CFGKanbanRoutePlanningRun']
        self.trip_controller=load('cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.py',
            dict(frappe=self.frappe,Document=self.Doc,validate_trip=self.office.validate_trip))['CFGKanbanDeliveryTrip']
        self.settings=self.b.add(self.ns['SETTINGS'],'SETTINGS',company='A',enabled=1,provider=model.PROVIDER,
            source_warehouse='SOURCE',vehicle_warehouse='LORRY',capacity_grams=1000000,shift_start='08:00',shift_end='18:00',
            start_location=pin_geojson(dict(latitude=3.004,longitude=101.394)),
            end_location=pin_geojson(dict(latitude=3.004,longitude=101.394)),gates_verified=1,max_stops=20,max_attempts_per_trip=10,
            modified=str(self.clock))
        for i in (1,2):
            self.data['CFG Kanban Customer Scan Point']['SITE'+str(i)].update(
                delivery_location=pin_geojson(dict(latitude=3+i/100,longitude=101.5)),planner_pin_verified=1,modified=str(self.clock))
            self.b.assign(n=i).planner_grams_per_stock_uom=1500
            self.b.doc.stops[i-1].update(planner_service_minutes=10,planner_window_start='08:00',
                planner_window_end='17:30',planner_finish_by_close=1)
        self.b.doc.update(sequence_policy='Flexible Order',vehicle_warehouse='LORRY',source_warehouse='SOURCE',
            expected_return_date=self.b.doc.trip_date,planner_enabled=1,planner_load_verified=1)
        self.b.persist()
        self.original=self.data[base.TRIP]['TRIP1'].as_dict()

    def get_doc(self,doctype,name=None,**kwargs):
        if isinstance(doctype,dict):values=base.document(doctype)
        else:
            self.b.reads.append((doctype,name,kwargs))
            values=base.document(self.data[doctype][name].as_dict())
            for flag in ('_denied','_deny_write'):
                values[flag]=self.data[doctype][name].get(flag)
        doc=self.Doc(values);doc.flags=base.Doc();return doc
    def throw(self,message,exc=ValueError):raise exc(message)
    def get_list(self,doctype,filters=None,fields=None,pluck=None,**kwargs):
        rows=[row for row in self.data.get(doctype,{}).values() if self.b.matches(row,filters)]
        if 'desc' in kwargs.get('order_by',''):rows=list(reversed(rows))
        length=kwargs.get('limit_page_length');rows=rows[:length] if length else rows
        if pluck:return [row.get(pluck) for row in rows]
        return [base.Doc({field:row.get(field) for field in fields}) if fields else base.Doc(row) for row in rows]
    def value(self,doctype,name,field):
        row=next((row for row in self.data.get(doctype,{}).values() if self.b.matches(row,name)),None) if isinstance(name,dict) else self.data.get(doctype,{}).get(name)
        return row.get(field) if row else None
    def enqueue(self,method,**kwargs):self.jobs.append((method,kwargs))
    def request(self):return self.ns['request_mock_proposal']('TRIP1',self.data[base.TRIP]['TRIP1'].modified)
    def worker(self,attempt=None):
        job=self.jobs[-1][1];self.ns['solve_mock_run'](job['run_name'],attempt or job['attempt'])
        return self.data[self.ns['RUN']][job['run_name']]
    def ready(self):self.request();return self.worker()
    def inventory(self):
        return {name:copy.deepcopy(self.data.get(name,{})) for name in ('CFG Kanban Dispatch Plan','CFG Kanban Dispatch Allocation',
            'CFG Kanban Movement Manifest','Stock Entry','Delivery Note','Stock Ledger Entry','Bin')}
    def decide(self,run,decision='Accept',reason='Reviewed fixture'):
        # Mirror Frappe's request rollback for deliberate validation/audit failure tests.
        before=copy.deepcopy(self.data)
        try:return self.ns['decide_mock_proposal'](run.name,decision,reason)
        except BaseException:
            self.data.clear();self.data.update(before);raise

    def test_request_worker_accept_preserves_exact_so_rows_rebuilds_lifo_and_never_posts(self):
        inventory=self.inventory();orders=copy.deepcopy(self.original['orders']);template=copy.deepcopy(self.b.template)
        keys=[row['stop_key'] for row in self.original['stops']]
        request=self.request();self.assertEqual(request['status'],'Queued');self.assertFalse(self.commits)
        self.assertTrue(self.jobs[-1][1]['enqueue_after_commit']);self.assertEqual(self.data[base.TRIP]['TRIP1'].as_dict(),self.original)
        run=self.worker();self.assertEqual(run.status,'Ready');self.assertEqual(len(self.commits),2)
        self.assertEqual(self.data[base.TRIP]['TRIP1'].as_dict(),self.original)
        result=self.decide(run);trip=self.data[base.TRIP]['TRIP1']
        self.assertTrue(result['accepted']);self.assertEqual([row.stop_key for row in trip.stops],keys[::-1])
        identity=lambda rows:sorted((r['sales_order'],r['sales_order_item'],r['stop_key'],r['planned_qty'],r['stock_uom']) for r in rows)
        self.assertEqual(identity(trip.orders),identity(orders));self.assertEqual(trip.planning_revision,self.original['planning_revision']+1)
        self.assertEqual([row.stop_key for row in trip.loading_sequence],keys)
        self.assertEqual([row.delivery_sequence for row in trip.loading_sequence],[2,1])
        self.assertEqual(self.b.template,template);self.assertEqual(self.inventory(),inventory)
        self.assertEqual(trip.planner_accepted_run,run.name);self.events.assert_called_once()

    def test_duplicate_request_worker_and_acceptance_never_create_a_second_run_or_reapply(self):
        first=self.request();again=self.request();self.assertEqual(first['name'],again['name']);self.assertEqual(len(self.jobs),1)
        run=self.worker();saves=len(self.saved);self.worker();self.assertEqual(len(self.saved),saves)
        self.decide(run);trip=self.data[base.TRIP]['TRIP1'];trip.notes='A later manual edit';trip.modified='2026-11-21 12:00:00'
        before=copy.deepcopy(trip);events=self.events.call_count
        replay=self.decide(self.data[self.ns['RUN']][run.name])
        self.assertTrue(replay['already_recorded']);self.assertEqual(self.data[base.TRIP]['TRIP1'],before)
        self.assertEqual(self.events.call_count,events)

    def test_two_visits_to_the_same_site_retain_distinct_stop_and_order_identities(self):
        trip=self.get_doc(base.TRIP,'TRIP1');trip.stops[1].update(customer_scan_point='SITE1',customer='C1',customer_address='A1')
        self.data['Sales Order']['SO2'].update(customer='C1',shipping_address_name='A1')
        trip.save();keys=[row.stop_key for row in trip.stops]
        run=self.ready();self.decide(run);saved=self.data[base.TRIP]['TRIP1']
        self.assertEqual([row.stop_key for row in saved.stops],keys[::-1])
        self.assertEqual(len(set(row.stop_key for row in saved.stops)),2)
        self.assertEqual({row.sales_order for row in saved.orders},{'SO1','SO2'})

    def test_default_off_or_disabled_provider_leaves_manual_planning_available(self):
        self.data[self.ns['SETTINGS']]['SETTINGS'].enabled=0
        trip=self.get_doc(base.TRIP,'TRIP1');trip.planner_enabled=0;trip.planner_load_verified=0
        for row in trip.orders:row.planner_grams_per_stock_uom=0
        for row in trip.stops:row.planner_window_start=None;row.planner_window_end=None;row.planner_service_minutes=0
        trip.save();panel=self.ns['get_planning_panel'](trip.name)
        self.assertFalse(panel['ready']);self.assertEqual(trip.state,'Draft')
        trip.state='Planned';trip.save();self.assertEqual(self.data[base.TRIP][trip.name].state,'Planned')
        self.assertFalse(self.data.get(self.ns['RUN']));self.assertFalse(self.jobs)

    def test_stale_trip_so_pin_vehicle_settings_and_assignment_reject_without_mutation(self):
        for target in ('trip','SO','pin','vehicle','settings','assignment'):
            with self.subTest(target=target):
                saved=copy.deepcopy(self.data);run=self.ready()
                if target=='trip':self.data[base.TRIP]['TRIP1'].modified='2026-11-21 11:00:00'
                if target=='SO':self.data['Sales Order']['SO1'].modified='2026-11-21 11:00:00'
                if target=='pin':self.data['CFG Kanban Customer Scan Point']['SITE1'].delivery_location=pin_geojson(dict(latitude=3.2,longitude=101.5))
                if target=='vehicle':self.data['Warehouse']['LORRY'].cfg_vehicle_reference='DIFFERENT'
                if target=='settings':self.data[self.ns['SETTINGS']]['SETTINGS'].capacity_grams=999999
                if target=='assignment':self.data[base.TRIP]['TRIP1'].orders[0].planned_qty=3
                before=copy.deepcopy(self.data);inventory=self.inventory()
                with self.assertRaisesRegex(ValueError,'changed|differs'):self.decide(run)
                self.assertEqual(self.data,before);self.assertEqual(self.inventory(),inventory)
                self.data.clear();self.data.update(saved)

    def test_changed_remaining_so_balance_blocks_both_request_and_accept(self):
        run=self.ready();self.data['Sales Order']['SO1']['items'][0].delivered_qty=9
        before=copy.deepcopy(self.data)
        with self.assertRaisesRegex(ValueError,'SO balance'):self.decide(run)
        self.assertEqual(self.data,before)
        with self.assertRaisesRegex(ValueError,'SO balance'):self.request()

    def test_cross_company_roles_write_and_source_permissions_remain_required(self):
        self.b.roles=['Stock User']
        with self.assertRaises(PermissionError):self.request()
        self.b.roles=['Stock Manager'];self.data[base.TRIP]['TRIP1']._deny_write=True
        with self.assertRaises(PermissionError):self.request()
        self.data[base.TRIP]['TRIP1']._deny_write=False;self.data['Sales Order']['SO1']._denied=True
        with self.assertRaises(PermissionError):self.request()
        self.data['Sales Order']['SO1']._denied=False;run=self.ready();self.data[self.ns['RUN']][run.name].company='B'
        with self.assertRaises(PermissionError):self.decide(run)

    def test_existing_dispatch_or_execution_blocks_even_draft_and_creates_no_plan(self):
        for change in ('plan','orphan_plan','started','planned','pool','stock','follow_on','other_dispatch'):
            with self.subTest(change=change):
                saved=copy.deepcopy(self.data);trip=self.data[base.TRIP]['TRIP1']
                if change=='plan':trip.dispatch_plans=[base.Doc(dispatch_plan='EXISTING')]
                if change=='orphan_plan':self.b.add('CFG Kanban Dispatch Plan','EXISTING',office_delivery_trip=trip.name)
                if change=='started':trip.driver_route_state='In Progress'
                if change=='planned':trip.state='Planned'
                if change=='pool':trip.allow_existing_lorry_sales=1
                if change=='stock':self.b.add('Bin','LORRY-BIN',warehouse='LORRY',item_code='UNRELATED',actual_qty=1)
                if change=='follow_on':trip.follow_on_of='EARLIER'
                if change=='other_dispatch':self.b.add('CFG Kanban Dispatch Plan','OTHER-LOAD',vehicle_warehouse='LORRY',state='Loading')
                before=copy.deepcopy(self.data)
                with self.assertRaisesRegex(ValueError,'blocked'):self.request()
                self.assertEqual(self.data,before)
                self.data.clear();self.data.update(saved)

    def test_failed_and_timeout_runs_keep_manual_trip_and_need_explicit_bounded_retry(self):
        before=copy.deepcopy(self.data[base.TRIP]['TRIP1'])
        self.ns['_provider']=Mock(side_effect=TimeoutError())
        self.request();run=self.worker();self.assertEqual(run.status,'Timed Out');self.assertEqual(self.data[base.TRIP]['TRIP1'],before)
        with self.assertRaisesRegex(ValueError,'reason'):self.ns['retry_mock_proposal'](run.name,'')
        self.ns['_provider']=model.mock_solve
        retry=self.ns['retry_mock_proposal'](run.name,'Retry the fixture');self.assertEqual(retry['attempt_count'],2)
        self.ns['retry_mock_proposal'](run.name,'Duplicate click');self.assertEqual(len(self.jobs),2)
        self.worker(attempt=1);self.assertEqual(self.data[self.ns['RUN']][run.name].status,'Queued')
        run=self.worker();self.assertEqual(run.status,'Ready')
        self.assertIn('Retry the fixture',run.attempt_history_json)

    def test_unknown_worker_exception_does_not_expose_payload_or_secrets(self):
        self.ns['_provider']=Mock(side_effect=RuntimeError('SECRET endpoint or token'))
        self.request();run=self.worker();self.assertEqual(run.status,'Failed')
        self.assertNotIn('SECRET',run.failure_message);self.assertFalse(run.response_json)

    def test_attempt_cap_rejection_and_explicit_rejection_are_safe_to_replay(self):
        self.data[self.ns['SETTINGS']]['SETTINGS'].max_attempts_per_trip=1
        self.ns['_provider']=Mock(side_effect=ValueError('Invalid fixture response'));self.request();run=self.worker()
        with self.assertRaisesRegex(ValueError,'limit reached'):self.ns['retry_mock_proposal'](run.name,'again')
        result=self.decide(run,'Reject','Keep manual sequence');self.assertEqual(result['run']['status'],'Rejected')
        count=self.events.call_count;self.assertTrue(self.decide(run,'Reject')['already_recorded']);self.assertEqual(count,self.events.call_count)

    def test_interrupted_worker_cannot_overwrite_a_newer_attempt(self):
        self.request();run=next(iter(self.data[self.ns['RUN']].values()))
        self.clock+=dt.timedelta(seconds=91)
        self.decide(run,'Mark Interrupted','Worker was stopped')
        self.assertEqual(self.data[self.ns['RUN']][run.name].status,'Timed Out')
        self.ns['retry_mock_proposal'](run.name,'Restart mock');self.worker(attempt=1)
        self.assertEqual(self.data[self.ns['RUN']][run.name].status,'Queued');self.worker()
        self.assertEqual(self.data[self.ns['RUN']][run.name].status,'Ready')

    def test_event_failure_rolls_back_trip_and_acceptance_at_request_boundary(self):
        run=self.ready();before=copy.deepcopy(self.data)
        self.events.side_effect=ValueError('Audit write failed')
        with self.assertRaisesRegex(ValueError,'Audit write'):self.decide(run)
        self.assertEqual(self.data,before)

    def test_corrupted_or_missing_stop_response_cannot_change_order(self):
        run=self.ready();response=json.loads(run.response_json);response['visits'].pop()
        self.data[self.ns['RUN']][run.name].response_json=json.dumps(response)
        before=copy.deepcopy(self.data)
        with self.assertRaisesRegex(ValueError,'every mandatory'):self.decide(run)
        self.assertEqual(self.data,before)

    def test_lock_order_and_current_reads_follow_normal_office_workflow(self):
        self.b.queries.clear()
        self.request();queries=[query for query,_ in self.b.queries if 'FOR UPDATE' in query]
        self.assertIn('Route Template',queries[0]);self.assertIn('Delivery Trip',queries[1]);self.assertIn('Sales Order',queries[2])
        self.assertTrue(any(dtname==base.TRIP and kwargs.get('for_update') for dtname,_name,kwargs in self.b.reads))

    def test_site_and_gate_verification_reset_on_identity_or_coordinate_change(self):
        site=self.get_doc('CFG Kanban Customer Scan Point','SITE1');site.planner_pin_verified_by='manager';site.planner_pin_verified_on=self.clock
        before=base.document(site.as_dict());site.delivery_location=pin_geojson(dict(latitude=3.2,longitude=101.5))
        self.ns['verify_site_pin'](site,before);self.assertEqual(site.planner_pin_verified,0);self.assertIsNone(site.planner_pin_verified_by)
        before=base.document(site.as_dict());site.planner_pin_verified=1
        self.ns['verify_site_pin'](site,before);self.assertEqual(site.planner_pin_verified_by,'planner@example.com')
        setup=self.get_doc(self.ns['SETTINGS'],'SETTINGS');setup._before=base.document(setup.as_dict())
        setup.start_location=pin_geojson(dict(latitude=3.2,longitude=101.5))
        self.ns['validate_settings'](setup);self.assertEqual(setup.gates_verified,0)

    def test_normal_site_controller_records_verified_pin_without_changing_delivery_policy(self):
        site=self.get_doc('CFG Kanban Customer Scan Point','SITE1');site._before=base.document(site.as_dict())
        site.planner_pin_verified=0;site._before.planner_pin_verified=0;site.planner_pin_verified=1
        site.update(proof_policy='Required',require_signature=1,require_gps=1)
        self.b.add('Dynamic Link','ADDRESS-LINK',parenttype='Address',parent='A1',link_doctype='Customer',link_name='C1')
        controller=load('cfg_kanban/doctype/cfg_kanban_customer_scan_point/cfg_kanban_customer_scan_point.py',
            dict(frappe=self.frappe,Document=self.Doc,validate_price_list_mode=Mock(),validate_warehouse_company=Mock()))['CFGKanbanCustomerScanPoint']
        controller.validate(site)
        self.assertEqual(site.planner_pin_verified_by,'planner@example.com')
        self.assertEqual(site.require_signature,1);self.assertEqual(site.require_gps,1);self.assertEqual(site.proof_policy,'Required')

    def test_run_controller_rejects_direct_edits_and_deletion(self):
        run=self.get_doc(dict(doctype=self.ns['RUN'],status='Accepted'))
        with self.assertRaisesRegex(ValueError,'controlled'):self.run_controller.validate(run)
        with self.assertRaisesRegex(ValueError,'history'):self.run_controller.on_trash(run)

    def test_history_permission_never_grants_access_and_checks_captured_source_documents(self):
        run=self.ready();self.frappe.has_permission=Mock(return_value=True)
        self.assertIsNone(self.ns['run_has_permission'](run,user='reviewer@example.com',ptype='read'))
        self.assertTrue(all(call.kwargs['user']=='reviewer@example.com' for call in self.frappe.has_permission.call_args_list))
        self.frappe.has_permission=Mock(side_effect=lambda doctype,*a,**kw:doctype!='Sales Order')
        self.assertFalse(self.ns['run_has_permission'](run,ptype='read'))
        self.assertIsNone(self.ns['run_has_permission'](run,ptype='write'))  # Native role/controller still deny edits.
        run.company='B';self.assertFalse(self.ns['run_has_permission'](run,ptype='read'))

    def test_history_list_uses_native_trip_scope_and_raw_json_is_not_a_role_level_zero_field(self):
        self.frappe.get_list=Mock(return_value=['TRIP1',"TRIP'2"])
        self.frappe.db.escape=lambda value:"'"+value.replace("'","''")+"'"
        condition=self.ns['run_query_conditions']('reviewer@example.com')
        self.assertIn("'TRIP''2'",condition)
        self.assertEqual(self.frappe.get_list.call_args.kwargs['user'],'reviewer@example.com')
        self.frappe.get_list.return_value=[];self.assertEqual(self.ns['run_query_conditions'](),'1=0')
        schema=json.loads((base.ROOT/'cfg_kanban/doctype/cfg_kanban_route_planning_run/cfg_kanban_route_planning_run.json').read_text())
        self.assertTrue(all(row.get('permlevel')==1 for row in schema['fields'] if row['fieldtype']=='Code'))
        self.assertTrue(all(row.get('permlevel',0)==0 for row in schema['permissions']))


if __name__=='__main__':unittest.main()

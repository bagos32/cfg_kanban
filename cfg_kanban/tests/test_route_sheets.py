"""Route template/order/approval/delegation behaviour over the existing delivery engines.

Offline stores exercise code paths; native transactions/concurrency remain site acceptance.
"""
import copy
import datetime
import hashlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from cfg_kanban.tests.test_vehicle_overview import Row, load, ROOT

class Doc(Row):
    def as_dict(self):
        def clean(value):
            if isinstance(value,dict):return {key:clean(item) for key,item in value.items() if not key.startswith('_')}
            if isinstance(value,list):return [clean(row) for row in value]
            return value
        return clean(self)
    def db_set(self,key,value=None,**kwargs):self.update(key if isinstance(key,dict) else {key:value})
    def set(self,key,value):self[key]=[Doc(row) for row in value] if isinstance(value,list) else value
    def is_new(self):return not self.name
    def get_doc_before_save(self):return self.get('_before')
    def insert(self,**kwargs):
        self.name='DOC-'+str(len(self._data.setdefault(self.doctype,{}))+1)
        for index,row in enumerate(self.get('stops') or [],1):row.name=self.name+'-ROW-'+str(index)
        self._data[self.doctype][self.name]=self
        return self
    def save(self,**kwargs):return self

class TestRouteSheets(unittest.TestCase):
    def setUp(self):
        self.data={};self.events=[];self.sql=[];self.role='Supervisor';self.allowed=True;self.n=0
        self.operator=Doc(employee='EMP',kanban_role='Supervisor',can_override=1,can_start=1,
            responsibilities=[Doc(responsibility='Dispatch'),Doc(responsibility='Customer Delivery')])
        self.session=Doc(name='SESSION',terminal_user='terminal@example.com')
        self.frappe=Row(get_doc=self.get_doc,get_all=self.get_all,get_list=self.get_all,
            parse_json=json.loads,as_json=json.dumps,throw=self.throw,PermissionError=PermissionError,
            db=Row(sql=self.db_sql,get_value=self.get_value,get_values=self.get_values,exists=self.exists))
        self.common=dict(frappe=self.frappe,json=json,cint=lambda value:int(value or 0),
            now_datetime=lambda:datetime.datetime(2026,11,20,12),require_operator=self.require_operator,
            canonical_key=lambda ns,*args:hashlib.sha256(json.dumps([ns,*args],sort_keys=True,default=str).encode()).hexdigest(),
            record=self.record)
        self.ns=load('services/route_sheets.py',dict(self.common))
        self.planning=Row(_assert_plan_authorized=self.authorize,_require_event_token=lambda value:self.throw('event token required') if not value else None,
            _vehicle_warehouse=lambda name:self.data['Warehouse'][name])
        r=load('services/route_delivery.py',dict(self.common,STOP='CFG Kanban Route Stop',STOP_FIELDS=['name','dispatch_plan','state','customer_scan_point','planned_sequence','actual_sequence']))
        self.routes=Row(_supervisor=r['_supervisor'],_stops=r['_stops'],_new_stop=r['_new_stop'],_assert_site_scope=r['_assert_site_scope'],
            start_route_stop=Mock(side_effect=self.start_open))
        self.delivery=Row(_customer_delivery_allowed=lambda operator:any(row.responsibility=='Customer Delivery' for row in operator.responsibilities),
            _require_customer_delivery=self.require_delivery,_resolve_customer_site=self.resolve_site,get_delivery_session=lambda name,token:self.data['CFG Kanban Delivery Session'][name].as_dict())
        self.fulfilment=Row(start_prepared_delivery=Mock(side_effect=self.start_known))
        self.ns.update(_plans=lambda:self.planning,_routes=lambda:self.routes,_delivery=lambda:self.delivery,_fulfilment=lambda:self.fulfilment)
        self.add('Company','B');self.add('Company','A');self.add('Warehouse','LORRY',company='B',cfg_vehicle_reference='TRUCK1')
        self.add('Customer','C1',disabled=0);self.add('Customer','C2',disabled=0)
        self.add('Address','A1',address_line1='Street One',city='Town');self.add('Address','A2',address_line1='Street Two',city='Town')
        self.add('CFG Kanban Customer Scan Point','S1',site_name='Shop One',site_code='QR1',active=1,selling_company='B',customer='C1',customer_address='A1')
        self.add('CFG Kanban Customer Scan Point','S2',site_name='Shop Two',site_code='QR2',active=1,selling_company='B',customer='C2',customer_address='A2')
        self.p1=self.plan('P1','Customer Order',customer_site='S1',customer='C1',customer_address='A1')
        self.p2=self.plan('P2','Open Route Stock')
        self.add('CFG Kanban Route Template','TEMPLATE',company='B',active=1,revision=1,
            stops=[Doc(customer_scan_point='S1',instructions='Door A'),Doc(customer_scan_point='S2',instructions='Door B')])
        self.rows=[dict(row_key='R1',dispatch_plan='P1',customer_scan_point='S1'),dict(row_key='R2',dispatch_plan='P2',customer_scan_point='S2')]

    def add(self,dt,name,**kwargs):
        row=Doc(doctype=dt,name=name,**kwargs);row._data=self.data;self.data.setdefault(dt,{})[name]=row;return row
    def plan(self,name,kind,**kwargs):
        return self.add('CFG Kanban Dispatch Plan',name,company='B',state='Loaded',fulfilment_mode='Vehicle Delivery',plan_type=kind,
            vehicle_warehouse='LORRY',vehicle_reference='TRUCK1',trip_date='2026-11-20',route_sequence_scope='Combined Lorry Trip',
            route_approval_required=1,stop_sequence_policy='Planned Order',profile_snapshot_json=json.dumps({'customer_verification':'Allow Assigned Stop Selection'}),**kwargs)
    def throw(self,message,exc=ValueError):raise exc(message)
    def authorize(self,plan,operator):
        if not self.allowed:raise PermissionError('Responsibility denied')
    def require_delivery(self,operator):
        if not self.delivery._customer_delivery_allowed(operator):raise PermissionError('Customer Delivery responsibility required')
    def require_operator(self,token,action=None):
        if token!='TOKEN' or (action=='start' and not self.operator.can_start):raise PermissionError('Start denied')
        return self.operator,self.session
    def get_doc(self,dt,name=None,**kwargs):
        if isinstance(dt,dict):
            row=Doc(dt);row._data=self.data
            if 'stops' in row:row.set('stops',row['stops'])
            return row
        return self.data[dt][name]
    def matches(self,row,filters):
        for key,value in filters.items():
            if isinstance(value,(tuple,list)):
                if value[0]=='in' and row.get(key) not in value[1]:return False
                if value[0]=='not in' and row.get(key) in value[1]:return False
            elif row.get(key)!=value:return False
        return True
    def get_all(self,dt,filters=None,fields=None,**kwargs):
        return [Doc({field:row.get(field) for field in fields}) if fields else row
                for row in self.data.get(dt,{}).values() if self.matches(row,filters or {})]
    def get_values(self,dt,filters,fields,**kwargs):return self.get_all(dt,filters,fields)
    def get_value(self,dt,filters,field,as_dict=False,**kwargs):
        row=self.data.get(dt,{}).get(filters) if isinstance(filters,str) else next((row for row in self.data.get(dt,{}).values() if self.matches(row,filters)),None)
        if row is None:return None
        if isinstance(field,(tuple,list)):return Doc({key:row.get(key) for key in field}) if as_dict else tuple(row.get(key) for key in field)
        return row.get(field)
    def exists(self,dt,filters):return bool(self.get_value(dt,filters,'name'))
    def db_sql(self,query,values=None,**kwargs):self.sql.append((query,values));return []
    def record(self,event_type,**kwargs):
        key=kwargs.get('idempotency_key');existing=self.get_value('CFG Kanban Event',{'idempotency_key':key},'name') if key else None
        if existing:return self.data['CFG Kanban Event'][existing]
        self.events.append((event_type,kwargs))
        return self.add('CFG Kanban Event','EVENT'+str(len(self.events)),idempotency_key=key,payload_json=json.dumps(kwargs.get('payload') or {}))
    def resolve_site(self,scan):
        return next(row for row in self.data['CFG Kanban Customer Scan Point'].values() if scan in (row.name,row.site_code))
    def start_known(self,plan,site,key,token):return self.create_delivery(plan,None)
    def start_open(self,plan,site,key,token,route_stop=None):return self.create_delivery(plan,route_stop)
    def create_delivery(self,plan,stop):
        self.n+=1;doc=self.add('CFG Kanban Delivery Session','KDS'+str(self.n),state='Allocating',dispatch_plan=plan,route_stop=stop)
        if stop:self.data['CFG Kanban Route Stop'][stop].update(state='In Progress',delivery_session=doc.name)
        else:self.data['CFG Kanban Dispatch Plan'][plan].update(delivery_session=doc.name,fulfilment_status='In Progress')
        return doc.as_dict()
    def save(self,action='Approve',**changes):
        args=dict(scope_key='V:LORRY',stops=self.rows,expected_revision=0,event_token='SAVE1',operator_session_token='TOKEN',action=action)
        args.update(changes);return self.ns['save_route_sheet'](**args)
    def sheet(self):return next(iter(self.data['CFG Kanban Route Sheet'].values()))
    def start(self,row='R1',event='VISIT1',scan=None):return self.ns['start_route_sheet_stop'](self.sheet().name,row,event,'TOKEN',scan)

    def test_combined_sheet_joins_known_and_open_plans_without_erp_work(self):
        result=self.save();sheet=self.sheet();self.assertEqual(sheet.state,'Approved');self.assertEqual(sheet.scope,'Combined Lorry Trip')
        self.assertEqual([row.dispatch_plan for row in sheet.stops],['P1','P2']);self.assertEqual(sheet.stops[0].address_display,'Street One, Town')
        self.assertTrue(sheet.stops[1].source_route_stop);self.assertEqual(self.p1.active_route_sheet,sheet.name)
        self.fulfilment.start_prepared_delivery.assert_not_called();self.routes.start_route_stop.assert_not_called()

    def test_order_can_change_before_approval_and_is_frozen_afterwards(self):
        self.save('Save Draft');self.rows.reverse();self.save(expected_revision=1,event_token='APPROVE')
        self.assertEqual([row.row_key for row in self.sheet().stops],['R2','R1'])
        with self.assertRaisesRegex(ValueError,'frozen'):self.save('Save Draft',expected_revision=2,event_token='CHANGE')

    def test_supervisor_is_required_for_approval_and_existing_draft_edits(self):
        self.operator.kanban_role='Operator';self.operator.can_override=0
        with self.assertRaises(ValueError):self.save()
        with self.assertRaises(ValueError):self.save('Save Draft')
        self.operator.kanban_role='Supervisor';self.operator.can_override=1
        self.save('Save Draft')
        self.operator.kanban_role='Operator';self.operator.can_override=0
        with self.assertRaises(ValueError):self.save('Save Draft',expected_revision=1,event_token='EDIT')

    def test_expected_revision_and_same_token_payload_cannot_be_overwritten(self):
        first=self.save('Save Draft');self.assertEqual(self.save('Save Draft'),first)
        with self.assertRaises(self.ns['RouteSheetReplayError']):self.save('Save Draft',stops=list(reversed(self.rows)))
        with self.assertRaisesRegex(ValueError,'changed'):self.save(event_token='OTHER')

    def test_missing_scope_plan_ambiguous_source_and_wrong_customer_are_rejected(self):
        for rows in (self.rows[:1],[dict(self.rows[0],dispatch_plan=None),self.rows[1]],
                     [dict(self.rows[0],customer_scan_point='S2'),self.rows[1]]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.save(stops=rows)

    def test_wrong_company_inactive_site_and_disabled_customer_are_rejected(self):
        site=self.data['CFG Kanban Customer Scan Point']['S2']
        for field,value in [('selling_company','A'),('active',0)]:
            old=site[field];site[field]=value
            with self.assertRaises(ValueError):self.save()
            site[field]=old
        self.data['Customer']['C2'].disabled=1
        with self.assertRaises(ValueError):self.save()

    def test_stable_row_keys_and_single_prepared_customer_are_enforced(self):
        with self.assertRaises(ValueError):self.save(stops=[self.rows[0],dict(self.rows[1],row_key='R1')])
        with self.assertRaises(ValueError):self.save(stops=self.rows+[dict(self.rows[0],row_key='EXTRA')])

    def test_approval_requires_loaded_members_and_correct_responsibility(self):
        self.p2.state='Loading'
        with self.assertRaisesRegex(ValueError,'Load'):self.save()
        self.p2.state='Loaded';self.allowed=False
        with self.assertRaises(PermissionError):self.save()

    def test_template_snapshot_is_frozen_and_changed_revision_rejected(self):
        context=self.ns['get_route_context']('TOKEN',warehouse='LORRY',template='TEMPLATE')
        self.data['CFG Kanban Route Template']['TEMPLATE'].revision=2
        with self.assertRaisesRegex(ValueError,'Template changed'):self.save(template='TEMPLATE',template_hash=context['template_hash'])

    def test_template_and_route_preview_list_readable_customers_and_addresses(self):
        context=self.ns['get_route_context']('TOKEN',warehouse='LORRY',template='TEMPLATE')
        self.assertEqual([row['customer_scan_point'] for row in context['stops']],['S1','S2'])
        self.assertEqual(context['sites'][0].address_display,'Street One, Town');self.assertTrue(context['can_edit'])

    def test_next_stop_is_enforced_across_plans_and_select_option_reuses_engines(self):
        self.save()
        with self.assertRaisesRegex(ValueError,'next customer'):self.start('R2')
        result=self.start();self.assertEqual(result['name'],'KDS1');self.fulfilment.start_prepared_delivery.assert_called_once()
        self.data['CFG Kanban Delivery Session']['KDS1'].state='Closed';self.p1.fulfilment_status='Completed'
        result=self.start('R2','VISIT2');self.assertEqual(result['name'],'KDS2');self.routes.start_route_stop.assert_called_once()

    def test_qr_enforcement_uses_strictest_member_and_rejects_wrong_site(self):
        self.p1.profile_snapshot_json=json.dumps({'customer_verification':'Require Customer Site QR'});self.save()
        with self.assertRaisesRegex(ValueError,'requires'):self.start()
        with self.assertRaisesRegex(ValueError,'does not match'):self.start(scan='QR2')
        self.assertEqual(self.start(scan='QR1')['name'],'KDS1')

    def test_flexible_order_allows_choice_but_requires_active_proof_to_finish(self):
        self.p1.stop_sequence_policy=self.p2.stop_sequence_policy='Flexible Order';self.save();self.start('R2')
        with self.assertRaisesRegex(ValueError,'active lorry'):self.start('R1','NEXT')
        self.routes.start_route_stop.assert_called_once()

    def test_direct_engine_guard_blocks_unapproved_or_wrong_customer_visit(self):
        with self.assertRaisesRegex(ValueError,'approval'):self.ns['assert_visit_allowed'](self.p1,'S1')
        self.save('Save Draft')
        with self.assertRaisesRegex(ValueError,'approve'):self.ns['assert_visit_allowed'](self.p1,'S1')

    def test_exact_visit_retry_survives_mutable_site_and_plan_changes(self):
        self.save();first=self.start();self.p1.state='Reconciled';self.data['CFG Kanban Customer Scan Point']['S1'].active=0
        self.assertEqual(self.start(),first);self.fulfilment.start_prepared_delivery.assert_called_once()
        with self.assertRaises(self.ns['RouteSheetReplayError']):self.start(scan='QR1')

    def test_void_and_recorded_action_reconciliation_never_duplicate_routes(self):
        result=self.ns['reconcile_route_sheet_action']('V:LORRY','SAVE1','TOKEN',void_reason='Wrong details');self.assertEqual(result['status'],'Voided')
        with self.assertRaises(self.ns['RouteSheetReplayError']):self.save()
        self.save(event_token='SAVE2');result=self.ns['reconcile_route_sheet_action']('V:LORRY','SAVE2','TOKEN');self.assertEqual(result['status'],'Recorded')
        self.assertEqual(len(self.data['CFG Kanban Route Sheet']),1)

    def test_unknown_visit_readback_and_void_guard_against_late_execution(self):
        self.save();name=self.sheet().name
        self.assertEqual(self.ns['reconcile_route_sheet_visit'](name,'R1','VISIT1','TOKEN')['status'],'Not Recorded')
        self.ns['reconcile_route_sheet_visit'](name,'R1','VISIT1','TOKEN',void_reason='Wrong stop')
        with self.assertRaises(self.ns['RouteSheetReplayError']):self.start()

    def test_changed_site_snapshots_are_rejected_before_delivery(self):
        self.save();self.data['CFG Kanban Customer Scan Point']['S2'].customer_address='A1'
        self.data['CFG Kanban Delivery Session']={};self.p1.delivery_session=None
        with self.assertRaisesRegex(ValueError,'details changed'):self.start('R2')

    def test_existing_reasoned_open_route_override_is_honored_without_reordering_sheet(self):
        self.save();source=self.data['CFG Kanban Route Stop'][self.sheet().stops[1].source_route_stop]
        source.override_approved_by='SUP';source.override_reason='Road closure'
        with self.assertRaisesRegex(ValueError,'next customer'):self.start('R2','EARLY')
        self.p2.allow_supervisor_override=1
        result=self.start('R2','APPROVED-EARLY')
        self.assertEqual(result['name'],'KDS1')
        self.assertEqual([row.row_key for row in self.sheet().stops],['R1','R2'])

    def test_route_status_reads_plan_projection_without_locking_delivery_sessions(self):
        self.save();self.start();original=self.frappe.db.get_value
        def current_value(doctype,filters,fields,**kwargs):
            if doctype=='CFG Kanban Delivery Session':raise AssertionError('Route read must not lock an existing Session')
            return original(doctype,filters,fields,**kwargs)
        self.frappe.db.get_value=current_value
        self.assertEqual(self.ns['sheet_context'](self.sheet(),self.operator)['stops'][0]['state'],'In Progress')

    def test_changed_vehicle_after_scope_lock_requires_fresh_review(self):
        key=self.ns['lock_plan_route_scope'](self.p1,self.operator)
        self.p1.vehicle_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'assignment changed'):self.ns['check_plan_route_scope'](self.p1,key)

    def test_invoice_status_does_not_skip_unfinished_delivery_proof(self):
        self.save();self.start();self.data['CFG Kanban Delivery Session']['KDS1'].state='Invoiced';self.p1.fulfilment_status='Delivered'
        with self.assertRaisesRegex(ValueError,'active lorry|next customer'):self.start('R2','VISIT2')

    def test_actual_trip_sequence_is_recorded_once_across_different_plan_engines(self):
        self.save();self.start();self.start()
        self.assertEqual(self.sheet().stops[0].actual_sequence,1)
        self.data['CFG Kanban Delivery Session']['KDS1'].state='Closed';self.p1.fulfilment_status='Completed'
        self.start('R2','VISIT2')
        self.assertEqual(self.sheet().stops[1].actual_sequence,2)
        result=self.ns['sheet_context'](self.sheet(),self.operator)
        self.assertEqual([row['actual_sequence'] for row in result['stops']],[1,2])

    def test_lorry_reassignment_cannot_reuse_an_approved_route(self):
        self.save();self.p1.vehicle_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'no longer matches'):self.start()

    def test_close_requires_e5_settlement_and_preserves_all_route_history(self):
        self.save()
        with self.assertRaisesRegex(ValueError,'settle|Complete'):self.save('Close',expected_revision=1,event_token='CLOSE',reason='Trip ended')
        for row in self.sheet().stops:row.state='Skipped'
        for stop in self.data.get('CFG Kanban Route Stop',{}).values():stop.state='Skipped'
        for plan in (self.p1,self.p2):plan.state='Reconciled';plan.dispatch_review_state='Settled'
        result=self.save('Close',expected_revision=1,event_token='CLOSE',reason='Trip ended')
        self.assertEqual(result['sheet']['state'],'Completed');self.assertFalse(self.sheet().active_scope_key);self.assertEqual(len(self.sheet().stops),2)

    def test_legacy_template_execution_excludes_visit_only_stops(self):
        template=self.data['CFG Kanban Route Template']['TEMPLATE']
        template.stops.insert(1,Doc(stop_purpose='Visit Only',customer='C1',instructions='Collect info'))
        self.assertEqual([row['customer_scan_point'] for row in self.ns['template_snapshot']('TEMPLATE','B')['stops']],['S1','S2'])
        template.stops=[template.stops[1]]
        with self.assertRaisesRegex(ValueError,'Visit Only'):self.ns['template_snapshot']('TEMPLATE','B')

    def test_template_controller_increments_revision_only_for_business_sequence_change(self):
        import re, uuid
        office=load('services/delivery_trips.py',dict(self.common,re=re,uuid=uuid))
        office['_address']=lambda name,customer:''  # Address validation has dedicated office-trip coverage.
        namespace=load('cfg_kanban/doctype/cfg_kanban_route_template/cfg_kanban_route_template.py',
                       dict(self.common,Document=Doc,_company=office['_company'],validate_stops=office['validate_stops']))
        cls=namespace['CFGKanbanRouteTemplate']
        before=cls(name='T',company='B',active=1,revision=3,stops=[Doc(customer_scan_point='S1'),Doc(customer_scan_point='S2')])
        current=cls(dict(before,_before=before));current.validate();self.assertEqual(current.revision,3)
        current.stops=list(reversed(current.stops));current.validate();self.assertEqual(current.revision,4)

    def test_approved_sheet_allows_native_modified_timestamps_but_rejects_reordering(self):
        namespace=load('cfg_kanban/doctype/cfg_kanban_route_sheet/cfg_kanban_route_sheet.py',dict(self.common,Document=Doc))
        cls=namespace['CFGKanbanRouteSheet'];self.save();before=self.sheet()
        current=cls(dict(before,_before=before));current.stops=[Doc(dict(row,modified='new timestamp')) for row in before.stops]
        current.validate()
        current.stops.reverse()
        with self.assertRaisesRegex(ValueError,'cannot be reordered'):current.validate()
        with self.assertRaisesRegex(ValueError,'audit records'):current.on_trash()

    def test_e5_settled_unvisited_customers_close_as_incomplete_without_fake_delivery(self):
        self.save()
        for plan in (self.p1,self.p2):plan.state='Reconciled';plan.dispatch_review_state='Settled'
        context=self.ns['sheet_context'](self.sheet(),self.operator)
        self.assertEqual(context['state'],'Ready to Close')
        self.assertEqual([row['state'] for row in context['stops']],['Closed Incomplete','Closed Incomplete'])
        result=self.save('Close',expected_revision=1,event_token='CLOSE-INCOMPLETE',reason='E5 approved stock staying on lorry')
        self.assertEqual(result['sheet']['state'],'Completed')
        self.fulfilment.start_prepared_delivery.assert_not_called();self.routes.start_route_stop.assert_not_called()

    def test_per_plan_scope_remains_available_and_legacy_qr_default_is_preserved(self):
        self.p1.route_sequence_scope='Per Dispatch Plan';self.p1.profile_snapshot_json='{}'
        result=self.save(scope_key='P:P1',stops=self.rows[:1]);self.assertEqual(result['sheet']['scope'],'Per Dispatch Plan')
        self.assertEqual(result['sheet']['verification_policy'],'Require Customer Site QR')

if __name__=='__main__':unittest.main()


class TestDeliveryRouteScopeLock(unittest.TestCase):
    """Exercise the real delivery entry points, not only the Sheet wrapper."""
    def exercise(self, open_route):
        from cfg_kanban.tests import test_dispatch_fulfilment as e4a
        from cfg_kanban.tests import test_route_delivery as e4b
        fixture=e4b.TestRouteDelivery() if open_route else e4a.TestDispatchFulfilment()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        base=fixture.b if open_route else fixture
        base.plan.update(route_approval_required=1,route_sequence_scope='Combined Lorry Trip')
        calls=[]
        helpers=types.ModuleType('cfg_kanban.services.route_sheets')
        def scope_lock(plan,operator):
            calls.append(('scope',plan.vehicle_warehouse));return 'V:'+plan.vehicle_warehouse
        def check(plan,key):
            calls.append(('check',key));raise ValueError('Refresh changed lorry assignment')
        helpers.lock_plan_route_scope=scope_lock;helpers.check_plan_route_scope=check
        def locked(name,operator):
            calls.append(('plan',name));return base.plan
        with patch.dict(sys.modules,{helpers.__name__:helpers}):
            if open_route:
                with patch.object(fixture.route,'_locked_plan',side_effect=locked):
                    with self.assertRaisesRegex(ValueError,'changed lorry'):fixture.start()
            else:
                with patch.object(base.planning,'_locked_authorized_plan',side_effect=locked):
                    with self.assertRaisesRegex(ValueError,'changed lorry'):
                        base.bridge.start_prepared_delivery('PLAN','SITE-QR','START','SESSION')
        self.assertEqual(calls,[('scope','LORRY1'),('plan','PLAN'),('check','V:LORRY1')])
        self.assertFalse(base.data.get(e4a.SESSION))
    def test_known_customer_start_takes_scope_before_plan_and_rejects_changed_lorry(self):
        self.exercise(False)
    def test_open_route_start_takes_scope_before_plan_and_rejects_changed_lorry(self):
        self.exercise(True)

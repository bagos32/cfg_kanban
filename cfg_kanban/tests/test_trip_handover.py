"""Trip handover reads and close gates against offline permission/record doubles."""
import datetime
import sys
import types
import unittest
from unittest.mock import Mock,patch

from cfg_kanban.tests import test_vehicle_overview as fixture
from cfg_kanban.tests import test_office_delivery_trip as office


class TestTripHandover(unittest.TestCase):
    def setUp(self):
        self.b=fixture.TestVehicleOverview();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.data=self.b.data;self.operator=self.b.operator
        self.operator.update(kanban_role='Operator',can_start=1,can_complete=1,can_override=0)
        self.session=fixture.Row(name='SESSION',employee='DRIVER')
        self.trip=self.b.add('CFG Kanban Delivery Trip','KTRIP-1',company='B',driver='DRIVER',
            assistant_drivers=[],dispatch_plans=[fixture.Row(dispatch_plan='DPL')],
            open_route_plan=None,vehicle_warehouse='LORRY',state='Planned',trip_title='Trip',driver_route_state='Completed')
        self.plan=self.data['CFG Kanban Dispatch Plan']['DPL'];self.plan.office_delivery_trip=self.trip.name
        self.plan.active_dispatch_review=None
        self.reads=[];old=self.b.frappe.get_doc
        def get_doc(dt,name):
            self.reads.append((dt,name));return old(dt,name)
        self.b.frappe.get_doc=get_doc
        def get_list(dt,filters=None,pluck=None,**kw):
            rows=[row for row in self.data.get(dt,{}).values() if self.b.matches(row,filters) and not row.get('_hidden')]
            start=kw.get('limit_start',0);rows=rows[start:start+kw.get('limit_page_length',20)]
            return [r[pluck] for r in rows] if pluck else rows
        self.b.frappe.get_list=get_list
        original_matches=self.b.matches
        def matches(row,filters):
            filters=dict(filters)
            for key,value in list(filters.items()):
                if isinstance(value,list) and value[0]=='>' and isinstance(value[1],datetime.datetime):
                    if not row.get(key) or row[key]<=value[1]:return False
                    del filters[key]
            return original_matches(row,filters)
        self.b.matches=matches
        self.b.frappe.db=fixture.Row(get_value=self.value,exists=lambda dt,name:name in self.data.get(dt,{}))
        self.ns=fixture.load('services/trip_handover.py',dict(frappe=self.b.frappe,cint=lambda n:int(n or 0),
            flt=lambda n:float(n or 0),get_datetime=lambda value:value if isinstance(value,datetime.datetime) else datetime.datetime.fromisoformat(str(value)),now_datetime=lambda:datetime.datetime(2026,11,24,12),
            require_operator=Mock(return_value=(self.operator,self.session)),public_operator=lambda op,s:dict(op)))
        driver=types.ModuleType('cfg_kanban.services.driver_routes')
        driver.assigned=lambda trip,op:trip.driver==op.employee or any(row.employee==op.employee for row in trip.assistant_drivers)
        driver.trip_vehicle_warehouse=lambda trip:trip.vehicle_warehouse
        driver.trip_driver_display=lambda trip:'Driver ('+trip.driver+')'
        review=types.ModuleType('cfg_kanban.services.dispatch_reconciliation');review.REVIEW='CFG Kanban Dispatch Review'
        review._planning=lambda:fixture.Row(_assert_plan_authorized=Mock());review._hash=lambda rows:'HASH';review._balances=lambda plan:[dict(dispatch_allocation='ALLOC',item_code='BAG',
            handling_unit='TAG',loaded_qty=5,delivered_qty=3,remaining_qty=2)]
        mixed=types.ModuleType('cfg_kanban.services.dispatch_recovery_mixed');mixed.context=Mock(return_value=None)
        self.counts=sys.modules['cfg_kanban.services.route_reconciliation'];self.counts._authorized=lambda op:any(r.responsibility=='Logistics Reconciliation' for r in op.responsibilities)
        patcher=patch.dict(sys.modules,{driver.__name__:driver,review.__name__:review,mixed.__name__:mixed})
        patcher.start();self.addCleanup(patcher.stop)

    def value(self,dt,name,field):return self.data.get(dt,{}).get(name,{}).get(field)
    def read(self,name='KTRIP-1',**kwargs):return self.ns['get_trip_handover'](name,'TOKEN',**kwargs)
    def supervisor(self):
        self.operator.kanban_role='Supervisor';self.operator.can_override=1
        self.operator.responsibilities.append(fixture.Row(responsibility='Logistics Reconciliation'))
    def case(self,name='KRTN-1',**kwargs):
        return self.b.add('CFG Kanban Return Case',name,driver_trip='KTRIP-1',selling_company='B',customer='CUST',
            state='Awaiting QC Receipt',return_flow='Customer Return for QC',stock_already_owned=0,
            lines=[fixture.Row(item_code='BAG',stock_uom='Nos',claimed_qty=3,received_qty=0)],**kwargs)

    def test_assigned_driver_sees_read_only_prepared_and_native_stock_summary(self):
        result=self.read()
        self.assertFalse(result['can_manage']);self.assertEqual(result['trip']['driver'],'Driver (DRIVER)')
        self.assertEqual(result['plans'][0]['balances'][0]['remaining_qty'],2)
        self.assertTrue(result['lorry_stock']);self.assertIn(('Company','B'),self.reads)
        self.assertIn(('Warehouse','LORRY'),self.reads);self.assertIn(('CFG Kanban Handling Unit','TAG'),self.reads)

    def test_plan_summary_carries_actual_settlement_and_fulfilment_states_for_colour_cues(self):
        self.plan.update(state='Loaded',fulfilment_status='Completed',dispatch_review_state='Completed')
        plan=self.read()['plans'][0]
        self.assertEqual((plan['state'],plan['fulfilment_status'],plan['dispatch_review_state']),('Loaded','Completed','Completed'))
        self.plan.state='Reconciled';self.assertEqual(self.read()['plans'][0]['state'],'Reconciled')

    def test_assistant_allowed_unassigned_driver_rejected(self):
        self.trip.driver='LEAD'
        with self.assertRaisesRegex(ValueError,'not assigned'):self.read()
        self.trip.assistant_drivers=[fixture.Row(employee='DRIVER')]
        self.assertEqual(self.read()['trip']['name'],'KTRIP-1')

    def test_native_company_plan_tag_and_trip_denials_are_enforced(self):
        for dt,name in [('Company','B'),('Item','BAG'),('Batch','LOT'),('CFG Kanban Dispatch Plan','DPL'),('CFG Kanban Handling Unit','TAG'),('CFG Kanban Delivery Trip','KTRIP-1')]:
            self.data[dt][name]['_denied']=1
            with self.subTest(dt=dt),self.assertRaises(PermissionError):self.read()
            del self.data[dt][name]['_denied']

    def test_other_company_or_lorry_plan_cannot_be_combined(self):
        self.plan.company='A'
        with self.assertRaisesRegex(ValueError,'Company or lorry'):self.read()
        self.plan.company='B';self.plan.vehicle_warehouse='OTHER-LORRY'
        with self.assertRaisesRegex(ValueError,'Company or lorry'):self.read()

    def test_old_customer_returns_are_separate_custody_not_available_stock(self):
        self.case();result=self.read()
        self.assertEqual(result['returns'][0]['items'][0]['claimed_qty'],3)
        self.assertFalse(result['returns'][0]['stock_already_owned'])
        self.assertIn('non-stock custody',result['boundary'])
        self.assertEqual(result['plans'][0]['balances'][0]['remaining_qty'],2)

    def test_hidden_cases_not_leaked_and_read_denial_hides_return_worklist(self):
        self.case(_hidden=1)
        self.assertEqual(self.read()['returns'],[])
        self.b.frappe.has_permission=lambda *a,**kw:False
        self.assertEqual(self.read()['returns'],[])

    def test_plan_scan_resolves_exact_office_trip_and_rejects_stale_membership(self):
        self.assertEqual(self.read('DPL')['trip']['name'],'KTRIP-1')
        self.trip.dispatch_plans=[]
        with self.assertRaisesRegex(ValueError,'not a member'):self.read('DPL')

    def test_route_sheet_scan_groups_only_its_original_plans_for_one_count(self):
        self.plan.office_delivery_trip=None
        self.b.add('CFG Kanban Route Sheet','DRS-DEMO',company='B',vehicle_warehouse='LORRY',state='Ready to Close',
            stops=[fixture.Row(dispatch_plan='DPL')])
        with self.assertRaisesRegex(ValueError,'Supervisor'):self.read('DRS-DEMO')
        self.supervisor();result=self.read('DRS-DEMO')
        self.assertEqual(result['route_sheet']['name'],'DRS-DEMO');self.assertIsNone(result['trip'])
        self.assertEqual([row['name'] for row in result['plans']],['DPL'])

    def test_standalone_plan_requires_authorized_reconciliation_supervisor(self):
        self.plan.office_delivery_trip=None
        with self.assertRaisesRegex(ValueError,'standalone Plan'):self.read('DPL')
        self.supervisor();result=self.read('DPL')
        self.assertTrue(result['can_manage']);self.assertIsNone(result['trip'])

    def test_guide_opens_all_reviews_before_one_shared_count_and_advances_to_each_plan(self):
        self.supervisor()
        base=dict(self.read(),plans=[dict(name='ONE',state='Loaded',review=None,review_state=None,balances=[]),
                                   dict(name='TWO',state='Loaded',review=None,review_state=None,balances=[])])
        guide=self.ns['closure_guide'](base,'B','LORRY')
        self.assertEqual((guide['stage'],guide['plan']),(0,'ONE'))
        for plan in base['plans']:
            plan.update(review='R-'+plan['name'],review_state='Reviewing',review_opened_on=datetime.datetime(2026,11,24,10))
        self.assertEqual(self.ns['closure_guide'](base,'B','LORRY')['stage'],2)
        self.b.add('CFG Kanban Route Reconciliation','ONE-COUNT',company='B',vehicle_warehouse='LORRY',state='Closed',
                   closed_on=datetime.datetime(2026,11,24,11),lines=[])
        first=self.ns['closure_guide'](base,'B','LORRY')
        self.assertEqual((first['stage'],first['shared_count'],first['plan']),(3,'ONE-COUNT','ONE'))
        base['plans'][0]['state']='Reconciled'
        second=self.ns['closure_guide'](base,'B','LORRY')
        self.assertEqual((second['shared_count'],second['plan']),('ONE-COUNT','TWO'))
        self.b.add('Stock Ledger Entry','LATE',company='B',warehouse='LORRY',creation=datetime.datetime(2026,11,24,11,30))
        self.assertEqual(self.ns['closure_guide'](base,'B','LORRY')['stage'],2)

    def test_guide_names_unfinished_delivery_before_opening_review(self):
        self.supervisor()
        base=dict(self.read(),plans=[dict(name='ONE',state='Loaded',review=None,review_state=None,balances=[])])
        self.b.add('CFG Kanban Delivery Session','NEEDS-PROOF',dispatch_plan='ONE',state='Delivered')
        guide=self.ns['closure_guide'](base,'B','LORRY')
        self.assertEqual(guide['delivery_session'],'NEEDS-PROOF')
        self.assertIn('proof',guide['message'])

    def test_guide_requires_finished_movements_and_count_after_latest_review(self):
        self.supervisor()
        base=dict(self.read(),plans=[dict(name='ONE',state='Loaded',review='R',review_state='Reviewing',
            review_opened_on=datetime.datetime(2026,11,24,12),balances=[],mixed_recovery=dict(active=True,
            groups=[dict(manifest='MOVE',state='Prepared')]))])
        self.assertEqual(self.ns['closure_guide'](base,'B','LORRY')['manifest'],'MOVE')
        base['plans'][0]['mixed_recovery']['groups'][0]['state']='Received'
        self.b.add('CFG Kanban Route Reconciliation','OLD',company='B',vehicle_warehouse='LORRY',state='Closed',
                   closed_on=datetime.datetime(2026,11,24,11),lines=[])
        self.assertEqual(self.ns['closure_guide'](base,'B','LORRY')['stage'],2)

    def test_no_recount_guide_opens_document_closure_and_ignores_cancelled_plans(self):
        self.supervisor()
        base=dict(self.read(),plans=[dict(name='ONE',state='Loaded',review=None,balances=[],active_route_sheet='SHEET'),
                                   dict(name='OLD',state='Cancelled',review=None,balances=[])])
        guide=self.ns['closure_guide'](base,'B','LORRY')
        self.assertTrue(guide['bypass_count']);self.assertEqual(guide['route_sheet'],'SHEET')
        self.assertIn('no lorry recount',guide['message'])

    def test_count_opening_delegates_to_existing_d3_with_native_source_read_checks(self):
        self.counts.start_route_reconciliation=Mock(return_value={'name':'COUNT'})
        result=self.ns['start_handover_count']('B','LORRY','EVENT','TOKEN')
        self.assertEqual(result['name'],'COUNT')
        self.counts.start_route_reconciliation.assert_called_once_with('B','LORRY','EVENT','TOKEN')
        self.data['Warehouse']['LORRY']['_denied']=1
        with self.assertRaises(PermissionError):self.ns['start_handover_count']('B','LORRY','EVENT','TOKEN')
        self.assertEqual(self.counts.start_route_reconciliation.call_count,1)


class TestTripReturnReceiptGate(unittest.TestCase):
    def setUp(self):
        self.b=office.TestOfficeDeliveryTrip();self.b.setUp()
        self.trip=fixture.Row(name='KTRIP-1')
    def case(self,**kw):
        values=dict(driver_trip='KTRIP-1',return_flow='Customer Return for QC',state='Awaiting QC Receipt',stock_already_owned=0,received_on=None)
        values.update(kw);return self.b.add('CFG Kanban Return Case','CASE',**values)
    def check(self):return self.b.ns['_assert_return_custody_received'](self.trip)
    def test_unreceived_old_return_blocks_even_when_hidden_from_current_user(self):
        self.case(_hidden=1)
        with self.assertRaisesRegex(ValueError,'physical handover'):self.check()
    def test_physical_receipt_suffices_while_qc_and_accounting_continue(self):
        self.case(received_on='2026-11-24 12:00:00',state='QC In Progress',accounting_status='Pending')
        self.check()
    def test_company_owned_refusal_never_requires_duplicate_customer_stock_receipt(self):
        self.case(stock_already_owned=1);self.check()
    def test_cancelled_return_or_other_trip_does_not_block(self):
        self.case(state='Cancelled');self.check()
        self.case(driver_trip='OTHER');self.check()


if __name__=='__main__':unittest.main()

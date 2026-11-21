"""Shared optional visits retain native route approval and E5 count controls offline."""
import sys,types,unittest
from unittest.mock import patch
from cfg_kanban.tests import test_route_sheets as sheet
from cfg_kanban.tests import test_dispatch_reconciliation as review
from cfg_kanban.tests.test_vehicle_overview import load

class TestTripRouteScope(unittest.TestCase):
    def setUp(self):
        self.b=sheet.TestRouteSheets();self.b.setUp();self.data=self.b.data
        self.mod=types.ModuleType('cfg_kanban.services.trip_dispatch');load('services/trip_dispatch.py',self.mod.__dict__)
        p=patch.dict(sys.modules,{self.mod.__name__:self.mod});p.start();self.addCleanup(p.stop)
        for plan in (self.b.p1,self.b.p2):plan.office_delivery_trip='TRIP'
        self.b.p2.update(existing_lorry_stock_only=1,lines=[],state='Ready for Fulfilment')
        self.trip=self.b.add('CFG Kanban Delivery Trip','TRIP',company='B',open_route_plan='P2',
            dispatch_plans=[sheet.Doc(dispatch_plan='P1',stop_key='K1')],stops=[
            sheet.Doc(stop_key='K1',customer_scan_point='S1'),sheet.Doc(stop_key='K2',customer_scan_point='S2'),sheet.Doc(stop_key='K3',customer_scan_point='S2')])
        for n in (2,3):self.b.add('CFG Kanban Route Stop','VISIT'+str(n),dispatch_plan='P2',state='Planned',
            office_delivery_trip='TRIP',office_stop_key='K'+str(n),customer_scan_point='S2',planned_sequence=n)
        self.rows=self.b.ns['_office_trip_seeds']([self.b.p1,self.b.p2])
        for n,row in enumerate(self.rows,1):row['row_key']='R'+str(n)
    def test_initial_sheet_seeds_known_and_repeated_shared_visits_in_office_order(self):
        self.assertEqual([(r['dispatch_plan'],r.get('source_route_stop')) for r in self.rows],[('P1',None),('P2','VISIT2'),('P2','VISIT3')])
        context=self.b.ns['get_route_context']('TOKEN',warehouse='LORRY')
        self.assertEqual([r.get('source_route_stop') for r in context['stops']],[None,'VISIT2','VISIT3'])
    def test_native_approval_accepts_existing_stock_pool_and_reuses_exact_visits(self):
        self.b.save(stops=self.rows)
        self.assertEqual([r.source_route_stop for r in self.b.sheet().stops],[None,'VISIT2','VISIT3'])
        self.assertEqual(len(self.data['CFG Kanban Route Stop']),2)
        self.assertEqual(self.b.p2.state,'Ready for Fulfilment')
    def test_omitted_duplicate_or_outside_visit_cannot_approve_an_office_route(self):
        with self.assertRaisesRegex(ValueError,'every exact'):self.b.save(stops=self.rows[:2])
        changed=[dict(r) for r in self.rows];changed[2]['source_route_stop']='VISIT2'
        with self.assertRaisesRegex(ValueError,'every exact'):self.b.save(stops=changed)
    def test_empty_pool_is_not_ready_without_explicit_controlled_mode(self):
        self.b.p2.existing_lorry_stock_only=0
        with self.assertRaisesRegex(ValueError,'Load'):self.b.save(stops=self.rows)
    def test_e5_still_requires_fresh_lorry_count_for_existing_stock_pool(self):
        b=review.TestDispatchReconciliation();b.setUp();self.addCleanup(b.doCleanups)
        b.plan.update(office_delivery_trip='TRIP',existing_lorry_stock_only=1,state='Ready for Fulfilment',lines=[],movement_manifest=None)
        result=b.begin();self.assertEqual(result['balances'],[])
        b.supervisor();b.count();b.finish('No Remaining Prepared Stock')
        self.assertEqual(b.plan.state,'Reconciled');self.assertFalse(b.b.posted)

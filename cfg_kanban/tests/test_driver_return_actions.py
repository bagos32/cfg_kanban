"""Driver mutation receipts/permissions over actual orchestration; custody engine is tested separately."""
import copy
import sys
import types
import unittest
from unittest.mock import Mock, patch
from cfg_kanban.tests import test_driver_route_actions as native
from cfg_kanban.tests.test_vehicle_overview import Row


class TestDriverReturnActions(unittest.TestCase):
    def setUp(self):
        self.b=native.TestDriverRouteActions();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.b.start()
        self.collections=types.ModuleType('cfg_kanban.services.driver_collections')
        self.collections.collect=Mock(return_value={'return_case':'RETURN1'})
        self.collections.context=Mock(return_value={'company':'A','customer':'C1'})
        self.collections.preview=Mock(return_value={'company':'A','lines':[]})
        self.outcome=types.ModuleType('cfg_kanban.services.driver_delivery_outcomes')
        self.outcome.OUTCOME='CFG Kanban Delivery Outcome';self.outcome.release=Mock();self.outcome.declare=Mock()
        self.outcome.quantities=Mock(return_value=[{'accepted_qty':3,'refused_qty':1}])
        self.outcome.full_refusal=lambda delivery:True
        self.outcome.refused_by_source=lambda delivery:{'ALLOC1':{'refused_qty':4,'stock_state':'Held','outcome':'OUT'}}
        p=patch.dict(sys.modules,{self.collections.__name__:self.collections,self.outcome.__name__:self.outcome});p.start();self.addCleanup(p.stop)
        self.scope=self.b.context()
        self.doc=self.b.b.add(self.outcome.OUTCOME,'OUT',delivery_trip=self.b.trip.name,stop_key=self.b.v.keys[0],lines=[])
    def request(self,action='Collect Old Return',payload=None):
        return dict(trip_name=self.b.trip.name,action=action,event_token='COLLECT1',operator_session_token='TOKEN',
            scope_hash=self.scope['scope_hash'],expected_revision=self.scope['revision'],stop_key=self.b.v.keys[0],dispatch_plan=None,payload=payload or {})
    def test_collection_result_is_receipted_and_replays_without_duplicate_intake(self):
        request=self.request(payload={'lines':[{'item_code':'ITEM','claimed_qty':3}]})
        first=self.b.perform(request);again=self.b.perform(request)
        self.assertEqual(first,again);self.assertEqual(first['result']['return_case'],'RETURN1');self.collections.collect.assert_called_once()
        self.assertFalse(self.b.calls);self.assertFalse(self.b.trip.stops[0].driver_completed_on)
        changed=copy.deepcopy(request);changed['payload']['lines'][0]['claimed_qty']=4
        with self.assertRaises(ValueError):self.b.perform(changed)
        self.collections.collect.assert_called_once()
    def test_collection_receipt_survives_mutable_assignment_change(self):
        request=self.request();first=self.b.perform(request);self.b.trip.driver='OTHER'
        self.assertEqual(self.b.perform(request),first);self.collections.collect.assert_called_once()
    def test_new_collection_requires_assignment_action_flag_and_current_revision(self):
        request=self.request();self.b.operator.can_start=0
        with self.assertRaises(PermissionError):self.b.perform(request)
        self.b.operator.can_start=1;self.b.trip.driver='OTHER'
        with self.assertRaises(PermissionError):self.b.perform(request)
        self.collections.collect.assert_not_called()
    def test_collection_stale_revision_and_plan_substitution_reject_before_intake(self):
        for changed in [{'expected_revision':0},{'dispatch_plan':'PLAN1'},{'stop_key':'OTHER'}]:
            request=self.request();request.update(changed)
            with self.assertRaises(ValueError):self.b.perform(request)
        self.collections.collect.assert_not_called()
    def test_supervisor_release_has_exact_outcome_stop_scope_and_receipt(self):
        request=self.request('Release Refused Stock',{'outcome':'OUT','line_names':['LINE'],'reason':'Sound stock'})
        with self.assertRaises(PermissionError):self.b.perform(request)
        self.b.operator.update(can_override=1,kanban_role='Supervisor',view_all_responsibilities=1)
        result=self.b.perform(request);self.assertEqual(result['result']['outcome'],'OUT');self.b.perform(request)
        self.outcome.release.assert_called_once()
        args=self.outcome.release.call_args.args;self.assertEqual(args[1:3],(['LINE'],'Sound stock'))
    def test_supervisor_cannot_release_another_trip_outcome(self):
        self.b.operator.update(can_override=1,kanban_role='Supervisor',view_all_responsibilities=1);self.doc.delivery_trip='OTHER'
        with self.assertRaisesRegex(ValueError,'another trip'):self.b.perform(self.request('Release Refused Stock',{'outcome':'OUT','line_names':['LINE'],'reason':'Release'}))
        self.outcome.release.assert_not_called()
    def test_begin_records_decision_before_native_delivery_and_has_one_receipt(self):
        request=self.b.request('Begin Delivery',customer_scan='QR1',quantities=[{'dispatch_allocation':'ALLOC1','accepted_qty':3,'condition':'Good / Unwanted','refusal_reason':'Downsize'}])
        result=self.b.perform(request);self.b.perform(request)
        self.outcome.declare.assert_called_once();self.b.prepared.start_prepared_delivery.assert_called_once()
        self.assertTrue(result['result']['delivery_session']);self.assertEqual(self.outcome.declare.call_args.args[3][0]['accepted_qty'],3)
    def test_zero_accepted_native_closed_session_can_complete_without_fabricated_dn(self):
        session=self.b.v.delivery(n=1,state='Closed',qty=0);session.update(driver_delivery_outcome='OUT',source_warehouse='LORRY',delivery_note=None)
        self.b.v.p1.fulfilment_status='Completed';self.b.v.p1.driver_delivery_outcome='OUT'
        self.assertTrue(self.b.ns['_is_ready'](self.b.trip,self.b.trip.stops[0],self.b.operator,'TOKEN'))
        session.state='Delivered';self.assertFalse(self.b.ns['_is_ready'](self.b.trip,self.b.trip.stops[0],self.b.operator,'TOKEN'))

if __name__=='__main__':unittest.main()

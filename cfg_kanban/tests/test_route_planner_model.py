"""Provider contract and bounded data modelling, with no Frappe or network dependency."""
import copy
import datetime as dt
import unittest

from cfg_kanban.services import route_planner_model as m
from cfg_kanban.tests.test_route_sheets import Doc


def snapshot():
    return dict(trip=dict(name='TRIP', company='A', trip_date='2026-11-22', expected_return_date='',
        sequence_policy='Flexible Order', planner_enabled=1, planner_load_verified=1),
        settings=dict(enabled=1, provider=m.PROVIDER, max_stops=20, shift_start='08:00', shift_end='18:00',
            capacity_grams=100000, gates_verified=1, start_pin=dict(latitude=3.004, longitude=101.394),
            end_pin=dict(latitude=3.004, longitude=101.394)),
        stops=[dict(stop_key='STOP_KEY_'+str(i), site_name='Private shop '+str(i), pin_verified=1,
            stop_purpose='Delivery', cancelled=False, pin=dict(latitude=3+i/100,longitude=101.5),
            planner_service_minutes='10', planner_window_start='08:00', planner_window_end='17:30',
            planner_finish_by_close=1) for i in (1,2)],
        lines=[dict(sales_order='PRIVATE-SO'+str(i), sales_order_item='ROW'+str(i), item_code='PRIVATE-SKU',
            stop_key='STOP_KEY_'+str(i), is_stock_item=1, planned_qty='3', planner_grams_per_stock_uom='1500') for i in (1,2)], errors=[])


class TestRoutePlannerModel(unittest.TestCase):
    def test_fixture_reverses_flexible_visits_without_mutating_or_exposing_business_ids(self):
        source=snapshot(); before=copy.deepcopy(source); result=m.readiness(source)
        self.assertTrue(result['ready'],result['errors']); self.assertEqual(result['total_load_grams'],9000)
        payload=result['model']; response=m.mock_solve(payload)
        self.assertEqual(m.validate_proposal(payload,response),['S0002','S0001'])
        self.assertEqual(source,before)
        for private in ('PRIVATE-SO','PRIVATE-SKU','Private shop','STOP_KEY','TRIP'):
            self.assertNotIn(private,m.encode(payload))

    def test_repeated_customer_pin_keeps_two_distinct_visits(self):
        source=snapshot(); source['stops'][1]['pin']=source['stops'][0]['pin']
        result=m.readiness(source);self.assertTrue(result['ready'])
        self.assertEqual(len(result['model']['shipments']),2)

    def test_planned_order_is_preserved_and_changed_order_rejected(self):
        source=snapshot();source['trip']['sequence_policy']='Planned Order'
        payload=m.readiness(source)['model'];response=m.mock_solve(payload)
        self.assertEqual(m.validate_proposal(payload,response),['S0001','S0002'])
        response['visits'].reverse()
        with self.assertRaisesRegex(ValueError,'Planned Order'):m.validate_proposal(payload,response)

    def test_missing_pin_verification_load_and_windows_are_exact_blockers(self):
        source=snapshot();source['stops'][0].update(pin=None,pin_verified=0)
        source['stops'][1]['planner_window_end']='07:00'
        source['trip']['planner_load_verified']=0
        result=m.readiness(source)
        self.assertFalse(result['ready']);self.assertIsNone(result['model'])
        self.assertTrue(any('Stop 1' in error and 'Verify' in error for error in result['errors']))
        self.assertTrue(any('Stop 2' in error and 'window' in error for error in result['errors']))
        self.assertTrue(any('packed-weight' in error for error in result['errors']))

    def test_overweight_and_fractional_grams_never_understate_load(self):
        source=snapshot();source['settings']['capacity_grams']=8999
        self.assertTrue(any('exceeds' in e for e in m.readiness(source)['errors']))
        source=snapshot();source['lines'][0].update(planned_qty='0.000001',planner_grams_per_stock_uom='0.000001')
        result=m.readiness(source);self.assertEqual(result['model']['shipments'][0]['load_grams'],1)

    def test_non_finite_negative_and_missing_conversion_are_rejected(self):
        for value in ('NaN','Infinity','-1','0','',True):
            with self.subTest(value=value):
                source=snapshot();source['lines'][0]['planner_grams_per_stock_uom']=value
                result=m.readiness(source);self.assertFalse(result['ready'])
                self.assertTrue(any('PRIVATE-SO1' in e for e in result['errors']))

    def test_multi_day_optional_visit_duplicate_identity_and_limit_are_blocked(self):
        for change in ('day','visit','identity','limit','duplicate_line'):
            with self.subTest(change=change):
                source=snapshot()
                if change=='day':source['trip']['expected_return_date']='2026-11-23'
                if change=='visit':source['stops'][0]['stop_purpose']='Visit Only'
                if change=='identity':source['stops'][1]['stop_key']=source['stops'][0]['stop_key']
                if change=='limit':source['settings']['max_stops']=1
                if change=='duplicate_line':source['lines'].append(copy.deepcopy(source['lines'][0]))
                self.assertFalse(m.readiness(source)['ready'])

    def test_finish_by_close_reduces_latest_start_and_time_is_dated_malaysia(self):
        source=snapshot();source['stops'][0].update(planner_window_end='09:00',planner_service_minutes='20')
        payload=m.readiness(source)['model']
        self.assertEqual(payload['shipments'][0]['latest_start'],'2026-11-22T08:40:00+08:00')
        self.assertEqual(m.clock(dt.timedelta(hours=8),dt.date(2026,11,22)).hour,8)

    def test_invalid_provider_results_cannot_be_accepted(self):
        payload=m.readiness(snapshot())['model'];valid=m.mock_solve(payload)
        for change in ('vehicle','missing','duplicate','unknown','skipped','late','undated','early_return'):
            with self.subTest(change=change):
                result=copy.deepcopy(valid)
                if change=='vehicle':result['vehicle_label']='OTHER'
                if change=='missing':result['visits'].pop()
                if change=='duplicate':result['visits'][1]['shipment_label']=result['visits'][0]['shipment_label']
                if change=='unknown':result['visits'][0]['shipment_label']='S9999'
                if change=='skipped':result['skipped_shipments']=['S0001']
                if change=='late':result['visits'][0]['start_time']='2026-11-22T19:00:00+08:00'
                if change=='undated':result['visits'][0]['start_time']='08:00'
                if change=='early_return':result['end_time']='2026-11-22T08:00:00+08:00'
                with self.assertRaises(ValueError):m.validate_proposal(payload,result)

    def test_old_default_off_trip_can_save_but_acceptance_facts_cannot_be_forged(self):
        doc=Doc(state='Planned',stops=[],orders=[],dispatch_plans=[],flags=Doc())
        before=Doc(doc);m.protect_trip_metadata(doc,before)
        doc.planner_accepted_run='FAKE'
        with self.assertRaisesRegex(ValueError,'controlled'):m.protect_trip_metadata(doc,before)

    def test_planning_metadata_is_frozen_after_dispatch_generation(self):
        before=Doc(state='Draft',stops=[],orders=[],dispatch_plans=[Doc(dispatch_plan='PLAN')])
        doc=Doc(before);doc.flags=Doc();doc.planner_enabled=1
        with self.assertRaisesRegex(ValueError,'before generating'):m.protect_trip_metadata(doc,before)

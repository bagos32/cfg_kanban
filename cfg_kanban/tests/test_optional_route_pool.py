"""Optional shared stock requests and cancelled-empty departure, using offline records."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch

from cfg_kanban.tests import test_trip_dispatch as generation
from cfg_kanban.tests import test_trip_sales as sales_fixture
from cfg_kanban.tests import test_driver_route_actions as driver_fixture
from cfg_kanban.tests.test_vehicle_overview import load,ROOT

PLAN='CFG Kanban Dispatch Plan'


def snapshot(value):
    if isinstance(value,dict):return {key:snapshot(item) for key,item in dict.items(value) if not key.startswith('_')}
    if isinstance(value,list):return [snapshot(item) for item in value]
    return copy.deepcopy(value)


class TestOptionalPoolGeneration(unittest.TestCase):
    def setUp(self):
        self.t=generation.TestTripDispatch();self.t.setUp();self.addCleanup(self.t.doCleanups)
        self.trip=self.t.trip;self.data=self.t.data

    def test_default_off_visit_only_stop_does_not_create_empty_plan_or_require_open_profile(self):
        self.trip.allow_existing_lorry_sales=0;self.trip.open_route_profile=None
        self.t.generate()
        self.assertEqual(len(self.t.plans()),1);self.assertFalse(self.trip.open_route_plan)
        self.assertFalse(self.data.get('CFG Kanban Route Stop'))
        self.assertEqual(self.trip.stops[1].stop_purpose,'Visit Only');self.t.ledger.assert_not_called()

    def test_missing_legacy_option_is_off_for_new_generation_and_explicit_opt_in_still_works(self):
        self.trip.pop('allow_existing_lorry_sales',None);self.t.generate()
        self.assertFalse(self.trip.open_route_plan)
        self.trip.allow_existing_lorry_sales=1;self.t.generate(explicit=True)
        pool=self.data[PLAN][self.trip.open_route_plan]
        self.assertTrue(pool.existing_lorry_stock_only);self.assertFalse(pool.lines)
        self.assertEqual(pool.state,'Ready for Fulfilment');self.assertEqual(len(self.t.plans()),2)
        self.t.ledger.assert_not_called()

    def test_explicit_existing_stock_request_keeps_profile_approval(self):
        self.t.open.approval_required=1;self.t.generate()
        pool=self.data[PLAN][self.trip.open_route_plan]
        self.assertEqual(pool.state,'Awaiting Approval');self.assertFalse(self.t.mod.route_ready(pool))

    def test_extra_goods_create_real_loading_plan_even_when_optional_existing_stock_sales_are_off(self):
        self.trip.allow_existing_lorry_sales=0
        self.trip.route_stock=[generation.base.Doc(item_code='ITEM2',qty=3,stock_uom='Nos')]
        self.t.mod.validate_setup(self.trip);self.t.generate()
        pool=self.data[PLAN][self.trip.open_route_plan]
        self.assertFalse(pool.existing_lorry_stock_only);self.assertEqual(pool.lines[0].requested_qty,3)
        self.assertEqual(pool.state,'Approved');self.t.ledger.assert_not_called()

    def test_cancelled_empty_opt_in_is_not_recreated_on_refresh_and_keeps_audit(self):
        self.t.generate();pool=self.data[PLAN][self.trip.open_route_plan]
        pool.update(state='Cancelled',cancellation_reason='Optional sales not needed',cancelled_by_operator='SUPERVISOR')
        before=copy.deepcopy(pool.as_dict());names=[row.name for row in self.t.plans()]
        self.t.generate(explicit=True)
        self.assertFalse(self.trip.open_route_plan);self.assertEqual(names,[row.name for row in self.t.plans()])
        self.assertEqual(before,pool.as_dict());self.t.ledger.assert_not_called()

    def test_turning_off_unused_optional_context_retires_it_through_existing_audit(self):
        self.t.generate();pool=self.data[PLAN][self.trip.open_route_plan]
        self.trip.allow_existing_lorry_sales=0;self.t.generate(explicit=True)
        self.assertEqual(pool.state,'Cancelled');self.assertFalse(self.trip.open_route_plan)
        self.assertEqual(len(self.t.plans()),2);self.t.ledger.assert_not_called()

    def test_absent_and_zero_option_preserve_legacy_departure_hash_input(self):
        self.trip.pop('allow_existing_lorry_sales',None)
        legacy=self.t.office._business(self.trip)
        self.trip.allow_existing_lorry_sales=0
        self.assertEqual(legacy,self.t.office._business(self.trip))
        self.trip.allow_existing_lorry_sales=1
        self.assertNotEqual(legacy,self.t.office._business(self.trip))

    def test_native_office_checkbox_is_default_off_and_in_the_form_order(self):
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.json').read_text())
        field=next(row for row in schema['fields'] if row['fieldname']=='allow_existing_lorry_sales')
        self.assertEqual((field['fieldtype'],field['default']),('Check','0'))
        self.assertEqual(schema['field_order'].count(field['fieldname']),1)


class TestCancelledEmptyPoolDeparture(unittest.TestCase):
    def setUp(self):
        self.t=sales_fixture.TestTripSales();self.t.setUp();self.addCleanup(self.t.doCleanups)
        self.t.existing_only();self.t.plan.update(state='Cancelled',cancellation_reason='No extra stock',cancelled_by_operator='SUPERVISOR',
            total_requested_qty=0,total_reserved_qty=0,total_loaded_qty=0,total_delivered_qty=0,
            route_stock_commitment=0,prepared_stock_commitment=0)
        # The native fixture starts with a real loaded Plan. This case instead
        # represents an empty generated context that has never had a Manifest.
        for name,row in list(self.t.data.get('CFG Kanban Movement Manifest',{}).items()):
            if row.dispatch_plan==self.t.plan.name:del self.t.data['CFG Kanban Movement Manifest'][name]

    def stock(self):
        return {dt:{name:snapshot(row) for name,row in self.t.data.get(dt,{}).items()} for dt in
            ('Stock Entry','Delivery Note','Stock Ledger Entry','CFG Kanban Movement Manifest',
             'CFG Kanban Handling Unit','CFG Kanban Handling Unit Quantity Ledger','CFG Kanban Dispatch Allocation')}

    def test_cancelled_empty_plan_does_not_block_start_repeat_or_information_visit_completion(self):
        plan=snapshot(self.t.plan);stock=self.stock();visits={n:snapshot(r) for n,r in self.t.data[sales_fixture.native.STOP].items()}
        context=self.t.actual_view('TRIP','TOKEN');self.assertIsNone(context['open_pool'])
        request=self.t.request('Start Route');self.t.act.perform_driver_action(**request);self.t.act.perform_driver_action(**request)
        self.assertEqual(self.t.trip.driver_route_state,'In Progress')
        self.assertNotIn('open_pool',json.loads(self.t.trip.driver_route_snapshot_json))
        next_step=self.t.act.driver_action_context('TRIP','TOKEN',self.t.trip.stops[0].stop_key)
        self.assertEqual(next_step['next_step'],'Complete Stop')
        self.t.run_action('Complete Stop')
        self.assertTrue(self.t.trip.stops[0].driver_completed_on)
        self.assertEqual(plan,snapshot(self.t.plan));self.assertEqual(stock,self.stock())
        self.assertEqual(visits,{n:snapshot(r) for n,r in self.t.data[sales_fixture.native.STOP].items()})
        self.assertFalse(self.t.data.get('Delivery Note'));self.assertFalse(self.t.data.get(sales_fixture.e4.SESSION))

    def test_cancelled_real_goods_plan_is_not_treated_as_an_unused_context(self):
        self.t.plan.lines=[sales_fixture.e4.Row(item_code='ITEM',requested_qty=2)]
        with self.assertRaisesRegex(ValueError,'Cancelled shared Plan'):self.t.start()
        self.assertEqual(self.t.trip.driver_route_state,'Not Started')

    def test_cancelled_real_goods_history_remains_readable_without_selling_or_reopening_it(self):
        self.t.plan.lines=[sales_fixture.e4.Row(item_code='ITEM',requested_qty=2)]
        self.t.trip.update(state='Closed',driver_route_state='Closed Incomplete')
        view=self.t.actual_view('TRIP','TOKEN')
        self.assertEqual(view['open_pool']['state'],'Cancelled')
        self.assertTrue(all(not stop.get('can_open_sale') for stop in view['stops']))

    def test_cancelled_empty_shape_with_quantity_commitment_or_approval_scope_keeps_blocker(self):
        for field,value in (('total_loaded_qty',1),('total_delivered_qty',1),('total_reserved_qty',1),
                ('prepared_stock_commitment',1),('route_stock_commitment',1),('visits_started',1),
                ('active_route_sheet','SHEET-REVIEW'),('active_dispatch_review','REVIEW'),('exception','UNRESOLVED')):
            with self.subTest(field=field):
                old=self.t.plan.get(field);self.t.plan[field]=value
                with self.assertRaisesRegex(ValueError,'Cancelled shared Plan'):self.t.start()
                self.assertEqual(self.t.trip.driver_route_state,'Not Started');self.t.plan[field]=old

    def test_unfinished_reservation_manifest_session_visit_or_pack_cannot_be_hidden_by_empty_header(self):
        cases=[('CFG Kanban Dispatch Allocation',{'state':'Reserved'}),('CFG Kanban Movement Manifest',{'state':'Draft'}),
            ('CFG Kanban Delivery Session',{'state':'Cancelled'}),('CFG Kanban Route Stop',{'state':'In Progress'}),
            ('CFG Kanban Loose Tag',{'state':'Packed'})]
        for dt,values in cases:
            with self.subTest(doctype=dt):
                self.t.b.add(dt,'UNRESOLVED',dispatch_plan=self.t.plan.name,**values)
                with self.assertRaisesRegex(ValueError,'Cancelled shared Plan'):self.t.start()
                self.assertEqual(self.t.trip.driver_route_state,'Not Started')
                del self.t.data[dt]['UNRESOLVED']

    def test_released_reservation_audit_is_retained_and_does_not_block_unused_cancelled_context(self):
        row=self.t.b.add('CFG Kanban Dispatch Allocation','RELEASED',dispatch_plan=self.t.plan.name,state='Released',allocated_qty=0)
        before=copy.deepcopy(row.as_dict());self.t.start()
        self.assertEqual(before,row.as_dict());self.assertEqual(self.t.trip.driver_route_state,'In Progress')

    def test_active_unapproved_existing_stock_request_still_blocks_even_with_empty_goods(self):
        self.t.plan.state='Awaiting Approval'
        with self.assertRaises(ValueError):self.t.start()
        self.assertEqual(self.t.trip.driver_route_state,'Not Started')

    def test_resolved_exception_and_terminal_route_sheet_are_retained_as_nonblocking_history(self):
        self.t.b.add('CFG Kanban Exception','RESOLVED',status='Resolved')
        self.t.b.add('CFG Kanban Route Sheet','OLD-SHEET',state='Completed')
        self.t.plan.update(exception='RESOLVED',active_route_sheet='OLD-SHEET')
        before=snapshot(self.t.plan);self.t.start()
        self.assertEqual(before,snapshot(self.t.plan));self.assertEqual(self.t.trip.driver_route_state,'In Progress')

    def test_legacy_active_pool_remains_available_when_new_option_defaults_to_zero(self):
        self.t.plan.state='Approved';self.t.trip.allow_existing_lorry_sales=0
        self.t.start()
        self.assertIn('open_pool',json.loads(self.t.trip.driver_route_snapshot_json))
        self.assertEqual(self.t.plan.state,'Ready for Fulfilment')


class TestMixedCustomerRouteWithCancelledPool(unittest.TestCase):
    def setUp(self):
        self.t=driver_fixture.TestDriverRouteActions();self.t.setUp()
        common=dict(self.t.b.ns);common.update(canonical_key=driver_fixture.canonical)
        self.office=types.ModuleType('cfg_kanban.services.delivery_trips');self.office.__dict__.update(self.t.b.ns)
        self.gen=types.ModuleType('cfg_kanban.services.trip_dispatch')
        self.gen.__dict__.update(load('services/trip_dispatch.py',dict(common)));self.gen._office=lambda:self.office
        self.sales=types.ModuleType('cfg_kanban.services.trip_sales');self.sales.__dict__.update(load('services/trip_sales.py',dict(common)))
        self.sales._office=lambda:self.office
        p=patch.dict(sys.modules,{self.office.__name__:self.office,self.gen.__name__:self.gen,self.sales.__name__:self.sales});p.start();self.addCleanup(p.stop)
        self.plan=self.t.b.add(PLAN,'CANCELLED-POOL',company='A',office_delivery_trip=self.t.trip.name,
            state='Cancelled',plan_type='Open Route Stock',fulfilment_mode='Vehicle Delivery',existing_lorry_stock_only=1,
            lines=[],movement_manifest=None,vehicle_warehouse='UNUSED-OLD-LORRY',cancellation_reason='No optional stock')
        self.t.trip.open_route_plan=self.plan.name

    def test_loaded_customer_deliveries_start_without_binding_cancelled_empty_old_lorry(self):
        before=copy.deepcopy(self.plan.as_dict());counts={dt:len(self.t.data.get(dt,{})) for dt in
            ('Stock Entry','Delivery Note','Stock Ledger Entry','CFG Kanban Movement Manifest')}
        view=self.t.v.read();self.assertIsNone(view['open_pool']);self.assertEqual(view['vehicle_warehouse'],'LORRY')
        self.t.start();self.assertEqual(self.t.trip.vehicle_warehouse,'LORRY');self.assertEqual(self.t.trip.driver_route_state,'In Progress')
        self.assertEqual(before,self.plan.as_dict())
        self.assertEqual(counts,{dt:len(self.t.data.get(dt,{})) for dt in counts})

    def test_cancelled_context_does_not_bypass_order_loading_approval_or_operator_checks(self):
        for mutation in ('unloaded','approval','operator'):
            with self.subTest(mutation=mutation):
                if mutation=='unloaded':self.t.v.p1.state='Approved'
                elif mutation=='approval':self.t.v.p1.route_approval_required=1
                else:self.t.operator.can_start=0
                with self.assertRaises((ValueError,PermissionError)):self.t.start()
                self.assertEqual(self.t.trip.driver_route_state,'Not Started')
                self.t.v.p1.state='Loaded';self.t.v.p1.route_approval_required=0;self.t.operator.can_start=1


if __name__=='__main__':unittest.main()

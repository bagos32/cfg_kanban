"""Actual Material Run classification/preview functions with offline Frappe doubles."""
import math
import re
from unittest.mock import Mock
from cfg_kanban.tests.test_operation_hoppers import HopperHarness, Row
from cfg_kanban.tests.test_material_actuals_yield import functions


class TestMaterialRunScanRouting(HopperHarness):
    def setUp(self):
        super().setUp()
        self.frappe._dict=Row
        self.pack.material_run_output_boundary='Every Material Run'
        self.rules=[Row(rule_row='BAG-RULE',item_code='BAG',stock_uom='Nos',scan_warehouse='Production',qty_per_output=1)]
        self.doc('CFG Kanban Handling Unit','BAG-HU',handling_unit_id='BAG_1',tag_kind='Main Stock Tag',item_code='BAG',stock_uom='Nos',
            inventory_company='CFG',current_warehouse='Production',identity_state='Active',quality_state='Released',available_qty=10,
            current_qty=10,batch_no='BATCH',source_boundary='OLD-BAG-BOUNDARY')
        self.modules['cfg_kanban.services.container_contents'].assert_not_loaded_in_container=lambda *args:None
        self.rotation=Mock(return_value={})
        self.ns=functions('services/operation_material_runs.py',[
            '_normalise_draw_requests','identify_material_run_scan','preview_material_draw','_normalise_boundary','_resolve_material_source','_match_source_rule','_draw_preview_payload'],{
            'frappe':self.frappe,'_':lambda x:x,'flt':lambda x:float(x or 0),'math':math,'re':re,'TOLERANCE':0.000001,
            'require_operator':self.modules['cfg_kanban.services.operator_auth'].require_operator,'_assert_enabled':Mock(),
            'material_run_rules':lambda execution:self.rules,'_operationally_available_source_qty':lambda unit:float(unit.available_qty),
            'validate_material_rotation':self.rotation})
    def scan(self,value,qty=0,**kwargs):
        return self.ns['identify_material_run_scan']('PACK',value,quantity=qty,operator_session_token='SESSION',**kwargs)
    def test_material_is_recognised_before_output_boundary_and_before_hopper(self):
        self.load_hopper(qty=3)
        result=self.scan('BAG_1',5)
        self.assertEqual((result['scan_type'],result['preview']['rule_row'],result['preview']['qty']),('Material','BAG-RULE',5))
        self.assertNotIn('CFG Kanban Operation Material Draw',self.data)
    def test_source_first_requires_no_invented_quantity_or_reservation(self):
        result=self.scan('BAG_1')
        self.assertEqual((result['scan_type'],result['preview']['qty']),('Material',0))
        self.assertEqual(self.data['CFG Kanban Handling Unit']['BAG-HU'].available_qty,10)
        self.rotation.assert_called_once()
    def test_hopper_and_its_planned_run_quantity_are_separate_from_raw_draws(self):
        run,_fill=self.load_hopper(qty=3);run.output_serial_boundary='OLD-RINSE-BOUNDARY'
        result=self.scan('HOPPER_1',5)
        self.assertEqual(result['scan_type'],'Hopper')
        self.assertEqual(result['preview']['source_boundary'],'OLD-RINSE-BOUNDARY')
        self.assertNotIn('boundary',result)
        self.assertEqual((result['preview']['loaded_qty'],result['preview']['run_qty']),(3,3))
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_reserved_qty,0)
    def test_new_boundary_never_inherits_incoming_source_boundary(self):
        self.scan('BAG_1',5)
        result=self.scan('NEW-PACK-BOUNDARY')
        self.assertEqual(result,{'scan_type':'Boundary','boundary':'NEW-PACK-BOUNDARY'})
        self.assertEqual(self.data['CFG Kanban Handling Unit']['BAG-HU'].source_boundary,'OLD-BAG-BOUNDARY')
    def test_wrong_item_warehouse_quality_and_overdraw_do_not_become_boundary(self):
        unit=self.data['CFG Kanban Handling Unit']['BAG-HU']
        for key,value in [('item_code','OTHER'),('current_warehouse','OTHER'),('quality_state','Hold')]:
            previous=unit[key];unit[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.scan('BAG_1',5)
            unit[key]=previous
        with self.assertRaisesRegex(ValueError,'available'):self.scan('BAG_1',11)
    def test_expiry_rotation_rejection_remains_authoritative(self):
        self.rotation.side_effect=ValueError('Expired source')
        with self.assertRaisesRegex(ValueError,'Expired source'):self.scan('BAG_1')
    def test_hopper_wrong_work_order_is_not_silently_treated_as_boundary(self):
        _,fill=self.load_hopper(qty=3);fill.work_order='OTHER'
        with self.assertRaisesRegex(ValueError,'another Work Order'):self.scan('HOPPER_1')
    def test_native_stock_loaded_in_a_hopper_matches_its_material_instead(self):
        containers=self.modules['cfg_kanban.services.container_contents'];unit=self.data['CFG Kanban Handling Unit']['HU-1']
        self.native[unit.name]=['NATIVE']
        containers.production_output_content=lambda name:(unit,self.data['CFG Kanban Handling Unit']['BAG-HU'],None)
        containers.validate_production_container_location=lambda *args:None
        result=self.scan('HOPPER_1',5)
        self.assertEqual((result['scan_type'],result['preview']['item_code'],result['preview']['physical_container_code']),('Material','BAG','HOPPER_1'))
    def test_none_policy_does_not_ask_for_or_accept_an_accidental_boundary(self):
        self.pack.material_run_output_boundary='None'
        with self.assertRaisesRegex(ValueError,'no new output boundary'):self.scan('UNKNOWN')
        with self.assertRaisesRegex(ValueError,'not configured'):self.scan('NEW',capture_boundary=1)
    def test_explicit_boundary_capture_and_invalid_control_inputs(self):
        self.assertEqual(self.scan('SERIAL-1',capture_boundary=1)['boundary'],'SERIAL-1')
        for value in ('CFG:CMD:INVALID','CFG:QTY:MATERIAL:3','BAD\nCODE','X'*141):
            with self.subTest(value=value),self.assertRaises(ValueError):self.scan(value,capture_boundary=1)
    def test_numeric_stock_tag_identity_remains_an_item_not_a_boundary(self):
        self.data['CFG Kanban Handling Unit']['BAG-HU'].handling_unit_id='12345'
        self.assertEqual(self.scan('12345')['scan_type'],'Material')
    def test_duplicate_item_rules_require_configuration_reconciliation(self):
        self.rules.append(Row(self.rules[0],rule_row='DUPLICATE'))
        with self.assertRaisesRegex(ValueError,'more than one Material Run rule'):self.scan('BAG_1',5)

    def test_final_draw_requests_reject_nonfinite_quantities(self):
        for qty in (float('nan'),float('inf'),-1,0):
            with self.subTest(qty=qty),self.assertRaises(ValueError):
                self.ns['_normalise_draw_requests']([{'scan_value':'BAG_1','qty':qty}])

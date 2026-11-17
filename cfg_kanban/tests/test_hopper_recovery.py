"""Offline physical WIP recovery tests; not MariaDB isolation/site acceptance."""
import json
from unittest.mock import Mock
from cfg_kanban.tests.test_operation_hoppers import HopperHarness, Row


class TestHopperRecovery(HopperHarness):
    def setUp(self):
        super().setUp()
        self.frappe.parse_json=json.loads
        self.recovery=self.load('hopper_recovery')
        self.audit={};old_sql=self.frappe.db.sql
        def sql(query,values=None,as_dict=False):
            if 'from `tabCFG Kanban Event`' in query:
                return [(self.audit[values],)] if values in self.audit else []
            if 'from `tabCFG Kanban Operation Material Run`' in query:
                return [(row.name,) for row in self.data.get('CFG Kanban Operation Material Run',{}).values()
                        if row.operation_hopper_fill==values and row.status=='Open']
            return old_sql(query,values,as_dict)
        self.frappe.db.sql=sql
        self.recovery.record=lambda event,**kw:self.audit.update({kw['idempotency_key']:json.dumps(kw['payload'],default=str)})
        _,self.fill=self.load_hopper(qty=3)
        self.order.production_item='PRODUCT'
    def call(self,action='Confirm physically empty',qty=0,**kw):
        return self.recovery.recover_hopper(self.fill.name,'HOPPER_1',action,qty,'Physical check','TOKEN',**kw)
    def test_closed_wo_and_cycle_are_visible_and_can_be_confirmed_empty(self):
        self.order.status='Closed';self.data['CFG Kanban Cycle']['RINSE'].status='Completed'
        context=self.recovery.recovery_context('HOPPER_1')
        self.assertEqual((context['item_code'],context['remaining_qty'],context['work_order_status']),('PRODUCT',3,'Closed'))
        self.call()
        self.assertEqual((self.fill.qty,self.fill.used_qty,self.fill.cleared_qty,self.fill.status),(3,0,3,'Empty'))
        self.assertIsNone(self.fill.active_hopper_key)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_qty,0)
        self.assertEqual(self.order.status,'Closed')
        self.assertEqual(self.wip[-1][0][1:3],('Rejected',3))
    def test_transfer_preserves_source_provenance_and_can_be_consumed_in_new_hopper(self):
        self.call('Transfer remaining',3,destination_scan='HOPPER_2')
        self.assertEqual((self.fill.handling_unit,self.fill.current_handling_unit,self.fill.active_hopper_key),('HU-1','HU-2','HU-2'))
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_qty,0)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-2'].operation_wip_qty,3)
        run=self.make_run('PACK-RUN',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_2')
        self.hoppers.validate_run_hopper(self.pack,run,1,1)
        self.hoppers.apply_run_hopper(self.pack,run,Row(name='P',processed_qty=1,good_qty=1))
        self.assertEqual((self.fill.used_qty,self.fill.active_hopper_key),(1,'HU-2'))
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-2'].operation_wip_qty,2)
        self.assertNotIn('Stock Entry',self.data)
    def test_transfer_from_closed_wo_is_allowed_without_reopening_or_reassigning_it(self):
        self.order.status='Closed';self.call('Transfer remaining',3,destination_scan='HOPPER_2')
        self.assertEqual(self.fill.work_order,'WO');self.assertEqual(self.order.status,'Closed')
    def test_full_discard_preserves_partial_actual_use(self):
        self.fill.used_qty=1
        self.call('Discard remaining',2)
        self.assertEqual((self.fill.qty,self.fill.used_qty,self.fill.cleared_qty),(3,1,2))
    def test_ambiguous_response_retry_returns_same_outcome_even_after_source_is_empty(self):
        self.call();result=self.call()
        self.assertTrue(result['duplicate']);self.assertEqual(len(self.audit),1)
        self.assertEqual(len(self.wip),1)
    def test_transfer_retry_does_not_move_again_or_require_source_still_loaded(self):
        self.call('Transfer remaining',3,destination_scan='HOPPER_2')
        self.assertTrue(self.call('Transfer remaining',3,destination_scan='HOPPER_2')['duplicate'])
    def test_changed_payload_reusing_token_is_rejected(self):
        self.call()
        with self.assertRaisesRegex(ValueError,'different recovery data'):self.call('Discard remaining',3)
    def test_reservation_release_is_required_before_clearing_physical_wip(self):
        run=self.make_run('PACK-RUN',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_1')
        with self.assertRaisesRegex(ValueError,'reservations'):self.call()
        self.assertEqual(self.fill.qty,3);self.assertFalse(self.fill.get('cleared_qty'))
        self.hoppers.cancel_run_hopper(run.name,'Return unused');run.status='Cancelled'
        self.call();self.assertEqual(self.fill.cleared_qty,3)
    def test_stale_open_run_blocks_even_if_counter_is_zero(self):
        run=self.make_run('PACK-RUN',self.pack);run.operation_hopper_fill=self.fill.name
        with self.assertRaisesRegex(ValueError,'reservations'):self.call()
    def test_transfer_rejects_mixing_wrong_location_and_native_erp_stock(self):
        _,other=self.load_hopper('HOPPER_2',1)
        with self.assertRaisesRegex(ValueError,'already has operation WIP'):
            self.call('Transfer remaining',3,destination_scan='HOPPER_2')
        other.active_hopper_key=None;other.status='Empty'
        unit=self.data['CFG Kanban Handling Unit']['HU-2'];unit.current_warehouse='Other'
        with self.assertRaisesRegex(ValueError,'Warehouse'):
            self.call('Transfer remaining',3,destination_scan='HOPPER_2')
        unit.current_warehouse='Production';self.native['HU-2']=['ERP-STOCK']
        with self.assertRaisesRegex(ValueError,'ERP-posted'):
            self.call('Transfer remaining',3,destination_scan='HOPPER_2')
    def test_empty_requires_zero_and_transfer_discard_require_exact_remainder(self):
        for action,qty in [('Confirm physically empty',3),('Discard remaining',2),('Transfer remaining',4)]:
            with self.subTest(action=action),self.assertRaises(ValueError):
                self.call(action,qty,destination_scan='HOPPER_2')
        self.assertFalse(self.audit)
    def test_nonfinite_invalid_and_inconsistent_quantities_are_rejected(self):
        for qty in (float('nan'),float('inf'),-1,'not a number'):
            with self.subTest(qty=qty),self.assertRaises(ValueError):self.call(qty=qty)
        self.fill.used_qty=4
        with self.assertRaisesRegex(ValueError,'quantities require reconciliation'):self.call()
    def test_unrecorded_hopper_is_not_guessed_and_wrong_fill_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'no recorded active'):self.recovery.recovery_context('HOPPER_2')
        self.fill.active_hopper_key='HU-2'
        with self.assertRaisesRegex(ValueError,'fill changed'):self.call()
    def test_supervisor_authorization_applies_to_source_even_when_wo_is_closed(self):
        auth=self.modules['cfg_kanban.services.operator_auth'].require_operator
        auth.side_effect=ValueError('Not authorized')
        with self.assertRaisesRegex(ValueError,'Not authorized'):self.call()
        with self.assertRaisesRegex(ValueError,'Not authorized'):self.recovery.recovery_context('HOPPER_1')
        self.assertFalse(self.audit)

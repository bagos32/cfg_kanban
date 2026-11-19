"""Real release control flow with in-memory Frappe doubles, not site acceptance."""
import copy
import sys
import types
import unittest
from unittest.mock import patch
from cfg_kanban.tests.test_container_repacking import RepackHarness, Row, HU, CONTENT, LEDGER, EVENT, functions


class TestContainerStockRelease(RepackHarness):
    def setUp(self):
        super().setUp()
        self.container('A','Production Output Container')
        self.episode=self.load('A','S')

    def release(self,**kw):
        args=dict(source_scan='A',source_stock='S',qty=10,reason='Product leaves bin',event_token='RELEASE-1',operator_session_token='TOKEN')
        args.update(kw)
        return self.service.release_container_stock(**args)

    def internal(self):
        self.data[HU]['S'].update(virtual_content=1,physical_container='A')

    def test_full_physical_tag_detaches_without_quantity_or_certificate_duplication(self):
        result=self.release()
        self.assertEqual(result['destination_stock'],'S');self.assertTrue(result['existing_tag_used'])
        self.assertIsNone(self.membership('S'));self.assertEqual(self.data[HU]['S'].current_qty,10)
        self.assertEqual(self.data[HU]['S'].current_warehouse,'STORE');self.assertEqual(self.data[HU]['A'].movement_state,'Empty')
        self.assertEqual(self.data[CONTENT][self.episode.name].state,'Unloaded')
        self.assertEqual(self.data[CONTENT][self.episode.name].unload_reason,'Product leaves bin')
        self.assertFalse(self.data[LEDGER]);self.assertFalse(self.certificate_calls)
        self.assertEqual(self.total(),10);self.assertEqual(len(self.data[EVENT]),1)

    def test_full_internal_fill_requires_new_tag_and_preserves_stock_identity(self):
        self.internal()
        with self.assertRaisesRegex(ValueError,'requires an unused'):self.release()
        result=self.release(new_tag='NEW001');tag=self.data[HU][result['destination_stock']]
        self.assertEqual((tag.handling_unit_id,tag.current_qty,tag.virtual_content),('NEW001',10,0))
        self.assertIsNone(tag.physical_container);self.assertIsNone(self.membership(tag.name));self.assertFalse(self.contents('A'))
        self.assertEqual(self.data[HU]['S'].identity_state,'Empty')
        for field in ('item_code','batch_no','stock_uom','expiry_date','process_certificate_set','packed_on','work_order','kanban_cycle','short_description','inventory_company','current_warehouse'):
            self.assertEqual(tag[field],self.data[HU]['S'][field])
        self.assertEqual(tag.origin_reference_name,'S');self.assertEqual(self.certificate_calls[0][3],{'replacement':True});self.assertEqual(self.total(),10)

    def test_partial_internal_fill_keeps_remainder_and_membership(self):
        self.internal();result=self.release(qty=3,new_tag='NEW001')
        self.assertEqual(self.data[HU]['S'].current_qty,7);self.assertEqual(self.membership('S').container_handling_unit,'A')
        self.assertEqual(self.data[HU]['A'].movement_state,'Packed');self.assertEqual(self.data[HU][result['destination_stock']].current_qty,3)
        self.assertIsNone(self.membership(result['destination_stock']));self.assertEqual(self.data[CONTENT][self.episode.name].qty,10)
        self.assertEqual(self.certificate_calls[0][3],{'replacement':False});self.assertEqual(self.total(),10)

    def test_partial_physical_stock_needs_a_new_main_tag(self):
        before=copy.deepcopy(self.data)
        with self.assertRaisesRegex(ValueError,'partial release requires'):self.release(qty=3)
        self.assertEqual(self.data,before)
        result=self.release(qty=3,new_tag='NEW001')
        self.assertEqual(self.data[HU]['S'].current_qty,7);self.assertIsNotNone(self.membership('S'));self.assertIsNone(self.membership(result['destination_stock']))

    def test_full_physical_release_can_explicitly_replace_the_tag(self):
        result=self.release(new_tag='NEW001')
        self.assertFalse(result['existing_tag_used']);self.assertEqual(self.data[HU][result['destination_stock']].current_qty,10)
        self.assertFalse(self.contents('A'));self.assertEqual(self.total(),10)

    def test_logistics_container_releases_only_selected_tag(self):
        self.container('A','Logistics Container');self.stock('OTHER',4);self.load('A','OTHER');self.release()
        self.assertEqual(len(self.contents('A')),1);self.assertEqual(self.contents('A')[0].content_handling_unit,'OTHER')
        self.assertEqual(self.data[HU]['A'].movement_state,'Packed')

    def test_conflicting_production_fills_block_release(self):
        self.stock('OTHER',4);self.load('A','OTHER')
        with self.assertRaisesRegex(ValueError,'one fill'):self.release()
        self.assertFalse(self.data[EVENT]);self.assertFalse(self.data[LEDGER])

    def test_preview_is_read_only_and_standalone_stock_is_not_released_again(self):
        self.internal();before=copy.deepcopy(self.data);result=self.service.release_source_context('A','TOKEN')
        self.assertTrue(result['options'][0]['requires_new_tag']);self.assertEqual(result['options'][0]['container'],'A');self.assertEqual(self.data,before)
        self.stock('OUTSIDE',2)
        with self.assertRaisesRegex(ValueError,'already outside'):self.service.release_source_context('OUTSIDE','TOKEN')

    def test_intermediate_wip_is_never_activated_as_stock(self):
        self.wip.add('A');before=copy.deepcopy(self.data)
        with self.assertRaisesRegex(ValueError,'Recover Hopper'):self.release(new_tag='NEW001')
        self.assertEqual(self.data,before)
        with self.assertRaisesRegex(ValueError,'Recover Hopper'):self.service.release_source_context('A','TOKEN')

    def test_reservations_draws_and_open_movements_are_blocked(self):
        for kind in ('reserved','draw','container','stock'):
            with self.subTest(kind=kind):
                if kind=='reserved':self.data[HU]['S'].update(reserved_qty=1,available_qty=9)
                if kind=='draw':self.draws['S']=1
                if kind=='container':self.open_movement.add('A')
                if kind=='stock':self.open_movement.add('S')
                with self.assertRaises(ValueError):self.release()
                self.assertIsNotNone(self.membership('S'));self.assertFalse(self.data[EVENT])
                self.data[HU]['S'].update(reserved_qty=0,available_qty=10);self.draws.clear();self.open_movement.clear()

    def test_held_inactive_serial_and_wrong_location_are_blocked(self):
        for name,field,value in [('S','quality_state','Hold'),('S','identity_state','Void'),('S','serial_count',1),('A','movement_state','Internal Transit'),('A','current_warehouse','OTHER'),('A','inventory_company','OTHER')]:
            with self.subTest(field=field):
                old=self.data[HU][name].get(field);self.data[HU][name][field]=value
                with self.assertRaises(ValueError):self.release()
                self.data[HU][name][field]=old
                self.assertFalse(self.data[EVENT]);self.assertFalse(self.data[LEDGER])

    def test_bad_quantities_reason_token_and_new_tag_do_not_mutate(self):
        for kw in ({'qty':0},{'qty':-1},{'qty':float('nan')},{'qty':float('inf')},{'qty':11},{'reason':''},{'event_token':''},{'qty':3,'new_tag':'S'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.release(**kw)
        self.assertFalse(self.data[EVENT]);self.assertFalse(self.data[LEDGER]);self.assertEqual(self.data[HU]['S'].current_qty,10)

    def test_whole_number_uom_and_exact_source_are_enforced(self):
        original=self.frappe.db.get_value
        self.frappe.db.get_value=lambda dt,*a,**kw:1 if dt=='UOM' else original(dt,*a,**kw)
        with self.assertRaisesRegex(ValueError,'whole-number'):self.release(qty=1.5,new_tag='NEW001')
        with self.assertRaisesRegex(ValueError,'exact Stock Tag'):self.release(source_scan='B')
        self.internal()
        with self.assertRaisesRegex(ValueError,'permanent container QR'):self.release(source_scan='S',new_tag='NEW001')

    def test_authorization_is_required_for_preview_and_release(self):
        self.retag_auth.side_effect=ValueError('Stock Retagging required')
        with self.assertRaisesRegex(ValueError,'Stock Retagging'):self.release()
        with self.assertRaisesRegex(ValueError,'Stock Retagging'):self.service.release_source_context('A','TOKEN')
        self.assertFalse(self.data[EVENT])

    def test_replay_after_full_release_is_idempotent(self):
        for internal in (False,True):
            with self.subTest(internal=internal):
                if internal:
                    self.stock('V',4,physical_container='A');self.data[HU]['V'].virtual_content=1;self.load('A','V')
                    kw=dict(source_stock='V',qty=4,new_tag='NEW002',event_token='SECOND')
                else:kw={}
                first=self.release(**kw);events=len(self.data[EVENT]);ledgers=len(self.data[LEDGER]);replay=self.release(**kw)
                self.assertTrue(replay['duplicate']);self.assertEqual(replay['destination_stock'],first['destination_stock'])
                self.assertEqual(len(self.data[EVENT]),events);self.assertEqual(len(self.data[LEDGER]),ledgers)

    def test_changed_payload_replay_is_rejected(self):
        self.release()
        with self.assertRaisesRegex(ValueError,'different container release data'):self.release(qty=9)
        self.assertEqual(len(self.data[EVENT]),1)

    def test_membership_changes_during_lock_wait_require_reload(self):
        ns=self.service.release_container_stock.__globals__;original=ns['_lock_units']
        def change(names):
            locked=original(names);self.data[CONTENT][self.episode.name].container_handling_unit='B';return locked
        ns['_lock_units']=change
        with self.assertRaisesRegex(ValueError,'membership changed'):self.release()
        self.assertFalse(self.data[EVENT]);self.assertEqual(self.data[HU]['S'].current_qty,10)

    def test_current_locked_quantity_wins_over_stale_preview(self):
        ns=self.service.release_container_stock.__globals__;original=ns['_lock_units']
        def reduce(names):
            self.data[HU]['S'].update(current_qty=4,available_qty=4);return original(names)
        ns['_lock_units']=reduce
        with self.assertRaisesRegex(ValueError,'exceeds available'):self.release(qty=5,new_tag='NEW001')
        self.assertFalse(self.data[EVENT]);self.assertFalse(self.data[LEDGER])

    def test_new_tag_can_be_dispatched_independently_without_new_erp_stock(self):
        self.internal();result=self.release(new_tag='NEW001');tag=self.doc(HU,result['destination_stock'])
        def outside(name,action):
            if self.membership(name):raise ValueError('still loaded')
        with patch.dict(sys.modules,{'cfg_kanban.services.container_contents':types.SimpleNamespace(active_container_membership=self.membership,assert_not_loaded_in_container=outside)}):
            validate=functions('api/logistics.py',{'_validate_dispatch_unit'},{'frappe':self.frappe,'flt':lambda v:float(v or 0)})._validate_dispatch_unit
            validate(tag,Row(source_company='TEST',source_warehouse='STORE'))
        self.assertFalse(self.data.get('Stock Entry'))

    def test_native_manufacture_cancellation_detects_released_fill(self):
        self.internal();self.data[HU]['S'].update(origin_reference_doctype='Stock Entry',origin_reference_name='SE',origin_reference_row='ROW')
        self.release(new_tag='NEW001')
        validate=functions('services/production_trace.py',{'_validate_trace_reversal'},{'frappe':self.frappe,'flt':lambda v:float(v or 0),'TOLERANCE':.000001})._validate_trace_reversal
        trace=Row(stock_entry='SE',lines=[Row(status='Confirmed',direction='Output',stock_entry_detail='ROW',handling_unit='S',qty=10,physical_container='A')])
        with self.assertRaisesRegex(ValueError,'moved, split, reduced'):validate(Row(),trace,{'ROW':Row(name='ROW',t_warehouse='STORE')})


if __name__=='__main__':unittest.main()

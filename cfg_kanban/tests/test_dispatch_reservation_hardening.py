"""Actual E2 entry points with lock/current-read and stock-service doubles."""
import datetime
import hashlib
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests.test_trip_continuation import FollowOnFixture,Doc,Row,load,PLAN,ALLOC

class TestDispatchReservationHardening(FollowOnFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.locks=[];self.ledger=[]
        self.plan=self.g.plans()[0];self.plan.update(state='Approved',source_warehouse='LORRY',tag_policy='Mixed',total_reserved_qty=0)
        self.line=self.plan.lines[0]
        self.line.parenttype=PLAN;self.line.parentfield='lines'
        self.data.setdefault('CFG Kanban Dispatch Plan Line',{})[self.line.name]=self.line
        self.unit=self.data['CFG Kanban Handling Unit']['HU'];self.unit.update(handling_unit_id='TAG',identity_state='Active',quality_state='Released',stock_uom='Nos',available_qty=4,reserved_qty=0)
        self.data['Item']['ITEM1'].update(has_batch_no=0,has_serial_no=0)
        self.native=load('services/dispatch_planning.py',dict(frappe=self.b.frappe,json=json,hashlib=hashlib,isfinite=math.isfinite,
            flt=lambda n:float(n or 0),cint=lambda n:int(n or 0),now_datetime=lambda:datetime.datetime(2026,11,25,10),
            require_operator=lambda *a:self.auth('TOKEN'),canonical_key=self.ns['canonical_key'],record=self.record,
            resolve_logistics_scan=lambda value:{'identity_type':'Handling Unit','name':'HU'} if value=='TAG' else None,
            assert_erp_stock=Mock(),post_quantity_event=self.post))
        self.available=4
        self.native['_untagged_available']=lambda *a,**kw:self.available if kw.get('current') else 100
        self.native['get_dispatch_plan']=lambda name,token:self.data[PLAN][name].as_dict()
        prepared=types.ModuleType('cfg_kanban.services.dispatch_fulfilment')
        prepared.__dict__.update(load('services/dispatch_fulfilment.py',dict(frappe=self.b.frappe,flt=lambda n:float(n or 0))))
        prepared.assert_delivery_tag_expiry=Mock();prepared._assert_untagged_batch_expiry=Mock();self.prepared=prepared
        p=patch.dict(sys.modules,{prepared.__name__:prepared});p.start();self.addCleanup(p.stop)
        original=self.b.frappe.get_doc
        def get_doc(dt,name=None,**kw):
            if dt=='CFG Kanban Handling Unit':self.locks.append(('tag',bool(kw.get('for_update'))))
            return original(dt,name,**kw)
        self.b.frappe.get_doc=get_doc
        lock=self.native['_lock_erp_bin']
        self.native['_lock_erp_bin']=lambda *a:(self.locks.append(('bin',True)),lock(*a))[-1]
    def post(self,**values):
        self.ledger.append(values)
        if values['event_type']=='Reserve':self.unit.reserved_qty+=values['qty'];self.unit.available_qty-=values['qty']
        return Doc(name='LEDGER-'+str(len(self.ledger)))
    def reserve_tag(self,qty=4,token='EVENT'):
        return self.native['reserve_dispatch_tag'](self.plan.name,self.line.name,'TAG',qty,token,'TOKEN')
    def reserve_loose(self,qty=4,token='EVENT'):
        return self.native['reserve_dispatch_untagged'](self.plan.name,self.line.name,qty,None,token,'TOKEN')
    def test_tag_source_is_locked_after_bin_and_receipt_replays_once(self):
        self.reserve_tag();self.reserve_tag()
        self.assertEqual(self.locks[:2],[('bin',True),('tag',True)])
        self.assertEqual(len(self.ledger),1);self.assertEqual(self.unit.reserved_qty,4)
        self.assertEqual(self.plan.total_reserved_qty,4);self.assertEqual(self.plan.state,'Ready for Vehicle')
    def test_existing_event_or_active_tag_cannot_silently_change_quantity(self):
        self.reserve_tag()
        for token in ('EVENT','ANOTHER'):
            with self.subTest(token=token),self.assertRaisesRegex(ValueError,'different original details'):self.reserve_tag(2,token)
        self.assertEqual(len(self.ledger),1);self.assertEqual(self.unit.reserved_qty,4)
    def test_after_waiting_for_lock_latest_tag_availability_is_used(self):
        original=self.b.frappe.get_doc
        def get_doc(dt,name=None,**kw):
            if dt=='CFG Kanban Handling Unit' and kw.get('for_update'):self.unit.available_qty=1
            return original(dt,name,**kw)
        self.b.frappe.get_doc=get_doc
        with self.assertRaisesRegex(ValueError,'only 1'):self.reserve_tag(2)
        self.assertFalse(self.ledger)
    def test_line_budget_is_a_current_row_read_not_a_stale_sum(self):
        self.b.add(ALLOC,'OTHER',dispatch_plan=self.plan.name,dispatch_plan_line=self.line.name,state='Reserved',allocated_qty=3)
        self.b.frappe.db.sql=lambda *a,**k:[] # a stale aggregate would incorrectly say zero
        with self.assertRaisesRegex(ValueError,'remaining quantity 1'):self.reserve_tag(2)
        self.assertFalse(self.ledger)
    def test_tag_committed_to_loaded_plan_is_not_reserved_again(self):
        self.b.add(PLAN,'LOADED',state='Loaded',plan_type='Customer Order',fulfilment_mode='Vehicle Delivery',prepared_stock_commitment=1,fulfilment_status='Not Started')
        self.b.add(ALLOC,'COMMITTED',dispatch_plan='LOADED',handling_unit='HU',allocated_qty=4,state='Loaded')
        with self.assertRaisesRegex(ValueError,'prepared Customer Order'):self.reserve_tag()
        self.assertFalse(self.ledger)
    def test_settled_old_plan_does_not_retain_a_stock_commitment(self):
        self.b.add(PLAN,'OLD',state='Reconciled',plan_type='Customer Order',fulfilment_mode='Vehicle Delivery',prepared_stock_commitment=0)
        self.b.add(ALLOC,'SETTLED',dispatch_plan='OLD',handling_unit='HU',allocated_qty=4,state='Loaded')
        self.reserve_tag();self.assertEqual(len(self.ledger),1)
    def test_untagged_current_availability_catches_competing_commit(self):
        self.available=0
        with self.assertRaisesRegex(ValueError,'available|0'):self.reserve_loose()
        self.assertFalse(self.data.get(ALLOC))
    def test_loose_replay_has_exact_quantity_and_no_second_allocation(self):
        self.reserve_loose();self.reserve_loose()
        self.assertEqual(len(self.data[ALLOC]),1)
        with self.assertRaisesRegex(ValueError,'different original details'):self.reserve_loose(2)
    def test_nonfinite_negative_boolean_and_unsupported_precision_are_rejected(self):
        for value in (float('nan'),float('inf'),-1,True,'BAD',0.0000001):
            for method in (self.reserve_tag,self.reserve_loose):
                with self.subTest(value=value,method=method),self.assertRaises(ValueError):method(value)
        self.assertFalse(self.ledger);self.assertFalse(self.data.get(ALLOC))
    def test_whole_uom_and_serial_exact_quantity_remain_enforced(self):
        for value in (0.5,1.000001,0.999999):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'whole-number'):self.reserve_tag(value)
        self.data['Item']['ITEM1'].has_serial_no=1
        with self.assertRaisesRegex(ValueError,'Serialized'):self.reserve_tag(2)
        with self.assertRaisesRegex(ValueError,'Serialized'):self.reserve_loose(2)
    def test_existing_expiry_and_company_gates_are_preserved(self):
        self.prepared.assert_delivery_tag_expiry.side_effect=ValueError('Expired physical tag')
        with self.assertRaisesRegex(ValueError,'Expired'):self.reserve_tag()
        self.prepared.assert_delivery_tag_expiry.side_effect=None;self.unit.inventory_company='OTHER'
        with self.assertRaisesRegex(ValueError,'belongs to'):self.reserve_tag()
        self.assertFalse(self.ledger)

    def test_waiting_request_cannot_use_old_plan_line_quantity_after_office_change(self):
        original=self.b.frappe.db.get_values
        def rows(dt,filters,fields,**kw):
            result=original(dt,filters,fields,**kw)
            if dt=='CFG Kanban Dispatch Plan Line':
                self.assertTrue(kw.get('for_update'))
                for row in result:row.requested_qty=1
            return result
        self.b.frappe.db.get_values=rows
        with self.assertRaisesRegex(ValueError,'remaining quantity 1'):self.reserve_tag(2)
        self.assertFalse(self.ledger)

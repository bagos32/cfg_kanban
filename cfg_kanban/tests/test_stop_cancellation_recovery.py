"""Cancelled stock exercises the real E5 Manifest/receipt flow with existing offline doubles."""
import datetime,json,sys,types,unittest
from unittest.mock import patch
from cfg_kanban.tests import test_dispatch_recovery as native
from cfg_kanban.tests.test_trip_stop_cancellation import module,STOCK,REQUEST
from cfg_kanban.tests.test_driver_route_actions import canonical
from cfg_kanban.tests.test_vehicle_overview import Row

class TestCancellationRecovery(unittest.TestCase):
    def setUp(self):
        self.n=native.TestDispatchRecovery();self.n.setUp();self.addCleanup(self.n.doCleanups)
        self.f=self.n.b.frappe;self.data=self.n.data;self.plan=self.n.plan;self.unit=self.n.unit
        self.plan.stop_cancellation='CANCEL';self.plan.prepared_stock_commitment=1
        self.parent=self.n.b.add(REQUEST,'CANCEL',delivery_trip='TRIP',company='B',state='Approved',request_type='Cancel Customer Stop')
        self.row=self.n.b.add(STOCK,'CANCEL-STOCK',parent='CANCEL',parenttype=REQUEST,parentfield='cancelled_stock',dispatch_plan=self.plan.name,dispatch_allocation='ALLOC',handling_unit=self.unit.name,item_code=self.unit.item_code,batch_no=self.unit.batch_no,
            stock_uom=self.unit.stock_uom,qty=self.unit.current_qty,company='B',original_warehouse='LORRY1',current_warehouse='LORRY1',stock_state='Held for Return')
        self.unit.reserved_qty=self.unit.current_qty;self.unit.available_qty=0
        old_values=self.f.db.get_values
        def values(dt,filters,fields,**kw):
            if dt!=STOCK:return old_values(dt,filters,fields,**kw)
            result=[]
            for row in self.data.get(STOCK,{}).values():
                if all(row.get(k) in v[1] if isinstance(v,list) and v[0]=='in' else row.get(k)==v for k,v in filters.items()):result.append(Row({key:row.get(key) for key in fields}))
            return result
        self.f.db.get_values=values;self.f.db.table_exists=lambda *_:True
        self.stock=module('cancelled_stop_stock','services/cancelled_stop_stock.py',frappe=self.f,flt=lambda v:float(v or 0),now_datetime=lambda:self.n.r.now,canonical_key=canonical,post_quantity_event=self.n.b.post_quantity)
        planning=types.ModuleType('cfg_kanban.services.dispatch_planning');planning._lock_erp_bin=lambda *a:None
        p=patch.dict(sys.modules,{self.stock.__name__:self.stock,planning.__name__:planning});p.start();self.addCleanup(p.stop)
    def test_unused_manifest_cancel_restores_hold_exactly_once_and_replacement_can_be_received(self):
        original=self.plan.movement_manifest;self.n.create();first=self.n.manifest().name;self.n.scan();self.n.prepare()
        self.assertEqual(self.row.stock_state,'Recovery Reserved');self.assertEqual(self.unit.reserved_qty,self.unit.current_qty)
        self.n.mod.cancel_dispatch_recovery(first,'Return destination changed','CANCEL','SESSION');self.n.mod.cancel_dispatch_recovery(first,'Return destination changed','CANCEL','SESSION')
        self.assertEqual(self.row.stock_state,'Held for Return');self.assertEqual(self.unit.reserved_qty,self.unit.current_qty)
        self.n.create(event='REPLACEMENT');self.n.scan();self.n.prepare();self.n.post();self.n.post()
        self.assertEqual(self.row.stock_state,'Recovered');self.assertEqual(self.unit.current_warehouse,'SOURCE');self.assertEqual(self.unit.reserved_qty,0)
        self.assertEqual(self.unit.process_certificate_set,'CERT');self.assertEqual(str(self.unit.expiry_date),'2027-04-01');self.assertEqual(self.plan.movement_manifest,original)
    def test_direct_return_receipt_frees_stock_but_e5_still_requires_a_fresh_count(self):
        self.n.create();self.n.r.count();self.n.scan();self.n.prepare();self.n.post()
        self.assertEqual(self.row.stock_state,'Recovered');self.assertEqual(self.plan.state,'Loaded')
        with self.assertRaisesRegex(ValueError,'changed|fresh'):self.n.r.finish('Returned to Warehouse',movement=self.n.saved_entries[-1].name)
        self.n.r.count();self.n.r.finish('Returned to Warehouse',movement=self.n.saved_entries[-1].name)
        self.assertEqual(self.plan.state,'Reconciled');self.assertFalse(self.plan.prepared_stock_commitment);self.assertEqual(self.unit.reserved_qty,0)

    def test_overnight_resume_keeps_the_cancelled_customer_hold(self):
        self.n.r.count();self.n.r.finish('Continue Same Plan Overnight')
        self.assertEqual(self.plan.dispatch_review_state,'Overnight');self.assertEqual(self.unit.reserved_qty,self.unit.current_qty)
        self.n.r.mod.resume_dispatch_review(self.n.r.review().name,'Resume return journey','RESUME','SESSION')
        self.assertEqual(self.plan.dispatch_review_state,'');self.assertEqual(self.row.stock_state,'Held for Return')
        self.assertEqual(self.unit.reserved_qty,self.unit.current_qty)

    def test_an_unrelated_hold_cannot_be_adopted_and_generic_dispatch_stays_blocked(self):
        self.n.create()
        self.row.dispatch_plan='OTHER'
        with self.assertRaisesRegex(ValueError,'available|reserved'):self.n.scan()
        self.row.dispatch_plan=self.plan.name
        with self.assertRaisesRegex(ValueError,'available|reserved'):
            self.n.log._validate_dispatch_unit(self.unit,self.n.manifest())
        self.assertFalse(self.n.manifest().lines[0].loading_confirmed)

    def test_mixed_container_must_be_separated_without_moving_other_stock(self):
        self.n.create();self.n.b.add('CFG Kanban Handling Unit','BIN',handling_unit_id='BIN',tag_kind='Reusable Container',identity_state='Active',quality_state='Released',inventory_company='B',current_warehouse='LORRY1')
        self.n.memberships[self.unit.name]=Row(container_handling_unit='BIN')
        self.n.memberships['OTHER']=Row(container_handling_unit='BIN')
        with self.assertRaisesRegex(ValueError,'Every tag'):self.n.scan('BIN')
        with self.assertRaisesRegex(ValueError,'physical container'):self.n.scan()
        self.assertFalse(self.n.manifest().lines[0].loading_confirmed)
        self.assertEqual(self.unit.reserved_qty,self.unit.current_qty)

if __name__=='__main__':unittest.main()

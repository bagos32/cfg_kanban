"""Actual drop-check services + prepared delivery/Loose Tag flows, with offline ERP/DB doubles.

No live ERPNext submission, MariaDB concurrency, kiosk scanner or camera acceptance.
"""
import copy
import datetime
import json
import math
import sys
import types
import unittest
from unittest.mock import patch

from cfg_kanban.tests.test_vehicle_overview import load, Row, ROOT
from cfg_kanban.tests import test_dispatch_fulfilment as fixture
from cfg_kanban.tests.test_loose_tags import LooseTagFixture


def install(test, base):
    f=base.frappe;events={};get_value=f.db.get_value
    def value(dt,name,field,**kwargs):
        if dt=='CFG Kanban Event':
            found=events.get(name.get('idempotency_key'))
            return json.dumps(found['payload'],default=str) if found else None
        return get_value(dt,name,field,**kwargs)
    f.db.get_value=value;f.session=Row(user='driver@example.com')
    def record(event,**kw):events[kw['idempotency_key']]=dict(event=event,**kw)
    def auth(token,action=None):
        if token!='TOKEN':raise ValueError('Inactive operator session')
        if action and not base.operator.get('can_'+action):raise PermissionError('Action not allowed')
        return base.operator,base.e3.session
    base.operator.update(can_start=1)
    mod=types.ModuleType('cfg_kanban.services.delivery_product_scans')
    load('services/delivery_product_scans.py',mod.__dict__)
    # Only imports/framework I/O are doubled; execute the actual application bodies.
    mod.__dict__.update(frappe=f,json=json,math=math,cint=lambda x:int(x or 0),flt=lambda x:float(x or 0),
        canonical_key=base.e3.fn['canonical_key'],record=record,require_operator=auth,
        now_datetime=lambda:datetime.datetime(2026,11,27,10),_engine=lambda:base.engine)
    foundation=types.ModuleType('cfg_kanban.services.logistics_foundation')
    existing=sys.modules.get(foundation.__name__)
    if existing:foundation.__dict__.update(existing.__dict__)
    foundation.resolve_logistics_scan=lambda code:next((dict(identity_type='Handling Unit',name=u.name)
        for u in base.data[fixture.HU].values() if code in (u.name,u.handling_unit_id,u.opaque_token)),None)
    container=types.ModuleType('cfg_kanban.services.container_contents')
    existing=sys.modules.get(container.__name__)
    if existing:container.__dict__.update(existing.__dict__)
    container.active_container_contents=lambda name:[]
    p=patch.dict(sys.modules,{mod.__name__:mod,foundation.__name__:foundation,container.__name__:container})
    p.start();test.addCleanup(p.stop)
    return mod,events,container


class TestDeliveryProductScans(unittest.TestCase):
    def setUp(self):
        self.b=fixture.TestDispatchFulfilment();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.service,self.events,self.container=install(self,self.b)
        self.b.site.require_delivery_product_scan=1
        self.b.loose(2);self.b.start()
        self.d=self.b.delivery();self.data=self.b.data
        self.tag=next(r for r in self.data[fixture.DA].values() if r.handling_unit)
        self.loose=next(r for r in self.data[fixture.DA].values() if not r.handling_unit)
    def verify(self,payload,key='SCAN'):
        return self.service.verify_delivery_goods(self.d.name,key,'TOKEN',payload)
    def tag_scan(self,key='TAG'):
        return self.verify(dict(scan_value=self.b.unit.handling_unit_id),key)
    def count(self,qty=2,key='COUNT'):
        return self.verify(dict(delivery_allocation=self.loose.name,item_code=self.loose.item_code,qty=qty),key)
    def no_stock_snapshot(self):
        return dict(posted=copy.deepcopy(self.b.posted),units=[(r.name,r.current_qty,r.reserved_qty)
            for r in self.data[fixture.HU].values()],native={dt:list(self.data.get(dt,{})) for dt in
            ('Stock Entry','Delivery Note','CFG Kanban Movement Manifest','Stock Ledger Entry')})
    def test_customer_policy_snapshot_and_missing_checks_block_allocation_confirmation(self):
        self.assertEqual(self.d.require_delivery_product_scan,1);self.b.site.require_delivery_product_scan=0
        self.assertEqual(self.b.engine.get_delivery_session(self.d.name,'TOKEN')['product_verification']['required'],True)
        before=self.no_stock_snapshot()
        with self.assertRaisesRegex(ValueError,'Verify delivery goods'):self.b.confirm()
        self.assertEqual(self.d.state,'Allocating Stock')
        self.assertTrue(all(r.state=='Reserved' for r in self.data[fixture.DA].values()))
        self.assertEqual(self.no_stock_snapshot(),before)
    def test_tag_then_exact_untagged_item_quantity_allow_native_confirmation_without_stock_posting(self):
        before=self.no_stock_snapshot();first=self.tag_scan()
        self.assertEqual(len(first['changed']),1);self.assertFalse(first['product_verification']['ready'])
        checked=next(r for r in first['product_verification']['rows'] if r['tagged']);self.assertTrue(checked['confirmed'])
        for qty in (0,1,3,'NaN','Infinity',None):
            with self.subTest(qty=qty),self.assertRaises(ValueError):self.count(qty,key='BAD'+str(qty))
        self.assertTrue(self.count()['product_verification']['ready'])
        self.b.confirm();payload=self.b.payload()
        self.assertEqual([r['qty'] for r in payload['items']],[5,2])
        self.assertEqual(self.d.state,'Awaiting Confirmation');self.assertEqual(self.no_stock_snapshot(),before)
        self.assertEqual(len([v for v in self.events.values() if v['event']=='Customer Drop Goods Verified']),2)
    def test_wrong_customer_tag_and_manual_confirmation_of_tagged_stock_are_rejected(self):
        self.b.add(fixture.HU,'OTHER-TAG',handling_unit_id='OTHER',opaque_token=None)
        for payload in (dict(scan_value='OTHER'),dict(scan_value='SITE-QR'),
                        dict(delivery_allocation=self.tag.name,item_code=self.tag.item_code,qty=5),
                        dict(delivery_allocation=self.loose.name,item_code='WRONG',qty=2),
                        dict(scan_value=self.b.unit.handling_unit_id,qty=5)):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.verify(payload)
        self.assertFalse(self.events);self.assertFalse(self.service.context(self.d)['ready'])
    def test_exact_retry_reuses_audit_and_cannot_change_original_details(self):
        before=self.no_stock_snapshot();result=self.tag_scan();n=len(self.events)
        self.assertEqual(self.tag_scan(),result);self.assertEqual(len(self.events),n)
        with self.assertRaisesRegex(ValueError,'different original'):self.verify(dict(scan_value='OTHER'),'TAG')
        self.tag_scan('NEW-NONCE')
        self.assertEqual(len([v for v in self.events.values() if v['event']=='Customer Drop Goods Verified']),1)
        self.assertEqual(self.no_stock_snapshot(),before)
    def test_evidence_is_bound_to_exact_allocation_quantity_and_customer(self):
        self.tag_scan();self.count();self.service.assert_verified(self.d)
        for field,value in [('allocated_qty',4),('batch_no','OTHER'),('source_warehouse','OTHER')]:
            old=self.tag.get(field);self.tag[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Verify delivery goods'):self.service.assert_verified(self.d)
            self.tag[field]=old
        self.d.customer='OTHER'
        with self.assertRaises(ValueError):self.service.assert_verified(self.d)
    def test_new_or_replacement_allocation_requires_its_own_check_released_history_is_ignored(self):
        self.tag_scan();self.count();self.tag.state='Released'
        self.assertTrue(self.service.context(self.d)['ready'])
        replacement=self.b.add(fixture.DA,'REPLACEMENT',**{k:v for k,v in dict.items(self.tag)
            if k not in ('name','_store','doctype','drop_scan_confirmed','drop_scan_evidence')})
        replacement.state='Reserved'
        self.assertFalse(self.service.context(self.d)['ready'])
        with self.assertRaises(ValueError):self.service.assert_verified(self.d)
    def test_loaded_container_requires_exact_current_membership_and_quantity_bin_can_scan(self):
        self.b.add(fixture.HU,'BIN',handling_unit_id='BIN-QR',opaque_token=None)
        self.tag.container_handling_unit='BIN';self.tag.container_visible_code='BIN-QR'
        self.container.active_container_contents=lambda name:[Row(content_handling_unit=self.tag.handling_unit)]
        before=self.no_stock_snapshot()
        self.assertEqual(self.verify(dict(scan_value='BIN-QR'))['changed'],[self.tag.name])
        self.assertEqual(self.no_stock_snapshot(),before)
        self.tag.drop_scan_confirmed=0
        self.container.active_container_contents=lambda name:[Row(content_handling_unit=self.tag.handling_unit),Row(content_handling_unit='ANOTHER-CUSTOMER')]
        with self.assertRaisesRegex(ValueError,'individual allocated'):self.verify(dict(scan_value='BIN-QR'),'MIXED')
        self.assertFalse(self.tag.drop_scan_confirmed)
    def test_native_draft_submit_and_payload_cannot_bypass_the_product_gate(self):
        before=self.no_stock_snapshot()
        self.tag.state=self.loose.state='Delivery Pending';self.d.state='Awaiting Confirmation'
        note=Row(name='DRAFT',cfg_delivery_session=self.d.name,company=self.d.selling_company,customer=self.d.customer)
        with self.assertRaisesRegex(ValueError,'Verify delivery goods'):self.service.validate_delivery_note(note)
        with self.assertRaisesRegex(ValueError,'Verify delivery goods'):self.b.payload()
        self.tag_scan();self.count();self.service.validate_delivery_note(note)
        note.company='FOREIGN'
        with self.assertRaisesRegex(ValueError,'does not match'):self.service.validate_delivery_note(note)
        self.service.validate_delivery_note(Row(name='NORMAL',company='FOREIGN'))
        self.assertEqual(self.no_stock_snapshot(),before)
    def test_submitted_and_cancelled_sessions_reject_new_checks_but_original_retry_reads_back(self):
        original=self.tag_scan();self.d.state='Delivered'
        self.assertEqual(self.tag_scan(),original)
        with self.assertRaisesRegex(ValueError,'closed'):self.tag_scan('NEW')
        self.d.state='Cancelled'
        with self.assertRaises(ValueError):self.count()
    def test_operator_authorization_and_payload_bounds_remain_required(self):
        for token in ('BAD',None):
            with self.assertRaises(ValueError):self.service.verify_delivery_goods(self.d.name,'SCAN',token,dict(scan_value='TAG1'))
        self.b.operator.can_start=0
        with self.assertRaises(PermissionError):self.tag_scan()
        self.b.operator.can_start=1
        for payload in (dict(scan_value='TAG1',company='B'),[],{'scan_value':'TAG1'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                self.service.verify_delivery_goods(self.d.name,'','TOKEN',payload)
        self.b.engine._can_view_delivery=lambda *args:False
        with self.assertRaisesRegex(ValueError,'cannot access'):self.tag_scan()
    def test_scan_rejects_tags_that_moved_changed_identity_or_are_no_longer_released(self):
        for field,value in [('inventory_company','OTHER'),('current_warehouse','OTHER'),('item_code','OTHER'),('quality_state','Quarantined'),('identity_state','Void'),('reserved_qty',0)]:
            old=self.b.unit.get(field);self.b.unit[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'no longer matches'):self.tag_scan()
            self.b.unit[field]=old
        self.assertFalse(self.events)

    def test_existing_expiry_validator_rejection_leaves_no_green_check_or_audit(self):
        from unittest.mock import Mock
        self.b.bridge.assert_delivery_tag_expiry=Mock(side_effect=ValueError('Expired material'))
        with self.assertRaisesRegex(ValueError,'Expired material'):self.tag_scan()
        self.assertFalse(self.events);self.assertFalse(self.tag.drop_scan_confirmed)

    def test_allocation_controller_disallows_forged_or_edited_check_evidence(self):
        source='cfg_kanban/doctype/cfg_kanban_delivery_allocation/cfg_kanban_delivery_allocation.py'
        ns=load(source,dict(frappe=self.b.frappe,Document=dict,cint=lambda v:int(v or 0),flt=lambda v:float(v or 0)))
        cls=ns['CFGKanbanDeliveryAllocation']
        class Doc(cls):
            def __getattr__(self,name):return self.get(name)
            def is_new(self):return not self.get('_before')
            def get_doc_before_save(self):return self.get('_before')
        doc=Doc(allocation_kind='Tagged Stock',handling_unit='TAG',allocated_qty=3,delivered_qty=0,drop_scan_confirmed='0')
        doc.validate()
        doc.drop_scan_confirmed=1
        # Dict fixture stores real field values by key, like the actual Document.get API.
        doc['drop_scan_confirmed']=1
        with self.assertRaisesRegex(ValueError,'controlled scan action'):doc.validate()
        doc['drop_scan_confirmed']=0;doc['_before']=Row(doc);doc['drop_scan_evidence']='forged'
        doc['meta']=Row(get_label=lambda f:f)
        with self.assertRaisesRegex(ValueError,'immutable'):doc.validate()

    def test_default_off_preserves_existing_session_without_retroactive_gating(self):
        self.d.require_delivery_product_scan=0
        self.assertFalse(self.service.context(self.d)['required'])
        self.service.assert_verified(self.d);self.b.confirm();self.assertEqual(self.d.state,'Awaiting Confirmation')
    def test_schema_and_before_submit_hook_preserve_read_only_audit_and_native_boundary(self):
        path=ROOT/'cfg_kanban/doctype/cfg_kanban_delivery_allocation/cfg_kanban_delivery_allocation.json'
        fields={r['fieldname']:r for r in json.loads(path.read_text())['fields']}
        self.assertTrue(fields['drop_scan_evidence']['read_only']);self.assertFalse(fields['drop_scan_evidence'].get('reqd'))
        hooks=(ROOT/'hooks.py').read_text();self.assertIn('cfg_kanban.services.delivery_product_scans.validate_delivery_note',hooks)
        for slug,field in [('cfg_kanban_delivery_session','require_delivery_product_scan'),('cfg_kanban_delivery_allocation','drop_scan_evidence')]:
            self.assertIn(field,(ROOT/f'cfg_kanban/doctype/{slug}/{slug}.py').read_text())


class TestLooseTagDropCheck(unittest.TestCase):
    def setUp(self):
        self.f=LooseTagFixture();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.service,self.events,self.container=install(self,self.f.base)
        self.f.base.site.require_delivery_product_scan=1
    def test_single_two_sku_box_scan_adopts_only_accepted_quantities_after_partial_refusal(self):
        f=self.f;f.create();f.load_pack();f.scan()
        quantities=[dict(dispatch_allocation=r.dispatch_allocation,accepted_qty=r.qty if i==0 else 1,
            refusal_reason='' if i==0 else 'Reduced order',condition='Good / Unwanted') for i,r in enumerate(f.pack().lines)]
        f.outcomes.declare(f.trip,f.trip.stops[0],f.plan,quantities,f.op,f.session,'DECISION')
        f.base.start();d=f.base.delivery();before=len(f.posted)
        check=self.service.context(d);self.assertTrue(check['ready']);self.assertEqual([r['qty'] for r in check['rows']],[3,1])
        self.assertTrue(all(r['confirmed'] for r in check['rows']))
        f.base.confirm();self.assertEqual(len(f.posted),before)
        self.assertEqual([r['qty'] for r in f.base.payload()['items']],[3,1])
    def test_wrong_stop_box_scan_and_missing_arrival_do_not_adopt_evidence(self):
        f=self.f;f.create();f.load_pack()
        with self.assertRaises(ValueError):f.scan('OTHER')
        with self.assertRaisesRegex(ValueError,'Scan every assigned'):f.base.start()
        self.assertFalse(self.events)

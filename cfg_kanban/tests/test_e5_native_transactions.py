"""Opt-in native rollback/receipt checks on an isolated, prepared test-site fixture.

Never enabled automatically. No native concurrency or physical acceptance is implied.
See docs/TEST_DISPATCH_E5_COMBINED.md for fixture/authorization prerequisites.
"""
import copy
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

try:
    import frappe
    from frappe.tests.utils import FrappeTestCase
except ImportError:
    frappe=None
    FrappeTestCase=unittest.TestCase

ENABLED=bool(frappe and os.environ.get('CFG_E5_NATIVE_ACCEPTANCE')=='1')


@unittest.skipUnless(ENABLED,'Requires an explicitly authorized isolated Frappe site and prepared E5 fixture')
class TestE5NativeTransactions(FrappeTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.conf.get('cfg_e5_isolated_acceptance'):
            raise RuntimeError('This site is not marked as an isolated E5 acceptance site')
        fixture_path=os.environ.get('CFG_E5_FIXTURE')
        self.token=os.environ.get('CFG_E5_OPERATOR_SESSION')
        if not fixture_path or not self.token:
            raise RuntimeError('Provide CFG_E5_FIXTURE and an active CFG_E5_OPERATOR_SESSION without committing or printing the token')
        self.fixture=json.loads(Path(fixture_path).read_text())
        self.old_user=frappe.session.user
        self.outer_active=False
        self.addCleanup(self.cleanup_request)
        frappe.set_user(self.fixture['terminal_user'])
        from cfg_kanban.services import trip_continuation
        self.subject=trip_continuation
        self.source=frappe.get_doc(trip_continuation.TRIP,self.fixture['source_trip'])
        self.source.check_permission('read')
        if self.source.company!=self.fixture['company'] or not self.fixture['payload'].get('returns'):
            raise RuntimeError('Use the reviewed Company-specific fixture including a pending old-return Case')
        self.outer='cfg_e5_acceptance_outer'
        frappe.db.savepoint(self.outer)
        self.outer_active=True
        self.payload=copy.deepcopy(self.fixture['payload'])
        context=self.subject.get_follow_on_context(self.source.name,self.token,self.payload['warehouse'])
        self.assertEqual(context['blockers'],[])
        self.payload['context_hash']=context['context_hash']
        self.units=set()
        for row in self.payload['stock']:
            preview=self.subject.preview_follow_on_stock(self.source.name,self.payload['warehouse'],row['source_row'],row['kind'],self.token,
                scan_value=row['scan_value'],item_code=row['item_code'],batch_no=row.get('batch_no'))
            self.assertEqual(preview['item_code'],row['item_code'])
            self.assertEqual(preview['batch_no'] or None,row.get('batch_no') or None)
            row['source_hash']=preview['source_hash']
            if preview.get('handling_unit'):self.units.add(preview['handling_unit'])
        self.baseline=self.snapshot()
    def tearDown(self):
        self.cleanup_request()
        super().tearDown()
    def cleanup_request(self):
        if getattr(self,'outer_active',False):
            try:frappe.db.rollback(save_point=self.outer)
            except Exception:frappe.db.rollback()
            self.outer_active=False
        if getattr(self,'old_user',None):frappe.set_user(self.old_user)
    def snapshot(self):
        tables=('CFG Kanban Delivery Trip','CFG Kanban Dispatch Plan','CFG Kanban Dispatch Allocation',
            'CFG Kanban Handling Unit Quantity Ledger','CFG Kanban Event','CFG Kanban Movement Manifest','Stock Entry','Delivery Note')
        source=frappe.db.get_value(self.subject.TRIP,self.source.name,
            ['state','modified','follow_on_trip','driver_route_state','driver_active_vehicle_key'],as_dict=True)
        cases={name:frappe.db.get_value('CFG Kanban Return Case',name,
            ['driver_trip','collection_vehicle_warehouse','custody_trip','custody_vehicle_warehouse','custody_handover_json','received_on','state','modified'],as_dict=True)
            for name in self.payload['returns']}
        units={name:frappe.db.get_value('CFG Kanban Handling Unit',name,['current_qty','reserved_qty','available_qty','current_warehouse','inventory_company','process_certificate_set','expiry_date','movement_state','modified'],as_dict=True) for name in self.units}
        plans=[r.dispatch_plan for r in self.source.dispatch_plans]+([self.source.open_route_plan] if self.source.get('open_route_plan') else [])
        sheet_names={frappe.db.get_value('CFG Kanban Dispatch Plan',name,'active_route_sheet') for name in plans}
        sheets={name:frappe.db.get_value('CFG Kanban Route Sheet',name,['state','revision','modified'],as_dict=True) for name in sheet_names if name}
        return dict(counts={name:frappe.db.count(name) for name in tables},source=source,cases=cases,units=units,sheets=sheets)
    def create(self,event=None):
        with patch.object(frappe.db,'commit',side_effect=AssertionError('E5 sub-operation attempted an unexpected commit')):
            return self.subject.create_follow_on_trip(self.source.name,copy.deepcopy(self.payload),event or str(uuid.uuid4()),self.token)
    def test_native_success_replays_one_child_and_accepts_its_real_allocation_receipt(self):
        event=str(uuid.uuid4());result=self.create(event);again=self.create(event)
        self.assertEqual(result,again)
        child=frappe.get_doc(self.subject.TRIP,result['trip'])
        self.assertEqual(child.follow_on_of,self.source.name)
        self.assertEqual(frappe.db.get_value(self.subject.TRIP,self.source.name,'state'),'Closed')
        for link in child.dispatch_plans:
            for name in frappe.get_all('CFG Kanban Dispatch Allocation',filters={'dispatch_plan':link.dispatch_plan},pluck='name'):
                allocation=frappe.get_doc('CFG Kanban Dispatch Allocation',name)
                allocation.run_method('validate')
                browser=frappe.get_doc(json.loads(allocation.as_json()))
                browser._doc_before_save=allocation
                browser.run_method('validate')
                self.assertFalse(allocation.movement_manifest)
        for name in self.payload['returns']:
            self.assertEqual(frappe.db.get_value('CFG Kanban Return Case',name,'custody_trip'),child.name)
    def test_native_rollback_after_source_closure_restores_return_custody_and_audit(self):
        with patch.object(self.subject,'_close_sheets',side_effect=RuntimeError('E5 injected after closure')):
            with self.assertRaisesRegex(RuntimeError,'injected after closure'):self.create()
        self.assertEqual(self.snapshot(),self.baseline)
    def test_native_rollback_after_reservation_exchange_and_final_audit(self):
        from cfg_kanban.services import trip_carry_in
        if not self.payload['stock']:self.fail('This native fixture must contain physical stock for rollback coverage')
        original=trip_carry_in.confirm
        def after_exchange(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError('E5 injected after exchange')
        with patch.object(trip_carry_in,'confirm',side_effect=after_exchange):
            with self.assertRaisesRegex(RuntimeError,'injected after exchange'):self.create()
        self.assertEqual(self.snapshot(),self.baseline)
        record=self.subject.record
        def after_audit(event,**values):
            result=record(event,**values)
            if event=='Follow-on Delivery Trip Created':raise RuntimeError('E5 injected final audit')
            return result
        with patch.object(self.subject,'record',side_effect=after_audit):
            with self.assertRaisesRegex(RuntimeError,'injected final audit'):self.create()
        self.assertEqual(self.snapshot(),self.baseline)
    def test_native_void_prevents_a_late_create_with_the_original_request(self):
        event=str(uuid.uuid4())
        result=self.subject.reconcile_follow_on(self.source.name,copy.deepcopy(self.payload),event,self.token,void_reason='Isolated acceptance: do not create')
        self.assertTrue(result['voided'])
        with self.assertRaises(self.subject.FollowOnReplayError):self.create(event)
        self.assertEqual(frappe.db.get_value(self.subject.TRIP,self.source.name,'follow_on_trip'),self.baseline['source'].follow_on_trip)
        self.assertEqual(frappe.db.count(self.subject.TRIP),self.baseline['counts'][self.subject.TRIP])

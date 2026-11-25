"""Actual mixed-recovery functions with the existing E5/ERP-feedback dependency doubles.

No real MariaDB, Frappe HTTP, ERP posting or device acceptance is claimed here.
"""
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock,patch

from cfg_kanban.tests import test_dispatch_recovery as e5b1
from cfg_kanban.tests import test_dispatch_fulfilment as fixture

SERVICE='cfg_kanban.services.dispatch_recovery_mixed'
MANIFEST,HU=e5b1.MANIFEST,e5b1.HU


class TestMixedRecovery(unittest.TestCase):
    def setUp(self):
        self.base=e5b1.TestDispatchRecovery();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.b=self.base.b;self.r=self.base.r;self.plan=self.base.plan;self.data=self.base.data
        self.mod=types.ModuleType(SERVICE)
        self.mod.__dict__.update(frappe=self.b.frappe,json=json,isfinite=math.isfinite,
            flt=lambda n:float(n or 0),now_datetime=lambda:self.r.now,canonical_key=self.base.mod.canonical_key,
            record=self.base.mod.record,KEEP='Keep on Lorry',MOVE='Return / Transfer',
            ACTION='Mixed Leftover Dispositions',EPS=0.000001)
        fixture.extract('services/dispatch_recovery_mixed.py',self.mod.__dict__)
        self.mod._recovery=lambda:self.base.mod
        patcher=patch.dict(sys.modules,{SERVICE:self.mod});patcher.start();self.addCleanup(patcher.stop)
        self.b.frappe.has_permission=Mock(return_value=True)
        self.b.add('Company','B')
        original=self.base.get_doc
        def get_doc(dt,name=None,**kwargs):
            doc=original(dt,name,**kwargs)
            if not callable(doc.get('check_permission')):doc.check_permission=Mock()
            return doc
        self.b.frappe.get_doc=get_doc
        for table in self.data.values():
            for doc in list(table.values()):
                if not callable(doc.get('check_permission')):doc.check_permission=Mock()
        self.base.loose(6)
        self.base.unit.process_certificate_set=None
        self.b.add('CFG Kanban Logistics Route','OTHER',**{key:value for key,value in self.base.route.items()
            if key not in ('doctype','name','_store','check_permission')},check_permission=Mock())
        self.data['CFG Kanban Logistics Route']['OTHER'].destination_warehouse='LORRY2'

    def choice(self,source='ALLOC',qty=5,route=None):
        return dict(dispatch_allocation=source,qty=qty,action=self.mod.KEEP if route is None else self.mod.MOVE,logistics_route=route)

    def create(self,choices=None,event='MIX',reason='Separate leftovers',hash_value=None):
        choices=choices or [self.choice(),self.choice('LOOSE',3,'RETURN'),self.choice('LOOSE',3,'OTHER')]
        return self.mod.create_mixed_dispatch_recovery(self.r.review().name,choices,reason,
            hash_value or self.r.mod._hash(self.r.mod._balances(self.plan)),event,'SESSION')

    def members(self):
        return [self.data[MANIFEST][g['manifest']] for g in self.mod.active(self.r.review())['groups']]

    def post(self,manifest):
        for line in manifest.lines:
            if line.handling_unit:self.base.mod.scan_dispatch_recovery(manifest.name,'TAG1','SCAN','SESSION')
            else:self.base.mod.confirm_dispatch_recovery_loose(manifest.name,line.name,line.dispatch_qty,'LOOSE','SESSION')
        self.base.mod.prepare_dispatch_recovery(manifest.name,'PREPARE','SESSION')
        self.base.mod.post_dispatch_recovery(manifest.name,'POST','SESSION')
        sle=self.data['Stock Ledger Entry'].pop('RECOVERY-SLE')
        self.data['Stock Ledger Entry']['SLE-'+manifest.name]=sle

    def test_approval_freezes_exact_multiple_destinations_and_kept_stock_without_posting(self):
        before=(self.b.erp_balance,self.base.unit.current_qty,self.base.unit.reserved_qty)
        result=self.create();members=self.members()
        self.assertEqual(len(members),2)
        self.assertEqual({m.destination_warehouse for m in members},{'SOURCE','LORRY2'})
        self.assertTrue(all(m.recovery_bundle_key for m in members))
        self.assertTrue(result['mixed_recovery']['active']);self.assertFalse(result['mixed_recovery']['all_received'])
        self.assertEqual((self.b.erp_balance,self.base.unit.current_qty,self.base.unit.reserved_qty),before)
        self.assertFalse(self.base.saved_entries)

    def test_real_feedback_two_loose_movements_keep_tag_then_fresh_count_settles(self):
        self.create()
        for manifest in self.members():self.post(manifest)
        self.assertEqual(self.b.erp_balance,5);self.assertEqual(self.base.unit.current_warehouse,'LORRY1')
        self.assertEqual(self.plan.vehicle_warehouse,'LORRY1');self.assertNotEqual(self.plan.state,'Reconciled')
        self.r.count();result=self.r.finish(self.mod.ACTION)
        self.assertEqual(result['review']['state'],'Completed');self.assertEqual(self.plan.state,'Reconciled')
        self.assertEqual(self.plan.route_stock_commitment,0)
        self.assertEqual(len(self.base.saved_entries),2)

    def test_tag_movement_preserves_certificate_and_loose_stock_stays_on_lorry(self):
        self.base.unit.process_certificate_set='CERT'
        self.create([self.choice(route='RETURN'),self.choice('LOOSE',6)])
        self.post(self.members()[0]);self.r.count();self.r.finish(self.mod.ACTION)
        self.assertEqual((self.base.unit.current_warehouse,self.base.unit.process_certificate_set),('SOURCE','CERT'))
        self.assertEqual(self.b.erp_balance,6)

    def test_ambiguous_certified_loose_transfer_still_requires_physical_tag(self):
        self.base.unit.process_certificate_set='CERT'
        self.create()
        with self.assertRaisesRegex(ValueError,'Certified stock exists'):
            self.post(self.members()[0])
        self.assertFalse(self.base.saved_entries)

    def test_all_stock_kept_needs_no_manifest_but_still_requires_count_and_final_review(self):
        self.create([self.choice(),self.choice('LOOSE',6)])
        self.assertEqual(self.members(),[]);self.assertFalse(self.r.review().recovery_manifest)
        self.r.count();self.r.finish(self.mod.ACTION)
        self.assertEqual(self.b.erp_balance,11)

    def test_missing_excess_nan_negative_foreign_and_fractional_whole_uom_rejected(self):
        variants=[[],[self.choice()],[self.choice(),self.choice('LOOSE',7,'RETURN')],
            [self.choice(),self.choice('LOOSE',float('nan'),'RETURN')],
            [self.choice(),self.choice('LOOSE',-6,'RETURN')],
            [self.choice('NOT-THIS-PLAN'),self.choice('LOOSE',6,'RETURN')]]
        for rows in variants:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                self.mod.create_mixed_dispatch_recovery(self.r.review().name,rows,'Reason',
                    self.r.mod._hash(self.r.mod._balances(self.plan)),'INVALID','SESSION')
        original=self.b.frappe.db.get_value
        self.b.frappe.db.get_value=lambda dt,name,field,**kw:1 if dt=='UOM' else original(dt,name,field,**kw)
        with self.assertRaisesRegex(ValueError,'whole-number'):
            self.create([self.choice(),self.choice('LOOSE',2.5,'RETURN'),self.choice('LOOSE',3.5)])
        self.assertFalse(self.r.review().mixed_recovery_json)

    def test_physical_tag_cannot_be_split_or_duplicated_across_choices(self):
        with self.assertRaisesRegex(ValueError,'physical Stock Tag'):
            self.create([self.choice(qty=2,route='RETURN'),self.choice(qty=3),self.choice('LOOSE',6)])

    def test_return_holds_cannot_be_kept_or_split_between_destinations(self):
        self.mod._held=lambda plan,source:[object()] if source=='LOOSE' else []
        with self.assertRaisesRegex(ValueError,'held for return'):
            self.create([self.choice(),self.choice('LOOSE',6)])
        with self.assertRaisesRegex(ValueError,'held source'):
            self.create()

    def test_native_read_route_permissions_company_and_stale_balance_enforced(self):
        self.plan.check_permission.side_effect=ValueError('Not permitted')
        with self.assertRaisesRegex(ValueError,'Not permitted'):self.create()
        self.plan.check_permission.side_effect=None
        self.base.route.check_permission.side_effect=ValueError('Route not permitted')
        with self.assertRaisesRegex(ValueError,'Route not permitted'):self.create()
        self.base.route.check_permission.side_effect=None
        self.base.route.destination_company='A'
        with self.assertRaisesRegex(ValueError,'same-Company'):self.create()
        self.base.route.destination_company='B'
        with self.assertRaisesRegex(ValueError,'balances changed'):self.create(hash_value='STALE')

    def test_same_request_replays_after_posting_and_settlement_without_duplicate_movements(self):
        choices=[self.choice(route='RETURN'),self.choice('LOOSE',6)]
        hash_value=self.r.mod._hash(self.r.mod._balances(self.plan))
        self.create(choices,hash_value=hash_value);self.create(choices,hash_value=hash_value)
        self.post(self.members()[0]);self.r.count();self.r.finish(self.mod.ACTION)
        result=self.create(choices,hash_value=hash_value)
        self.assertEqual(result['review']['state'],'Completed');self.assertEqual(len(self.base.saved_entries),1)
        with self.assertRaisesRegex(ValueError,'different per-item'):
            self.create(choices,reason='Changed',hash_value=hash_value)

    def test_legacy_recovery_cannot_replace_frozen_bundle_or_resume_it(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'per-item recovery'):self.base.create()
        with self.assertRaisesRegex(ValueError,'cannot be resumed'):
            self.r.mod.resume_dispatch_review(self.r.review().name,'Resume','RESUME','SESSION')

    def test_settlement_blocked_until_all_groups_received_or_if_kept_stock_changes(self):
        self.create();self.post(self.members()[0]);self.r.count()
        with self.assertRaisesRegex(ValueError,'every per-item'):self.r.finish(self.mod.ACTION)
        self.post(self.members()[1]);self.base.unit.current_qty=4;self.base.unit.available_qty=4
        self.r.count()
        with self.assertRaisesRegex(ValueError,'Stock Tag moved|current physical|ERP stock changed'):
            self.r.finish(self.mod.ACTION)

    def test_individual_cancellation_blocked_whole_unused_bundle_cancel_restores_reservations(self):
        self.create([self.choice(route='RETURN'),self.choice('LOOSE',6,'OTHER')])
        tag=next(m for m in self.members() if m.lines[0].handling_unit)
        self.base.mod.scan_dispatch_recovery(tag.name,'TAG1','SCAN','SESSION')
        self.base.mod.prepare_dispatch_recovery(tag.name,'PREP','SESSION')
        self.assertEqual(self.base.unit.reserved_qty,5)
        with self.assertRaisesRegex(ValueError,'whole unused'):
            self.base.mod.cancel_dispatch_recovery(tag.name,'Cancel','CANCEL','SESSION')
        self.mod.cancel_mixed_dispatch_recovery(self.r.review().name,'Correct choices','CANCEL','SESSION')
        self.assertFalse(self.mod.active(self.r.review()));self.assertEqual(self.base.unit.reserved_qty,0)
        self.assertEqual(tag.state,'Cancelled')
        self.create(event='REVISED')
        self.assertEqual(len(self.members()),2)

    def test_bundle_cancellation_blocked_after_any_native_draft_or_posted_movement(self):
        self.create();self.members()[0].dispatch_command='COMMAND'
        with self.assertRaisesRegex(ValueError,'after any ERP work'):
            self.mod.cancel_mixed_dispatch_recovery(self.r.review().name,'Cancel','CANCEL','SESSION')
        self.assertTrue(self.mod.active(self.r.review()))

    def test_reopening_second_manifest_does_not_silently_select_first_destination(self):
        self.create();second=self.members()[1]
        result=self.base.mod.get_dispatch_recovery_context(second.name,'SESSION')
        self.assertEqual(result['recovery_manifest']['name'],second.name)

    def test_mixed_loose_movement_cannot_be_reused_as_another_plans_evidence(self):
        self.create();manifest=self.members()[0];self.post(manifest)
        other=fixture.Record(name='OTHER-REVIEW',opened_on=self.r.now)
        rows=self.r.mod._balances(self.plan)
        with self.assertRaisesRegex(ValueError,'another Dispatch Review'):
            self.r.mod._movement_evidence(self.plan,other,rows,manifest.dispatch_stock_entry,
                manifest.recovery_action,fixture.Record(closed_on=self.r.now))

    def test_qc_release_and_disposal_wait_for_mixed_settlement_without_blocking_old_review(self):
        namespace=dict(frappe=self.b.frappe,json=json)
        fixture.extract('services/driver_delivery_outcomes.py',namespace,{'assert_custody_not_frozen'})
        check=namespace['assert_custody_not_frozen']
        check(self.plan.name)  # Ordinary E5A/B1 review remains unchanged.
        self.create([self.choice(),self.choice('LOOSE',6)])
        with self.assertRaisesRegex(ValueError,'Settle the frozen per-item'):check(self.plan.name)
        self.r.count();self.r.finish(self.mod.ACTION)
        check(self.plan.name)

    def test_saved_recipe_tampering_and_movement_cancellation_after_settlement_rejected(self):
        self.create([self.choice(route='RETURN'),self.choice('LOOSE',6)])
        manifest=self.members()[0];original=manifest.recovery_snapshot_json
        manifest.recovery_snapshot_json='[]'
        with self.assertRaisesRegex(ValueError,'remainder changed'):
            self.base.mod.validate_recovery_manifest(manifest,confirmed=False)
        manifest.recovery_snapshot_json=original;self.post(manifest);self.r.count();self.r.finish(self.mod.ACTION)
        with self.assertRaisesRegex(ValueError,'audited follow-on'):
            self.mod.protect_movement_cancellation(self.base.saved_entries[0])


if __name__=='__main__':unittest.main()

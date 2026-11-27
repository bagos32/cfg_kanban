"""Actual Close Plan code with native-shaped child rows and late ERP Stock Adoption.

Offline evidence/transaction doubles, not native Frappe/MariaDB acceptance.
"""
import datetime
import json
import unittest

from cfg_kanban.tests import test_dispatch_closure as fixture


class TestReturnedStockAdoption(unittest.TestCase):
    def setUp(self):
        self.t = fixture.TestDocumentClosure()
        self.t.setUp()
        self.addCleanup(self.t.doCleanups)
        self.data = self.t.data
        self.p = self.t.closure
        self.loaded = datetime.datetime(2026, 11, 19, 10)
        self.adopted = datetime.datetime(2026, 11, 19, 12)
        self.returned = datetime.datetime(2026, 11, 19, 18)

    def adoption(self, tag='LATE-TAG', qty=2, loose=2, at=None, name='ADOPT'):
        at = at or self.adopted
        adoption = self.t.add(self.p.ADOPTION, name, status='Adopted', handling_unit=tag,
            company='B', warehouse='LORRY', item_code='B', batch_no=None, stock_uom='Nos',
            adopted_qty=qty, adopted_on=at, erp_qty_at_adoption=loose+10,
            tagged_qty_before=10, untagged_qty_before=loose, remaining_untagged_qty=loose-qty)
        self.t.add(fixture.HU, tag, handling_unit_id=tag, tag_kind='Main Stock Tag',
            current_qty=qty, current_warehouse='SOURCE', inventory_company='B', item_code='B',
            stock_uom='Nos', origin_reference_doctype=self.p.ADOPTION, origin_reference_name=name)
        self.t.add(fixture.LEDGER, 'ACTIVATE-'+tag, event_type='Pack / Activate',
            reference_doctype=self.p.ADOPTION, reference_name=name, destination_handling_unit=tag,
            item_code='B', stock_uom='Nos', stock_qty=qty, destination_qty_delta=qty, source_qty_delta=0,
            destination_company='B', destination_warehouse='LORRY',
            creation=at+datetime.timedelta(microseconds=100))
        return adoption

    def late_return(self):
        # Preserve the original untagged load; only the later return has the new tag.
        manifest, entry = self.t.returned()
        self.adoption()
        manifest.lines[0].update(handling_unit='LATE-TAG', dispatch_allocation=None)
        entry.items[0].cfg_handling_unit = 'LATE-TAG'
        self.location('LATE-TAG', 2)
        self.native_rows(manifest, entry)
        return manifest, entry

    def location(self, tag, qty, name='LOCATION'):
        self.t.add(fixture.LEDGER, name, event_type='Location Transfer',
            source_handling_unit=tag, reference_doctype='Stock Entry', reference_name='RETURN-STE',
            item_code='B', stock_uom='Nos', stock_qty=qty, source_company='B', source_warehouse='LORRY',
            destination_company='B', destination_warehouse='SOURCE', creation=self.returned)

    def native_rows(self, manifest, entry):
        manifest.lines = [fixture.NativeDocument(**row.as_dict()) for row in manifest.lines]
        entry.items = [fixture.NativeDocument(**row.as_dict()) for row in entry.items]

    def extra_return_line(self, manifest, entry, name, qty, tag=None, source=None):
        line = fixture.NativeDocument(name=name,dispatch_allocation=source,handling_unit=tag,
            item_code='B',stock_uom='Nos',dispatch_qty=qty,received_qty=qty,state='Received')
        item = fixture.NativeDocument(name=name+'-ITEM',cfg_manifest_line=name,cfg_handling_unit=tag,
            item_code='B',stock_uom='Nos',uom='Nos',transfer_qty=qty,s_warehouse='LORRY',t_warehouse='SOURCE')
        manifest.lines.append(line); entry.items.append(item)
        for warehouse, sign in (('LORRY',-1),('SOURCE',1)):
            self.t.add('Stock Ledger Entry',name+'-'+warehouse,voucher_type='Stock Entry',voucher_no=entry.name,
                voucher_detail_no=item.name,warehouse=warehouse,item_code='B',stock_uom='Nos',actual_qty=sign*qty,
                creation=self.returned)
        return line, item

    def evidence(self, result):
        return json.loads(result['review']['closure_evidence_json'])['returned']

    def unchanged_after_failure(self, regex):
        before = self.t.snapshot_stock()
        sources = {name: row.as_dict() for name, row in self.data[fixture.SOURCE].items()}
        reviews = {name: row.as_dict() for name, row in self.data.get(fixture.REVIEW, {}).items()}
        events = len(self.t.r.events)
        with self.assertRaisesRegex(ValueError, regex): self.t.close_plan()
        self.assertEqual(before, self.t.snapshot_stock())
        self.assertEqual(sources, {name: row.as_dict() for name, row in self.data[fixture.SOURCE].items()})
        self.assertEqual(reviews, {name: row.as_dict() for name, row in self.data.get(fixture.REVIEW, {}).items()})
        self.assertEqual(events, len(self.t.r.events)); self.assertFalse(self.t.prohibited)
        self.assertEqual(self.data[fixture.PLAN]['P2'].state, 'Loaded')

    def test_real_shaped_child_rows_fix_the_reported_crash_for_original_loose_return(self):
        manifest, entry = self.t.returned()
        self.native_rows(manifest, entry)
        with self.assertRaises(TypeError): manifest.lines[0]['item_code']
        before = self.t.snapshot_stock()
        self.assertEqual(self.t.close_plan()['review']['action'], 'Returned to Warehouse')
        self.assertEqual(before, self.t.snapshot_stock())

    def test_native_tagged_return_rows_keep_original_matching_and_location_validation(self):
        manifest, entry = self.t.returned(tag='ORIGINAL-TAG')
        self.native_rows(manifest, entry)
        self.assertEqual(self.t.close_plan()['plan']['state'], 'Reconciled')

    def test_loose_load_adopted_then_returned_is_discovered_and_settled_with_no_stock_writes(self):
        self.late_return()
        self.t.review(self.data[fixture.PLAN]['P2'])
        stock = self.t.snapshot_stock(); source = self.data[fixture.SOURCE]['SRC-P2'].as_dict()
        adoption = self.data[self.p.ADOPTION]['ADOPT'].as_dict()
        self.assertEqual(self.p.get_close_plan_context('P2', 'TOKEN')['return_manifest'], 'RETURN')
        result = self.t.close_plan(manifest=None)
        returned = self.evidence(result)
        self.assertEqual(result['plan']['fulfilment_status'], 'Closed Incomplete')
        self.assertEqual(result['plan']['total_delivered_qty'], 0)
        self.assertEqual(returned['stock_entries'], ['RETURN-STE'])
        self.assertEqual(returned['tag_ledgers'], ['LOCATION'])
        self.assertTrue(returned['posted_before_review'])
        change = returned['identity_changes'][0]
        self.assertEqual((change['stock_adoption'], change['activation_ledger'], change['handling_unit'], change['qty']),
                         ('ADOPT', 'ACTIVATE-LATE-TAG', 'LATE-TAG', 2))
        self.assertEqual(returned['allocation_sources'], [dict(manifest_line='RET-LINE', handling_unit='LATE-TAG',
            dispatch_allocation='SRC-P2', qty=2, stock_uom='Nos')])
        self.assertEqual(source, self.data[fixture.SOURCE]['SRC-P2'].as_dict())
        self.assertEqual(adoption, self.data[self.p.ADOPTION]['ADOPT'].as_dict())
        self.assertIsNone(self.data[fixture.SOURCE]['SRC-P2'].handling_unit)
        self.assertEqual(stock, self.t.snapshot_stock()); self.assertFalse(self.t.prohibited)

    def test_retry_same_or_new_token_has_one_settlement_and_no_duplicate_stock_or_audit(self):
        self.late_return(); self.t.close_plan()
        stock = self.t.snapshot_stock(); events = len(self.t.r.events)
        self.t.close_plan(); self.t.close_plan('NEW-TOKEN')
        self.assertEqual(len(self.data[fixture.REVIEW]), 1)
        self.assertEqual(len(self.t.r.events), events); self.assertEqual(stock, self.t.snapshot_stock())

    def test_mixed_original_tag_and_later_tag_keep_both_physical_and_loaded_identities(self):
        manifest,entry = self.late_return(); plan = self.data[fixture.PLAN]['P2']
        plan.lines[0].loaded_qty = 5; plan.total_loaded_qty = 5
        self.t.add(fixture.SOURCE,'SRC-ORIGINAL',dispatch_plan=plan.name,dispatch_plan_line='P2-LINE',
            movement_manifest=plan.movement_manifest,state='Loaded',load_confirmed=1,allocated_qty=3,
            allocation_kind='Tagged Stock',item_code='B',stock_uom='Nos',handling_unit='ORIGINAL')
        self.t.add(fixture.HU,'ORIGINAL',handling_unit_id='ORIGINAL',current_qty=3,inventory_company='B',
            current_warehouse='SOURCE',item_code='B',stock_uom='Nos')
        self.extra_return_line(manifest,entry,'ORIGINAL-LINE',3,'ORIGINAL','SRC-ORIGINAL')
        self.location('ORIGINAL',3,'ORIGINAL-LOCATION')
        before = self.t.snapshot_stock(); returned = self.evidence(self.t.close_plan())
        self.assertEqual(len(returned['identity_changes']),1)
        self.assertEqual(set(returned['tag_ledgers']),{'LOCATION','ORIGINAL-LOCATION'})
        self.assertEqual({row['dispatch_allocation']:row['qty'] for row in returned['allocation_sources']},
                         {'SRC-P2':2,'SRC-ORIGINAL':3})
        self.assertEqual(before,self.t.snapshot_stock())

    def test_same_plan_loose_sources_distribute_exactly_after_explicit_source_is_accounted_for(self):
        manifest,entry = self.late_return(); plan = self.data[fixture.PLAN]['P2']
        plan.lines[0].loaded_qty = 3; plan.total_loaded_qty = 3
        self.t.add(fixture.SOURCE,'SRC-SECOND',dispatch_plan=plan.name,dispatch_plan_line='P2-LINE',
            movement_manifest=plan.movement_manifest,state='Loaded',load_confirmed=1,allocated_qty=1,
            allocation_kind='Untagged ERP Stock',item_code='B',stock_uom='Nos')
        self.data[self.p.ADOPTION]['ADOPT'].update(erp_qty_at_adoption=13,untagged_qty_before=3,remaining_untagged_qty=1)
        # This explicit row comes last physically but must take its source budget first.
        self.extra_return_line(manifest,entry,'ZZ-EXPLICIT',1,source='SRC-P2')
        returned = self.evidence(self.t.close_plan())
        self.assertEqual([(row['dispatch_allocation'],row['qty']) for row in returned['allocation_sources']],
                         [('SRC-P2',1),('SRC-P2',1),('SRC-SECOND',1)])

    def test_sequential_adoptions_from_one_loose_pool_are_audited_without_double_using_the_pool(self):
        manifest,entry = self.late_return()
        manifest.lines[0].update(dict(dispatch_qty=1,received_qty=1)); entry.items[0].transfer_qty = 1
        self.data[self.p.ADOPTION]['ADOPT'].update(adopted_qty=1,remaining_untagged_qty=1)
        self.data[fixture.LEDGER]['ACTIVATE-LATE-TAG'].update(stock_qty=1,destination_qty_delta=1)
        self.data[fixture.LEDGER]['LOCATION'].stock_qty = 1
        for event in self.data['Stock Ledger Entry'].values(): event.actual_qty = 1 if event.warehouse == 'SOURCE' else -1
        self.adoption('SECOND-TAG',1,1,self.adopted+datetime.timedelta(hours=1),'SECOND-ADOPT')
        self.extra_return_line(manifest,entry,'SECOND-LINE',1,'SECOND-TAG')
        self.location('SECOND-TAG',1,'SECOND-LOCATION')
        changes = self.evidence(self.t.close_plan())['identity_changes']
        self.assertEqual({row['stock_adoption']:row['prior_adopted_qty'] for row in changes}, {'ADOPT':0,'SECOND-ADOPT':1})

    def test_batch_and_stock_uom_remain_exact_for_later_adopted_tag(self):
        manifest,entry = self.late_return(); source = self.data[fixture.SOURCE]['SRC-P2']
        source.update(batch_no='LOT',stock_uom='Kg'); self.data[fixture.PLAN]['P2'].lines[0].update(batch_no='LOT',stock_uom='Kg')
        self.data[self.p.ADOPTION]['ADOPT'].update(batch_no='LOT',stock_uom='Kg')
        manifest.lines[0].update(dict(batch_no='LOT',stock_uom='Kg')); entry.items[0].update(dict(batch_no='LOT',stock_uom='Kg',uom='Kg'))
        for event in self.data[fixture.LEDGER].values(): event.update(batch_no='LOT',stock_uom='Kg')
        for event in self.data['Stock Ledger Entry'].values(): event.stock_uom='Kg'
        self.assertEqual(self.evidence(self.t.close_plan())['identity_changes'][0]['group'],['B','LOT','Kg'])

    def test_failure_after_settlement_rolls_back_audit_review_and_plan(self):
        self.late_return(); original = self.p._response
        def failed(plan, result=None):
            if plan.state == 'Reconciled': raise ValueError('Injected response failure')
            return original(plan, result)
        self.p._response = failed
        self.unchanged_after_failure('Injected response failure')
        self.assertFalse(self.t.r.events)

    def test_wrong_adoption_scope_dates_status_and_snapshots_fail_without_writes(self):
        cases = [{'company':'A'}, {'warehouse':'OTHER'}, {'item_code':'OTHER'}, {'batch_no':'LOT'},
            {'stock_uom':'Kg'}, {'handling_unit':'OTHER'}, {'status':'Pending'},
            {'adopted_on':self.loaded-datetime.timedelta(hours=1)},
            {'adopted_on':self.returned+datetime.timedelta(hours=1)},
            {'adopted_qty':3}, {'erp_qty_at_adoption':20}, {'remaining_untagged_qty':1}]
        for change in cases:
            with self.subTest(change=change):
                self.setUp(); self.late_return(); self.data[self.p.ADOPTION]['ADOPT'].update(change)
                self.unchanged_after_failure('Adoption|tag')

    def test_missing_wrong_or_duplicate_activation_and_location_ledgers_are_rejected(self):
        for case in ('missing', 'wrong_scope', 'wrong_qty', 'wrong_time', 'duplicate', 'location'):
            with self.subTest(case=case):
                self.setUp(); self.late_return(); event = self.data[fixture.LEDGER]['ACTIVATE-LATE-TAG']
                if case == 'missing': del self.data[fixture.LEDGER][event.name]
                if case == 'wrong_scope': event.destination_warehouse = 'OTHER'
                if case == 'wrong_qty': event.destination_qty_delta = 1
                if case == 'wrong_time': event.creation = self.loaded
                if case == 'duplicate': self.t.add(fixture.LEDGER, 'DUPLICATE', **{k:v for k,v in event.as_dict().items() if k not in ('name','doctype')})
                if case == 'location': self.data[fixture.LEDGER]['LOCATION'].stock_qty = 1
                self.unchanged_after_failure('activation|location-transfer')

    def test_adoption_without_origin_partial_tag_or_intervening_quantity_change_needs_e5(self):
        for case in ('origin', 'partial', 'split', 'refill', 'consume'):
            with self.subTest(case=case):
                self.setUp(); self.late_return()
                if case == 'origin': self.data[fixture.HU]['LATE-TAG'].origin_reference_doctype = 'Stock Entry'
                elif case == 'partial': self.data[self.p.ADOPTION]['ADOPT'].adopted_qty = 3
                else:
                    self.t.add(fixture.LEDGER, 'CHANGED', event_type=case, source_handling_unit='LATE-TAG',
                        source_qty_delta=-1 if case != 'refill' else 0, destination_handling_unit='LATE-TAG' if case == 'refill' else None,
                        destination_qty_delta=1 if case == 'refill' else 0, creation=self.adopted+datetime.timedelta(hours=1))
                self.unchanged_after_failure('provenance|whole unchanged|changed quantity')

    def test_later_use_after_historical_return_remains_valid(self):
        self.late_return(); self.data[fixture.HU]['LATE-TAG'].update(current_qty=0,item_code='NEW',inventory_company='A')
        self.data[self.p.ADOPTION]['ADOPT'].status = 'Allocated to Cycle'
        self.t.add(fixture.LEDGER, 'LATER-USE', source_handling_unit='LATE-TAG', source_qty_delta=-2,
            creation=self.returned+datetime.timedelta(hours=1))
        self.assertEqual(self.t.close_plan()['plan']['state'], 'Reconciled')

    def transit_return(self):
        manifest,entry = self.late_return()
        manifest.update(internal_transfer_mode='Goods in Transit',transit_warehouse='TRANSIT',receipt_stock_entry='RECEIPT-STE')
        entry.cfg_transfer_stage = 'Outward'; entry.items[0].t_warehouse = 'TRANSIT'
        self.data['Stock Ledger Entry']['SLE-SOURCE'].warehouse = 'TRANSIT'
        self.data[fixture.LEDGER]['LOCATION'].destination_warehouse = 'TRANSIT'
        item = entry.items[0]
        self.t.add('Stock Entry Detail',item.name,parent=entry.name,cfg_manifest_line=item.cfg_manifest_line)
        receipt_item = fixture.NativeDocument(**dict(item.as_dict(),name='RECEIPT-ITEM',s_warehouse='TRANSIT',
            t_warehouse='SOURCE',against_stock_entry=entry.name,ste_detail=item.name))
        self.t.add('Stock Entry','RECEIPT-STE',company='B',docstatus=1,purpose='Material Transfer',
            cfg_movement_manifest=manifest.name,cfg_transfer_stage='Receipt',items=[receipt_item])
        for warehouse,sign in (('TRANSIT',-1),('SOURCE',1)):
            self.t.add('Stock Ledger Entry','RECEIPT-'+warehouse,voucher_type='Stock Entry',voucher_no='RECEIPT-STE',
                voucher_detail_no=receipt_item.name,warehouse=warehouse,item_code='B',stock_uom='Nos',actual_qty=sign*2,
                creation=self.returned+datetime.timedelta(hours=2))
        self.t.add(fixture.LEDGER,'RECEIPT-LOCATION',event_type='Location Transfer',source_handling_unit='LATE-TAG',
            reference_doctype='Stock Entry',reference_name='RECEIPT-STE',item_code='B',stock_uom='Nos',stock_qty=2,
            source_company='B',source_warehouse='TRANSIT',destination_company='B',destination_warehouse='SOURCE')

    def test_native_goods_in_transit_rows_require_both_exact_legs_and_tag_ledgers(self):
        self.transit_return(); before = self.t.snapshot_stock()
        returned = self.evidence(self.t.close_plan())
        self.assertEqual(returned['stock_entries'],['RETURN-STE','RECEIPT-STE'])
        self.assertEqual(returned['tag_ledgers'],['LOCATION','RECEIPT-LOCATION'])
        self.assertEqual(before,self.t.snapshot_stock())

    def test_adopted_tag_changed_between_transit_legs_is_not_a_whole_unchanged_return(self):
        self.transit_return()
        self.t.add(fixture.LEDGER,'IN-TRANSIT-CONSUMPTION',source_handling_unit='LATE-TAG',source_qty_delta=-1,
            creation=self.returned+datetime.timedelta(hours=1))
        self.unchanged_after_failure('changed quantity through ledger IN-TRANSIT-CONSUMPTION')

    def competing_plan(self, at=None):
        other = self.t.r.plan('OTHER', 'Open Route Stock')
        self.t.make_load(other, 'B', None, 1)
        other.loaded_on = at or self.loaded
        return other

    def test_competing_loose_plan_at_adoption_cannot_be_claimed_even_if_it_settled_later(self):
        for settled in (False, True):
            with self.subTest(settled=settled):
                self.setUp(); self.late_return(); other = self.competing_plan()
                if settled:
                    review = self.t.review(other)
                    review.update(state='Completed', closed_on=self.returned+datetime.timedelta(hours=1))
                    other.update(state='Reconciled', dispatch_review_state='Settled')
                self.unchanged_after_failure('ambiguous loose ownership with Plan OTHER')

    def test_unrelated_tagged_stock_and_loose_stock_loaded_after_adoption_do_not_block(self):
        self.late_return(); self.competing_plan(self.adopted+datetime.timedelta(hours=1))
        other = self.t.r.plan('TAGGED-OTHER', 'Open Route Stock')
        self.t.make_load(other, 'B', 'UNRELATED-TAG', 10)
        self.assertEqual(self.t.close_plan()['plan']['state'], 'Reconciled')

    def test_surplus_unassigned_loose_stock_makes_snapshot_ownership_ambiguous(self):
        self.late_return(); self.data[self.p.ADOPTION]['ADOPT'].update(erp_qty_at_adoption=13,
            untagged_qty_before=3, remaining_untagged_qty=1)
        self.unchanged_after_failure('Plan loose balance was 2 Nos, untagged snapshot was 3')

    def test_unrelated_loose_movement_before_adoption_blocks_even_when_net_totals_match(self):
        self.late_return()
        item = fixture.NativeDocument(name='UNRELATED-ROW',item_code='B',stock_uom='Nos',s_warehouse='LORRY',t_warehouse='SOURCE')
        self.t.add('Stock Entry','UNRELATED-STE',company='B',docstatus=1,items=[item])
        self.t.add('Stock Ledger Entry','UNRELATED-SLE',warehouse='LORRY',item_code='B',stock_uom='Nos',actual_qty=-2,
            voucher_type='Stock Entry',voucher_no='UNRELATED-STE',voucher_detail_no=item.name,
            creation=self.adopted-datetime.timedelta(minutes=1))
        self.unchanged_after_failure('UNRELATED-STE changes loose B before tagging')

    def partial_delivery(self, when):
        self.t.deliver('P2')  # Delivered two of a five-unit original loose load.
        note = self.data['Delivery Note']['DN-P2']
        note.items = [fixture.NativeDocument(**row.as_dict()) for row in note.items]
        source = self.data[fixture.SOURCE]['SRC-P2']; source.allocated_qty = 5
        plan = self.data[fixture.PLAN]['P2']; plan.lines[0].loaded_qty = 5; plan.total_loaded_qty = 5
        self.t.add('Stock Ledger Entry','DN-SLE',voucher_type='Delivery Note',voucher_no='DN-P2',
            voucher_detail_no='DN-LINE-P2',warehouse='LORRY',item_code='B',stock_uom='Nos',actual_qty=-2,creation=when)
        manifest, entry = self.late_return()
        manifest.lines[0].update(dict(dispatch_qty=3,received_qty=3)); entry.items[0].transfer_qty = 3
        self.data[self.p.ADOPTION]['ADOPT'].update(adopted_qty=3,erp_qty_at_adoption=13,
            untagged_qty_before=3,remaining_untagged_qty=0)
        self.data[fixture.LEDGER]['ACTIVATE-LATE-TAG'].update(stock_qty=3,destination_qty_delta=3)
        self.data[fixture.LEDGER]['LOCATION'].stock_qty = 3
        for row in self.data['Stock Ledger Entry'].values():
            if row.voucher_type == 'Stock Entry': row.actual_qty = 3 if row.warehouse == 'SOURCE' else -3

    def test_partial_delivery_before_tagging_uses_posting_time_and_retains_actual_delivery_outcome(self):
        self.partial_delivery(self.adopted-datetime.timedelta(hours=1))
        before = self.t.snapshot_stock(); result = self.t.close_plan()
        self.assertEqual(result['plan']['total_delivered_qty'], 2)
        self.assertEqual(result['plan']['fulfilment_status'], 'Closed Incomplete')
        self.assertEqual(self.evidence(result)['identity_changes'][0]['custody_stock_ledgers'], ['DN-SLE'])
        self.assertEqual(before, self.t.snapshot_stock())

    def test_deliveries_after_adoption_cannot_fake_a_smaller_pre_adoption_snapshot(self):
        self.partial_delivery(self.adopted+datetime.timedelta(hours=1))
        self.unchanged_after_failure('Plan loose balance was 5 Nos, untagged snapshot was 3')

    def test_missing_delivery_posting_evidence_does_not_allow_guessing_a_tagged_balance(self):
        self.partial_delivery(self.adopted-datetime.timedelta(hours=1)); del self.data['Stock Ledger Entry']['DN-SLE']
        self.unchanged_after_failure('lacks exact posted stock-ledger')

    def test_return_stock_entry_tag_batch_uom_and_reuse_checks_remain_mandatory(self):
        for field, value in (('cfg_handling_unit','WRONG'),('batch_no','OTHER'),('stock_uom','Kg')):
            with self.subTest(field=field):
                self.setUp(); _manifest,entry = self.late_return(); setattr(entry.items[0],field,value)
                self.unchanged_after_failure('tag / stock UOM|Batch|differs|no longer matches')
        self.setUp(); self.late_return()
        self.t.add(fixture.REVIEW,'USED',state='Completed',movement_stock_entry='RETURN-STE')
        with self.assertRaisesRegex(ValueError,'already settled Review USED'): self.t.close_plan()

    def test_existing_closure_permissions_and_foreign_source_reference_remain_required(self):
        for role in ('operator','native-read','source'):
            with self.subTest(role=role):
                self.setUp(); manifest,_entry = self.late_return()
                if role == 'operator':
                    self.t.r.operator.kanban_role = 'Operator'
                    self.unchanged_after_failure('Supervisor')
                elif role == 'native-read':
                    self.data[self.p.ADOPTION]['ADOPT'].check_permission = lambda action: (_ for _ in ()).throw(PermissionError('Adoption read denied'))
                    with self.assertRaisesRegex(PermissionError,'Adoption read denied'): self.t.close_plan()
                else:
                    manifest.lines[0].dispatch_allocation = 'OTHER-SOURCE'
                    self.unchanged_after_failure('another source allocation')


if __name__ == '__main__':
    unittest.main()

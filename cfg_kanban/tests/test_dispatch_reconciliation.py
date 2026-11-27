"""Actual E5A functions with dependency doubles; no native DB/ERP acceptance claim."""
import datetime
import json
import types
import unittest
from unittest.mock import Mock

from cfg_kanban.tests import test_route_delivery as route_tests
from cfg_kanban.tests import test_dispatch_fulfilment as e4a
from cfg_kanban.tests.test_dispatch_e3_behavior import Row, PLAN, HU

REVIEW='CFG Kanban Dispatch Review'


class TestDispatchReconciliation(unittest.TestCase):
    def setUp(self):
        self.r=route_tests.TestRouteDelivery();self.r.setUp();self.addCleanup(self.r.doCleanups)
        self.b,self.plan,self.unit,self.operator=self.r.b,self.r.plan,self.r.unit,self.r.operator
        self.data=self.b.data;self.plan.as_dict=lambda:dict(self.plan)
        self.operator.responsibilities.append(Row(responsibility='Logistics Reconciliation'))
        self.now=datetime.datetime(2026,11,20,12)
        self.counts=types.SimpleNamespace()
        common=dict(self.b.bridge.__dict__,EPSILON=0.000001,
            get_datetime=lambda v:v if isinstance(v,datetime.datetime) else datetime.datetime.fromisoformat(str(v)),
            now_datetime=lambda:self.now,RECONCILIATION_RESPONSIBILITY='Logistics Reconciliation')
        cn=dict(common,active_container_membership=self.b.engine.active_container_membership)
        e4a.extract('services/route_reconciliation.py',cn,{'_authorized','_require_authorized','_validate_vehicle_warehouse',
            '_assert_no_open_vehicle_work','_validate_scan_snapshot'})
        self.counts.__dict__.update(cn)
        self.counts._erp_balances=lambda *a,**k:{('ITEM',''):self.b.erp_balance} if self.b.erp_balance else {}
        self.b.frappe.session=Row(user='terminal')
        self.mod=types.ModuleType('dispatch_reconciliation');self.mod.__dict__.update(common)
        self.mod.REVIEW=REVIEW;self.mod.EPSILON=0.000001
        self.mod.ACTIONS=('No Remaining Prepared Stock','Close Trip - Stock Stays','Continue Same Plan Overnight','Returned to Warehouse','Transferred to Another Lorry')
        self.mod.FROZEN=('Reviewing','Held','Overnight','Settled');self.mod.DispatchReviewReplayError=ValueError
        e4a.extract('services/dispatch_reconciliation.py',self.mod.__dict__)
        self.mod._planning=lambda:self.b.planning;self.mod._counts=lambda:self.counts;self.mod._fulfilment=lambda:self.b.bridge
        self.plan.route_stock_commitment=1;self.plan.prepared_stock_commitment=0
        self.b.posted.clear()

    def test_open_movement_still_blocks_balanced_route_closure_until_resolved(self):
        self.b.frappe.db.get_value=Mock(return_value=None)
        self.b.frappe.db.sql=Mock(return_value=[['KMF-2026-00066']])
        doc=Row(company='B',vehicle_warehouse='LORRY1',state='Ready to Close')
        with self.assertRaisesRegex(ValueError,'KMF-2026-00066'):
            self.counts._assert_no_open_vehicle_work(doc)
        query,params=self.b.frappe.db.sql.call_args.args
        self.assertIn('source_warehouse=%s or destination_warehouse=%s',query)
        self.assertEqual(params,('LORRY1','LORRY1'))
        self.assertIn("'Received'",query);self.assertIn("'Cancelled'",query)
        self.assertNotIn("'Draft'",query)
        self.b.frappe.db.sql.return_value=[]
        self.counts._assert_no_open_vehicle_work(doc)

    def begin(self,event='OPEN'):
        return self.mod.begin_dispatch_review('PLAN',event,'SESSION')
    def review(self):return self.data[REVIEW][self.plan.active_dispatch_review]
    def supervisor(self):self.r.supervisor()
    def count(self):
        scans=[]
        if self.unit.current_warehouse=='LORRY1' and self.unit.current_qty:
            scans=[Row(handling_unit='TAG',visible_code='TAG1',qty=self.unit.current_qty)]
        lines=[] if not self.b.erp_balance else [Row(item_code='ITEM',batch_no=None,expected_closing_qty=self.b.erp_balance,variance_qty=0)]
        return self.b.add('CFG Kanban Route Reconciliation','COUNT',company='B',vehicle_warehouse='LORRY1',
            state='Closed',closed_on=self.now,scans=scans,lines=lines)
    def finish(self,action='Close Trip - Stock Stays',event='FINISH',movement=None,reason='Trip ended',hash_value=None):
        return self.mod.finish_dispatch_review(self.review().name,action,'COUNT',reason,event,'SESSION',movement,
            hash_value or self.mod._hash(self.mod._balances(self.plan)))
    def deliver(self,qty=2):
        self.r.start();self.r.allocate(qty);return self.r.submit()
    def move(self,destination='SOURCE',tag=True):
        qty=self.unit.current_qty
        self.b.add('Warehouse',destination,company='B',disabled=0,is_group=0,
            cfg_is_vehicle_warehouse=int(destination.startswith('LORRY')),cfg_vehicle_reference='V2')
        entry=self.b.add('Stock Entry','MOVE',docstatus=1,company='B',purpose='Material Transfer',
            posting_date=self.now.date(),posting_time=str(self.now.time()),
            cfg_movement_manifest='RECOVERY' if tag else None,
            items=[e4a.Record(item_code='ITEM',batch_no=None,stock_uom='Nos',uom='Nos',transfer_qty=qty,
                s_warehouse='LORRY1',t_warehouse=destination,cfg_handling_unit='TAG' if tag else None)])
        self.b.add('Stock Ledger Entry','SLE',voucher_type='Stock Entry',voucher_no='MOVE',warehouse='LORRY1',creation=self.now)
        if tag:
            self.b.add('CFG Kanban Movement Manifest','RECOVERY',state='Received',dispatch_stock_entry='MOVE',
                source_company='B',destination_company='B',source_warehouse='LORRY1',destination_warehouse=destination)
            self.unit.current_warehouse=destination
        self.b.erp_balance-=qty
        return entry

    def test_begin_freezes_without_inventory_or_erp_mutation(self):
        before=(self.unit.current_qty,self.unit.reserved_qty,self.b.erp_balance)
        result=self.begin()
        self.assertEqual(self.plan.dispatch_review_state,'Reviewing');self.assertEqual(result['review']['state'],'Reviewing')
        self.assertEqual((self.unit.current_qty,self.unit.reserved_qty,self.b.erp_balance),before)
        self.assertFalse(self.b.posted)

    def test_reopen_and_same_token_replay_keep_one_active_review(self):
        first=self.begin();self.begin();again=self.begin('NEW')
        self.assertEqual(first['review']['name'],again['review']['name']);self.assertEqual(len(self.data[REVIEW]),1)

    def test_loaded_delivered_and_remaining_are_separate_from_unassigned_deliveries(self):
        self.deliver(2);result=self.begin();row=result['balances'][0]
        self.assertEqual((row['loaded_qty'],row['delivered_qty'],row['remaining_qty']),(5,2,3))
        self.assertEqual(result['quantity_totals']['Nos']['remaining'],3)

    def test_unfinished_proof_or_stock_session_blocks_review(self):
        self.r.start()
        with self.assertRaisesRegex(ValueError,'unfinished Delivery'):self.begin()
        self.assertIsNone(self.plan.active_dispatch_review)

    def test_wrong_responsibility_or_non_vehicle_plan_rejected(self):
        self.operator.responsibilities=[Row(responsibility='Logistics Reconciliation')]
        with self.assertRaisesRegex(ValueError,'responsibility'):self.begin()
        self.operator.responsibilities.append(Row(responsibility='Dispatch'));self.plan.fulfilment_mode='Customer Pickup'
        with self.assertRaisesRegex(ValueError,'Vehicle Delivery'):self.begin()

    def test_begin_freeze_blocks_new_route_and_planning_actions(self):
        self.begin()
        with self.assertRaisesRegex(ValueError,'frozen Dispatch Review'):self.r.start()
        with self.assertRaisesRegex(ValueError,'frozen Dispatch Review'):self.r.add()

    def test_new_reconciliation_requires_closed_current_balanced_count(self):
        self.supervisor();self.begin();count=self.count();count.state='Variance'
        with self.assertRaisesRegex(ValueError,'count must be closed'):self.finish()
        count.state='Closed';count.lines[0].variance_qty=1
        with self.assertRaisesRegex(ValueError,'unresolved variance'):self.finish()
        count.lines[0].variance_qty=0;count.closed_on=self.now-datetime.timedelta(days=1)
        with self.assertRaisesRegex(ValueError,'after the Dispatch Review'):self.finish()

    def test_erp_movement_after_closed_count_cannot_settle_stale_balance(self):
        self.supervisor();self.begin();self.count();self.b.erp_balance+=1
        with self.assertRaisesRegex(ValueError,'fresh D3 count'):self.finish()
        self.assertEqual(self.review().state,'Reviewing')

    def test_changed_tag_after_count_is_rejected(self):
        self.supervisor();self.begin();self.count();self.unit.current_qty=4
        with self.assertRaisesRegex(ValueError,'changed after scanning'):self.finish()

    def test_any_other_open_vehicle_delivery_blocks_settlement(self):
        self.supervisor();self.begin();self.count()
        self.b.add(e4a.SESSION,'OTHER',selling_company='B',source_warehouse='LORRY1',state='Allocating Stock')
        with self.assertRaisesRegex(ValueError,'open Customer Delivery'):self.finish()

    def test_leftover_decision_requires_supervisor_and_reason(self):
        self.begin();self.count()
        with self.assertRaisesRegex(ValueError,'Supervisor'):self.finish()
        self.supervisor()
        with self.assertRaisesRegex(ValueError,'provide its reason'):self.finish(reason='')

    def test_close_trip_releases_commitments_and_preserves_actual_stock(self):
        self.supervisor();self.begin();self.count();result=self.finish()
        self.assertEqual(self.plan.state,'Reconciled');self.assertEqual(self.plan.route_stock_commitment,0)
        self.assertEqual(self.plan.fulfilment_status,'Closed Incomplete');self.assertEqual(self.unit.current_qty,5)
        self.assertEqual(result['review']['action'],'Close Trip - Stock Stays');self.assertFalse(self.b.posted)
        with self.assertRaisesRegex(ValueError,'frozen Dispatch Review'):self.r.start()

    def test_keep_same_plan_overnight_preserves_commitment_until_explicit_resume(self):
        self.supervisor();self.begin();self.count();self.finish('Continue Same Plan Overnight')
        self.assertEqual(self.plan.state,'Loaded');self.assertEqual(self.plan.route_stock_commitment,1)
        self.assertEqual(self.review().state,'Overnight')
        with self.assertRaisesRegex(ValueError,'frozen Dispatch Review'):self.r.start()
        review=self.review();self.mod.resume_dispatch_review(review.name,'Start next day','RESUME','SESSION')
        self.assertEqual(review.state,'Resumed');self.assertIsNone(self.plan.active_dispatch_review)
        self.assertEqual(self.plan.route_stock_commitment,1);self.assertFalse(self.plan.dispatch_review_state)
        self.r.start();self.assertEqual(self.r.delivery().state,'Customer Identified')

    def test_no_remaining_prepared_stock_can_close_after_completed_delivery(self):
        self.deliver(5);self.begin();self.count();self.finish('No Remaining Prepared Stock')
        self.assertEqual(self.plan.state,'Reconciled');self.assertEqual(self.plan.fulfilment_status,'Completed')
        self.assertEqual(self.unit.current_qty,0)

    def test_no_remaining_choice_cannot_hide_leftover_or_over_delivery(self):
        self.supervisor();self.begin();self.count()
        with self.assertRaisesRegex(ValueError,'Prepared stock remains'):self.finish('No Remaining Prepared Stock')
        self.b.add(e4a.DA,'BAD',dispatch_allocation='ALLOC',state='Delivered',delivered_qty=6)
        with self.assertRaisesRegex(ValueError,'exceed'):self.mod._balances(self.plan)

    def test_changed_balance_hash_requires_operator_re_review(self):
        self.supervisor();self.begin();self.count()
        with self.assertRaisesRegex(ValueError,'balances changed'):self.finish(hash_value='OLD')

    def test_same_closing_token_replays_and_changed_payload_conflicts(self):
        self.supervisor();self.begin();self.count();before=self.mod._hash(self.mod._balances(self.plan));self.finish(hash_value=before)
        self.finish(hash_value=before)
        with self.assertRaisesRegex(ValueError,'different closing details'):self.finish(reason='Changed',hash_value=before)
        self.assertEqual(self.review().state,'Completed')

    def test_original_open_token_stays_historical_after_resume(self):
        self.supervisor();opened=self.begin();old=self.review()
        self.mod.resume_dispatch_review(old.name,'Continue driving','RESUME','SESSION')
        replay=self.begin();self.assertEqual(replay['review']['name'],old.name);self.assertEqual(old.state,'Resumed')
        self.assertIsNone(self.plan.active_dispatch_review)
        self.begin('NEW-OPEN');self.assertNotEqual(self.review().name,old.name)

    def test_hold_retains_stock_and_cannot_be_resumed_without_counted_recovery(self):
        self.supervisor();self.begin();review=self.review()
        self.mod.hold_dispatch_review(review.name,'Investigate quantity','HOLD','SESSION')
        self.mod.hold_dispatch_review(review.name,'Investigate quantity','HOLD','SESSION')
        self.assertEqual(review.state,'Held');self.assertEqual(self.unit.current_qty,5)
        self.assertEqual(len(self.data['CFG Kanban Exception']),1)
        with self.assertRaisesRegex(ValueError,'held review'):self.mod.resume_dispatch_review(review.name,'Skip hold','R','SESSION')
        self.count();self.finish()
        self.assertEqual(next(iter(self.data['CFG Kanban Exception'].values())).status,'Resolved')

    def test_return_requires_exact_submitted_movement_and_current_tag_destination(self):
        self.supervisor();self.begin();entry=self.move();self.count();entry.docstatus=0
        with self.assertRaisesRegex(ValueError,'submitted same-Company'):self.finish('Returned to Warehouse',movement='MOVE')
        entry.docstatus=1;self.finish('Returned to Warehouse',movement='MOVE')
        self.assertEqual(self.review().destination_warehouse,'SOURCE');self.assertEqual(self.plan.vehicle_warehouse,'LORRY1')
        self.assertEqual(self.unit.current_warehouse,'SOURCE');self.assertFalse(self.b.posted)

    def test_transfer_to_other_lorry_does_not_rewrite_original_vehicle(self):
        self.supervisor();self.begin();self.move('LORRY2');self.count()
        self.finish('Transferred to Another Lorry',movement='MOVE')
        self.assertEqual(self.review().destination_warehouse,'LORRY2');self.assertEqual(self.plan.vehicle_warehouse,'LORRY1')

    def test_missing_or_wrong_movement_quantity_and_manifest_reject(self):
        self.supervisor();self.begin();entry=self.move();self.count()
        entry.items[0].transfer_qty=4
        with self.assertRaisesRegex(ValueError,'every exact remaining'):self.finish('Returned to Warehouse',movement='MOVE')
        entry.items[0].transfer_qty=5;entry.cfg_movement_manifest=None
        with self.assertRaisesRegex(ValueError,'completed controlled Movement'):self.finish('Returned to Warehouse',movement='MOVE')

    def test_old_movement_or_different_company_cannot_explain_recovery(self):
        self.supervisor();self.begin();entry=self.move();self.count()
        self.data['Stock Ledger Entry']['SLE'].creation=self.now-datetime.timedelta(days=1)
        with self.assertRaisesRegex(ValueError,'post after'):self.finish('Returned to Warehouse',movement='MOVE')
        self.data['Stock Ledger Entry']['SLE'].creation=self.now;entry.company='OTHER'
        with self.assertRaisesRegex(ValueError,'same-Company'):self.finish('Returned to Warehouse',movement='MOVE')

    def test_moved_stock_cannot_be_declared_overnight_or_resumed_as_at_source(self):
        self.supervisor();self.begin();self.move();self.count()
        with self.assertRaisesRegex(ValueError,'moved, changed'):self.finish('Continue Same Plan Overnight')
        with self.assertRaisesRegex(ValueError,'moved, changed'):
            self.mod.resume_dispatch_review(self.review().name,'Continue','RESUME','SESSION')

    def test_posted_customer_note_cannot_reopen_during_review_or_after_settlement(self):
        note,delivery=self.deliver(2);self.begin()
        with self.assertRaisesRegex(ValueError,'reviewed/frozen trip'):
            self.b.feedback._on_customer_delivery_cancel(note,delivery.name)
        self.assertEqual(self.unit.current_qty,3)

    def test_stock_stays_with_mixed_prepared_loose_stock_releases_exact_plan_budget(self):
        self.b.loose(6);self.supervisor();self.begin();self.count();self.finish()
        self.assertEqual(self.plan.state,'Reconciled');self.assertEqual(self.unit.current_qty,5)
        self.assertEqual(self.b.erp_balance,11);self.assertEqual(len(json.loads(self.review().closing_snapshot_json)),2)

    def test_missing_loose_stock_cannot_be_hidden_by_a_balanced_erp_count(self):
        self.b.loose(6);self.supervisor();self.begin();self.b.erp_balance=10;self.count()
        with self.assertRaisesRegex(ValueError,'loose stock is missing'):self.finish()
        self.assertEqual(self.plan.route_stock_commitment,1)

    def test_report_distinguishes_other_stock_and_unassigned_deliveries(self):
        self.r.start();self.r.allocate(2,source='unassigned',scan=None,item='ITEM');self.r.submit()
        context=self.mod.get_dispatch_review_context('PLAN','SESSION')
        self.assertEqual(context['unassigned_deliveries'][0]['delivered_qty'],2)
        self.assertEqual(context['quantity_totals']['Nos']['delivered'],0)
        self.assertEqual(context['lorry_balances'][0]['erp_qty'],9)
        self.assertEqual(context['lorry_balances'][0]['prepared_remaining_budget'],5)

    def test_unvisited_planned_stops_are_preserved_as_skipped_at_trip_close(self):
        stop=self.r.add();self.supervisor();self.begin();self.count();self.finish()
        self.assertEqual(self.data['CFG Kanban Route Stop'][stop['name']].state,'Skipped')
        self.assertEqual(self.data['CFG Kanban Route Stop'][stop['name']].skip_reason,'Trip ended')

    def test_settled_movement_evidence_cannot_be_cancelled(self):
        self.supervisor();self.begin();entry=self.move();self.count();self.finish('Returned to Warehouse',movement=entry.name)
        self.b.frappe.db.table_exists=lambda name:True
        with self.assertRaisesRegex(ValueError,'settled Dispatch Review'):
            self.mod.protect_review_movement_cancellation(entry)

    def test_second_begin_resumes_the_same_active_or_overnight_review(self):
        self.supervisor();first=self.begin();self.begin('ANOTHER')
        self.assertEqual(len(self.data[REVIEW]),1);self.count();self.finish('Continue Same Plan Overnight')
        again=self.begin('LATER');self.assertEqual(again['review']['name'],first['review']['name'])
        self.assertEqual(len(self.data[REVIEW]),1)

    def test_settled_review_remains_readable_when_lorry_is_disabled(self):
        self.supervisor();self.begin();self.count();self.finish();self.data['Warehouse']['LORRY1'].disabled=1
        context=self.mod.get_dispatch_review_context(self.review().name,'SESSION')
        self.assertEqual(context['review']['state'],'Completed');self.assertEqual(self.begin()['review']['name'],self.review().name)

    def test_recovery_entry_cannot_explain_two_plans_leftovers(self):
        self.supervisor();self.begin();entry=self.move();self.count()
        self.b.add(REVIEW,'OTHER-REVIEW',state='Completed',movement_stock_entry=entry.name)
        with self.assertRaisesRegex(ValueError,'already settled another'):self.finish('Returned to Warehouse',movement=entry.name)

    def test_movement_reference_has_database_unique_guard_and_no_review_write_permission(self):
        schema=json.loads((e4a.ROOT/'cfg_kanban/doctype/cfg_kanban_dispatch_review/cfg_kanban_dispatch_review.json').read_text())
        fields={row['fieldname']:row for row in schema['fields']}
        self.assertEqual(fields['movement_stock_entry']['unique'],1)
        self.assertEqual(fields['active_plan_key']['unique'],1)
        self.assertTrue(all(not row.get('write') and not row.get('delete') for row in schema['permissions']))

    def advance_days(self,days):
        self.now+=datetime.timedelta(days=days)
        for module in (self.r.route,self.b.engine,self.b.bridge,self.b.feedback):
            module.now_datetime=lambda:self.now

    def test_three_day_trip_keeps_one_plan_and_no_forced_daily_review(self):
        self.plan.trip_date='2026-11-20';original=self.plan.name
        self.deliver(2);self.advance_days(1)
        self.r.start('OTHER-SITE','DAY2');self.r.allocate(2,token='DAY2-STOCK');self.r.submit()
        self.advance_days(1);self.assertEqual(self.plan.state,'Loaded');self.assertFalse(self.plan.dispatch_review_state)
        self.supervisor();self.begin();count=self.count();count.period_start=datetime.datetime(2026,11,20,8)
        self.finish();self.assertEqual(self.plan.name,original);self.assertEqual(self.plan.trip_date,'2026-11-20')
        self.assertEqual(self.plan.total_delivered_qty,4);self.assertEqual(self.unit.current_qty,1)
        self.assertEqual(self.plan.state,'Reconciled');self.assertEqual(self.plan.completed_stop_count,2)

    def test_two_formal_overnight_pauses_keep_same_prepared_commitment(self):
        self.supervisor()
        for day in range(2):
            self.begin('OPEN'+str(day));self.count();self.finish('Continue Same Plan Overnight',event='FINISH'+str(day))
            review=self.review();self.advance_days(1)
            self.mod.resume_dispatch_review(review.name,'Continue same trip','RESUME'+str(day),'SESSION')
            self.assertEqual(self.plan.state,'Loaded');self.assertEqual(self.plan.route_stock_commitment,1)
        self.r.start();self.assertEqual(self.r.delivery().dispatch_plan,self.plan.name)
        self.assertEqual(len(self.data[REVIEW]),2)

    def test_movement_posted_after_closing_count_requires_fresh_count(self):
        self.supervisor();self.begin();self.move();self.count()
        self.data['Stock Ledger Entry']['SLE'].creation=self.now+datetime.timedelta(minutes=1)
        with self.assertRaisesRegex(ValueError,'fresh route count'):self.finish('Returned to Warehouse',movement='MOVE')

    def test_future_posting_time_cannot_be_used_as_completed_count_evidence(self):
        self.supervisor();self.begin();entry=self.move();self.count()
        entry.posting_date=(self.now+datetime.timedelta(days=1)).date()
        with self.assertRaisesRegex(ValueError,'posting time is later'):self.finish('Returned to Warehouse',movement='MOVE')


class TestCurrentD3Balances(unittest.TestCase):
    def test_current_raw_and_grouped_reads_preserve_legacy_and_bundle_totals(self):
        queries=[]
        def sql(query,params,**kwargs):
            queries.append((query,params))
            if 'for update' in query:
                self.assertNotIn('group by',query);self.assertEqual(len(params),5)
                return [Row(item_code='I',batch_no='B',qty=5),Row(item_code='I',batch_no='B',qty=-2)] if 'join' not in query else [Row(item_code='I',batch_no='B',qty=3),Row(item_code='I',batch_no='B',qty=-1)]
            self.assertEqual(len(params),6)
            return [Row(item_code='I',batch_no='B',qty=3 if 'join' not in query else 2)]
        ns=dict(frappe=Row(get_meta=lambda *a:Row(has_field=lambda f:True),db=Row(sql=sql,table_exists=lambda *a:True)),
            flt=lambda v:float(v or 0),get_datetime=lambda v:datetime.datetime.fromisoformat(v),EPSILON=0.000001)
        e4a.extract('services/route_reconciliation.py',ns,{'_erp_balances'})
        self.assertEqual(ns['_erp_balances']('B','WH','2026-11-20 12:00:00',current=True),{('I','B'):5})
        self.assertEqual(ns['_erp_balances']('B','WH','2026-11-20 12:00:00'),{('I','B'):5})
        self.assertIn("ifnull(sle.is_cancelled, 0)=0",queries[0][0])
        self.assertIn("ifnull(sle.serial_and_batch_bundle, '')=''",queries[0][0])


if __name__=='__main__':unittest.main()

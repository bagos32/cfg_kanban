"""Real E4C functions with in-memory documents/stock; native transaction acceptance is separate."""
import json
import sys
import types
import unittest
from unittest.mock import patch

from cfg_kanban.tests import test_dispatch_fulfilment as e4a
from cfg_kanban.tests.test_dispatch_e3_behavior import Row, PLAN, ALLOC, LINE, HU


class TestWarehouseFulfilment(unittest.TestCase):
    def setUp(self):
        self.b=e4a.TestDispatchFulfilment();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.data,self.plan,self.unit,self.operator=self.b.data,self.b.plan,self.b.unit,self.b.operator
        self.plan.update(state='Ready for Fulfilment',fulfilment_mode='Direct Warehouse Delivery',
            vehicle_warehouse=None,vehicle_reference=None,movement_manifest=None,dispatch_point='DISPATCH',
            delivery_session=None,total_loaded_qty=0,total_reserved_qty=5,prepared_stock_commitment=0)
        self.plan.as_dict=lambda:dict(self.plan)
        self.plan.lines[0].update(parent='PLAN',reserved_qty=5,loaded_qty=0,line_state='Reserved')
        # E2 reads child rows with current locks; keep the offline document API and scope faithful.
        self.plan.lines[0].update(parenttype=PLAN,parentfield='lines')
        self.data[LINE]={self.plan.lines[0].name:self.plan.lines[0]}
        setter=patch.object(type(self.plan),'set',lambda doc,key,value:doc.__setitem__(key,value),create=True)
        setter.start();self.addCleanup(setter.stop)
        self.unit.update(current_warehouse='SOURCE',reserved_qty=5,available_qty=0)
        self.source=self.data[ALLOC]['ALLOC'];self.source.update(state='Reserved',movement_manifest=None,
            active_handling_unit_key='TAG',movement_state_before_reservation='Received',
            reservation_key='ORIGINAL',load_confirmed=0)
        self.b.add('Warehouse','SOURCE',company='B',is_group=0,disabled=0,cfg_is_vehicle_warehouse=0)
        self.b.add('CFG Kanban Card','DISPATCH',active=1,blocked=0)
        self.operator.update(can_start=1,can_complete=1,can_override=1)
        self.b.planning.post_quantity_event=self.b.post_quantity
        self.b.planning.RESERVABLE_STATES={'Approved','Picking','Ready for Vehicle','Ready for Fulfilment'}
        e4a.extract('services/dispatch_planning.py',self.b.planning.__dict__,{
            '_release_allocation','_refresh_plan_totals','_active_line_reserved','_current_reservation_lines','_cancel_unposted_plan','cancel_dispatch_plan','release_dispatch_allocation'})
        self.w=types.ModuleType('cfg_kanban.services.warehouse_fulfilment');self.w.__dict__.update(self.b.bridge.__dict__)
        self.w.MODES=('Direct Warehouse Delivery','Customer Pickup');self.w.ACTIVE_STATES=('Ready for Fulfilment','Fulfilment In Progress')
        e4a.extract('services/warehouse_fulfilment.py',self.w.__dict__)
        self.w._bridge=lambda:self.b.bridge
        self.patch=patch.dict(sys.modules,{'cfg_kanban.services.warehouse_fulfilment':self.w});self.patch.start();self.addCleanup(self.patch.stop)
        self.b.frappe.db.sql=self.sql
        self.b.posted.clear()
        self.media=[]
        self.proof=dict(self.b.bridge.__dict__,assert_delivery_access=lambda name,profile:self.b.engine._delivery_for_operator(name,profile),
            _require_responsibility=self.b.engine._require_customer_delivery,list_reference_media=lambda *a,**kw:self.media,
            POLICY_DISPOSITIONS={'Required':('Attended',),'Optional':('Attended','No Proof Recorded'),'No Proof Required':('No Proof Recorded',)})
        e4a.extract('services/delivery_proof.py',self.proof,{'get_or_create_delivery_proof','get_delivery_proof','submit_delivery_proof','_validate_location'})

    def sql(self,query,params=None,**kwargs):
        if 'where dispatch_plan_line=%s' in query and 'sum(allocated_qty)' in query:
            return [[sum(float(r.allocated_qty) for r in self.data[ALLOC].values() if r.dispatch_plan_line==params and r.state=='Reserved')]]
        return self.b.sql(query,params,**kwargs)

    def start(self,event='START',scan='SITE-QR'):
        return self.b.bridge.start_prepared_delivery('PLAN',scan,event,'SESSION')
    def delivery(self):return self.b.delivery()
    def loose(self,qty=6):
        self.plan.lines[0].requested_qty=5+qty;self.plan.total_requested_qty=5+qty
        return self.b.add(ALLOC,'LOOSE',dispatch_plan='PLAN',dispatch_plan_line='LINE',state='Reserved',
            allocation_kind='Untagged ERP Stock',item_code='ITEM',stock_uom='Nos',allocated_qty=qty,
            source_company='B',source_warehouse='SOURCE',reservation_key='LOOSE-ORIGINAL')
    def submit(self):
        self.b.confirm();note=self.b.note();self.b.bridge.validate_prepared_delivery_note(note)
        note.docstatus=1;self.b.data.setdefault('Delivery Note',{})[note.name]=note
        self.b.feedback._on_customer_delivery_submit(note,self.delivery().name)
        return note
    def pickup(self,requirement='Recipient Name'):
        self.plan.fulfilment_mode='Customer Pickup';self.plan.proof_policy='No Proof Required'
        self.plan.profile_snapshot_json=json.dumps({'auto_submit_delivery_note':1,'pickup_acknowledgement':requirement})
        self.b.site.require_recipient_name=0;self.b.site.require_signature=0
    def proof_record(self):return self.proof['get_or_create_delivery_proof'](self.delivery().name,'SESSION')
    def acknowledge(self,name=None):
        proof=self.proof_record()
        return self.proof['submit_delivery_proof'](proof['name'],'Attended','ACK','SESSION',recipient_name=name)

    def test_mixed_handoff_preserves_one_stock_hold_without_transfer(self):
        self.loose();result=self.start()
        self.assertEqual(result['source_warehouse'],'SOURCE');self.assertIsNone(result['vehicle_reference'])
        self.assertEqual(len(result['allocations']),2);self.assertEqual(self.plan.state,'Fulfilment In Progress')
        self.assertEqual((self.unit.current_qty,self.unit.reserved_qty,self.unit.available_qty),(5,5,0))
        self.assertEqual([r['event_type'] for r in self.b.posted],['Unreserve','Reserve'])
        self.assertEqual(self.source.state,'In Fulfilment');self.assertIsNone(self.source.active_handling_unit_key)
        self.assertIsNone(self.plan.movement_manifest);self.assertEqual(self.plan.total_loaded_qty,0)
        self.assertEqual(self.b.planning._untagged_available('B','SOURCE','ITEM',None),0)

    def test_untagged_only_has_no_tag_or_quantity_ledger(self):
        self.data[ALLOC].pop('ALLOC');self.unit.update(current_qty=0,reserved_qty=0,available_qty=0)
        self.loose(6);self.plan.lines[0].requested_qty=6;self.plan.total_requested_qty=6
        self.start();self.assertEqual(self.b.posted,[]);self.assertEqual(len(self.data[HU]),1)
        self.assertFalse(self.delivery().allocations)
        self.assertIsNone(next(iter(self.data[e4a.DA].values())).handling_unit)

    def test_replay_and_refresh_create_one_session_and_one_handoff(self):
        first=self.start();again=self.start();refresh=self.start('NEW-TOKEN')
        self.assertEqual(first['name'],again['name']);self.assertEqual(first['name'],refresh['name'])
        self.assertEqual(len(self.data[e4a.SESSION]),1);self.assertEqual(len(self.b.posted),2)

    def test_wrong_customer_and_operator_cannot_replay(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'Customer Site'):self.start(scan='OTHER-SITE')
        self.operator.employee='OTHER'
        with self.assertRaisesRegex(ValueError,'another Plan or operator'):self.start()

    def test_replay_after_stock_posting_returns_original_session(self):
        self.plan.proof_policy='No Proof Required';first=self.start();self.submit()
        self.assertEqual(self.plan.state,'Fulfilled');self.assertEqual(self.start()['name'],first['name'])
        self.assertEqual(sum(r['event_type']=='Deliver' for r in self.b.posted),1)

    def test_start_requires_company_source_and_exact_site_snapshot(self):
        self.plan.customer_address='WRONG'
        with self.assertRaisesRegex(ValueError,'differs'):self.start()
        self.plan.customer_address='ADDR';self.data['Warehouse']['SOURCE'].company='OTHER'
        with self.assertRaisesRegex(ValueError,'selling Company'):self.start()

    def test_disabled_group_warehouse_blocked_before_unreserve(self):
        for field in ('disabled','is_group'):
            self.data['Warehouse']['SOURCE'][field]=1
            with self.assertRaisesRegex(ValueError,'active stock Warehouse'):self.start()
            self.assertFalse(self.b.posted);self.data['Warehouse']['SOURCE'][field]=0

    def test_unprepared_and_vehicle_plan_cannot_use_warehouse_start(self):
        self.plan.state='Picking'
        with self.assertRaisesRegex(ValueError,'Fully prepare'):self.start()
        self.plan.state='Ready for Fulfilment';self.plan.vehicle_warehouse='LORRY1'
        with self.assertRaisesRegex(ValueError,'vehicle claim'):self.start()

    def test_blocked_card_and_wrong_dispatch_responsibility_rejected(self):
        self.data['CFG Kanban Card']['DISPATCH'].blocked=1
        with self.assertRaisesRegex(ValueError,'inactive or blocked'):self.start()
        self.data['CFG Kanban Card']['DISPATCH'].blocked=0
        self.operator.responsibilities=[Row(responsibility='Customer Delivery')]
        with self.assertRaisesRegex(ValueError,'responsibility'):self.start()

    def test_exact_line_budget_not_just_header_total(self):
        self.source.allocated_qty=4
        with self.assertRaisesRegex(ValueError,'fully and exactly'):self.start()
        self.assertFalse(self.b.posted)

    def test_tag_identity_and_reservation_must_match(self):
        self.unit.reserved_qty=4
        with self.assertRaisesRegex(ValueError,'identity or reservation'):self.start()
        self.assertFalse(self.b.posted)

    def test_missing_loose_stock_rejects_before_any_handoff(self):
        self.loose();self.b.erp_balance=10
        with self.assertRaisesRegex(ValueError,'active tagged'):self.start()
        self.assertFalse(self.b.posted);self.assertEqual(self.source.state,'Reserved')

    def test_partial_release_cannot_confirm_and_empty_cancel_requires_reprepare(self):
        self.loose();self.start();delivery=self.delivery();rows=list(self.data[e4a.DA].values())
        self.b.engine.release_delivery_allocation(rows[0].name,'Change','REL1','SESSION')
        with self.assertRaisesRegex(ValueError,'Every prepared'):self.b.confirm()
        for row in rows[1:]:self.b.engine.release_delivery_allocation(row.name,'Change','REL2','SESSION')
        self.b.engine.cancel_delivery_session(delivery.name,'Reprepare','CANCEL','SESSION')
        self.assertEqual(self.plan.state,'Approved');self.assertIsNone(self.plan.delivery_session)
        self.assertEqual(self.source.state,'Released');self.assertEqual(self.unit.reserved_qty,0)
        self.assertEqual(self.start()['name'],delivery.name)  # original token remains a replay, never another start
        with self.assertRaisesRegex(ValueError,'Fully prepare'):self.start('NEW')

    def test_plan_cancel_and_release_blocked_after_handoff(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'cannot be cancelled'):self.b.planning.cancel_dispatch_plan('PLAN','No','C','SESSION')
        with self.assertRaisesRegex(ValueError,'cannot be released'):self.b.planning.release_dispatch_allocation('ALLOC','No','R','SESSION')
        self.assertEqual(self.unit.reserved_qty,5)

    def test_payload_and_native_pre_submit_keep_certificates_source_and_exact_qty(self):
        self.loose();self.start();self.b.confirm();note=self.b.note()
        self.assertTrue(all(row.warehouse=='SOURCE' for row in note.items))
        self.assertEqual(sum(row.qty for row in note.items),11)
        self.assertEqual(next(r for r in note.items if r.cfg_handling_unit).process_certificate_set,'CERT')
        self.assertIsNone(next(r for r in note.items if not r.cfg_handling_unit).process_certificate_set)
        self.b.bridge.validate_prepared_delivery_note(note)
        note.items[0].qty=4;note.items[0].stock_qty=4
        with self.assertRaisesRegex(ValueError,'quantity'):self.b.bridge.validate_prepared_delivery_note(note)

    def test_draft_and_proof_waiting_do_not_falsely_complete_plan(self):
        self.start();self.b.confirm();self.b.note()
        self.assertEqual(self.unit.current_qty,5);self.assertEqual(self.plan.state,'Fulfilment In Progress')
        note=self.b.note();self.b.feedback._on_customer_delivery_submit(note,self.delivery().name)
        self.assertEqual(self.unit.current_qty,0);self.assertEqual(self.plan.fulfilment_status,'Delivered')
        self.assertEqual(self.plan.state,'Fulfilment In Progress')

    def test_new_reservation_totals_choose_warehouse_readiness(self):
        self.plan.state='Picking';self.b.planning._refresh_plan_totals('PLAN')
        self.assertEqual(self.plan.state,'Ready for Fulfilment')
        self.plan.fulfilment_mode='Vehicle Delivery';self.b.planning._refresh_plan_totals('PLAN')
        self.assertEqual(self.plan.state,'Ready for Vehicle')

    def test_site_queue_and_plan_context_expose_modes_without_vehicle(self):
        queue=self.w.warehouse_plans('SITE',self.operator)
        self.assertEqual(queue[0].fulfilment_mode,'Direct Warehouse Delivery')
        self.assertEqual(queue[0].quantity_summary,'5 Nos')
        result=self.b.bridge.prepared_delivery_context('PLAN','SESSION')
        self.assertEqual(result['plans'][0]['source_warehouse'],'SOURCE')

    def test_name_pickup_requires_attended_name_even_with_no_proof_policy(self):
        self.pickup();self.start();self.submit()
        self.assertEqual(self.delivery().state,'Delivered');self.assertEqual(self.delivery().proof_policy,'Required')
        with self.assertRaisesRegex(ValueError,'Recipient name'):self.acknowledge()
        proof=self.acknowledge('Customer Rep')
        self.assertEqual(proof['state'],'Submitted');self.assertEqual(self.plan.state,'Fulfilled')
        self.assertEqual(self.plan.fulfilment_status,'Completed')

    def test_signature_only_pickup_can_omit_name_when_site_allows(self):
        self.pickup('Signature');self.start();self.submit()
        with self.assertRaisesRegex(ValueError,'signature'):self.acknowledge()
        self.media=[Row(evidence_kind='signature')];self.acknowledge()
        self.assertEqual(self.delivery().state,'Closed')

    def test_both_pickup_requires_name_and_signature(self):
        self.pickup('Recipient Name and Signature');self.start();self.submit()
        with self.assertRaisesRegex(ValueError,'Recipient name'):self.acknowledge()
        with self.assertRaisesRegex(ValueError,'signature'):self.acknowledge('Customer')
        self.media=[Row(evidence_kind='signature')];self.acknowledge('Customer')
        self.assertEqual(self.plan.state,'Fulfilled')

    def test_customer_site_additional_evidence_cannot_be_disabled_by_pickup_profile(self):
        self.pickup('Signature');self.b.site.require_recipient_name=1;self.b.site.require_photo=1
        self.start();self.submit();self.media=[Row(evidence_kind='signature')]
        with self.assertRaisesRegex(ValueError,'Recipient name'):self.acknowledge()
        with self.assertRaisesRegex(ValueError,'photograph'):self.acknowledge('Receiver')
        self.media.append(Row(evidence_kind='photo'));self.acknowledge('Receiver')

    def test_pickup_cannot_close_unattended_or_no_proof(self):
        self.pickup();self.start();self.submit();proof=self.proof_record()
        for disposition in ('Unattended','No Proof Recorded'):
            with self.assertRaisesRegex(ValueError,'not allowed'):
                self.proof['submit_delivery_proof'](proof['name'],disposition,'ACK','SESSION')
        self.assertEqual(self.plan.state,'Fulfilment In Progress')

    def test_snapshot_policy_survives_profile_changes_and_ack_replay(self):
        self.pickup('Signature');self.start();self.submit();self.media=[Row(evidence_kind='signature')]
        self.acknowledge();self.acknowledge()
        self.assertEqual(self.delivery().pickup_acknowledgement,'Signature')
        self.assertEqual(len(self.data['CFG Kanban Delivery Proof']),1)

    def test_sales_order_native_uom_and_link_reused(self):
        self.b.order();self.start();self.b.confirm();note=self.b.note()
        self.assertEqual(note.items[0].against_sales_order,'SO')
        self.assertEqual(note.items[0].stock_qty,5)
        self.b.bridge.validate_prepared_delivery_note(note)

    def test_submitted_pickup_proof_blocks_unsafe_delivery_note_cancellation(self):
        self.pickup();self.start();note=self.submit();self.acknowledge('Customer')
        with self.assertRaisesRegex(ValueError,'proof was submitted'):
            self.b.feedback._on_customer_delivery_cancel(note,self.delivery().name)

    def container(self,role='Production Output Container'):
        holder=self.b.add(HU,'BIN',handling_unit_id='BIN1',tag_kind='Reusable Container',
            reusable_container_role=role,identity_state='Active',quality_state='Released',movement_state='Received',
            current_warehouse='SOURCE',inventory_company='B')
        self.b.add('CFG Kanban Container Content','MEM',state='Loaded',container_handling_unit='BIN',
            container_visible_code='BIN1',content_handling_unit='TAG',content_visible_code='TAG1',qty=5)
        self.b.engine.active_container_contents=lambda name:[r for r in self.data['CFG Kanban Container Content'].values()
            if r.container_handling_unit==name and r.state=='Loaded']
        self.b.engine.active_container_membership=lambda name:next((r for r in self.data['CFG Kanban Container Content'].values()
            if r.content_handling_unit==name and r.state=='Loaded'),None)
        e4a.extract('services/customer_delivery.py',self.b.engine.__dict__,{'_validate_container'})
        e4a.extract('integrations/logistics_feedback.py',self.b.feedback.__dict__,{'_unload_customer_container','_restore_customer_container'})
        return holder

    def partial(self):
        self.source.allocated_qty=2;self.plan.lines[0].requested_qty=2;self.plan.total_requested_qty=2
        self.unit.reserved_qty=2;self.unit.available_qty=3

    def test_partial_quantity_bin_preserves_remaining_stock_and_membership(self):
        holder=self.container();self.partial();self.start();self.submit()
        self.assertEqual(self.unit.current_qty,3);self.assertEqual(holder.movement_state,'Packed')
        self.assertEqual(self.data['CFG Kanban Container Content']['MEM'].state,'Loaded')

    def test_partial_bin_reversal_restores_reservation_without_duplicate_membership(self):
        self.container();self.partial();self.start();note=self.submit()
        self.b.feedback._on_customer_delivery_cancel(note,self.delivery().name)
        self.assertEqual(self.unit.current_qty,5);self.assertEqual(self.unit.reserved_qty,2)
        self.assertEqual(len(self.data['CFG Kanban Container Content']),1)
        self.assertEqual(self.plan.fulfilment_status,'In Progress');self.assertEqual(self.source.state,'In Fulfilment')

    def test_ordinary_logistics_container_cannot_deliver_part_of_a_tag(self):
        self.container('Logistics Container');self.partial()
        with self.assertRaisesRegex(ValueError,'every tag in full'):self.start()
        self.assertFalse(self.b.posted)

    def test_full_container_must_include_each_current_tag(self):
        self.container('Logistics Container')
        self.b.add('CFG Kanban Container Content','EXTRA',state='Loaded',container_handling_unit='BIN',
            container_visible_code='BIN1',content_handling_unit='OTHER',content_visible_code='OTHER1',qty=1)
        with self.assertRaisesRegex(ValueError,'complete physical contents'):self.start()

    def test_expiry_gate_is_checked_before_reservation_handoff(self):
        self.b.bridge.assert_delivery_tag_expiry.side_effect=ValueError('Printed expiry has passed')
        with self.assertRaisesRegex(ValueError,'expiry'):self.start()
        self.assertFalse(self.b.posted)

    def test_other_customer_delivery_responsibility_required_even_for_dispatch_operator(self):
        self.operator.responsibilities=[Row(responsibility='Dispatch')]
        with self.assertRaisesRegex(ValueError,'Customer Delivery'):self.start()
        self.assertFalse(self.b.posted)


if __name__=='__main__':unittest.main()

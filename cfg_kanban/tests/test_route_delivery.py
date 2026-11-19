"""Actual E4B route/stock and existing delivery functions with offline ERP/DB doubles."""
import ast
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_dispatch_fulfilment as e4a

STOP='CFG Kanban Route Stop'

class TestRouteDelivery(unittest.TestCase):
    def setUp(self):
        self.b=e4a.TestDispatchFulfilment();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.data,self.plan,self.unit=self.b.data,self.b.plan,self.b.unit
        self.plan.update(plan_type='Open Route Stock',customer_site=None,customer=None,customer_address=None,
            stop_sequence_policy='Flexible Order',proof_policy='No Proof Required',route_stock_commitment=1,
            actual_stop_count=0,completed_stop_count=0,allow_supervisor_override=1)
        self.operator=self.b.operator
        self.other=self.b.add('CFG Kanban Customer Scan Point','OTHER',active=1,site_code='OTHER-SITE',
            site_name='Second Customer',selling_company='B',customer='CUSTOMER2',customer_address='ADDR2',
            default_price_list='SELL',proof_policy='Required')
        self.b.engine._resolve_customer_site=lambda scan: self.b.site if scan=='SITE-QR' else self.other if scan=='OTHER-SITE' else (_ for _ in ()).throw(ValueError('Wrong site'))
        self.identities={'SITE-QR':{'identity_type':'Customer Scan Point','name':'SITE'},
                         'OTHER-SITE':{'identity_type':'Customer Scan Point','name':'OTHER'},
                         'TAG1':{'identity_type':'Handling Unit','name':'TAG'}}
        self.b.engine.resolve_logistics_scan=lambda value:self.identities.get(value)
        self.b.frappe.db.count=lambda dt,filters:len(self.b.e3.get_all(dt,filters=filters))
        self.route=types.ModuleType('cfg_kanban.services.route_delivery')
        self.route.__dict__.update(self.b.bridge.__dict__);self.route.__name__="cfg_kanban.services.route_delivery"
        source=(e4a.ROOT/'services/route_delivery.py').read_text()
        for node in ast.parse(source).body:
            if isinstance(node,ast.Assign):
                for name in node.targets:
                    if isinstance(name,ast.Name):self.route.__dict__[name.id]=ast.literal_eval(node.value)
        e4a.extract('services/route_delivery.py',self.route.__dict__)
        self.route.RouteReplayConflictError=ValueError;self.route.RouteActionVoidedError=ValueError
        self.route._engine=lambda:self.b.engine;self.route._planning=lambda:self.b.planning;self.route._fulfilment=lambda:self.b.bridge
        self.patch=patch.dict(sys.modules,{self.route.__name__:self.route});self.patch.start();self.addCleanup(self.patch.stop)
        self.old_sql=self.b.sql;self.b.frappe.db.sql=self.sql
        e4a.extract('services/customer_delivery.py',self.b.engine.__dict__,{'_validate_container'})
        # These are real feedback functions: partial-container assertions below use their store updates.
        e4a.extract('integrations/logistics_feedback.py',self.b.feedback.__dict__,{
            '_unload_customer_container','_restore_customer_container'})
        def event(event_type,**values):
            return self.b.add('CFG Kanban Event',f'EVENT-{len(self.data.get("CFG Kanban Event",{}))+1}',event_type=event_type,**values)
        self.b.e3.events.side_effect=event
        self.note_counter=0

    def sql(self,query,params=None,**kwargs):
        if 'from `tabCFG Kanban Delivery Allocation` where dispatch_allocation=%s' in query:
            rows=[r for r in self.data.get(e4a.DA,{}).values() if r.dispatch_allocation==params]
            states=['Delivered'] if "and state='Delivered'" in query else ['Reserved','Delivery Pending','Exception','Delivered']
            return [[sum(float(r.allocated_qty) for r in rows if r.state in states)]]
        if 'group by allocation.route_source_kind' in query:
            values={}
            for row in self.data.get(e4a.DA,{}).values():
                delivery=self.data[e4a.SESSION][row.delivery_session]
                if delivery.dispatch_plan==params and row.state=='Delivered':
                    values[row.route_source_kind]=values.get(row.route_source_kind,0)+float(row.delivered_qty)
            return [e4a.Row(route_source_kind=kind,qty=qty) for kind,qty in values.items()]
        return self.old_sql(query,params,**kwargs)

    def supervisor(self,on=True):
        self.operator.kanban_role='Supervisor' if on else 'Operator';self.operator.can_override=1 if on else 0
    def add(self,scan='SITE-QR',token='PLAN'):
        self.supervisor();result=self.route.add_route_stop('PLAN',scan,token,'SESSION');self.supervisor(False);return result
    def start(self,scan='SITE-QR',token='START',stop=None):
        return self.route.start_route_stop('PLAN',scan,token,'SESSION',stop)
    def stop(self):return self.data[STOP][self.plan.active_route_stop]
    def delivery(self):return self.data[e4a.SESSION][self.stop().delivery_session]
    def context(self,scan=None,item=None,batch=None):
        return self.route.route_stock_context(self.delivery().name,'SESSION',scan,item,batch)
    def allocate(self,qty=2,source='ALLOC',scan='TAG1',item=None,token='STOCK'):
        return self.route.allocate_route_stock(self.delivery().name,source,qty,token,'SESSION',scan,item,None)
    def confirm(self):
        return self.b.engine.confirm_delivery_allocations(self.delivery().name,'CONFIRM','SESSION')
    def note(self):
        self.note_counter+=1
        note=self.b.gateway['build_customer_delivery_note'](self.delivery(),self.b.engine._customer_delivery_payload(self.delivery()))
        note.name=f'DN-{self.note_counter}';return note
    def submit(self):
        self.confirm();note=self.note();delivery=self.delivery()
        self.b.bridge.validate_prepared_delivery_note(note)
        self.b.erp_balance-=sum(float(row.stock_qty) for row in note.items)
        self.b.feedback._on_customer_delivery_submit(note,delivery.name)
        return note,delivery

    def test_two_customers_receive_separate_notes_and_actual_sequence(self):
        first=self.start();self.allocate(2);note1,delivery1=self.submit()
        self.assertEqual(delivery1.state,'Closed');self.assertIsNone(self.plan.active_route_stop)
        second=self.start('OTHER-SITE','START2');self.allocate(3,token='STOCK2');note2,delivery2=self.submit()
        self.assertNotEqual(first['name'],second['name']);self.assertNotEqual(note1.name,note2.name)
        self.assertEqual(delivery2.customer,'CUSTOMER2');self.assertEqual(self.unit.current_qty,0)
        self.assertEqual(self.plan.actual_stop_count,2);self.assertEqual(self.plan.completed_stop_count,2)
        self.assertEqual(self.plan.total_delivered_qty,5);self.assertNotEqual(self.plan.fulfilment_status,'Completed')

    def test_both_sequence_policies_are_snapshotted_fields(self):
        from pathlib import Path
        root=e4a.ROOT/'cfg_kanban/doctype'
        schema=json.loads((root/'cfg_kanban_dispatch_profile/cfg_kanban_dispatch_profile.json').read_text())
        f=next(f for f in schema['fields'] if f['fieldname']=='stop_sequence_policy')
        self.assertEqual(f['options'],'Flexible Order\nPlanned Order')
        self.assertIn('stop_sequence_policy',(e4a.ROOT/'services/dispatch_planning.py').read_text())

    def test_flexible_order_records_deviation_without_changing_planned_positions(self):
        a=self.add(token='P1');b=self.add('OTHER-SITE','P2')
        self.start('OTHER-SITE','S2',b['name'])
        self.assertEqual(self.stop().planned_sequence,2);self.assertEqual(self.stop().actual_sequence,1)
        self.assertEqual(self.data[STOP][a['name']].state,'Planned')

    def test_strict_order_rejects_second_customer_without_approval(self):
        self.plan.stop_sequence_policy='Planned Order';self.add(token='P1');b=self.add('OTHER-SITE','P2')
        with self.assertRaisesRegex(ValueError,'next planned'):
            self.start('OTHER-SITE','START',b['name'])
        self.assertNotIn(e4a.SESSION,self.data)

    def test_strict_override_requires_supervisor_reason_and_is_audited(self):
        self.plan.stop_sequence_policy='Planned Order';self.add(token='P1');b=self.add('OTHER-SITE','P2')
        with self.assertRaisesRegex(ValueError,'Supervisor'):
            self.route.approve_route_stop_order(b['name'],'Customer waiting','APPROVE','SESSION')
        self.supervisor()
        with self.assertRaisesRegex(ValueError,'reason'):
            self.route.approve_route_stop_order(b['name'],'','APPROVE','SESSION')
        self.route.approve_route_stop_order(b['name'],'Customer waiting','APPROVE','SESSION');self.supervisor(False)
        self.start('OTHER-SITE','START',b['name']);self.assertEqual(self.stop().override_reason,'Customer waiting')

    def test_strict_unplanned_visit_is_rejected(self):
        self.plan.stop_sequence_policy='Planned Order'
        with self.assertRaisesRegex(ValueError,'Supervisor-planned'):self.start()

    def test_active_stop_prevents_another_customer_and_reopen_reuses_session(self):
        first=self.start();again=self.start(token='REOPEN')
        self.assertEqual(first['name'],again['name']);self.assertEqual(self.plan.actual_stop_count,1)
        with self.assertRaisesRegex(ValueError,'active Route Stop'):self.start('OTHER-SITE','START2')

    def test_start_token_cannot_be_reused_for_another_site(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'another Customer Site'):self.start('OTHER-SITE')

    def test_wrong_company_and_customer_route_scope_are_rejected(self):
        self.other.selling_company='A'
        with self.assertRaisesRegex(ValueError,'another selling Company'):self.start('OTHER-SITE')
        self.other.selling_company='B';self.plan.delivery_route_reference='NORTH';self.other.route_reference='SOUTH'
        with self.assertRaisesRegex(ValueError,'Route Reference'):self.start('OTHER-SITE')

    def test_route_budget_rejects_reusing_previous_customer_quantity(self):
        self.start();self.allocate(4);self.submit();self.start('OTHER-SITE','START2')
        choice=self.context('TAG1')['choices'][0];self.assertEqual(choice['available_qty'],1)
        with self.assertRaisesRegex(ValueError,'within the displayed'):self.allocate(2,token='SECOND')
        self.allocate(1,token='THIRD');self.assertEqual(self.unit.reserved_qty,1)

    def test_route_allocation_replay_keeps_original_payload_even_after_stock_changes(self):
        self.start();self.allocate(2);self.allocate(2)
        self.assertEqual(len(self.data[e4a.DA]),1)
        with self.assertRaisesRegex(ValueError,'another source or quantity'):self.allocate(3)
        self.assertEqual(self.unit.reserved_qty,2)

    def test_prepared_and_unassigned_loose_stock_have_separate_choices(self):
        self.b.loose(6);self.b.erp_balance=15;self.start()
        result=self.context(item='ITEM');keys={r['source_key'] for r in result['choices']}
        self.assertEqual(keys,{'LOOSE','unassigned'})
        free=next(r for r in result['choices'] if r['source_key']=='unassigned')
        self.assertEqual(free['available_qty'],4)
        self.allocate(2,source='unassigned',scan=None,item='ITEM');self.submit()
        self.assertEqual(self.plan.unassigned_delivered_qty,2)
        self.assertEqual(self.b.bridge.waiting_prepared_untagged_qty('B','LORRY1','ITEM',None),6)

    def test_partial_prepared_loose_sales_reduce_commitment_without_freeing_unsold_balance(self):
        self.b.loose(6);self.start();self.allocate(2,source='LOOSE',scan=None,item='ITEM');self.submit()
        self.assertEqual(self.b.bridge.waiting_prepared_untagged_qty('B','LORRY1','ITEM',None),4)
        self.assertEqual(self.b.planning._untagged_available('B','LORRY1','ITEM',None),0)
        self.start('OTHER-SITE','START2');self.allocate(4,source='LOOSE',scan=None,item='ITEM',token='SECOND');self.submit()
        self.assertEqual(self.b.bridge.waiting_prepared_untagged_qty('B','LORRY1','ITEM',None),0)
        self.assertEqual(sum(r['event_type']=='Deliver' for r in self.b.posted),0)

    def test_supervisor_skip_advances_strict_planned_order_without_removing_history(self):
        self.plan.stop_sequence_policy='Planned Order';a=self.add(token='P1');b=self.add('OTHER-SITE','P2')
        self.supervisor();self.route.skip_route_stop(a['name'],'Site closed','SKIP','SESSION');self.supervisor(False)
        self.start('OTHER-SITE','START',b['name'])
        self.assertEqual(self.data[STOP][a['name']].state,'Skipped');self.assertEqual(self.stop().actual_sequence,1)

    def test_cancelled_empty_planned_visit_preserves_actual_history_and_creates_retry_position(self):
        self.plan.stop_sequence_policy='Planned Order';a=self.add()
        self.start(stop=a['name']);delivery=self.delivery();old=self.stop()
        self.b.engine.cancel_delivery_session(delivery.name,'Wrong arrival','CANCEL','SESSION')
        self.assertEqual(old.state,'Cancelled');self.assertEqual(old.actual_sequence,1)
        planned=[s for s in self.data[STOP].values() if s.state=='Planned']
        self.assertEqual(len(planned),1);self.assertEqual(planned[0].retry_of_stop,old.name)
        self.start(token='START2',stop=planned[0].name);self.assertEqual(self.stop().actual_sequence,2)

    def container(self,role='Production Output Container',mixed=False):
        holder=self.b.add(e4a.HU,'BIN',handling_unit_id='BIN1',tag_kind='Reusable Container',
            reusable_container_role=role,identity_state='Active',quality_state='Released',movement_state='Received',
            current_warehouse='LORRY1',inventory_company='B')
        self.b.add('CFG Kanban Container Content','MEM',state='Loaded',container_handling_unit='BIN',
            container_visible_code='BIN1',content_handling_unit='TAG',content_visible_code='TAG1',qty=5)
        self.identities['BIN1']={'identity_type':'Handling Unit','name':'BIN'}
        if mixed:
            self.b.add(e4a.HU,'FREE',handling_unit_id='FREE1',tag_kind='Stock Tag',identity_state='Active',
                quality_state='Released',movement_state='Received',inventory_company='B',current_warehouse='LORRY1',
                current_qty=3,available_qty=3,reserved_qty=0,item_code='ITEM',stock_uom='Nos')
            self.b.add('CFG Kanban Container Content','MEM2',state='Loaded',container_handling_unit='BIN',
                container_visible_code='BIN1',content_handling_unit='FREE',content_visible_code='FREE1',qty=3)
        self.b.engine.active_container_contents=lambda name:[r for r in self.data['CFG Kanban Container Content'].values()
                                                           if r.container_handling_unit==name and r.state=='Loaded']
        self.b.engine.active_container_membership=lambda name:next((r for r in self.data['CFG Kanban Container Content'].values()
                                                                   if r.content_handling_unit==name and r.state=='Loaded'),None)
        return holder

    def test_partial_quantity_bin_delivery_retains_live_contents(self):
        holder=self.container();self.start()
        context=self.context('BIN1');self.assertEqual(context['mode'],'stock_tag')
        self.allocate(2,scan='BIN1');self.submit()
        self.assertEqual(self.unit.current_qty,3);self.assertEqual(holder.movement_state,'Packed')
        self.assertEqual(self.data['CFG Kanban Container Content']['MEM'].state,'Loaded')
        self.start('OTHER-SITE','START2');self.assertEqual(self.context('BIN1')['choices'][0]['available_qty'],3)

    def test_cancel_partial_quantity_bin_note_keeps_one_membership(self):
        self.container();self.start();self.allocate(2,scan='BIN1');note,delivery=self.submit()
        self.b.erp_balance+=2
        self.b.feedback._on_customer_delivery_cancel(note,delivery.name)
        self.assertEqual(self.unit.current_qty,5);self.assertEqual(self.unit.reserved_qty,2)
        self.assertEqual(len(self.data['CFG Kanban Container Content']),1)
        self.assertEqual(self.data['CFG Kanban Container Content']['MEM'].state,'Loaded')

    def test_full_mixed_logistics_container_delivers_each_origin_without_merging_tags(self):
        holder=self.container('Logistics Container',mixed=True);self.start()
        context=self.context('BIN1');self.assertEqual(context['mode'],'container')
        self.allocate(0,source='container',scan='BIN1');self.submit()
        self.assertEqual(holder.movement_state,'Empty');self.assertEqual(self.plan.unassigned_delivered_qty,3)
        self.assertEqual(len(self.data[e4a.DA]),2)
        self.assertTrue(all(r.state=='Unloaded' for r in self.data['CFG Kanban Container Content'].values()))

    def test_regular_logistics_container_cannot_be_partially_delivered(self):
        self.container('Logistics Container');self.start()
        with self.assertRaisesRegex(ValueError,'full-content'):self.allocate(2,source='container',scan='BIN1')

    def test_loose_quantity_cannot_exceed_prepared_budget_or_use_another_plan_source(self):
        self.b.loose(6);self.start()
        with self.assertRaisesRegex(ValueError,'within the displayed'):
            self.allocate(7,source='LOOSE',scan=None,item='ITEM')
        with self.assertRaisesRegex(ValueError,'exact current numbered'):
            self.allocate(2,source='OTHER-PLAN',scan=None,item='ITEM',token='OTHER')

    def test_prepared_route_tag_rejects_ad_hoc_delivery_session(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'prepared Customer Order/Route'):
            self.b.engine._validate_allocation_unit(self.unit,e4a.Row(selling_company='B',source_warehouse='LORRY1'))

    def test_profile_approval_and_scope_do_not_allow_another_operator_to_adopt_active_visit(self):
        self.start();self.operator.employee='OTHER'
        with self.assertRaisesRegex(ValueError,'cannot access'):self.start(token='NEW')

    def test_required_proof_holds_stop_active_until_existing_proof_submission(self):
        self.plan.proof_policy='Required';self.start();self.allocate(2);note,delivery=self.submit()
        self.assertEqual(delivery.state,'Delivered');self.assertEqual(self.stop().state,'Delivered')
        with self.assertRaisesRegex(ValueError,'active Route Stop'):self.start('OTHER-SITE','START2')
        proof=self.b.add('CFG Kanban Delivery Proof','PROOF',delivery_session=delivery.name,state='Draft',
            proof_policy='Required',require_recipient_name=1,require_signature=0,require_photo=0,require_gps=0)
        ns=dict(self.b.bridge.__dict__,assert_delivery_access=lambda name,profile:delivery,
                _require_responsibility=self.b.engine._require_customer_delivery,
                list_reference_media=lambda *a,**kw:[],POLICY_DISPOSITIONS={'Required':('Attended',)},
                get_delivery_proof=lambda *a:proof.as_dict())
        e4a.extract('services/delivery_proof.py',ns,{'submit_delivery_proof','_validate_location'})
        ns['submit_delivery_proof']('PROOF','Attended','PROOF-EVENT','SESSION',recipient_name='Receiver')
        self.assertIsNone(self.plan.active_route_stop);self.assertEqual(self.plan.completed_stop_count,1)
        self.start('OTHER-SITE','START2');self.assertEqual(self.stop().actual_sequence,2)

    def test_order_approval_respects_the_profile_override_snapshot(self):
        stop=self.add();self.supervisor();self.plan.allow_supervisor_override=0
        with self.assertRaisesRegex(ValueError,'does not permit'):
            self.route.approve_route_stop_order(stop['name'],'Urgent','APPROVE','SESSION')

    def test_recorded_stock_action_can_be_reconciled_without_reallocating(self):
        self.start();self.allocate(2)
        result=self.route.reconcile_route_action('stock','STOCK','SESSION',delivery_session=self.delivery().name)
        self.assertEqual(result['recorded'],1);self.assertEqual(self.unit.reserved_qty,2)
        self.assertEqual(len(self.data[e4a.DA]),1)

    def test_void_unrecorded_stock_action_blocks_a_late_original_request(self):
        self.start();delivery=self.delivery()
        result=self.route.void_unrecorded_route_action('stock','STOCK','Operator cancelled','SESSION',delivery_session=delivery.name)
        self.assertEqual(result['voided'],1)
        with self.assertRaisesRegex(ValueError,'cancelled before recording'):self.allocate(2)
        self.assertEqual(self.unit.reserved_qty,0)
        self.allocate(1,token='NEW-ACTION');self.assertEqual(self.unit.reserved_qty,1)

    def test_void_of_a_recorded_action_returns_result_and_never_reverses_stock(self):
        self.start();self.allocate(2)
        result=self.route.void_unrecorded_route_action('stock','STOCK','Cancel if missing','SESSION',delivery_session=self.delivery().name)
        self.assertEqual(result['recorded'],1);self.assertEqual(result['voided'],0)
        self.assertEqual(self.unit.reserved_qty,2)

    def test_voided_visit_cannot_arrive_late_and_create_a_session(self):
        result=self.route.void_unrecorded_route_action('visit','START','Not visiting','SESSION',dispatch_plan='PLAN')
        self.assertEqual(result['voided'],1)
        with self.assertRaisesRegex(ValueError,'cancelled before recording'):self.start()
        self.assertNotIn(e4a.SESSION,self.data)

    def test_no_record_readback_does_not_claim_original_request_was_rejected(self):
        self.start();result=self.route.reconcile_route_action('stock','UNKNOWN','SESSION',delivery_session=self.delivery().name)
        self.assertEqual(result['recorded'],0);self.assertEqual(result['voided'],0)
        self.assertNotIn(e4a.DA,self.data)

    def test_old_supervisor_approval_token_does_not_rewrite_a_newer_approval(self):
        stop=self.add();self.supervisor()
        self.route.approve_route_stop_order(stop['name'],'First reason','A1','SESSION')
        self.route.approve_route_stop_order(stop['name'],'New reason','A2','SESSION')
        self.route.approve_route_stop_order(stop['name'],'First reason','A1','SESSION')
        self.assertEqual(self.data[STOP][stop['name']].override_reason,'New reason')
        with self.assertRaisesRegex(ValueError,'another reason'):
            self.route.approve_route_stop_order(stop['name'],'Changed reason','A1','SESSION')

    def test_erpnext_15_batch_quantity_signature_is_respected(self):
        ns=dict(self.b.bridge.__dict__)
        e4a.extract('services/logistics_foundation.py',ns,{'assert_erp_stock'})
        self.unit.batch_no='BATCH'
        self.assertEqual(ns['assert_erp_stock'](self.unit,'LORRY1',2),11)
        self.b.planning._untagged_available('B','LORRY1','ITEM','BATCH')

    def test_mutations_request_current_document_and_budget_reads(self):
        calls=[];original=self.b.frappe.get_doc
        def docs(*args,**kwargs):calls.append((args,kwargs));return original(*args,**kwargs)
        self.b.frappe.get_doc=docs
        values=Mock(side_effect=self.b.get_values);self.b.frappe.db.get_values=values
        self.start();self.allocate(2)
        self.assertTrue(any(args[0]=='CFG Kanban Dispatch Plan' and kwargs.get('for_update') for args,kwargs in calls))
        self.assertTrue(any(args[0]=='CFG Kanban Delivery Session' and kwargs.get('for_update') for args,kwargs in calls))
        budgets=[call for call in values.call_args_list if call.args and call.args[0]=='CFG Kanban Delivery Allocation'
                 and len(call.args)>1 and call.args[1].get('dispatch_allocation')]
        self.assertTrue(budgets);self.assertTrue(all(call.kwargs.get('for_update') for call in budgets))

    def test_duplicate_planned_sites_require_explicit_stop_identity(self):
        self.add(token='P1');self.add(token='P2')
        with self.assertRaisesRegex(ValueError,'Several planned visits'):self.start()

    def test_historical_route_loads_only_activate_commitment_after_explicit_revalidation(self):
        self.b.loose(6);self.plan.route_stock_commitment=0
        self.assertEqual(self.b.bridge.waiting_prepared_untagged_qty('B','LORRY1','ITEM',None),0)
        self.start();self.assertEqual(self.plan.route_stock_commitment,1)
        self.assertEqual(self.b.bridge.waiting_prepared_untagged_qty('B','LORRY1','ITEM',None),6)

if __name__=='__main__':unittest.main()

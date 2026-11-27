"""Consolidated customer demand over real CFG services, with offline ERP/DB doubles.

These tests do not certify MariaDB locking, native ERP hooks or site permissions.
"""
import copy
import datetime
import json
import math
import re
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

from cfg_kanban.tests import test_trip_dispatch as generation
from cfg_kanban.tests import test_dispatch_fulfilment as native
from cfg_kanban.tests import test_driver_delivery_outcomes as refusals
from cfg_kanban.tests import test_trip_stop_cancellation as cancellation
from cfg_kanban.tests import test_driver_route_actions as driver
from cfg_kanban.tests import test_loose_tags as packs
from cfg_kanban.tests import test_route_sheets as sheets
from cfg_kanban.tests.test_vehicle_overview import load

STOP = 'CFG Kanban Route Stop'


def install(test, frappe, canonical):
    module = types.ModuleType('cfg_kanban.services.consolidated_dispatch')
    module.__dict__.update(frappe=frappe,json=json,cint=lambda value:int(value or 0),
        flt=lambda value:float(value or 0), now_datetime=lambda:datetime.datetime(2026,11,27,12))
    load('services/consolidated_dispatch.py',module.__dict__)
    idem=types.ModuleType('cfg_kanban.services.idempotency');idem.canonical_key=canonical
    p=patch.dict(sys.modules,{module.__name__:module,idem.__name__:idem})
    p.start();test.addCleanup(p.stop)
    return module


class TestConsolidatedGeneration(unittest.TestCase):
    def setUp(self):
        self.b=generation.TestTripDispatch();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.b.b.frappe._dict=generation.base.Doc
        original=self.b.b.get_list
        self.b.b.frappe.get_all=lambda dt,**kwargs:original(dt,**{k:v for k,v in kwargs.items() if k!='limit_page_length' or v})
        self.mod=install(self,self.b.b.frappe,self.b.mod.canonical_key)
        self.trip=self.b.trip;self.trip.stops[1].stop_purpose='Delivery'
        self.b.b.assign(n=2,qty=2)
        self.trip.consolidated_customer_orders=1
        self.trip.state='Draft';self.trip.save();self.trip.state='Planned'

    def test_one_real_plan_one_loading_request_exact_customer_and_order_rows(self):
        self.b.generate()
        plans=self.b.plans();self.assertEqual(len(plans),1)
        plan=plans[0];self.assertEqual(plan.plan_type,'Customer Order')
        self.assertTrue(plan.consolidated_customer_orders)
        self.assertFalse(plan.customer_site);self.assertFalse(plan.sales_order)
        self.assertEqual(len(self.trip.dispatch_plans),1)
        self.assertTrue(self.trip.dispatch_plans[0].consolidated_customer_orders)
        self.assertFalse(self.trip.dispatch_plans[0].stop_key)
        self.assertEqual({(r.office_stop_key,r.sales_order,r.sales_order_item,r.requested_qty) for r in plan.lines},
            {(r.stop_key,r.sales_order,r.sales_order_item,r.planned_qty) for r in self.trip.orders})
        self.assertEqual(len(self.mod.stops(plan)),2)
        self.assertEqual([r['delivery_sequence'] for r in self.trip.loading_sequence],[2,1])
        self.b.ledger.assert_not_called();self.assertFalse(self.b.data.get('Stock Entry'))

    def test_repeat_generation_reuses_plan_and_scopes_without_duplicating_demand(self):
        self.b.generate();ids=[p.name for p in self.b.plans()];scopes=set(self.b.data[STOP])
        self.b.generate();self.assertEqual(ids,[p.name for p in self.b.plans()]);self.assertEqual(scopes,set(self.b.data[STOP]))

    def test_default_mode_retains_distinct_customer_plans(self):
        self.trip.consolidated_customer_orders=0;self.b.generate()
        self.assertEqual(len(self.b.plans()),2)
        self.assertTrue(all(not p.get('consolidated_customer_orders') for p in self.b.plans()))

    def test_mode_cannot_be_changed_after_generation(self):
        self.b.generate();self.trip.consolidated_customer_orders=0
        with self.assertRaisesRegex(ValueError,'before generating'):self.trip.save()

    def test_same_sku_in_different_orders_retains_both_demand_rows(self):
        order=self.b.data['Sales Order'][self.trip.orders[1].sales_order]
        order['items'][0].item_code=self.trip.orders[0].item_code
        self.trip.orders[1].item_code=order['items'][0].item_code
        self.b.generate();self.assertEqual(len(self.b.plans()[0].lines),2)

    def test_wrong_company_or_profile_scope_is_rejected(self):
        self.b.customer.company='B'
        with self.assertRaisesRegex(ValueError,'Company'):self.b.generate()


class TestConsolidatedNativeDelivery(unittest.TestCase):
    def setUp(self):
        self.r=refusals.TestDriverDeliveryOutcomes();self.r.setUp();self.addCleanup(self.r.doCleanups)
        self.b=self.r.b;self.data=self.b.data;self.plan=self.b.plan
        self.mod=install(self,self.b.frappe,self.b.bridge.canonical_key)
        cancelled=types.ModuleType('cfg_kanban.services.cancelled_stop_stock')
        cancelled.__dict__.update(frappe=self.b.frappe,flt=lambda value:float(value or 0))
        load('services/cancelled_stop_stock.py',cancelled.__dict__)
        self.b.frappe.db.table_exists=lambda dt:True
        p=patch.dict(sys.modules,{cancelled.__name__:cancelled});p.start();self.addCleanup(p.stop)
        # Two customers, same SKU: five tagged units and six untagged units.
        self.b.loose(6);self.plan.lines[0].loaded_qty=5
        second=self.b.add('CFG Kanban Dispatch Plan Line','LINE2',item_code='ITEM',stock_uom='Nos',
            requested_qty=6,loaded_qty=6,sales_order='SO2',sales_order_item='SO2-ROW',office_stop_key='CUSTOMER2')
        self.plan.lines.append(second);self.data[native.ALLOC]['LOOSE'].dispatch_plan_line=second.name
        self.plan.lines[0].update(sales_order='SO1',sales_order_item='SO1-ROW',office_stop_key='CUSTOMER1')
        self.plan.update(consolidated_customer_orders=1,office_delivery_trip='TRIP',office_stop_key=None,
            customer_site=None,customer=None,customer_address=None,sales_order=None,
            proof_policy='No Proof Required',total_requested_qty=11)
        self.site2=self.b.add('CFG Kanban Customer Scan Point','SITE2',active=1,site_code='SITE2-QR',site_name='Second Customer',
            selling_company='B',customer='CUSTOMER2',customer_address='ADDR2',default_price_list='SELL',proof_policy='Required')
        self.scopes=[]
        for n,(site,qty) in enumerate(((self.b.site,5),(self.site2,6)),1):
            self.scopes.append(self.b.add(STOP,'SCOPE'+str(n),state='Planned',dispatch_plan=self.plan.name,company='B',
                office_delivery_trip='TRIP',office_stop_key='CUSTOMER'+str(n),planned_sequence=n,
                customer_scan_point=site.name,customer=site.customer,customer_address=site.customer_address,
                site_name=site.site_name,fulfilment_status='Not Started'))
            row=native.Record(name=f'SO{n}-ROW',item_code='ITEM',stock_uom='Nos',uom='Nos',qty=qty,
                delivered_qty=0,conversion_factor=1,rate=n*3)
            self.b.add('Sales Order','SO'+str(n),items=[row],docstatus=1,company='B',customer=site.customer,status='To Deliver',
                project='PROJECT',selling_price_list='SELL',currency='MYR',conversion_rate=1,price_list_currency='MYR',plc_conversion_rate=1)
        self.b.engine.resolve_logistics_scan=lambda scan:dict(identity_type='Customer Scan Point',name='SITE2' if scan=='SITE2-QR' else 'SITE' if scan=='SITE-QR' else 'OTHER')
        def site(scan):
            if scan in ('SITE','SITE-QR'):return self.b.site
            if scan in ('SITE2','SITE2-QR'):return self.site2
            raise ValueError('Wrong customer Site')
        self.b.engine._resolve_customer_site=site
        self.b.frappe.get_all=self.all
        self.b.frappe.db.count=lambda dt,filters:len(self.all(dt,filters))
        # Native stock and unrelated prepared commitments remain the existing fixture seams.
        self.b.planning._untagged_available=lambda *args,**kwargs:self.b.erp_balance

    def all(self,dt,filters=None,pluck=None,**kwargs):
        rows=[r for r in self.data.get(dt,{}).values() if self.b.matches(r,filters)]
        return [r.get(pluck) for r in rows] if pluck else rows

    def view(self,n):return self.mod.scoped(self.plan,'CUSTOMER'+str(n))
    def start(self,n=1,token='START'):
        return self.b.bridge.start_prepared_delivery('PLAN','SITE-QR' if n==1 else 'SITE2-QR',token,'SESSION',customer_dispatch_stop='SCOPE'+str(n))
    def delivery(self,n):return self.data[native.SESSION][self.scopes[n-1].delivery_session]
    def post(self,n):
        delivery=self.delivery(n)
        self.b.engine.confirm_delivery_allocations(delivery.name,'CONFIRM'+str(n),'SESSION')
        payload=self.b.engine._customer_delivery_payload(delivery)
        doc=self.b.gateway['build_customer_delivery_note'](delivery,payload)
        doc.name='DN'+str(n);doc.state='To Bill';delivery.state='ERP Document Pending'
        self.b.feedback._on_customer_delivery_submit(doc,delivery.name)
        return payload,doc

    def test_two_customers_one_manifest_separate_native_notes_and_exact_prices(self):
        self.start(1);self.assertEqual({row.dispatch_allocation for row in self.data[native.DA].values()},{'ALLOC'})
        first,doc1=self.post(1)
        self.assertEqual(self.scopes[0].fulfilment_status,'Completed')
        self.assertEqual(self.scopes[1].fulfilment_status,'Not Started')
        self.assertEqual(self.plan.fulfilment_status,'In Progress');self.assertTrue(self.plan.prepared_stock_commitment)
        self.start(2);second,doc2=self.post(2)
        self.assertEqual(doc1.customer,'CUSTOMER');self.assertEqual(doc2.customer,'CUSTOMER2')
        self.assertEqual(first['items'][0]['against_sales_order'],'SO1')
        self.assertEqual(second['items'][0]['against_sales_order'],'SO2')
        self.assertEqual((first['items'][0]['rate'],second['items'][0]['rate']),(3,6))
        self.assertEqual(self.plan.fulfilment_status,'Completed');self.assertEqual(self.plan.total_delivered_qty,11)
        self.assertFalse(self.plan.delivery_session);self.assertEqual(len(self.data[native.MANIFEST]),1)

    def test_repeat_start_and_feedback_never_duplicate_stock_consumption(self):
        first=self.start();again=self.start(token='REOPEN')
        self.assertEqual(first['name'],again['name']);self.assertEqual(len(self.data[native.SESSION]),1)
        _payload,doc=self.post(1)
        before=copy.deepcopy(self.b.posted)
        self.b.feedback._on_customer_delivery_submit(doc,self.delivery(1).name)
        self.assertEqual(before,self.b.posted)

    def test_wrong_customer_scope_and_cross_customer_allocation_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact assigned'):self.b.bridge.start_prepared_delivery('PLAN','SITE-QR','BAD','SESSION',customer_dispatch_stop='SCOPE2')
        self.assertFalse(self.data.get(native.SESSION));self.assertFalse(self.b.posted)
        self.start();delivery=self.delivery(1)
        row=next(iter(self.data[native.DA].values()));row.dispatch_allocation='LOOSE'
        with self.assertRaisesRegex(ValueError,'exact prepared load'):self.b.bridge.validate_prepared_allocations(delivery)

    def test_second_driver_cannot_start_another_customer_while_one_is_active(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'active consolidated'):self.start(2)
        self.assertEqual(len(self.data[native.SESSION]),1)

    def test_partial_refusal_is_per_customer_and_keeps_other_customer_demand(self):
        view=self.view(1)
        self.r.out.declare(self.r.trip,native.Record(stop_key='CUSTOMER1'),view,[dict(dispatch_allocation='ALLOC',accepted_qty=3,
            refusal_reason='Customer downsized',condition='Good / Unwanted')],self.r.operator,self.r.session,'REFUSE')
        self.start();payload,_doc=self.post(1)
        self.assertEqual(payload['items'][0]['qty'],3)
        self.assertEqual(self.b.unit.current_qty,2);self.assertEqual(self.b.unit.reserved_qty,2)
        self.assertEqual(self.scopes[1].fulfilment_status,'Not Started')
        self.start(2);second,_doc=self.post(2);self.assertEqual(second['items'][0]['qty'],6)

    def test_scope_can_never_cancel_or_clear_commitment_for_whole_plan(self):
        view=self.view(1)
        with self.assertRaisesRegex(ValueError,'shared'):view.db_set('state','Cancelled')
        with self.assertRaisesRegex(ValueError,'Only E5'):view.db_set('prepared_stock_commitment',0)
        self.assertEqual(self.plan.state,'Loaded')

    def test_two_orders_at_one_customer_keep_exact_rows_and_different_prices(self):
        self.plan.lines[1].office_stop_key='CUSTOMER1'
        self.scopes.pop();self.data[STOP].pop('SCOPE2')
        self.data['Sales Order']['SO2'].customer='CUSTOMER'
        self.start();payload,_doc=self.post(1)
        self.assertEqual({(r['against_sales_order'],r['so_detail'],r['rate']) for r in payload['items']},
                         {('SO1','SO1-ROW',3),('SO2','SO2-ROW',6)})
        self.assertEqual(self.plan.total_delivered_qty,11)

    def test_mismatched_currency_or_price_list_fails_before_session_or_reservation(self):
        self.plan.lines[1].office_stop_key='CUSTOMER1';self.scopes.pop();self.data[STOP].pop('SCOPE2')
        self.data['Sales Order']['SO2'].customer='CUSTOMER';self.data['Sales Order']['SO2'].currency='USD'
        with self.assertRaisesRegex(ValueError,'matching currency'):self.start()
        self.assertFalse(self.data.get(native.SESSION));self.assertFalse(self.b.posted)

    def test_multiple_orders_preserve_native_uom_conversion_and_validate_order_links(self):
        self.plan.lines[1].office_stop_key='CUSTOMER1';self.scopes.pop();self.data[STOP].pop('SCOPE2')
        self.data['Sales Order']['SO2'].customer='CUSTOMER'
        self.data['Sales Order']['SO1'].items[0].update(uom='Box',qty=2.5,conversion_factor=2)
        self.start();payload,doc=self.post(1)
        first=next(row for row in doc.items if row.so_detail=='SO1-ROW')
        self.assertEqual((first.qty,first.stock_qty,first.uom,first.conversion_factor),(2.5,5,'Box',2))
        allocations=list(self.data[native.DA].values());first.so_detail='SO2-ROW'
        with self.assertRaisesRegex(ValueError,'Sales Order reference'):
            self.b.feedback._validate_customer_delivery_rows(doc,self.delivery(1),allocations)

    def test_loose_reservation_keeps_other_customers_pending_quantity_protected(self):
        self.data[native.ALLOC]['ALLOC'].update(allocation_kind='Untagged ERP Stock',handling_unit=None)
        self.b.unit.update(current_qty=0,reserved_qty=0,available_qty=0)
        self.b.erp_balance=6  # Five for A plus six for B cannot fit this balance.
        self.assertEqual(self.mod.other_untagged_commitment(self.plan,'CUSTOMER1','ITEM',None,current=True),6)
        with self.assertRaisesRegex(ValueError,'available'):
            self.start(1)
        self.assertFalse(self.data.get(native.DA));self.assertFalse(self.b.posted)

    def test_e5_counts_own_held_loose_refusal_without_releasing_it_to_other_customers(self):
        self.data[native.ALLOC]['ALLOC'].update(allocation_kind='Untagged ERP Stock',handling_unit=None)
        self.b.unit.update(current_qty=0,reserved_qty=0,available_qty=0)
        outcome=self.r.out.declare(self.r.trip,native.Record(stop_key='CUSTOMER1'),self.view(1),[
            dict(dispatch_allocation='ALLOC',accepted_qty=3,refusal_reason='Downsized',condition='Good / Unwanted')],
            self.r.operator,self.r.session,'REFUSE')
        self.start(1);self.post(1)
        self.assertEqual(self.mod.own_held_untagged(self.plan,'ITEM',None,current=True),2)
        self.assertEqual(self.mod.other_untagged_commitment(self.plan,'CUSTOMER2','ITEM',None,current=True),0)
        self.assertEqual(outcome.lines[0].stock_state,'Held')


class TestConsolidatedDriverAndCancellation(unittest.TestCase):
    def setUp(self):
        self.b=cancellation.TestStopCancellation();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.a=self.b.a;self.trip=self.b.trip;self.data=self.b.data;self.f=self.b.f
        self.mod=install(self,self.f,driver.canonical)
        self.plan=self.a.v.p1;second=self.a.v.p2
        self.plan.update(consolidated_customer_orders=1,office_delivery_trip=self.trip.name,
            office_stop_key=None,customer=None,customer_site=None,customer_address=None,sales_order=None)
        for n,root in enumerate((self.plan,second),1):
            root.lines[0].update(office_stop_key=self.b.b.keys[n-1],sales_order='SO'+str(n),sales_order_item='ROW'+str(n))
        self.plan.lines+=second.lines
        self.data['CFG Kanban Dispatch Allocation']['ALLOC2'].update(dispatch_plan=self.plan.name,movement_manifest='MAN1')
        self.plan.total_loaded_qty=6;self.plan.total_requested_qty=6
        self.trip.dispatch_plans=[generation.base.Doc(dispatch_plan=self.plan.name,stop_key=None,consolidated_customer_orders=1)]
        self.trip.consolidated_customer_orders=1
        self.trip.driver_route_state='Not Started';self.trip.driver_route_snapshot_json=None;self.trip.driver_active_stop_key=None
        self.trip.driver_route_started_on=None;self.trip.driver_route_revision=0;self.trip.driver_active_vehicle_key=None
        for n,source in enumerate(self.trip.stops[:2],1):
            self.a.b.add(STOP,'CS'+str(n),state='Planned',dispatch_plan=self.plan.name,company='A',
                office_delivery_trip=self.trip.name,office_stop_key=source.stop_key,planned_sequence=n,
                customer_scan_point=source.customer_scan_point,customer=source.customer,
                customer_address=source.customer_address,site_name=source.site_name,fulfilment_status='Not Started')
        self.a.prepared._loaded_allocations=self.b.prepared['_loaded_allocations']
        out=sys.modules['cfg_kanban.services.driver_delivery_outcomes'];resalable=out._assert_resalable
        out.__dict__.update(frappe=self.f,json=json,math=math,flt=lambda v:float(v or 0))
        load('services/driver_delivery_outcomes.py',out.__dict__)
        out._assert_resalable=resalable;out._prepared=lambda:generation.base.Doc(self.b.prepared)
        planning=types.ModuleType('cfg_kanban.services.dispatch_planning');planning.__dict__.update(self.b.plan)
        p=patch.dict(sys.modules,{planning.__name__:planning});p.start();self.addCleanup(p.stop)

    def test_driver_projects_two_stops_and_exact_stock_from_one_plan(self):
        result=self.a.v.read()
        self.assertEqual([r['state'] for r in result['stops'][:2]],['Loaded','Loaded'])
        self.assertEqual([[s['dispatch_allocation'] for s in r['sources']] for r in result['stops'][:2]],[['ALLOC1'],['ALLOC2']])
        self.a.start();context=self.a.context()
        self.assertEqual(context['next_step'],'Begin Delivery')
        self.assertEqual({row['dispatch_allocation'] for row in context['quantities']},{'ALLOC1'})

    def test_departure_snapshot_has_stable_customer_policies_and_stock_ownership(self):
        self.a.start();snapshot=json.loads(self.trip.driver_route_snapshot_json)
        self.assertEqual(set(snapshot['policies']),{self.plan.name+':'+r.stop_key for r in self.trip.stops[:2]})
        self.assertEqual(snapshot['customer_sources'],{'ALLOC1':self.trip.stops[0].stop_key,'ALLOC2':self.trip.stops[1].stop_key})
        current=self.a.ns['_execution'](self.trip,self.a.operator,self.a.v.read())
        self.assertEqual(snapshot,json.loads(json.dumps(current,default=str)))

    def test_cancel_loaded_customer_keeps_other_delivery_and_root_loading_intact(self):
        self.a.start();self.b.supervisor()
        result=self.b.direct(0)
        self.assertTrue(result['result']['stop_cancelled'])
        scopes=self.data[STOP]
        self.assertEqual(scopes['CS1'].state,'Skipped');self.assertEqual(scopes['CS2'].state,'Planned')
        self.assertEqual(self.plan.state,'Loaded');self.assertFalse(self.plan.stop_cancellation)
        self.assertEqual(self.plan.movement_manifest,'MAN1');self.assertTrue(self.plan.prepared_stock_commitment)
        context=self.a.context(n=2)
        self.assertEqual(context['next_step'],'Begin Delivery')
        self.assertEqual({r['dispatch_allocation'] for r in context['quantities']},{'ALLOC2'})
        self.assertEqual(len(self.b.ledgers),1)
        self.a.perform(self.b.last);self.assertEqual(len(self.b.ledgers),1)

    def test_released_cancelled_stock_is_removed_only_from_its_e5_balance(self):
        self.a.start();self.b.supervisor();self.b.direct(0,disposition='Release for Same-trip Sale')
        rows=self.b.review._balances(self.plan,current=True)
        balances={r['dispatch_allocation']:r['remaining_qty'] for r in rows}
        self.assertEqual(balances,{'ALLOC1':0,'ALLOC2':2})

    def test_held_cancelled_stock_still_requires_e5_controlled_recovery(self):
        self.a.start();self.b.supervisor();self.b.direct(0)
        with self.assertRaisesRegex(ValueError,'reserved for return'):
            self.b.stock.assert_review_action(self.plan,'Close Trip - Stock Stays')
        rows=self.b.review._balances(self.plan,current=True)
        self.b.review._at_source(self.plan,rows,current=True)
        self.assertEqual(sum(r['remaining_qty'] for r in rows),6)

    def test_wrong_customer_stop_cannot_use_another_scope(self):
        self.a.start()
        context=self.a.context(n=2)
        self.assertEqual({r['dispatch_allocation'] for r in context['quantities']},{'ALLOC2'})
        with self.assertRaisesRegex(ValueError,'loaded source|exact|quantity'):
            self.a.ns['preview_driver_quantities'](self.trip.name,self.trip.stops[1].stop_key,self.plan.name,
                [dict(dispatch_allocation='ALLOC1',accepted_qty=1)],'TOKEN')

    def test_unused_customer_cancellation_releases_only_its_reservation(self):
        self.trip.driver_route_state='Not Started';self.plan.state='Picking'
        self.plan.vehicle_warehouse=None;self.plan.movement_manifest=None
        self.data['CFG Kanban Dispatch Plan Line']={}
        for line in self.plan.lines:
            line.parent=self.plan.name;line.parenttype=native.PLAN;line.parentfield='lines'
            line.loaded_qty=0;line.reserved_qty=line.requested_qty
            self.data['CFG Kanban Dispatch Plan Line'][line.name]=line
        for n in (1,2):
            allocation=self.data[native.ALLOC]['ALLOC'+str(n)]
            allocation.update(state='Reserved',source_company='A',source_warehouse='SOURCE',doctype=native.ALLOC)
            unit=self.data[native.HU]['HU'+str(n)];unit.current_warehouse='SOURCE';unit.reserved_qty=unit.current_qty;unit.available_qty=0
        view=self.mod.scoped(self.plan,self.trip.stops[0].stop_key)
        self.mod.cancel_customer(view,generation.base.Doc(name='DECISION'),self.a.operator,
            generation.base.Doc(name='SESSION',terminal_user='office'),'Customer closed','CANCEL')
        self.assertEqual(self.data[native.ALLOC]['ALLOC1'].state,'Released')
        self.assertEqual(self.data[native.ALLOC]['ALLOC2'].state,'Reserved')
        self.assertEqual(self.plan.total_requested_qty,2)
        self.assertEqual(self.plan.total_reserved_qty,2)
        self.assertEqual(self.plan.state,'Ready for Vehicle')
        with self.assertRaisesRegex(ValueError,'active customer demand'):
            self.b.plan['_plan_line'](self.plan,self.plan.lines[0].name)


class TestConsolidatedLooseTags(unittest.TestCase):
    def setUp(self):
        self.b=packs.LooseTagFixture();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.mod=install(self,self.b.f,self.b.common['canonical_key'])
        self.b.plan.update(consolidated_customer_orders=1,customer=None,customer_site=None,customer_address=None,office_stop_key=None)
        self.b.trip.consolidated_customer_orders=1;self.b.trip.dispatch_plans[0].stop_key=None
        for n,line in enumerate(self.b.plan.lines,1):
            line.update(office_stop_key='STOP',sales_order='SO',sales_order_item='SO-L'+str(n))
        self.b.add(STOP,'CS',state='Planned',dispatch_plan='PLAN',company='B',office_delivery_trip='TRIP',
            office_stop_key='STOP',planned_sequence=1,customer_scan_point='SITE',customer='CUSTOMER',customer_address='ADDR',fulfilment_status='Not Started')

    def test_multi_sku_packing_keeps_scope_and_reuses_original_reservations_on_retry(self):
        result=self.b.create(stop_key='STOP');before=len(self.b.ledgers)
        again=self.b.create(stop_key='STOP')
        self.assertEqual(result['name'],again['name']);self.assertEqual(before,len(self.b.ledgers))
        self.assertEqual({r.item_code for r in self.b.pack().lines},{'ITEM','ITEM2'})
        self.assertTrue(self.b.plan.has_loose_tags);self.assertEqual(self.b.pack().customer,'CUSTOMER')

    def test_one_box_loading_scan_validates_customer_lines_against_shared_header(self):
        self.b.create(stop_key='STOP')
        self.b.loose._validate_lines(self.b.pack(),self.b.plan,'Reserved')
        self.b.load_pack();self.b.scan()
        self.assertEqual(self.b.pack().state,'Scanned')
        with self.assertRaisesRegex(ValueError,'another customer stop'):self.b.scan('OTHER')

    def test_unused_pack_undo_preserves_root_plan_and_source_quantities(self):
        self.b.create(stop_key='STOP');pack=self.b.pack()
        self.b.loose.cancel_loose_tag(pack.qr_payload,'Repack the box','UNDO','TOKEN')
        self.assertEqual(pack.state,'Cancelled');self.assertEqual(self.b.source.current_qty,10)
        self.assertEqual(self.b.source2.current_qty,8);self.assertEqual(self.b.plan.state,'Approved')

    def test_prepared_lookup_preserves_customer_scope_for_plan_and_site_scans(self):
        self.b.plan.state='Loaded'
        choices=self.mod.prepared_choices('SITE',self.b.op,self.b.plan)
        self.assertEqual(len(choices),1)
        self.assertEqual((choices[0].name,choices[0].customer,choices[0].customer_dispatch_stop),('PLAN','CUSTOMER','CS'))
        self.assertEqual({row['office_stop_key'] for row in choices[0].lines},{'STOP'})
        self.assertEqual(self.mod.prepared_choices('WRONG-SITE',self.b.op,self.b.plan),[])


class TestConsolidatedRouteSheet(unittest.TestCase):
    def setUp(self):
        self.b=sheets.TestRouteSheets();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.mod=install(self,self.b.frappe,driver.canonical)
        self.plan=self.b.p1
        self.plan.update(consolidated_customer_orders=1,office_delivery_trip='TRIP',customer_site=None,customer=None,customer_address=None)
        self.b.data[native.PLAN].pop('P2')
        self.trip=self.b.add('CFG Kanban Delivery Trip','TRIP',company='B',
            dispatch_plans=[sheets.Doc(dispatch_plan=self.plan.name,stop_key=None)],open_route_plan=None,
            stops=[sheets.Doc(stop_key='K1',customer_scan_point='S1',instructions=''),sheets.Doc(stop_key='K2',customer_scan_point='S2',instructions='')])
        self.rows=[]
        for n in (1,2):
            site=self.b.data['CFG Kanban Customer Scan Point']['S'+str(n)]
            self.b.add(STOP,'CS'+str(n),state='Planned',dispatch_plan=self.plan.name,company='B',office_delivery_trip='TRIP',
                office_stop_key='K'+str(n),customer_scan_point=site.name,customer=site.customer,customer_address=site.customer_address,
                planned_sequence=n,fulfilment_status='Not Started')
            self.rows.append(dict(row_key='ROW'+str(n),dispatch_plan=self.plan.name,customer_scan_point=site.name,source_route_stop='CS'+str(n)))

    def test_route_sheet_retains_both_exact_customer_scopes_and_rejects_missing_one(self):
        rows=self.b.ns['_normal_rows'](self.rows,[self.plan])
        self.assertEqual([r['source_route_stop'] for r in rows],['CS1','CS2'])
        with self.assertRaisesRegex(ValueError,'every exact office Trip visit'):
            self.b.ns['_normal_rows'](self.rows[:1],[self.plan])

    def test_approved_sequence_reuses_customer_scopes_without_creating_open_sales(self):
        rows=self.b.ns['_normal_rows'](list(reversed(self.rows)),[self.plan])
        sheet=self.b.add('CFG Kanban Route Sheet','SHEET',scope='Combined Lorry Trip',state='Draft',stops=[sheets.Doc(r) for r in rows])
        self.b.ns['_approve'](sheet,[self.plan],self.b.operator)
        self.assertEqual(sheet.state,'Approved');self.assertEqual(len(self.b.data[STOP]),2)
        self.assertEqual(self.b.data[STOP]['CS2'].planned_sequence,1)


class TestConsolidatedCommitmentSQL(unittest.TestCase):
    def test_completed_customers_do_not_release_cancelled_or_refused_loose_balances(self):
        """Execute the real aggregate SQL; ERP/MariaDB integration remains separate."""
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.create_function('greatest',-1,lambda *args:max(args))
        db.executescript('''
            CREATE TABLE `tabCFG Kanban Dispatch Plan` (name, state, plan_type, fulfilment_mode,
                company, vehicle_warehouse, prepared_stock_commitment, route_stock_commitment,
                fulfilment_status, consolidated_customer_orders);
            CREATE TABLE `tabCFG Kanban Dispatch Allocation` (name, dispatch_plan, allocation_kind,
                state, item_code, batch_no, allocated_qty);
            CREATE TABLE `tabCFG Kanban Delivery Allocation` (dispatch_allocation, state, allocated_qty);
            CREATE TABLE `tabCFG Kanban Delivery Outcome Line` (dispatch_allocation, refused_qty);
            CREATE TABLE `tabCFG Kanban Cancelled Stop Stock` (dispatch_allocation, stock_state, qty);
            INSERT INTO `tabCFG Kanban Dispatch Plan` VALUES ('CON','Loaded','Customer Order','Vehicle Delivery',
                'A','LORRY',1,0,'Completed',1), ('OLD','Loaded','Customer Order','Vehicle Delivery','A','LORRY',1,0,'Completed',0);
            INSERT INTO `tabCFG Kanban Dispatch Allocation` VALUES ('A','CON','Untagged ERP Stock','Loaded','SKU',NULL,6),
                ('B','OLD','Untagged ERP Stock','Loaded','SKU',NULL,4);
            INSERT INTO `tabCFG Kanban Delivery Allocation` VALUES ('A','Delivered',2);
            INSERT INTO `tabCFG Kanban Delivery Outcome Line` VALUES ('A',1);
            INSERT INTO `tabCFG Kanban Cancelled Stop Stock` VALUES ('A','Released for Sale',1),('A','Held for Return',2);
        ''')
        calls=[]
        def sql(query,values):
            calls.append(query)
            return db.execute(re.sub(r'%\((\w+)\)s',r':\1',query),values).fetchall()
        f=native.Row(db=native.Row(sql=sql,exists=lambda *args:False))
        ns=dict(frappe=f,flt=lambda value:float(value or 0))
        native.extract('services/dispatch_fulfilment.py',ns,{'waiting_prepared_untagged_qty','held_refused_untagged_qty'})
        waiting=ns['waiting_prepared_untagged_qty']
        self.assertEqual(waiting('A','LORRY','SKU',None),2)
        self.assertEqual(waiting('A','LORRY','SKU',None,exclude_plan='CON'),0)
        self.assertEqual(waiting('OTHER','LORRY','SKU',None),0)
        self.assertEqual(waiting('A','OTHER','SKU',None),0)
        db.execute("UPDATE `tabCFG Kanban Dispatch Plan` SET consolidated_customer_orders=0 WHERE name='CON'")
        self.assertEqual(waiting('A','LORRY','SKU',None),0)




if __name__ == '__main__':unittest.main()

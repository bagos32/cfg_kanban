"""Offline multi-SKU packing → native E2/E3 → prepared DN/feedback scenarios.

Actual service functions, explicit document/database/ERP-stock/permission doubles.
No native MariaDB concurrency, live site, hardware scanner or printer acceptance.
"""
import copy
import datetime
import hashlib
import json
import math
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_vehicle_overview import load
from cfg_kanban.tests import test_dispatch_fulfilment as native_fixture
from cfg_kanban.tests.test_dispatch_fulfilment import Record, Row, PLAN, ALLOC, HU, SESSION, DA
from cfg_kanban.services.handling_unit_math import event_deltas, apply_balance_delta

PACK='CFG Kanban Loose Tag'
PLINE='CFG Kanban Loose Tag Line'
TRIP='CFG Kanban Delivery Trip'
DLINE='CFG Kanban Dispatch Plan Line'


class Document(Record):
    def check_permission(self, kind):
        if self.get('_denied'):raise PermissionError('Document access denied')
    def set(self,key,value):self[key]=value
    def insert(self, **kwargs):
        table=self._store.setdefault(self.doctype,{})
        self.name=self.name or ('KLT-' if self.doctype==PACK else 'ROW-')+str(len(table)+1)
        if self.doctype==PACK and any(r.creation_key==self.creation_key for r in table.values()):raise ValueError('Duplicate pack key')
        table[self.name]=self
        childtype=PLINE if self.doctype==PACK else 'CFG Kanban Delivery Outcome Line' if self.doctype=='CFG Kanban Delivery Outcome' else None
        for i,line in enumerate(self.get('lines') or [],1):
            line.update(name=self.name+'-L'+str(i),parent=self.name,parenttype=self.doctype,parentfield='lines',idx=i)
            if childtype:self._store.setdefault(childtype,{})[line.name]=line
        return self


class LooseTagFixture(unittest.TestCase):
    def setUp(self):
        self.base=native_fixture.TestDispatchFulfilment();self.base.setUp();self.addCleanup(self.base.doCleanups)
        b=self.base;self.data=b.data;self.f=b.frappe;self.op=b.operator;self.session=b.e3.session
        self.op.responsibilities.append(Row(responsibility='Container Loading'))
        self.op.update(can_start=1,can_complete=1,can_override=1,kanban_role='Supervisor',view_all_responsibilities=1)
        self.plan=b.plan
        self.plan.update(state='Approved',tag_policy='Mixed',vehicle_warehouse=None,vehicle_reference=None,movement_manifest=None,
            total_reserved_qty=0,total_loaded_qty=0,total_requested_qty=5,delivery_session=None,
            dispatch_point='DISPATCH',office_delivery_trip='TRIP',office_stop_key='STOP',prepared_stock_commitment=0)
        self.plan.lines=[Document(name='A',parent='PLAN',parenttype=PLAN,parentfield='lines',item_code='ITEM',stock_uom='Nos',requested_qty=3,loaded_qty=0),
                         Document(name='B',parent='PLAN',parenttype=PLAN,parentfield='lines',item_code='ITEM2',stock_uom='Nos',requested_qty=2,loaded_qty=0)]
        self.data[DLINE]={r.name:r for r in self.plan.lines};self.data[ALLOC]={};self.data.pop(SESSION,None);self.data.pop(DA,None)
        self.source=b.unit;self.source.update(current_qty=10,available_qty=10,reserved_qty=0,current_warehouse='SOURCE',tag_kind='Main Stock Tag',expiry_date='2027-01-31',process_certificate_set='CERT')
        self.source2=self.add(HU,'TAG2',**{k:v for k,v in dict.items(self.source) if k not in ('name','doctype','_store')})
        self.source2.update(item_code='ITEM2',handling_unit_id='TAG2',current_qty=8,available_qty=8,batch_no='BATCH2')
        self.data[HU][self.source.name]=self.source;self.data[HU]['TAG2']=self.source2
        for dt,name in [('Company','B'),('Warehouse','SOURCE'),('Warehouse','LORRY1'),('CFG Kanban Card','DISPATCH')]:
            self.add(dt,name,active=1,blocked=0,company='B')
        self.trip=self.add(TRIP,'TRIP',state='Planned',company='B',driver=self.op.employee,driver_route_state='Not Started',
            driver_route_snapshot_json='{"stop_order":["STOP","OTHER"],"strict":false}',driver_active_stop_key=None,
            stops=[Document(stop_key='STOP',customer='CUSTOMER',customer_scan_point='SITE',site_name='Shop',stop_purpose='Delivery'),
                   Document(stop_key='OTHER',customer='OTHER',customer_scan_point='SITE2',stop_purpose='Delivery')],
            dispatch_plans=[Document(dispatch_plan='PLAN',stop_key='STOP')])
        self.f.ValidationError=ValueError;self.f.flags=Row();self.f.session=Row(user='warehouse');self.f.generate_hash=lambda length: 'x'*length
        self.f.get_roles=lambda *a:['Stock Manager'];self.f.copy_doc=lambda d:self.new_doc(copy.deepcopy(d.as_dict()))
        self.f.get_doc=self.get_doc;self.f.get_all=self.get_all
        self.f.db.get_value=self.get_value;self.f.db.get_values=self.get_values;self.f.db.exists=lambda dt,filters:self.get_value(dt,filters,'name')
        self.f.db.savepoint=self.savepoint;self.f.db.rollback=self.rollback;self.f.db.sql=self.sql
        self.f.db.count=lambda dt,filters:len(self.get_all(dt,filters))
        self.f.db.set_value=self.set_value
        self.saves={};self.posted=[];self.ledgers={};self.certificate_calls=[];self.locks=[]
        for dt,table in self.data.items():
            for name,doc in list(table.items()):
                if not isinstance(doc,Document):table[name]=Document(doc)
                table[name].setdefault('flags',Row())
        self.plan=self.data[PLAN][self.plan.name];self.base.plan=self.plan
        self.source=self.data[HU][self.source.name];self.base.unit=self.source
        self.base.manifest=self.data['CFG Kanban Movement Manifest'][self.base.manifest.name]
        self.common=dict(frappe=self.f,json=json,isfinite=math.isfinite,math=math,contextmanager=contextmanager,
            flt=lambda v:float(v or 0),cint=lambda v:int(v or 0),now_datetime=lambda:datetime.datetime(2026,11,26,10),
            canonical_key=lambda *v:hashlib.sha256(json.dumps(v,sort_keys=True,default=str).encode()).hexdigest(),
            require_operator=lambda *a,**k:(self.op,self.session),record=Mock(),_=lambda t:t,
            resolve_logistics_scan=self.resolve,post_quantity_event=self.post,assert_erp_stock=Mock())
        self.planning=types.ModuleType('cfg_kanban.services.dispatch_planning');self.planning.__dict__.update(self.common);load('services/dispatch_planning.py',self.planning.__dict__)
        self.planning.get_dispatch_plan=lambda *a:self.plan.as_dict()
        self.planning._manifest_result=lambda *a:dict(name=a[0])
        self.planning.validate_warehouse_company=Mock()
        self.base.bridge._planning_services=lambda:self.planning
        self.base.engine.post_quantity_event=self.post;self.base.feedback.post_quantity_event=self.post
        # Source validation is the actual Quantity Bin validator, without imposing its single-SKU fill rule.
        quantity=types.ModuleType('cfg_kanban.services.logistics_quantity_bins');quantity.__dict__.update(self.common,active_container_membership=lambda n:None);load('services/logistics_quantity_bins.py',quantity.__dict__)
        contents=types.ModuleType('cfg_kanban.services.container_contents');contents.__dict__.update(self.common);load('services/container_contents.py',contents.__dict__)
        contents.active_container_membership=lambda n:None
        identity=types.ModuleType('cfg_kanban.services.logistics_stock_identity')
        identity.inherit_split_certificates=lambda a,b,q,k:self.certificate_calls.append((a.name,b.name,q))
        identity.assert_merge_compatible=lambda a,b:None
        identity.identity_snapshot=lambda unit:dict(expiry=unit.expiry_date)
        identity._expiry=lambda snapshot:snapshot['expiry']
        self.loose=types.ModuleType('cfg_kanban.services.loose_tags');self.loose.__dict__.update(self.common);load('services/loose_tags.py',self.loose.__dict__)
        self.loose._atomic=contextmanager(self.loose._atomic)
        self.loose._planning=lambda:self.planning;self.loose._identity=lambda:identity
        self.outcomes=types.ModuleType('cfg_kanban.services.driver_delivery_outcomes');self.outcomes.__dict__.update(self.common);load('services/driver_delivery_outcomes.py',self.outcomes.__dict__)
        self.outcomes._prepared=lambda:self.base.bridge
        self.outcomes._returns=lambda:Row(CONDITIONS={'Good / Unwanted','Damaged'},_assert_enabled=Mock(),_require_intake=Mock())
        self.outcomes._quality_case=Mock()
        self.base.bridge._driver_outcomes=lambda:self.outcomes
        self.actions=types.ModuleType('cfg_kanban.services.driver_route_actions')
        # Actual stop-selection guard; snapshot generation itself is covered by driver action regressions.
        self.actions.__dict__.update(self.common);load('services/driver_route_actions.py',self.actions.__dict__)
        self.actions._root=lambda name:self.trip
        self.actions._owned=lambda trip,op:None if trip.driver==op.employee else self.f.throw('Wrong driver')
        p=patch.dict(sys.modules,{self.loose.__name__:self.loose,self.planning.__name__:self.planning,
            quantity.__name__:quantity,contents.__name__:contents,identity.__name__:identity,self.outcomes.__name__:self.outcomes,
            self.actions.__name__:self.actions})
        p.start();self.addCleanup(p.stop)
        self.base.bridge.assert_delivery_tag_expiry=lambda *a:None
        self.raw=[dict(dispatch_plan_line='A',source_scan=self.source.handling_unit_id,qty=3),dict(dispatch_plan_line='B',source_scan='TAG2',qty=2)]

    def add(self,dt,name,**values):
        doc=Document(doctype=dt,name=name,flags=Row(),_store=self.data,**values);self.data.setdefault(dt,{})[name]=doc;return doc
    def new_doc(self,values):
        values=dict(values);values['flags']=Row()
        for key in ('lines','items','stops','dispatch_plans'):
            if key in values:values[key]=[Document(v) for v in values[key]]
        return Document(values,_store=self.data)
    def get_doc(self,dt,name=None,**kw):
        if isinstance(dt,dict):return self.new_doc(dt)
        doc=self.data[dt][name]
        if kw.get('for_update'):self.locks.append((dt,name))
        if not isinstance(doc,Document):
            doc=Document(doc);self.data[dt][name]=doc
        return doc
    def matches(self,row,filters):
        for k,v in (filters or {}).items():
            actual=row.get(k)
            if isinstance(v,(list,tuple)):
                op,want=v
                if op=='in' and actual not in want:return False
                if op=='not in' and actual in want:return False
                if op=='!=' and actual==want:return False
                if op=='>' and not float(actual or 0)>want:return False
            elif actual!=v:return False
        return True
    def get_all(self,dt,filters=None,fields=None,pluck=None,**kw):
        rows=[d for d in self.data.get(dt,{}).values() if self.matches(d,filters)]
        if pluck:return [d.get(pluck) for d in rows]
        return [Row({f:d.get(f) for f in fields}) if fields and fields!=['*'] else d for d in rows]
    def get_values(self,dt,filters=None,fieldname=None,**kw):return self.get_all(dt,filters,fieldname or kw.pop('fields',None),**kw)
    def get_value(self,dt,name,fields='name',**kw):
        if dt=='Item':
            values=Row(is_stock_item=1,has_serial_no=0,has_batch_no=0,stock_uom='Nos')
            if isinstance(fields,list):return Row({f:values.get(f) for f in fields})
            return values.get(fields)
        if dt=='UOM':return 1
        if dt=='Customer':return 0
        if isinstance(name,dict):doc=next((d for d in self.data.get(dt,{}).values() if self.matches(d,name)),None)
        else:doc=self.data.get(dt,{}).get(name)
        if not doc:return None
        if isinstance(fields,(list,tuple)):return Row({f:doc.get(f) for f in fields})
        return doc.get(fields)
    def set_value(self,dt,name,field,value=None,**kw):self.data[dt][name].db_set(field,value)
    def savepoint(self,name):self.saves[name]=(copy.deepcopy(self.data),copy.deepcopy(self.ledgers),len(self.posted),len(self.certificate_calls))
    def rollback(self,save_point=None):
        restored,ledgers,count,certs=self.saves[save_point];self.ledgers=ledgers;del self.posted[count:];del self.certificate_calls[certs:];self.data.clear();self.data.update(restored)
        for table in self.data.values():
            for doc in table.values():doc._store=self.data
    def sql(self,query,params=None,**kw):
        if 'for update' in query:return []
        return self.base.sql(query,params,**kw)
    def resolve(self,value):
        for unit in self.data[HU].values():
            if unit.handling_unit_id==value:return dict(identity_type='Handling Unit',name=unit.name)
        return None
    def post(self,**args):
        key=args['idempotency_key']
        if key in self.ledgers:return self.ledgers[key]
        d=event_deltas(args['event_type'],args['qty'],release_reserved=args.get('release_reserved',False))
        for side in ('source','destination'):
            name=args.get(side+'_handling_unit')
            if name:
                unit=self.data[HU][name]
                balance=apply_balance_delta(unit.current_qty,unit.reserved_qty,qty_delta=d[side+'_qty_delta'],reserved_delta=d[side+'_reserved_delta'])
                unit.update(current_qty=balance[0],reserved_qty=balance[1],available_qty=balance[2])
        self.posted.append(args);doc=Row(name='LEDGER-'+str(len(self.posted)));self.ledgers[key]=doc;return doc
    def create(self,**kwargs):return self.loose.create_loose_tag('PLAN',kwargs.pop('lines',self.raw),kwargs.pop('event_token','PACK'),'TOKEN',**kwargs)
    def pack(self):return next(iter(self.data[PACK].values()))
    def load_pack(self):
        pack=self.pack();self.plan.update(state='Loaded',vehicle_warehouse='LORRY1',movement_manifest=self.base.manifest.name,
            total_loaded_qty=5,prepared_stock_commitment=1)
        self.plan.lines[0].loaded_qty=3;self.plan.lines[1].loaded_qty=2
        # Actual E3 current-identity and loading checks precede simulated native ERP transfer feedback.
        self.plan.state='Ready for Vehicle';self.planning._assert_e3_allocations_ready(self.plan)
        self.plan.state='Loading'
        self.base.manifest.update(state='Draft',dispatch_plan='PLAN')
        for row in pack.lines:
            a=self.data[ALLOC][row.dispatch_allocation];a.update(manifest_line=row.name,movement_manifest=self.base.manifest.name)
            self.data['CFG Kanban Manifest Line'][row.name]=Document(name=row.name)
        self.planning.confirm_plan_tag_loaded(self.base.manifest.name,pack.qr_payload,'LOAD','TOKEN')
        for row in pack.lines:
            a=self.data[ALLOC][row.dispatch_allocation];a.state='Loaded'
            u=self.data[HU][row.handling_unit];self.post(event_type='Unreserve',qty=row.qty,stock_uom=row.stock_uom,
                source_handling_unit=u.name,idempotency_key='LOAD-RELEASE-'+row.name)
            u.update(current_warehouse='LORRY1',movement_state='Received')
        self.plan.state='Loaded';self.base.manifest.state='Received'
        self.trip.driver_route_state='In Progress'
        return pack
    def scan(self,stop='STOP'):return self.loose.scan_loose_tag('TRIP',stop,self.pack().qr_payload,'TOKEN')


class TestLooseTags(LooseTagFixture):
    def test_two_skus_one_qr_split_and_reserve_exact_source_quantities(self):
        result=self.create();self.assertTrue(result['qr_payload'].startswith('CFG:LOOSE:'))
        self.assertEqual(len(result['lines']),2);self.assertEqual([r['qty'] for r in result['lines']],[3,2])
        self.assertEqual((self.source.current_qty,self.source2.current_qty),(7,6))
        self.assertEqual(len(self.data[ALLOC]),2)
        for r in self.pack().lines:
            unit=self.data[HU][r.handling_unit]
            self.assertEqual(unit.current_qty,unit.reserved_qty);self.assertEqual(unit.available_qty,0)
            self.assertEqual(unit.origin_reference_name,r.source_handling_unit)
            self.assertEqual(unit.process_certificate_set,'CERT');self.assertEqual(unit.expiry_date,'2027-01-31')
        self.assertEqual(len(self.certificate_calls),2)
    def test_retry_after_lost_response_and_processed_state_does_not_split_twice(self):
        first=self.create();count=len(self.posted);self.create();self.assertEqual(len(self.posted),count)
        self.plan.state='Loaded';self.pack().state='Processed';self.trip.state='Closed'
        self.assertEqual(self.create()['name'],first['name']);self.assertEqual(len(self.data[PACK]),1)
        with self.assertRaisesRegex(ValueError,'different packed'):self.create(lines=[dict(self.raw[0],qty=2),self.raw[1]])
    def test_overallocation_duplicate_source_invalid_uom_and_foreign_scope_are_rejected(self):
        for lines in ([dict(self.raw[0],qty=4),self.raw[1]],[self.raw[0],self.raw[0]],[dict(self.raw[0],qty=1.5),self.raw[1]]):
            with self.assertRaises(ValueError):self.create(lines=lines)
        self.assertFalse(self.posted)
        self.source.inventory_company='FOREIGN'
        with self.assertRaises(ValueError):self.create()
    def test_wrong_stop_and_duplicate_scan_cannot_move_stock(self):
        self.create();self.load_pack();n=len(self.posted)
        with self.assertRaises(ValueError):self.scan('OTHER')
        self.assertEqual(self.pack().state,'Ready')
        self.scan();self.scan();self.assertEqual(self.pack().state,'Scanned');self.assertEqual(len(self.posted),n)
    def test_cancel_before_delivery_releases_and_restores_source_then_voids_qr(self):
        self.create();result=self.loose.cancel_loose_tag(self.pack().qr_payload,'Packing corrected','CANCEL','TOKEN')
        self.assertEqual(result['state'],'Cancelled');self.assertEqual((self.source.current_qty,self.source2.current_qty),(10,8))
        self.assertTrue(all(r.state=='Released' for r in self.data[ALLOC].values()))
        n=len(self.posted);self.loose.cancel_loose_tag(self.pack().qr_payload,'Packing corrected','CANCEL','TOKEN')
        self.assertEqual(len(self.posted),n)
        with self.assertRaises(ValueError):self.loose.stock_codes(self.pack().qr_payload)
    def test_native_plan_cancellation_unpacks_and_individual_release_is_blocked(self):
        self.create();row=self.pack().lines[0]
        with self.assertRaisesRegex(ValueError,'Cancel the unused'):self.planning.release_dispatch_allocation(row.dispatch_allocation,'x','REL','TOKEN')
        self.planning._cancel_unposted_plan(self.plan,self.op,self.session,'No delivery','CANCEL')
        self.assertEqual(self.pack().state,'Cancelled');self.assertEqual(self.source.current_qty,10)
    def test_loaded_pack_cannot_be_merged_into_original_warehouse(self):
        self.create();self.load_pack()
        with self.assertRaisesRegex(ValueError,'before vehicle claim'):self.loose.cancel_loose_tag(self.pack().qr_payload,'x','CANCEL','TOKEN')
    def test_stock_scan_group_keeps_both_lines_for_existing_recovery_and_count(self):
        self.create();self.load_pack();seen=[]
        self.loose.scan_group(self.pack().qr_payload,lambda code:seen.append(code))
        self.assertEqual(len(seen),2)
        self.data[HU][self.pack().lines[0].handling_unit].current_qty=0
        self.assertEqual(len(self.loose.stock_codes(self.pack().qr_payload)),1)
    def test_void_unknown_request_prevents_a_late_original_create(self):
        result=self.loose.void_packing_request('PLAN',self.raw,'PACK','Operator abandoned','TOKEN')
        self.assertEqual(result['state'],'Cancelled');self.assertEqual(self.create()['state'],'Cancelled');self.assertFalse(self.posted)
    def test_readback_is_exact_and_does_not_lose_authorization(self):
        self.create();self.assertTrue(self.loose.read_packing_request('PLAN',self.raw,'PACK','TOKEN')['recorded'])
        with self.assertRaisesRegex(ValueError,'different packed'):self.loose.read_packing_request('PLAN',[dict(self.raw[0],qty=2)],'PACK','TOKEN')
        self.trip._denied=True
        with self.assertRaises(PermissionError):self.create()
    def test_rollback_after_second_reservation_failure_preserves_all_stock_and_history(self):
        original=self.planning.reserve_dispatch_tag;count=0
        def fail(*a,**k):
            nonlocal count
            count+=1
            if count==2:raise ValueError('Injected reservation failure')
            return original(*a,**k)
        self.planning.reserve_dispatch_tag=fail
        with self.assertRaisesRegex(ValueError,'Injected'):self.create()
        self.assertFalse(self.data.get(PACK));self.assertFalse(self.data[ALLOC]);self.assertFalse(self.posted);self.assertFalse(self.ledgers)
        self.assertEqual(self.data[HU][self.source.name].current_qty,10)
    def test_scan_required_before_native_delivery_and_two_sku_dn_uses_posting_feedback(self):
        self.create();self.load_pack()
        with self.assertRaisesRegex(ValueError,'Scan every assigned'):self.base.start()
        self.scan();self.base.start();self.base.confirm();note=self.base.note()
        self.assertEqual([r.qty for r in note.items],[3,2]);self.assertEqual(len(self.data[HU]),4)
        self.assertTrue(all(self.data[HU][r.handling_unit].current_qty==r.qty for r in self.pack().lines))
        self.base.feedback._on_customer_delivery_submit(note,self.base.delivery().name)
        self.assertEqual(self.pack().state,'Processed');self.assertEqual(self.pack().delivery_note,'DN')
        self.assertTrue(all(self.data[HU][r.handling_unit].current_qty==0 for r in self.pack().lines))
        n=len(self.posted);self.base.feedback._on_customer_delivery_submit(note,self.base.delivery().name);self.assertEqual(len(self.posted),n)
    def test_partial_refusal_one_line_uses_existing_outcome_and_no_duplicate_receipt(self):
        self.create();self.load_pack();self.scan()
        submitted=[dict(dispatch_allocation=r.dispatch_allocation,accepted_qty=r.qty-(1 if r.item_code=='ITEM2' else 0),
            refusal_reason='Customer downsized' if r.item_code=='ITEM2' else '',condition='Good / Unwanted') for r in self.pack().lines]
        self.outcomes.declare(self.trip,self.trip.stops[0],self.plan,submitted,self.op,self.session,'REFUSAL')
        self.base.start();self.base.confirm();note=self.base.note();self.assertEqual([r.qty for r in note.items],[3,1])
        self.base.feedback._on_customer_delivery_submit(note,self.base.delivery().name)
        residual=self.data[HU][self.pack().lines[1].handling_unit]
        self.assertEqual((residual.current_qty,residual.reserved_qty),(1,1))
        self.assertEqual(self.pack().state,'Processed');self.assertEqual(len(self.loose.stock_codes(self.pack().qr_payload)),1)
        self.assertFalse(self.data.get('CFG Kanban Return Case'));self.outcomes._quality_case.assert_not_called()
    def test_internal_fill_cannot_be_created_by_user_or_claim_another_line(self):
        self.create();fill=self.data[HU][self.pack().lines[0].handling_unit]
        with self.assertRaisesRegex(ValueError,'controlled packing'):self.loose.validate_internal_fill(fill)
    def test_shared_open_route_requires_explicit_stop_and_filters_packed_sources(self):
        self.plan.update(plan_type='Open Route Stock',office_stop_key=None,customer=None,customer_site=None)
        self.trip.open_route_plan='PLAN';self.trip.stops[0].stop_purpose='Visit Only';self.trip.stops[1].stop_purpose='Visit Only'
        context=self.loose.packing_context('PLAN','TOKEN');self.assertEqual(len(context['stops']),2)
        with self.assertRaises(ValueError):self.create()
        self.create(stop_key='STOP');self.assertEqual(self.pack().customer,'CUSTOMER')
        self.load_pack();context=self.loose.open_context(self.plan,'STOP');self.assertEqual(len(context['quantities']),2)
        self.assertFalse(self.loose.open_context(self.plan,'OTHER'))

    def open_environment(self):
        self.plan.update(plan_type='Open Route Stock',office_stop_key=None,customer=None,customer_site=None,route_stock_commitment=1)
        self.trip.open_route_plan='PLAN';self.trip.stops[0].stop_purpose='Visit Only'
        self.create(stop_key='STOP');self.load_pack()
        native=self.add('CFG Kanban Route Stop','RSTOP',dispatch_plan='PLAN',office_delivery_trip='TRIP',office_stop_key='STOP',
            customer='CUSTOMER',customer_scan_point='SITE',customer_address='ADDR',planned_sequence=1,state='Planned')
        route=types.ModuleType('cfg_kanban.services.route_delivery');route.__dict__.update(self.common);load('services/route_delivery.py',route.__dict__)
        route._planning=lambda:self.planning;route._engine=lambda:self.base.engine;route._fulfilment=lambda:self.base.bridge
        sales=types.ModuleType('cfg_kanban.services.trip_sales')
        sales.lock_scope=lambda p:self.trip;sales.authorize=lambda *a,**kw:(self.trip,self.trip.stops[0],native);sales.assert_delivery_scope=lambda d:None
        def begin(trip,stop,scan,key,operator,token):
            created=self.base.engine._start_delivery_session(self.base.site,'LORRY1',key,self.op,self.session,
                snapshots=dict(dispatch_plan='PLAN',route_stop='RSTOP',proof_policy='Required',auto_submit_delivery_note=1))
            native.delivery_session=created.name;self.plan.active_route_stop='RSTOP';trip.driver_active_stop_key='STOP'
            return self.base.engine.get_delivery_session(created.name,token)
        sales.begin=begin;sales.visit=lambda *a,**k:native
        p=patch.dict(sys.modules,{route.__name__:route,sales.__name__:sales});p.start();self.addCleanup(p.stop)
        original=self.base.engine.resolve_logistics_scan
        self.base.engine.resolve_logistics_scan=lambda value:self.resolve(value) or original(value)
        self.scan()
        return route,native

    def open_deliver(self,refused=False,condition='Good / Unwanted'):
        route,native=self.open_environment()
        values=dict(customer_scan='SITE-QR',quantities=[dict(dispatch_allocation=r.dispatch_allocation,
            accepted_qty=r.qty-(1 if refused and r.item_code=='ITEM2' else 0),
            refusal_reason='Rejected bag' if refused and r.item_code=='ITEM2' else '',condition=condition) for r in self.pack().lines])
        result=self.loose.begin_open_packs(self.trip,self.trip.stops[0],self.plan,values,'OPEN',self.op,self.session,'TOKEN')
        delivery=self.data[SESSION][result['name']]
        self.plan.delivery_session=delivery.name  # Fixture helpers only; native shared pool never uses this field.
        self.base.confirm();note=self.base.note()
        self.base.feedback._on_customer_delivery_submit(note,delivery.name)
        return result,delivery,note

    def test_open_route_pack_delivers_two_skus_via_native_route_allocation_dn_and_feedback(self):
        result,delivery,note=self.open_deliver()
        self.assertEqual([r.qty for r in note.items],[3,2]);self.assertEqual(self.pack().state,'Processed')
        self.assertTrue(all(r.route_stop=='RSTOP' and r.route_source_kind=='Prepared Route Stock' for r in self.data[DA].values()))
        n=len(self.posted);self.base.feedback._on_customer_delivery_submit(note,delivery.name);self.assertEqual(len(self.posted),n)

    def test_open_route_partial_refusal_stays_on_lorry_in_existing_hold_workflow(self):
        result,delivery,note=self.open_deliver(refused=True)
        self.assertEqual([r.qty for r in note.items],[3,1]);self.assertEqual(self.pack().state,'Processed')
        residual=self.data[HU][self.pack().lines[1].handling_unit]
        self.assertEqual((residual.current_qty,residual.reserved_qty),(1,1))
        self.assertEqual(self.outcomes.outcome_for(delivery).customer,'CUSTOMER')
        self.assertFalse(self.data.get('CFG Kanban Return Case'))
        projected=self.loose.project_open_sources(self.plan,'STOP',delivery)
        self.assertEqual(len(projected),2);self.assertEqual(projected[1]['refused_qty'],1)
        self.assertEqual(projected[1]['refusal_outcome'],delivery.driver_delivery_outcome)

    def test_open_route_pack_cannot_be_selected_at_another_stop_or_as_separate_internal_lines(self):
        route,native=self.open_environment()
        created=self.base.engine._start_delivery_session(self.base.site,'LORRY1','BYPASS',self.op,self.session,
            snapshots=dict(dispatch_plan='PLAN',route_stop='RSTOP',proof_policy='Required'))
        native.delivery_session=created.name
        unit=self.data[HU][self.pack().lines[0].handling_unit]
        with self.assertRaisesRegex(ValueError,'complete Loose Tag'):route._unit_choice(unit,created,self.plan)
        native.office_stop_key='OTHER'
        with self.assertRaisesRegex(ValueError,'another customer'):route._unit_choice(unit,created,self.plan)

    def test_full_refusal_known_customer_closes_without_delivery_note(self):
        self.create();self.load_pack();self.scan()
        submitted=[dict(dispatch_allocation=r.dispatch_allocation,accepted_qty=0,refusal_reason='No sale',condition='Good / Unwanted') for r in self.pack().lines]
        self.outcomes.declare(self.trip,self.trip.stops[0],self.plan,submitted,self.op,self.session,'ALL-REFUSED')
        self.base.start();delivery=self.base.delivery()
        self.assertEqual(delivery.state,'Closed');self.assertFalse(delivery.delivery_note)
        self.assertEqual(self.pack().state,'Processed');self.assertTrue(self.outcomes.full_refusal(delivery))

    def test_full_refusal_open_route_uses_existing_closed_session_without_a_fake_dn(self):
        route,native=self.open_environment()
        values=dict(quantities=[dict(dispatch_allocation=r.dispatch_allocation,accepted_qty=0,refusal_reason='No sale',condition='Good / Unwanted') for r in self.pack().lines])
        result=self.loose.begin_open_packs(self.trip,self.trip.stops[0],self.plan,values,'ALL-REFUSED',self.op,self.session,'TOKEN')
        delivery=self.data[SESSION][result['name']]
        self.assertEqual(delivery.state,'Closed');self.assertFalse(delivery.delivery_note)
        self.assertEqual(self.pack().state,'Processed');self.assertTrue(self.outcomes.full_refusal(delivery))
        self.assertFalse(self.data.get(DA))

    def test_source_change_during_unpacked_correction_rolls_back_both_lines(self):
        self.create();self.source2.current_warehouse='MOVED'
        with self.assertRaisesRegex(ValueError,'Original source changed'):
            self.loose.cancel_loose_tag(self.pack().qr_payload,'Correcting','CANCEL','TOKEN')
        self.assertEqual(self.pack().state,'Ready')
        self.assertTrue(all(a.state=='Reserved' for a in self.data[ALLOC].values()))
        self.assertTrue(all(self.data[HU][r.handling_unit].current_qty==r.qty for r in self.pack().lines))
        self.assertFalse(any(r['event_type']=='Merge' for r in self.posted))

    def test_internal_fill_checks_its_exact_persisted_line(self):
        self.create();pack=self.pack();fill=self.data[HU][pack.lines[0].handling_unit]
        pack.state='Building';self.f.flags.cfg_creating_loose_tag=pack.name
        self.loose.validate_internal_fill(fill)
        fill.item_code='OTHER'
        with self.assertRaisesRegex(ValueError,'exact controlled'):self.loose.validate_internal_fill(fill)

    def test_open_route_refusal_is_in_existing_e5_balance_and_recovery_hold_controls(self):
        result,delivery,note=self.open_deliver(refused=True)
        self.plan.delivery_session=None  # Restore native shared-pool shape after fixture-only helpers.
        recovery=types.ModuleType('recovery_subject');recovery.__dict__.update(self.common);load('services/dispatch_recovery.py',recovery.__dict__)
        review=types.ModuleType('review_subject');review.__dict__.update(self.common);load('services/dispatch_reconciliation.py',review.__dict__)
        review._fulfilment=lambda:self.base.bridge
        unit=self.data[HU][self.pack().lines[1].handling_unit]
        self.assertEqual(recovery._refused_reserve(self.plan,unit.name),1)
        self.assertEqual(review._refusal_reserve(self.plan,dict(handling_unit=unit.name)),1)
        balances=review._balances(self.plan)
        self.assertEqual(next(r for r in balances if r['item_code']=='ITEM2')['remaining_qty'],1)
        row=self.pack().lines[1]
        manifest=Document(name='RECOVERY',source_warehouse='LORRY1',destination_warehouse='SOURCE',lines=[Document(dispatch_allocation=row.dispatch_allocation)])
        self.outcomes.recovery_adopt(manifest)
        self.assertEqual(unit.reserved_qty,0)
        unit.current_warehouse='SOURCE'  # Native transfer feedback is tested by the recovery regression fixtures.
        self.outcomes.recovery_restore(manifest,received=True)
        self.assertEqual(unit.reserved_qty,1)
        held=self.outcomes.held_rows({'dispatch_allocation':row.dispatch_allocation})
        self.assertEqual(held[0].stock_state,'Transferred Hold');self.assertEqual(held[0].current_warehouse,'SOURCE')

    def test_visit_cancellation_cannot_orphan_assigned_boxes(self):
        self.plan.update(plan_type='Open Route Stock',office_stop_key=None,customer=None,customer_site=None)
        self.trip.open_route_plan='PLAN';self.trip.stops[0].stop_purpose='Visit Only'
        self.create(stop_key='STOP')
        with self.assertRaisesRegex(ValueError,'Cancel unused packs'):
            self.loose.assert_visit_cancellation_ready(self.plan,'STOP')
        self.loose.cancel_loose_tag(self.pack().qr_payload,'Visit cancelled','CANCEL','TOKEN')
        self.loose.assert_visit_cancellation_ready(self.plan,'STOP')

    def test_plan_flag_cannot_be_edited_to_bypass_the_pack_scan_gate(self):
        namespace=load('cfg_kanban/doctype/cfg_kanban_dispatch_plan/cfg_kanban_dispatch_plan.py',
            dict(self.common,Document=Document,hashlib=hashlib))
        controller=namespace['CFGKanbanDispatchPlan']
        doc=controller(self.plan.as_dict());doc.has_loose_tags=0
        doc.is_new=lambda:False
        # Use a separate immutable before image without duplicate dict keyword handling.
        before=Document(self.plan.as_dict());before.has_loose_tags=1
        doc.get_doc_before_save=lambda:before
        with self.assertRaisesRegex(ValueError,'tracking is controlled'):doc.validate()

    def test_loose_qr_namespace_cannot_be_activated_as_an_ordinary_stock_identity(self):
        namespace=load('services/logistics_foundation.py',dict(self.common))
        for kind in ('Handling Unit','Tag Identity','Customer Scan Point'):
            with self.assertRaisesRegex(ValueError,'reserved for controlled'):
                namespace['validate_physical_code_namespace']('CFG:LOOSE:KLT-1',kind)

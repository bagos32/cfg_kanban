"""E4A actual bridge, reservation, payload and feedback functions with offline stores."""
import ast
import datetime
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_dispatch_e3_behavior as e3_fixture
Doc, Row = e3_fixture.Doc, e3_fixture.Row
PLAN, ALLOC, MANIFEST, HU = e3_fixture.PLAN, e3_fixture.ALLOC, e3_fixture.MANIFEST, e3_fixture.HU
from cfg_kanban.services.handling_unit_math import event_deltas, apply_balance_delta

ROOT=Path(__file__).resolve().parents[1]
SESSION='CFG Kanban Delivery Session'
DA='CFG Kanban Delivery Allocation'

class Record(Doc):
    def __getattribute__(self,name):
        if not name.startswith('__') and dict.__contains__(self,name):return dict.__getitem__(self,name)
        return super().__getattribute__(name)
    def as_dict(self):
        def clean(value):
            if isinstance(value,dict):return {k:clean(v) for k,v in dict.items(value) if k!='_store'}
            if isinstance(value,list):return [clean(v) for v in value]
            return value
        return clean(self)
    def set_missing_values(self):
        for i,row in enumerate(self.get('items') or [],1):
            row.setdefault('name',f'DN-ROW-{i}');row.setdefault('stock_uom',row.get('uom'));row.setdefault('stock_qty',row.get('qty')*(row.get('conversion_factor') or 1))
    def insert(self,**kwargs):
        super().insert(**kwargs)
        return self

def extract(path,namespace,names=None):
    body=[]
    for node in ast.parse((ROOT/path).read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and (names is None or node.name in names):
            node.decorator_list=[];body.append(node)
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)

class TestDispatchFulfilment(unittest.TestCase):
    def setUp(self):
        self.e3=e3_fixture.TestDispatchE3Behavior();self.e3.setUp();self.e3.claim();self.e3.load()
        self.e3.fn['mark_plan_loaded'](self.e3.manifest().name,'STE')
        self.e3.matches=self.matches
        self.data=self.e3.data;self.plan=self.e3.plan;self.unit=self.e3.unit;self.manifest=self.e3.manifest()
        self.manifest.update(state='Received',dispatch_stock_entry='STE',source_company='B',source_warehouse='SOURCE',destination_company='B',destination_warehouse='LORRY1')
        self.plan.update(plan_type='Customer Order',customer_site='SITE',customer='CUSTOMER',customer_address='ADDR',proof_policy='Inherit Customer Site',
            profile_snapshot_json=json.dumps({'auto_submit_delivery_note':1}),sales_order=None)
        self.unit.update(identity_state='Active',quality_state='Released',movement_state='Received',
            current_warehouse='LORRY1',reserved_qty=0,available_qty=5)
        self.operator=self.e3.operator;self.operator.responsibilities.append(Row(responsibility='Customer Delivery'))
        self.site=self.add('CFG Kanban Customer Scan Point','SITE',active=1,site_code='SITE-QR',site_name='Customer Site',
            selling_company='B',customer='CUSTOMER',customer_address='ADDR',default_price_list='SELL',
            proof_policy='Required',auto_submit_delivery_note=0,require_recipient_name=1,doctype='CFG Kanban Customer Scan Point')
        self.add('Stock Entry','STE',docstatus=1,company='B')
        self.erp_balance=11;self.posted=[];self.sql_calls=[]
        self.frappe=Row(_dict=Row,parse_json=json.loads,as_json=json.dumps,
            get_doc=self.get_doc,get_all=self.e3.get_all,PermissionError=PermissionError,DuplicateEntryError=KeyError,
            throw=lambda msg,*args:(_ for _ in ()).throw(ValueError(msg)),
            db=Row(get_value=self.get_value,get_values=self.get_values,set_value=self.e3.set_value,exists=self.exists,sql=self.sql,
                   get_single_value=lambda *args:'SELL'))
        common=dict(frappe=self.frappe,json=json,flt=lambda n:float(n or 0),cint=lambda n:int(n or 0),
            getdate=lambda value:datetime.date.fromisoformat(str(value)[:10]),today=lambda:'2026-11-19',
            now_datetime=lambda:datetime.datetime(2026,11,19,12),_=lambda text:text,
            canonical_key=self.e3.fn['canonical_key'],record=self.e3.events,
            require_operator=Mock(return_value=(self.operator,self.e3.session)))
        self.planning=types.ModuleType('cfg_kanban.services.dispatch_planning');self.planning.__dict__.update(self.e3.fn)
        self.planning.__dict__.update(common);self.planning.validate_warehouse_company=Mock();self.planning._validate_batch=Mock()
        extract('services/dispatch_planning.py',self.planning.__dict__,{'_untagged_available','_assert_untagged_allocation_available','_lock_erp_bin'})
        self.engine=types.ModuleType('cfg_kanban.services.customer_delivery');self.engine.__dict__.update(common)
        self.engine.__dict__.update(CUSTOMER_DELIVERY_RESPONSIBILITY='Customer Delivery',
            DELIVERY_TERMINAL_STATES={'Invoiced','Closed','Rejected','Cancelled'},ACTIVE_ALLOCATION_STATES=('Reserved','Delivery Pending','Exception'),
            validate_price_list_mode=Mock(),price_list_rate=lambda *args:2,
            resolve_logistics_scan=lambda value:({'identity_type':'Customer Scan Point','name':'SITE'} if value=='SITE-QR' else
                                                {'identity_type':'Customer Scan Point','name':'OTHER'} if value=='OTHER-SITE' else None),
            active_container_membership=lambda name:None,active_container_contents=lambda name:[],
            post_quantity_event=self.post_quantity,assert_erp_stock=Mock())
        extract('services/customer_delivery.py',self.engine.__dict__,{'_start_delivery_session','get_delivery_session','_reserve_unit',
            '_validate_allocation_unit','_require_customer_delivery','_customer_delivery_allowed','_can_view_all','_can_view_delivery',
            '_delivery_for_operator','_validate_confirmed_container_groups','confirm_delivery_allocations','_customer_delivery_payload',
            '_release_allocation_row','release_delivery_allocation','cancel_delivery_session','_assert_allocation_session','get_delivery_allocation_candidate'})
        self.engine._assert_not_in_open_manifest=Mock()
        self.engine._vehicle_warehouse=lambda wh,company:Row(name=wh,vehicle_reference='VEHICLE1')
        self.engine._resolve_customer_site=lambda scan:self.site if scan=='SITE-QR' else (_ for _ in ()).throw(ValueError('Wrong site scan'))
        self.bridge=types.ModuleType('cfg_kanban.services.dispatch_fulfilment');self.bridge.__dict__.update(common)
        extract('services/dispatch_fulfilment.py',self.bridge.__dict__)
        self.bridge._delivery_services=lambda:self.engine;self.bridge._planning_services=lambda:self.planning
        self.bridge.assert_delivery_tag_expiry=Mock()
        self.feedback=types.ModuleType('cfg_kanban.integrations.logistics_feedback');self.feedback.__dict__.update(common)
        self.feedback.post_quantity_event=self.post_quantity
        extract('integrations/logistics_feedback.py',self.feedback.__dict__,{'_on_customer_delivery_submit','_on_customer_delivery_cancel',
            '_validate_customer_delivery_header','_validate_customer_delivery_rows','_assert_customer_delivery_reversal_is_safe'})
        self.feedback._resolve_delivery_exception=Mock();self.feedback._unload_customer_container=Mock();self.feedback._restore_customer_container=Mock()
        self.feedback._raise_delivery_cancel_exception=lambda *args:None
        self.feedback._customer_delivery_cancel_exception=lambda *args:None
        self.feedback._delivery_exception=Mock(return_value=Row(name='EXCEPTION'))
        # Cancellation creates a persistent Exception; its record contents are outside this fixture.
        self.gateway=dict(common,_tag_stock_identity_fields=lambda name,dt:({'process_certificate_set':'CERT'} if name else {}),
                          apply_required_erp_inputs=Mock(),get_required_erp_inputs=lambda doc:[])
        extract('integrations/erp_gateway.py',self.gateway,{'build_customer_delivery_note'})
        stock=types.ModuleType('erpnext.stock.utils');stock.get_stock_balance=lambda *args,**kwargs:self.erp_balance
        batch=types.ModuleType('erpnext.stock.doctype.batch.batch');batch.get_batch_qty=lambda batch_no=None,warehouse=None,item_code=None,posting_date=None,posting_time=None,ignore_voucher_nos=None,for_stock_levels=False,consider_negative_batches=False,do_not_check_future_batches=False:self.erp_balance
        self.patch=patch.dict(sys.modules,{self.bridge.__name__:self.bridge,self.engine.__name__:self.engine,
            self.feedback.__name__:self.feedback,'erpnext.stock.utils':stock,'erpnext.stock.doctype.batch.batch':batch})
        self.patch.start();self.addCleanup(self.patch.stop)

    def matches(self,row,filters):
        for key,expected in (filters or {}).items():
            value=row.get(key)
            if isinstance(expected,list):
                op,target=expected
                if op=='in' and value not in target:return False
                if op=='not in' and value in target:return False
                if op=='!=' and value==target:return False
                if op=='<' and not value<target:return False
            elif value!=expected:return False
        return True

    def add(self,dt,name,**values):
        values.setdefault('doctype',dt)
        row=Record(name=name,_store=self.data,**values);self.data.setdefault(dt,{})[name]=row;return row

    def get_doc(self,doctype,name=None,**kwargs):
        if isinstance(doctype,dict):
            values=dict(doctype)
            if 'items' in values:values['items']=[Record(row) for row in values['items']]
            return Record(values,_store=self.data)
        return self.data[doctype][name]

    def get_values(self,doctype,filters=None,fieldname=None,fields=None,**kwargs):
        return self.e3.get_all(doctype,filters=filters)

    def exists(self,dt,filters):return self.get_value(dt,filters,'name')
    def get_value(self,dt,name,fields,**kwargs):
        if dt=='Item':return Row(is_stock_item=1,has_serial_no=0,has_batch_no=0,stock_uom='Nos') if isinstance(fields,list) else 1
        if dt=='Sales Order Item':
            for order in self.data.get('Sales Order',{}).values():
                for row in order.items:
                    if row.name==name:return Row(parent=order.name,uom=row.uom,conversion_factor=row.conversion_factor)
            return None
        if dt=='Customer':return 0
        if dt=='UOM':return 0
        return self.e3.get_value(dt,name,fields,**kwargs)

    def sql(self,query,params=None,**kwargs):
        self.sql_calls.append((query,params))
        if 'for update' in query:return []
        if 'allocation.dispatch_plan' in query and 'allocation.handling_unit=%s' in query:
            rows=[]
            for source in self.data[ALLOC].values():
                plan=self.data[PLAN].get(source.dispatch_plan)
                if not plan or source.handling_unit!=params or source.state!='Loaded':continue
                held=((plan.plan_type=='Customer Order' and plan.prepared_stock_commitment and plan.fulfilment_status not in ('Completed','Delivered')) or
                      (plan.plan_type=='Open Route Stock' and plan.route_stock_commitment))
                used=sum(float(r.allocated_qty) for r in self.data.get(DA,{}).values() if r.dispatch_allocation==source.name and r.state in ('Reserved','Delivery Pending','Exception','Delivered'))
                if held and float(source.allocated_qty)>used+0.000001:rows.append([source.dispatch_plan,plan.plan_type])
            return rows
        if "plan.plan_type='Customer Order'" in query and 'greatest(allocation.allocated_qty' in query:
            value=0
            for row in self.data[ALLOC].values():
                plan=self.data[PLAN].get(row.dispatch_plan)
                if not plan or plan.name==params.get('excluded') or plan.vehicle_warehouse!=params['warehouse']:continue
                held=((plan.plan_type=='Customer Order' and plan.prepared_stock_commitment and plan.fulfilment_status not in ('Completed','Delivered')) or
                      (plan.plan_type=='Open Route Stock' and plan.route_stock_commitment))
                if not held or row.state!='Loaded' or row.allocation_kind!='Untagged ERP Stock' or row.item_code!=params['item']:continue
                used=sum(float(a.allocated_qty) for a in self.data.get(DA,{}).values() if a.dispatch_allocation==row.name and a.state in ('Reserved','Delivery Pending','Exception','Delivered'))
                value+=max(float(row.allocated_qty)-used,0)
            return [[value]]
        if 'sum(delivered_qty)' in query:
            return [[sum(float(r.delivered_qty or 0) for r in self.data.get(DA,{}).values() if r.delivery_session==params and r.state=='Delivered')]]
        if 'sum(allocation.allocated_qty)' in query:
            return [[sum(float(r.allocated_qty) for r in self.data.get(DA,{}).values() if r.allocation_kind=='Untagged ERP Stock' and
                r.state in ('Reserved','Delivery Pending','Exception') and r.item_code==params['item'] and r.source_warehouse==params['warehouse'])]]
        if 'sum(current_qty)' in query:
            return [[sum(float(r.current_qty or 0) for r in self.data.get(HU,{}).values() if r.item_code==params['item'] and r.current_warehouse==params['warehouse'])]]
        if 'sum(allocated_qty)' in query:
            return [[sum(float(r.allocated_qty) for r in self.data.get(ALLOC,{}).values() if r.allocation_kind=='Untagged ERP Stock' and r.state=='Reserved' and r.source_warehouse==params['warehouse'] and r.item_code==params['item'])]]
        return []

    def post_quantity(self,**args):
        self.posted.append(args)
        name=args.get('source_handling_unit') or args.get('destination_handling_unit')
        unit=self.data[HU][name];delta=event_deltas(args['event_type'],args['qty'],release_reserved=args.get('release_reserved',False))
        prefix='source' if args.get('source_handling_unit') else 'destination'
        balance=apply_balance_delta(unit.current_qty,unit.reserved_qty,qty_delta=delta[prefix+'_qty_delta'],reserved_delta=delta[prefix+'_reserved_delta'])
        unit.update(current_qty=balance[0],reserved_qty=balance[1],available_qty=balance[2])
        return Row(name=f'LEDGER-{len(self.posted)}')

    def loose(self,qty=6):
        self.plan.lines[0].loaded_qty=5+qty;self.plan.total_loaded_qty=5+qty
        return self.add(ALLOC,'LOOSE',dispatch_plan='PLAN',dispatch_plan_line='LINE',movement_manifest=self.manifest.name,
            state='Loaded',allocation_kind='Untagged ERP Stock',handling_unit=None,item_code='ITEM',stock_uom='Nos',
            allocated_qty=qty,load_confirmed=1)

    def start(self,token='START',scan='SITE-QR'):
        return self.bridge.start_prepared_delivery('PLAN',scan,token,'SESSION')
    def delivery(self):return self.data[SESSION][self.plan.delivery_session]
    def confirm(self):return self.engine.confirm_delivery_allocations(self.delivery().name,'CONFIRM','SESSION')
    def payload(self):return self.engine._customer_delivery_payload(self.delivery())
    def note(self,payload=None):
        doc=self.gateway['build_customer_delivery_note'](self.delivery(),payload or self.payload())
        doc.name='DN';doc.state='To Bill';return doc

    def test_mixed_loaded_plan_stages_exact_stock_without_fake_tag(self):
        self.loose();result=self.start()
        self.assertEqual(result['state'],'Allocating Stock');self.assertEqual(len(result['allocations']),2)
        self.assertEqual(self.unit.reserved_qty,5);self.assertEqual(len(self.posted),1)
        self.assertEqual(len(self.data[HU]),1);self.assertEqual(self.plan.fulfilment_status,'In Progress')
        loose=next(r for r in result['allocations'] if not r.get('handling_unit'))
        self.assertEqual(loose['allocation_kind'],'Untagged ERP Stock');self.assertEqual(loose['allocated_qty'],6)
        self.assertEqual(self.delivery().auto_submit_delivery_note,1)

    def test_replay_and_reopen_reuse_one_session(self):
        self.loose();first=self.start();self.start();again=self.start('NEW-TOKEN')
        self.assertEqual(first['name'],again['name']);self.assertEqual(len(self.data[SESSION]),1);self.assertEqual(len(self.posted),1)

    def test_other_site_and_operator_cannot_resume(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'Customer Site'):self.start(scan='OTHER-SITE')
        self.operator.employee='OTHER'
        with self.assertRaisesRegex(ValueError,'another Plan or operator'):self.start()

    def test_replay_does_not_depend_on_mutable_stock_or_site_activity(self):
        self.start();self.unit.current_qty=0;self.site.active=0
        self.assertEqual(self.start()['name'],self.delivery().name)

    def test_new_start_rejects_wrong_company_address_and_nonloaded_state(self):
        for field,value in [('company','A'),('customer_address','WRONG'),('state','Ready to Dispatch')]:
            previous=self.plan[field];self.plan[field]=value
            with self.assertRaises(ValueError):self.start()
            self.plan[field]=previous
        self.assertNotIn(SESSION,self.data)

    def test_draft_loading_entry_cannot_start_delivery(self):
        self.data['Stock Entry']['STE'].docstatus=0
        with self.assertRaisesRegex(ValueError,'must be submitted'):self.start()

    def test_missing_loose_balance_rejects_delivery(self):
        self.loose();self.erp_balance=10
        with self.assertRaisesRegex(ValueError,'Untagged lorry stock'):self.start()

    def test_changed_tag_quantity_blocks_delivery(self):
        self.unit.current_qty=4
        with self.assertRaisesRegex(ValueError,'quantity changed'):self.start()

    def test_shared_availability_subtracts_delivery_and_dispatch_reservations(self):
        self.loose();self.start()
        self.assertEqual(self.planning._untagged_available('B','LORRY1','ITEM',None),0)
        self.add(ALLOC,'OTHER',state='Reserved',allocation_kind='Untagged ERP Stock',allocated_qty=1,
                 source_warehouse='LORRY1',source_company='B',item_code='ITEM')
        with self.assertRaisesRegex(ValueError,'require'):
            self.bridge.validate_untagged_delivery_stock(self.delivery(),self.data[DA]['M-2'])

    def test_confirm_and_payload_preserve_mixed_identities(self):
        self.loose();self.start();self.confirm();payload=self.payload()
        self.assertEqual(len(payload['items']),2);self.assertEqual(sum(r['qty'] for r in payload['items']),11)
        self.assertEqual([r['handling_unit'] for r in payload['items']].count(None),1)
        self.assertEqual(self.plan.state,'Loaded');self.assertEqual(self.plan.fulfilment_status,'In Progress')

    def test_delivery_note_builder_keeps_untagged_without_certificate_or_tag(self):
        self.loose();self.start();self.confirm();doc=self.note()
        self.assertEqual(len(doc.items),2)
        loose=next(r for r in doc.items if not r.cfg_handling_unit)
        self.assertIsNone(loose.get('process_certificate_set'));self.assertEqual(loose.qty,6)
        tagged=next(r for r in doc.items if r.cfg_handling_unit)
        self.assertEqual(tagged.process_certificate_set,'CERT')

    def test_actual_submit_feedback_consumes_tag_once_and_waits_for_proof(self):
        self.loose();self.start();self.confirm();doc=self.note();self.delivery().state='ERP Document Pending'
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        self.assertEqual(self.unit.current_qty,0);self.assertEqual(self.unit.reserved_qty,0)
        self.assertEqual(self.delivery().state,'Delivered');self.assertEqual(self.plan.fulfilment_status,'Delivered')
        self.assertEqual(self.plan.total_delivered_qty,11)
        self.assertEqual(sum(r['event_type']=='Deliver' for r in self.posted),1)
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        self.assertEqual(sum(r['event_type']=='Deliver' for r in self.posted),1)

    def test_no_proof_policy_closes_only_after_submit_feedback(self):
        self.plan.proof_policy='No Proof Required';self.start();self.confirm();doc=self.note()
        self.assertEqual(self.plan.fulfilment_status,'In Progress')
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        self.assertEqual(self.plan.fulfilment_status,'Completed');self.assertIsNotNone(self.plan.fulfilment_completed_on)

    def test_partial_release_blocks_confirm_then_empty_cancel_allows_restart(self):
        self.loose();self.start();names=list(self.data[DA])
        self.engine.release_delivery_allocation(names[0],'Restart','REL1','SESSION')
        with self.assertRaisesRegex(ValueError,'Every loaded allocation'):self.confirm()
        self.engine.release_delivery_allocation(names[1],'Restart','REL2','SESSION')
        delivery=self.delivery()
        self.engine.cancel_delivery_session(delivery.name,'Restart','CANCEL','SESSION')
        self.assertIsNone(self.plan.delivery_session);self.assertEqual(self.unit.reserved_qty,0)
        self.start('NEW');self.assertEqual(len(self.data[SESSION]),2)

    def test_before_submit_rejects_changed_quantity_and_price(self):
        self.loose();self.start();self.confirm();doc=self.note()
        self.bridge.validate_prepared_delivery_note(doc)
        doc.items[0].rate=99
        with self.assertRaisesRegex(ValueError,'rate differs'):self.bridge.validate_prepared_delivery_note(doc)
        doc.items[0].rate=2;doc.items[0].stock_qty=99
        with self.assertRaisesRegex(ValueError,'quantity differs'):self.bridge.validate_prepared_delivery_note(doc)

    def test_before_submit_rechecks_missing_untagged_balance(self):
        self.loose();self.start();self.confirm();doc=self.note();self.erp_balance=9
        with self.assertRaisesRegex(ValueError,'require'):self.bridge.validate_prepared_delivery_note(doc)

    def order(self,qty=5,delivered=0,factor=2):
        self.plan.sales_order='SO'
        row=Record(name='SO-ROW',item_code='ITEM',stock_uom='Nos',uom='Box',qty=qty,delivered_qty=delivered,conversion_factor=factor,rate=8)
        return self.add('Sales Order','SO',items=[row],docstatus=1,company='B',customer='CUSTOMER',status='To Deliver',
            project='PROJECT',selling_price_list='SELL',currency='MYR',conversion_rate=1,price_list_currency='MYR',plc_conversion_rate=1)

    def test_sales_order_rows_and_stock_uom_price_are_bound_to_native_note(self):
        self.order();self.start();self.confirm();payload=self.payload();doc=self.note(payload)
        self.assertEqual(payload['items'][0]['rate'],8)
        self.assertEqual(payload['items'][0]['qty'],2.5)
        self.assertEqual(doc.items[0].stock_qty,5)
        self.assertEqual(doc.items[0].against_sales_order,'SO');self.assertEqual(doc.items[0].so_detail,'SO-ROW')
        self.assertEqual(doc.currency,'MYR');self.assertEqual(doc.project,'PROJECT')
        self.bridge.validate_prepared_delivery_note(doc)
        doc.items[0].so_detail='OTHER'
        with self.assertRaisesRegex(ValueError,'Sales Order reference'):self.bridge.validate_prepared_delivery_note(doc)

    def test_sales_order_remaining_is_rechecked_before_note(self):
        order=self.order();self.start();self.confirm();order.items[0].delivered_qty=4
        with self.assertRaisesRegex(ValueError,'remaining stock quantity'):self.payload()

    def test_plan_allocation_link_cannot_be_substituted(self):
        self.start();next(iter(self.data[DA].values())).dispatch_allocation='OTHER'
        with self.assertRaisesRegex(ValueError,'exact prepared load'):self.confirm()

    def test_unassigned_delivery_responsibility_is_rejected(self):
        self.operator.responsibilities=[Row(responsibility='Dispatch')]
        with self.assertRaisesRegex(ValueError,'Customer Delivery'):self.start()

    def test_actual_cancel_restores_tag_reservation_and_keeps_untagged_without_ledger(self):
        self.loose();self.start();self.confirm();doc=self.note()
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        self.feedback._on_customer_delivery_cancel(doc,self.delivery().name)
        self.assertEqual(self.unit.current_qty,5);self.assertEqual(self.unit.reserved_qty,5)
        self.assertEqual(self.delivery().state,'Awaiting Confirmation')
        self.assertEqual(self.plan.total_delivered_qty,0);self.assertEqual(self.plan.fulfilment_status,'In Progress')
        self.assertEqual(sum(row['event_type']=='Customer Return' for row in self.posted),1)
        self.feedback._on_customer_delivery_cancel(doc,self.delivery().name)
        self.assertEqual(sum(row['event_type']=='Customer Return' for row in self.posted),1)

    def test_actual_proof_submission_completes_the_plan(self):
        self.start();self.confirm();doc=self.note()
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        proof=self.add('CFG Kanban Delivery Proof','PROOF',delivery_session=self.delivery().name,state='Draft',
            proof_policy='Required',require_recipient_name=1,require_signature=0,require_photo=0,require_gps=0)
        ns=dict(self.bridge.__dict__,assert_delivery_access=lambda name,profile:self.delivery(),
            _require_responsibility=self.engine._require_customer_delivery,list_reference_media=lambda *a,**kw:[],
            POLICY_DISPOSITIONS={'Required':('Attended',)},get_delivery_proof=lambda *a:proof.as_dict())
        extract('services/delivery_proof.py',ns,{'submit_delivery_proof','_validate_location'})
        ns['submit_delivery_proof']('PROOF','Attended','PROOF-EVENT','SESSION',recipient_name='Receiver')
        self.assertEqual(self.delivery().state,'Closed');self.assertEqual(self.plan.fulfilment_status,'Completed')
        self.assertEqual(self.plan.delivery_proof,'PROOF');self.assertEqual(self.plan.delivery_note,'DN')
        self.data['CFG Kanban Delivery Proof']['PROOF'].state='Submitted'
        with self.assertRaisesRegex(ValueError,'proof was submitted'):
            self.feedback._on_customer_delivery_cancel(doc,self.delivery().name)

    def test_native_currency_float_representation_does_not_reject(self):
        self.order();self.start();self.confirm();doc=self.note()
        doc.conversion_rate=1.0;doc.plc_conversion_rate=1.0
        self.bridge.validate_prepared_delivery_note(doc)
        doc.conversion_rate=2
        with self.assertRaisesRegex(ValueError,'currency context'):
            self.bridge.validate_prepared_delivery_note(doc)

    def test_untagged_only_load_uses_no_quantity_ledger(self):
        self.data[ALLOC].pop('ALLOC');self.unit.current_qty=0;self.unit.available_qty=0
        self.loose(6);self.plan.lines[0].loaded_qty=6;self.erp_balance=6
        self.start();self.confirm();doc=self.note()
        self.feedback._on_customer_delivery_submit(doc,self.delivery().name)
        self.assertEqual(self.posted,[]);self.assertEqual(self.plan.total_delivered_qty,6)

    def test_missing_serial_identity_cannot_be_delivered_as_untagged(self):
        self.loose();original=self.get_value
        def values(dt,name,fields,**kwargs):
            result=original(dt,name,fields,**kwargs)
            if dt=='Item' and isinstance(fields,list):result.has_serial_no=1
            return result
        self.frappe.db.get_value=values
        with self.assertRaisesRegex(ValueError,'non-serialized'):self.start()

    def test_loaded_known_customer_loose_stock_is_not_free_ad_hoc_stock(self):
        self.loose()
        self.assertEqual(self.planning._untagged_available('B','LORRY1','ITEM',None),0)
        self.start();self.assertEqual(self.planning._untagged_available('B','LORRY1','ITEM',None),0)

    def test_loaded_tag_rejects_ad_hoc_customer_allocation(self):
        fake=Row(source_warehouse='LORRY1',selling_company='B')
        with self.assertRaisesRegex(ValueError,'prepared Customer Order'):
            self.engine._validate_allocation_unit(self.unit,fake)

    def test_schema_retains_optional_prepared_links_and_explicit_allocation_kind(self):
        base=ROOT/'cfg_kanban/doctype'
        allocation=json.loads((base/'cfg_kanban_delivery_allocation/cfg_kanban_delivery_allocation.json').read_text())
        fields={row['fieldname']:row for row in allocation['fields']}
        self.assertFalse(fields['handling_unit'].get('reqd'))
        self.assertEqual(fields['allocation_kind']['default'],'Tagged Stock')
        session=json.loads((base/'cfg_kanban_delivery_session/cfg_kanban_delivery_session.json').read_text())
        self.assertTrue(next(f for f in session['fields'] if f['fieldname']=='active_dispatch_plan_key')['unique'])
        self.assertIn('cfg_kanban.patches.v1_8.backfill_delivery_allocation_kind',(ROOT/'patches.txt').read_text())

    def test_wrong_delivery_correction_handles_untagged_native_stock_without_phantom_ledger(self):
        extract('integrations/logistics_feedback.py',self.feedback.__dict__,{'_on_correction_return_submit','_on_correction_return_cancel'})
        line=Record(name='RETURN-ROW',original_delivery_note_item='DN-ROW',claimed_qty=2,stock_uom='Nos',
                    item_code='ITEM',original_handling_unit=None)
        case=self.add('CFG Kanban Return Case','RETURN',return_flow='Delivery Note Correction',
                      original_delivery_note='DN',lines=[line],claimed_total_qty=2)
        note=Record(name='RETURN-DN',return_against='DN',items=[Record(dn_detail='DN-ROW',stock_qty=-2)])
        self.feedback._on_correction_return_submit(note,'RETURN')
        self.assertEqual(case.state,'Delivery Correction Posted');self.assertEqual(self.posted,[])
        self.feedback._on_correction_return_cancel(note,'RETURN');self.assertEqual(self.posted,[])

    def test_currency_or_certificate_tampering_on_untagged_note_is_rejected(self):
        self.loose();self.start();self.confirm();note=self.note()
        next(row for row in note.items if not row.cfg_handling_unit).process_certificate_set='OTHER CERT'
        with self.assertRaisesRegex(ValueError,'certificate identity'):
            self.bridge.validate_prepared_delivery_note(note)

    def test_untagged_batch_is_explicit_in_native_note_and_expired_batch_is_rejected(self):
        self.loose();self.unit.batch_no='BATCH';self.e3.allocation.batch_no='BATCH';self.data[ALLOC]['LOOSE'].batch_no='BATCH'
        batch=self.add('Batch','BATCH',item='ITEM',expiry_date='2027-01-01')
        self.start();self.confirm();note=self.note()
        self.assertEqual(next(r for r in note.items if not r.cfg_handling_unit).use_serial_batch_fields,1)
        self.bridge.validate_prepared_delivery_note(note)
        batch.expiry_date='2026-11-18'
        with self.assertRaisesRegex(ValueError,'expired'):self.payload()

    def test_historical_loaded_plan_does_not_retroactively_commit_already_delivered_stock(self):
        self.loose();self.plan.prepared_stock_commitment=0
        self.assertEqual(self.planning._untagged_available('B','LORRY1','ITEM',None),6)
        self.start();self.assertEqual(self.plan.prepared_stock_commitment,1)
        self.assertEqual(self.planning._untagged_available('B','LORRY1','ITEM',None),0)

if __name__=='__main__':unittest.main()

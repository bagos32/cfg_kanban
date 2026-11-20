"""E5B1 actual recovery/Manifest/feedback functions with dependency doubles.

These checks do not establish MariaDB locking, native ERP submission or floor acceptance.
"""
import ast
import datetime
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_dispatch_reconciliation as e5a
from cfg_kanban.tests import test_dispatch_fulfilment as e4a
from cfg_kanban.tests.test_dispatch_e3_behavior import Row, ALLOC, MANIFEST, HU, MLINE

SERVICE='cfg_kanban.services.dispatch_recovery'


class TestDispatchRecovery(unittest.TestCase):
    def setUp(self):
        self.r=e5a.TestDispatchReconciliation();self.r.setUp();self.addCleanup(self.r.doCleanups)
        self.b,self.plan,self.unit,self.operator=self.r.b,self.r.plan,self.r.unit,self.r.operator
        self.data=self.b.data;self.r.supervisor();self.r.begin()
        self.b.frappe.ValidationError=ValueError
        self.b.frappe.get_doc=self.get_doc
        self.b.frappe.db.get_value=self.get_value
        self.b.frappe.db.sql=self.sql
        self.b.frappe.db.exists=self.exists
        self.b.frappe.get_meta=lambda dt:Row(has_field=lambda field:field in ('process_certificate_set','to_process_certificate_set'))
        self.plan.as_dict=lambda:dict(self.plan)
        self.route=self.b.add('CFG Kanban Logistics Route','RETURN',active=1,route_type='Internal Warehouse Transfer',
            internal_transfer_mode='Direct Transfer',source_company='B',destination_company='B',
            source_warehouse='LORRY1',destination_warehouse='SOURCE',dispatch_responsibility='Dispatch',
            supervisor_responsibility='Dispatch',auto_submit_internal_dispatch=1)
        self.b.add('Warehouse','SOURCE',company='B',disabled=0,is_group=0,cfg_is_vehicle_warehouse=0)
        self.unit.process_certificate_set='CERT';self.unit.expiry_date='2027-04-01'
        common=dict({key:value for key,value in self.r.mod.__dict__.items() if not key.startswith('__')},isfinite=math.isfinite,MANIFEST=MANIFEST,HU=HU,
            ROUTE='CFG Kanban Logistics Route',RECOVERY_ACTIONS=('Returned to Warehouse','Transferred to Another Lorry'),
            DispatchRecoveryReplayError=ValueError,resolve_logistics_scan=self.resolve)
        self.mod=types.ModuleType(SERVICE);self.mod.__dict__.update(common)
        e4a.extract('services/dispatch_recovery.py',self.mod.__dict__)
        self.mod._review_service=lambda:self.r.mod
        self.log=types.ModuleType('cfg_kanban.api.logistics');self.log.__dict__.update(common)
        e4a.extract('api/logistics.py',self.log.__dict__,{'_require_route_responsibility','_responsibilities','_can_view_all',
            '_validate_dispatch_unit','_validate_dispatch_container','_validate_manifest_container_groups',
            '_assert_not_in_other_open_manifest','prepare_manifest','remove_dispatch_tag','scan_dispatch_tag','cancel_manifest'})
        self.log.get_manifest=lambda name,token:self.data[MANIFEST][name].as_dict()
        self.log._assert_erp_stock=self.b.engine.assert_erp_stock
        self.log.post_quantity_event=self.b.post_quantity
        self.log.confirm_dispatch=self.submit
        self.mod._logistics=lambda:self.log
        self.contents=types.ModuleType('cfg_kanban.services.container_contents')
        self.memberships={};self.contents.active_container_membership=lambda name:self.memberships.get(name)
        self.contents.active_container_contents=lambda container:[Row(content_handling_unit=name) for name,row in self.memberships.items() if row.container_handling_unit==container]
        self.contents.assert_not_loaded_in_container=lambda name,*args: (_ for _ in ()).throw(ValueError('Scan the physical container')) if name in self.memberships else None
        self.contents.assert_container_not_in_open_delivery=Mock()
        self.mod._contents=lambda:self.contents
        self.identity=types.ModuleType('cfg_kanban.services.logistics_stock_identity');self.identity.__dict__.update(common)
        self.identity.IDENTITY_FIELDS=('item_code','batch_no','stock_uom','process_certificate_set','expiry_date','packed_on','short_description','work_order','current_operation','kanban_cycle','kanban_card')
        self.identity.certificate_output_evidence=lambda *args:[];self.identity.printed_expiry_dates=lambda evidence:[]
        e4a.extract('services/logistics_stock_identity.py',self.identity.__dict__,{'_json','_serials','identity_snapshot','capture_manifest_line','validate_saved_manifest_fields','_expiry','_line_identity','erp_identity_fields','validate_logistics_document'})
        self.feedback=self.b.feedback
        e4a.extract('integrations/logistics_feedback.py',self.feedback.__dict__,{'_post_internal_direct','_unreserve_manifest_line','_post_tag_location','_finish_internal_line','_update_manifest_containers','validate_internal_stock_entry'})
        transfer=types.ModuleType('cfg_kanban.services.internal_transfer');transfer.complete_transfer_cycle=Mock()
        patcher=patch.dict(sys.modules,{SERVICE:self.mod,'cfg_kanban.services.dispatch_reconciliation':self.r.mod,
            'cfg_kanban.services.container_contents':self.contents,self.identity.__name__:self.identity,
            transfer.__name__:transfer,'cfg_kanban.services.route_reconciliation':self.r.counts})
        patcher.start();self.addCleanup(patcher.stop)
        self.gateway=dict(common,apply_required_erp_inputs=Mock())
        e4a.extract('integrations/erp_gateway.py',self.gateway,{'build_internal_transfer_stock_entry'})
        tree=ast.parse((e4a.ROOT/'cfg_kanban/doctype/cfg_kanban_movement_manifest/cfg_kanban_movement_manifest.py').read_text())
        klass=next(node for node in tree.body if isinstance(node,ast.ClassDef))
        ns=dict(common,Document=e4a.Record)
        exec(compile(ast.Module(body=[klass],type_ignores=[]),'manifest_controller.py','exec'),ns)
        self.controller=ns[klass.name]
        self.saved_entries=[]

    def resolve(self,value):
        unit=next((row for row in self.data[HU].values() if row.handling_unit_id==value),None)
        return dict(identity_type='Handling Unit',name=unit.name) if unit else None

    def get_doc(self,doctype,name=None,**kwargs):
        if not isinstance(doctype,dict):return self.data[doctype][name]
        outer=self
        class Document(outer.controller):
            def set(self,key,value):self[key]=value
            def is_new(self):return not self.name
            def get_doc_before_save(self):return None
            def insert(self,**kwargs):
                if self.doctype==MANIFEST:
                    outer.controller.before_insert(self);outer.controller.validate(self)
                return super().insert(**kwargs)
            def save(self,**kwargs):
                if self.doctype==MANIFEST:outer.controller.validate(self)
                return self
        values=dict(doctype)
        for field in ('lines','items'):
            if field in values:values[field]=[e4a.Record(row) for row in values[field]]
        return Document(values,_store=self.data)

    def get_value(self,dt,name,fields,**kwargs):
        if dt=='Item':
            item=Row(is_stock_item=1,has_serial_no=0,has_batch_no=int(name=='BATCHED'),stock_uom='Nos')
            return item if isinstance(fields,list) else item.get(fields)
        return self.b.get_value(dt,name,fields,**kwargs)

    def exists(self,dt,filters):
        if dt==HU and isinstance(filters,dict) and filters.get('process_certificate_set')==['is','set']:
            filters={key:value for key,value in filters.items() if key!='process_certificate_set'}
            return next((row.name for row in self.data[HU].values() if row.get('process_certificate_set') and self.b.matches(row,filters)),None)
        return self.b.exists(dt,filters)

    def sql(self,query,params=None,**kwargs):
        if 'select current_qty from `tabCFG Kanban Handling Unit`' in query:
            return [Row(current_qty=row.current_qty) for row in self.data[HU].values()
                if row.inventory_company==params['company'] and row.current_warehouse==params['warehouse']
                and row.item_code==params['item'] and (row.batch_no or '')==(params['batch'] or '') and row.current_qty>0]
        if 'select allocated_qty from `tabCFG Kanban Dispatch Allocation`' in query:
            return [Row(allocated_qty=row.allocated_qty) for row in self.data[ALLOC].values()
                if row.state=='Reserved' and row.allocation_kind=='Untagged ERP Stock'
                and row.source_warehouse==params['warehouse'] and row.item_code==params['item']]
        if 'select allocation.allocated_qty' in query or 'select allocation.name, allocation.allocated_qty' in query:return []
        return self.r.r.sql(query,params,**kwargs)

    def create(self,event='CREATE',route='RETURN',reason='Return leftovers',hash_value=None):
        return self.mod.create_dispatch_recovery(self.r.review().name,route,reason,
            hash_value or self.r.mod._hash(self.r.mod._balances(self.plan)),event,'SESSION')
    def manifest(self):return self.data[MANIFEST][self.r.review().recovery_manifest]
    def scan(self,value='TAG1'):return self.mod.scan_dispatch_recovery(self.manifest().name,value,'SCAN','SESSION')
    def prepare(self):return self.mod.prepare_dispatch_recovery(self.manifest().name,'PREPARE','SESSION')
    def post(self):return self.mod.post_dispatch_recovery(self.manifest().name,'POST','SESSION')
    def submit(self,name,event,token,required_erp_inputs=None):
        manifest=self.data[MANIFEST][name]
        if manifest.state=='Received':return self.log.get_manifest(name,token)
        doc=self.gateway['build_internal_transfer_stock_entry'](manifest,{'stage':'Direct','required_erp_inputs':required_erp_inputs})
        doc.name=f'MOVE-{len(self.saved_entries)+1}';doc.docstatus=0
        doc.posting_date=self.r.now.date();doc.posting_time=str(self.r.now.time())
        if not self.route.auto_submit_internal_dispatch:
            self.data.setdefault('Stock Entry',{})[doc.name]=doc;manifest.dispatch_stock_entry=doc.name
            manifest.state='Dispatch Document Pending';self.saved_entries.append(doc);return
        self.submit_doc(manifest,doc)
    def submit_doc(self,manifest,doc):
        self.mod.validate_recovery_stock_entry(doc)
        self.feedback.validate_internal_stock_entry(doc)
        doc.docstatus=1;self.data.setdefault('Stock Entry',{})[doc.name]=doc
        self.saved_entries.append(doc)
        self.b.erp_balance-=sum(row.qty for row in doc.items)
        self.b.add('Stock Ledger Entry','RECOVERY-SLE',voucher_type='Stock Entry',voucher_no=doc.name,warehouse='LORRY1',creation=self.r.now)
        self.feedback._post_internal_direct(manifest,doc)
    def loose(self,qty=6,batch=None):
        self.b.loose(qty)
        if batch:
            allocation=self.data[ALLOC]['LOOSE'];allocation.item_code='BATCHED';allocation.batch_no=batch
            self.plan.lines[0].item_code='ITEM'
            self.b.add('CFG Kanban Dispatch Plan Line','LOOSE-LINE',item_code='BATCHED',stock_uom='Nos',requested_qty=qty,loaded_qty=qty)
            allocation.dispatch_plan_line='LOOSE-LINE';self.plan.lines.append(self.data['CFG Kanban Dispatch Plan Line']['LOOSE-LINE'])
            self.plan.lines[0].loaded_qty=5
            self.b.add('Batch',batch,item='BATCHED',expiry_date='2027-02-01')
        self.r.counts._erp_balances=lambda *args,**kwargs:{('ITEM',''):self.b.erp_balance} if not batch else {('ITEM',''):5,('BATCHED',batch):qty}
    def confirm_loose(self,qty=None):
        row=next(row for row in self.manifest().lines if not row.handling_unit)
        return self.mod.confirm_dispatch_recovery_loose(self.manifest().name,row.name,qty if qty is not None else row.dispatch_qty,'LOOSE','SESSION')

    def test_create_copies_exact_recipe_and_identity_without_stock_mutation(self):
        before=(self.plan.movement_manifest,self.plan.vehicle_warehouse,self.unit.current_qty,self.unit.reserved_qty)
        result=self.create();m=self.manifest()
        self.assertEqual(m.source_warehouse,'LORRY1');self.assertEqual(m.destination_warehouse,'SOURCE')
        self.assertEqual(m.recovery_action,'Returned to Warehouse');self.assertFalse(m.dispatch_plan)
        self.assertEqual(m.lines[0].dispatch_allocation,'ALLOC');self.assertFalse(m.lines[0].loading_confirmed)
        self.assertEqual((m.lines[0].process_certificate_set,str(m.lines[0].expiry_date)),('CERT','2027-04-01'))
        self.assertEqual((self.plan.movement_manifest,self.plan.vehicle_warehouse,self.unit.current_qty,self.unit.reserved_qty),before)
        self.assertFalse(self.b.posted);self.assertEqual(result['recovery_manifest']['name'],m.name)

    def test_identical_replay_and_changed_token_do_not_create_second_manifest(self):
        first=self.create();self.create();self.create('ANOTHER')
        self.assertEqual(len(self.data[MANIFEST]),2)  # Original E3 load plus one recovery.
        self.assertEqual(first['recovery_manifest']['name'],self.manifest().name)
        with self.assertRaisesRegex(ValueError,'different details'):self.create(reason='Different')
        with self.assertRaisesRegex(ValueError,'already has a recovery'):self.create('OTHER',reason='Different')

    def test_replay_is_resolved_before_changed_source_or_terminal_state(self):
        args=(self.r.review().name,'RETURN','Return leftovers',self.r.mod._hash(self.r.mod._balances(self.plan)),'CREATE','SESSION')
        self.mod.create_dispatch_recovery(*args);self.scan();self.prepare();self.post()
        self.r.count();self.r.finish('Returned to Warehouse',movement=self.manifest().dispatch_stock_entry)
        result=self.mod.create_dispatch_recovery(*args)
        self.assertEqual(result['recovery_manifest']['state'],'Received');self.assertEqual(len(self.saved_entries),1)

    def test_supervisor_and_both_route_responsibilities_are_required(self):
        self.r.r.supervisor(False)
        with self.assertRaisesRegex(ValueError,'Supervisor'):self.create()
        self.r.supervisor();self.route.supervisor_responsibility='Other'
        with self.assertRaisesRegex(ValueError,'not assigned'):self.create()

    def test_wrong_company_source_transit_and_inactive_destination_are_rejected(self):
        for field,value in [('source_company','A'),('source_warehouse','SOURCE'),('internal_transfer_mode','Goods in Transit'),('active',0)]:
            old=self.route[field];self.route[field]=value
            with self.assertRaisesRegex(ValueError,'Direct Transfer'):self.create()
            self.route[field]=old
        self.data['Warehouse']['SOURCE'].disabled=1
        with self.assertRaisesRegex(ValueError,'active leaf'):self.create()

    def test_refresh_context_lists_only_authorized_routes_and_resumes_manifest(self):
        self.create();self.b.add('CFG Kanban Logistics Route','OTHER',**{key:value for key,value in dict.items(self.route) if key not in ('doctype','name','_store')})
        self.data['CFG Kanban Logistics Route']['OTHER'].supervisor_responsibility='Other'
        result=self.mod.get_dispatch_recovery_context('PLAN','SESSION')
        self.assertEqual([r['name'] for r in result['recovery_routes']],['RETURN'])
        self.assertEqual(self.mod.get_dispatch_recovery_context(self.manifest().name,'SESSION')['review']['name'],self.r.review().name)

    def test_reason_hash_and_nonzero_remainder_are_mandatory(self):
        with self.assertRaisesRegex(ValueError,'reason'):self.create(reason='')
        with self.assertRaisesRegex(ValueError,'balances changed'):self.create(hash_value='OLD')
        self.b.add(e4a.DA,'RECORDED',dispatch_allocation='ALLOC',state='Delivered',delivered_qty=5)
        self.unit.current_qty=0;self.unit.available_qty=0
        with self.assertRaisesRegex(ValueError,'No prepared stock'):self.create()

    def test_physical_scan_required_and_outside_tag_rejected(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'Scan each physical'):self.prepare()
        self.b.add(HU,'EXTRA',handling_unit_id='EXTRA1',tag_kind='Stock Tag')
        with self.assertRaisesRegex(ValueError,'belong to this prepared'):self.scan('EXTRA1')
        self.scan();self.assertTrue(self.manifest().lines[0].loading_confirmed)
        self.scan();self.assertFalse(self.b.posted)

    def test_prepare_reserves_once_and_blocks_recipe_tampering(self):
        self.create();self.scan();self.prepare();self.prepare()
        self.assertEqual(self.unit.reserved_qty,5);self.assertEqual(len(self.b.posted),1)
        self.manifest().lines[0].dispatch_qty=4
        with self.assertRaisesRegex(ValueError,'exact prepared remainder'):self.post()
        self.assertFalse(self.saved_entries)

    def test_native_feedback_moves_tag_and_preserves_certificates_and_original_load(self):
        self.create();self.scan();snapshot=self.manifest().lines[0].stock_identity_snapshot
        original=self.plan.movement_manifest;self.prepare();self.post();self.post()
        self.assertEqual(self.unit.current_warehouse,'SOURCE');self.assertEqual(self.unit.current_qty,5)
        self.assertEqual(self.unit.reserved_qty,0);self.assertEqual(self.unit.process_certificate_set,'CERT')
        self.assertEqual(self.manifest().state,'Received');self.assertEqual(self.plan.movement_manifest,original)
        self.assertEqual(self.plan.vehicle_warehouse,'LORRY1');self.assertEqual(self.plan.state,'Loaded')
        self.assertEqual(self.manifest().lines[0].stock_identity_snapshot,snapshot)
        self.assertEqual(len(self.saved_entries),1)

    def test_lorry_destination_infers_correct_disposition_without_reassigning_plan(self):
        self.route.destination_warehouse='LORRY2';self.create();self.scan();self.prepare();self.post()
        self.assertEqual(self.manifest().recovery_action,'Transferred to Another Lorry')
        self.assertEqual(self.unit.current_warehouse,'LORRY2');self.assertEqual(self.plan.vehicle_warehouse,'LORRY1')
        self.r.count();self.r.finish('Transferred to Another Lorry',movement=self.manifest().dispatch_stock_entry)
        self.assertEqual(self.plan.state,'Reconciled')

    def test_review_cannot_resume_or_close_other_disposition_while_recovery_active(self):
        self.create();self.r.count()
        with self.assertRaisesRegex(ValueError,'linked recovery'):self.r.mod.resume_dispatch_review(self.r.review().name,'Continue','RESUME','SESSION')
        with self.assertRaisesRegex(ValueError,'linked recovery'):self.r.finish()
        self.scan();self.prepare();self.post();self.r.count()
        with self.assertRaisesRegex(ValueError,'linked recovery'):self.r.finish()
        self.r.finish('Returned to Warehouse',movement=self.manifest().dispatch_stock_entry)
        self.assertEqual(self.plan.state,'Reconciled')

    def test_unused_cancel_releases_reservation_and_preserves_history_for_new_destination(self):
        self.create();first=self.manifest();self.scan();self.prepare()
        self.mod.cancel_dispatch_recovery(first.name,'Destination changed','CANCEL','SESSION')
        self.assertEqual(first.state,'Cancelled');self.assertEqual(self.unit.reserved_qty,0)
        self.route.destination_warehouse='LORRY2';self.create('CREATE2');self.assertNotEqual(self.manifest().name,first.name)
        self.assertEqual(self.data[MANIFEST][first.name].destination_warehouse,'SOURCE')

    def test_cancel_unused_prepared_recovery_releases_once_and_allows_new_destination(self):
        self.create();self.scan();self.prepare();name=self.manifest().name
        for _ in range(2):self.mod.cancel_dispatch_recovery(name,'Keep at source','CANCEL','SESSION')
        self.assertEqual(self.unit.reserved_qty,0);self.assertEqual(self.manifest().state,'Cancelled')
        self.assertEqual(len([event for event in self.b.posted if event['event_type']=='Unreserve']),1)
        self.route.destination_warehouse='LORRY2';self.create('NEW')
        self.assertNotEqual(self.manifest().name,name);self.assertEqual(self.data[MANIFEST][name].state,'Cancelled')

    def test_submitted_or_pending_erp_movement_cannot_be_cancelled(self):
        self.create();self.scan();self.prepare();self.post()
        with self.assertRaisesRegex(ValueError,'unused Draft/Prepared'):self.mod.cancel_dispatch_recovery(self.manifest().name,'Wrong','CANCEL','SESSION')

    def test_mixed_tagged_and_loose_requires_exact_loose_confirmation(self):
        self.unit.process_certificate_set=None
        self.loose();self.create();self.scan()
        for qty in [0,5,7,float('nan'),float('inf')]:
            with self.assertRaisesRegex(ValueError,'exact displayed'):self.confirm_loose(qty)
        with self.assertRaisesRegex(ValueError,'confirm every loose'):self.prepare()
        self.confirm_loose();self.prepare();self.post()
        self.assertEqual(len(self.saved_entries[0].items),2)
        self.assertFalse(self.saved_entries[0].items[1].cfg_handling_unit)
        self.assertEqual(len([event for event in self.b.posted if event['event_type']=='Reserve']),1)

    def test_native_batch_builder_keeps_batch_and_legacy_bundle_control(self):
        self.loose(batch='LOT');self.create();self.scan();self.confirm_loose();self.prepare();self.post()
        row=self.saved_entries[0].items[1]
        self.assertEqual(row.batch_no,'LOT');self.assertEqual(row.use_serial_batch_fields,1)
        self.assertFalse(row.cfg_handling_unit)

    def test_manual_draft_submit_rechecks_recipe_and_current_stock(self):
        self.route.auto_submit_internal_dispatch=0
        self.create();self.scan();self.prepare();self.post()
        self.assertEqual(self.manifest().state,'Dispatch Document Pending');self.assertEqual(self.unit.current_warehouse,'LORRY1')
        doc=self.saved_entries[0];self.unit.current_qty=4
        with self.assertRaisesRegex(ValueError,'quantity/location/reservation'):self.submit_doc(self.manifest(),doc)
        self.unit.current_qty=5;self.submit_doc(self.manifest(),doc)
        self.assertEqual(self.manifest().state,'Received')

    def test_direct_line_removal_or_unrelated_scan_cannot_expand_recipe(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'exact prepared remainder'):self.log.remove_dispatch_tag(self.manifest().name,'SESSION',line_name=self.manifest().lines[0].name)
        self.log.scan_dispatch_tag(self.manifest().name,'TAG1','SCAN','SESSION')
        self.assertEqual(len(self.manifest().lines),1);self.assertTrue(self.manifest().lines[0].loading_confirmed)

    def test_source_identity_change_blocks_saved_native_entry(self):
        self.create();self.scan();self.prepare();self.unit.expiry_date='2027-05-01'
        with self.assertRaisesRegex(ValueError,'identity changed'):self.post()
        self.assertFalse(self.saved_entries)

    def test_container_scan_confirms_exact_group_and_rejects_extra_stock(self):
        self.b.add(HU,'BIN',handling_unit_id='BIN1',tag_kind='Reusable Container',identity_state='Active',quality_state='Released',inventory_company='B',current_warehouse='LORRY1')
        self.memberships['TAG']=Row(container_handling_unit='BIN')
        self.create()
        with self.assertRaisesRegex(ValueError,'physical container'):self.scan()
        self.scan('BIN1');self.assertTrue(self.manifest().lines[0].loading_confirmed)
        self.prepare();self.post();self.assertEqual(self.data[HU]['BIN'].current_warehouse,'SOURCE')


    def test_loose_stock_cannot_borrow_certificate_identity_from_nearby_tag(self):
        self.loose();self.create();self.scan();self.confirm_loose();self.prepare()
        with self.assertRaisesRegex(ValueError,'Certified stock exists'):self.post()
        self.assertFalse(self.saved_entries)

    def test_extra_container_stock_cannot_be_silently_added(self):
        self.b.add(HU,'BIN',handling_unit_id='BIN1',tag_kind='Reusable Container',identity_state='Active',quality_state='Released',inventory_company='B',current_warehouse='LORRY1')
        self.memberships['TAG']=Row(container_handling_unit='BIN')
        self.memberships['EXTRA']=Row(container_handling_unit='BIN')
        self.create()
        with self.assertRaisesRegex(ValueError,'Every tag'):self.scan('BIN1')
        self.assertFalse(self.manifest().lines[0].loading_confirmed)
        self.assertFalse(self.b.posted)


    def test_real_before_submit_hook_composes_recovery_and_manifest_guards(self):
        self.create();self.scan();self.prepare()
        doc=self.gateway['build_internal_transfer_stock_entry'](self.manifest(),{'stage':'Direct'})
        ns=dict(self.mod.__dict__)
        e4a.extract('integrations/erp_feedback.py',ns,{'validate_stock_entry'})
        self.unit.current_qty=4
        with self.assertRaisesRegex(ValueError,'quantity/location/reservation'):ns['validate_stock_entry'](doc)
        self.unit.current_qty=5;ns['validate_stock_entry'](doc)
        self.assertFalse(self.saved_entries)

    def test_recovery_route_and_recipe_are_immutable_on_a_saved_manifest(self):
        self.create();m=self.manifest();before=e4a.Record(m.as_dict())
        m.get_doc_before_save=lambda:before;m.meta=Row(get_label=lambda field:field)
        for field in ('dispatch_recovery_review','recovery_action','recovery_reason','recovery_snapshot_json','recovery_payload_hash'):
            old=m[field];m[field]='CHANGED'
            with self.assertRaisesRegex(ValueError,'immutable route snapshot'):self.controller._validate_route_snapshot(m)
            m[field]=old

    def test_pending_saved_erp_document_cannot_be_substituted_or_deleted(self):
        self.route.auto_submit_internal_dispatch=0
        self.create();self.scan();self.prepare();self.post()
        doc=self.saved_entries[0];original=doc.name;doc.name='SUBSTITUTE'
        with self.assertRaisesRegex(ValueError,'substitute document'):self.mod.validate_recovery_stock_entry(doc)
        doc.name=original
        with self.assertRaisesRegex(ValueError,'audit records'):self.mod.protect_recovery_draft_delete(doc)
        self.assertEqual(self.manifest().dispatch_stock_entry,original)
        self.assertEqual(self.unit.current_warehouse,'LORRY1')

    def test_delete_guard_does_not_change_unrelated_stock_entries(self):
        self.mod.protect_recovery_draft_delete(Row())
        self.mod.protect_recovery_draft_delete(Row(cfg_movement_manifest=self.b.manifest.name))

    def test_saved_recovery_document_cannot_drop_or_change_its_manifest(self):
        self.create();m=self.manifest()
        doc=Row(cfg_movement_manifest=None,is_new=lambda:False,
            get_doc_before_save=lambda:Row(cfg_movement_manifest=m.name))
        with self.assertRaisesRegex(ValueError,'cannot be detached'):self.mod.protect_recovery_document_identity(doc)
        doc.cfg_movement_manifest=self.b.manifest.name
        with self.assertRaisesRegex(ValueError,'cannot be detached'):self.mod.protect_recovery_document_identity(doc)
        doc.cfg_movement_manifest=m.name;self.mod.protect_recovery_document_identity(doc)

    def test_native_recovery_purpose_and_existing_document_cannot_be_substituted(self):
        self.create();self.scan();self.prepare()
        doc=self.gateway['build_internal_transfer_stock_entry'](self.manifest(),{'stage':'Direct'});doc.name='DRAFT'
        doc.purpose='Repack'
        with self.assertRaisesRegex(ValueError,'remain a Material Transfer'):self.mod.validate_recovery_stock_entry(doc)
        doc.purpose='Material Transfer';self.manifest().dispatch_stock_entry='ORIGINAL'
        with self.assertRaisesRegex(ValueError,'substitute document'):self.mod.validate_recovery_stock_entry(doc)

class TestCurrentRecoveryAvailability(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.tagged=[Row(current_qty=7)];self.reserved=[Row(allocated_qty=2)]
        self.deliveries=[Row(allocated_qty=3)];self.waiting=[Row(name='A',allocated_qty=6),Row(name='B',allocated_qty=4)]
        self.picked=[Row(dispatch_allocation='A',allocated_qty=3),Row(dispatch_allocation='B',allocated_qty=6)]
        self.balance=30
        frappe=Row(db=Row(sql=self.sql,get_values=self.values))
        common=dict(frappe=frappe,flt=lambda value:float(value or 0),now_datetime=lambda:datetime.datetime(2026,11,20,12))
        self.bridge=types.ModuleType('cfg_kanban.services.dispatch_fulfilment');self.bridge.__dict__.update(common)
        e4a.extract('services/dispatch_fulfilment.py',self.bridge.__dict__,{'active_untagged_delivery_qty','waiting_prepared_untagged_qty'})
        self.counts=types.ModuleType('cfg_kanban.services.route_reconciliation')
        self.counts._erp_balances=Mock(side_effect=lambda *args,**kw:{('ITEM','LOT'):self.balance})
        self.ns=dict(common,validate_warehouse_company=Mock(),_lock_erp_bin=Mock())
        e4a.extract('services/dispatch_planning.py',self.ns,{'_untagged_available'})
        p=patch.dict(sys.modules,{self.bridge.__name__:self.bridge,self.counts.__name__:self.counts});p.start();self.addCleanup(p.stop)
    def sql(self,query,params=None,**kwargs):
        self.calls.append((query,params,kwargs))
        if 'select current_qty' in query:return self.tagged
        if 'select allocated_qty' in query:return self.reserved
        if 'select allocation.allocated_qty' in query:return self.deliveries
        if 'select allocation.name, allocation.allocated_qty' in query:return self.waiting
        raise AssertionError('Unexpected SQL: '+query)
    def values(self,dt,filters,fields,**kwargs):
        self.assertEqual(dt,'CFG Kanban Delivery Allocation');self.assertTrue(kwargs['for_update'])
        self.assertEqual(filters['state'],['in',['Reserved','Delivery Pending','Exception','Delivered']])
        return self.picked
    def available(self):return self.ns['_untagged_available']('B','LORRY','ITEM','LOT',exclude_prepared_plan='OWN',current=True)
    def test_current_reads_subtract_other_commitments_without_double_counting_prepared_picks(self):
        self.assertEqual(self.available(),15)
        self.ns['_lock_erp_bin'].assert_called_once_with('ITEM','LORRY')
        self.assertTrue(self.counts._erp_balances.call_args.kwargs['current'])
        for query,params,kw in self.calls:
            self.assertIn('for update',query);self.assertTrue(kw['as_dict']);self.assertEqual(params['company'],'B');self.assertEqual(params['batch'],'LOT')
        query,params,_=self.calls[-1]
        self.assertEqual(params['excluded'],'OWN');self.assertIn("plan.name!=%(excluded)s",query)
        self.assertIn("plan.state='Loaded'",query)
    def test_missing_or_competing_stock_never_creates_negative_availability(self):
        self.balance=1;self.assertEqual(self.available(),0)
    def test_empty_competing_rows_leave_current_erp_quantity_available(self):
        self.tagged=[];self.reserved=[];self.deliveries=[];self.waiting=[]
        self.assertEqual(self.available(),30)

if __name__=='__main__':unittest.main()

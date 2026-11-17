"""Real repack control flow + quantity ledger, offline store. No site/concurrency acceptance."""
import ast
import copy
import datetime
import hashlib
import json
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cfg_kanban.services.handling_unit_math import event_deltas, apply_balance_delta

ROOT = Path(__file__).resolve().parents[1]
HU = 'CFG Kanban Handling Unit'
CONTENT = 'CFG Kanban Container Content'
LEDGER = 'CFG Kanban Handling Unit Quantity Ledger'
EVENT = 'CFG Kanban Event'

class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    def __deepcopy__(self, memo):return Row(copy.deepcopy(dict(self),memo))


def functions(path, names, ns):
    tree = ast.parse((ROOT / path).read_text())
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (names is None or node.name in names):
            node.decorator_list = []; body.append(node)
        elif isinstance(node, ast.Assign) and names is None:
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), ns)
    return Row(ns)


class RepackHarness(unittest.TestCase):
    def setUp(self):
        self.data = {HU: {}, CONTENT: {}, LEDGER: {}, EVENT: {}}
        self.wip = set(); self.open_movement = set(); self.draws = {}; self.fail_certificate = False
        self.certificate_calls = []
        self.frappe = Row(throw=lambda msg: (_ for _ in ()).throw(ValueError(msg)),
                          get_doc=self.doc, copy_doc=lambda doc:self.doc(dict(doc)), parse_json=json.loads,
                          get_all=self.get_all)
        self.frappe.db = Row(sql=self.sql, set_value=self.set_value, get_value=self.get_value,
                             exists=lambda doctype, filters:False, table_exists=lambda doctype:True)
        self.retag_auth = Mock(); self.container_auth = Mock(return_value={'operator':'EMP','operator_session':'OS','terminal_user':'terminal'})
        ns = {'frappe':self.frappe, 'math':math, 'flt':lambda value:float(value or 0),
              'now_datetime':lambda:datetime.datetime(2026,11,17,10),
              'canonical_key':lambda *parts:hashlib.sha256(json.dumps(parts,default=str).encode()).hexdigest(),
              'normalize_physical_code':lambda value:str(value).strip().upper(),
              'resolve_logistics_scan':self.resolve, 'active_container_contents':self.contents,
              'active_container_membership':self.membership, '_authorize':self.container_auth,
              'authorize_stock_retagging':self.retag_auth,
              'assert_container_not_in_open_manifest':self.guard,
              'assert_container_not_in_open_delivery':self.guard,
              'identity_snapshot':lambda unit:{key:unit.get(key) for key in ('name','item_code','batch_no','expiry_date','process_certificate_set','current_qty')},
              'assert_merge_compatible':self.compatible, 'inherit_split_certificates':self.inherit,
              'record':self.record, 'event_deltas':event_deltas,'apply_balance_delta':apply_balance_delta}
        functions('services/logistics_foundation.py', {'post_quantity_event','_existing_ledger','_lock_handling_units','_calculate_updates','_require_event_endpoints'}, ns)
        self.service = functions('services/container_repacking.py', None, ns)
        self.modules = patch.dict(sys.modules, {
            'cfg_kanban.services.operation_hoppers':types.SimpleNamespace(assert_no_operation_fill=self.no_wip),
            'cfg_kanban.services.operation_material_runs':types.SimpleNamespace(_source_reserved_qty=lambda name:self.draws.get(name,0)),
            'cfg_kanban.services.logistics_quantity_bins':types.SimpleNamespace(_assert_source_not_in_open_transaction=self.guard),
            'cfg_kanban.services.tag_to_tag_transfer':types.SimpleNamespace(_validate_unused_main_tag=self.unused)})
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.stock('S',10)
        self.container('A'); self.container('B')

    def doc(self, doctype, name=None):
        if isinstance(doctype, dict): values=copy.deepcopy(doctype)
        else: values=copy.deepcopy(self.data[doctype][name])
        harness=self
        class Doc(Row):
            def __init__(self, values): super().__init__(values); object.__setattr__(self,'flags',Row())
            def insert(self, **kw):
                self.name = self.get('name') or f'{self.doctype}-{len(harness.data[self.doctype])+1}'
                if self.doctype==CONTENT and harness.membership(self.content_handling_unit):raise ValueError('already loaded')
                harness.data[self.doctype][self.name]=Row(copy.deepcopy(dict(self))); return self
            def reload(self): self.update(copy.deepcopy(harness.data[self.doctype][self.name])); return self
            def db_set(self, values, value=None, **kw):
                if isinstance(values,str):values={values:value}
                self.update(values);harness.data[self.doctype][self.name].update(values)
        return Doc(values)

    def stock(self, name, qty, **kw):
        self.data[HU][name] = Row(doctype=HU,name=name,handling_unit_id=name,tag_kind='Main Stock Tag',
            identity_state='Active',quality_state='Released',movement_state='Received',item_code='PRODUCT',batch_no='BATCH',
            stock_uom='Kg',inventory_company='TEST',current_warehouse='STORE',current_qty=qty,available_qty=qty,reserved_qty=0,
            virtual_content=0,expiry_date='2027-01-31',process_certificate_set='CERTSET',packed_on='2026-11-01',
            current_operation='Pack',origin_reference_doctype='Purchase Receipt',origin_reference_name='PR-1',
            work_order='WO',kanban_cycle='CYCLE',kanban_card='CARD',short_description='Original product',**kw)
        return self.doc(HU,name)

    def container(self, name, role='Logistics Container'):
        self.data[HU][name] = Row(doctype=HU,name=name,handling_unit_id=name,tag_kind='Reusable Container',
            reusable_container_role=role,identity_state='Active',quality_state='Released',movement_state='Empty',
            inventory_company='TEST',current_warehouse='STORE',current_qty=0,reserved_qty=0,available_qty=0)
        return self.doc(HU,name)

    def load(self, container, stock):
        return self.service._attach(self.doc(HU,container),self.doc(HU,stock),{},'fixture')
    def resolve(self, scan):
        match=next((row for row in self.data[HU].values() if row.handling_unit_id==scan or row.name==scan),None)
        return {'identity_type':'Handling Unit','name':match.name} if match else None
    def contents(self, name):return [self.doc(CONTENT,row.name) for row in self.data[CONTENT].values() if row.container_handling_unit==name and row.state=='Loaded']
    def membership(self,name):return next((self.doc(CONTENT,row.name) for row in self.data[CONTENT].values() if row.content_handling_unit==name and row.state=='Loaded'),None)
    def guard(self, name, *args):
        if name in self.open_movement:raise ValueError('open movement')
    def no_wip(self,name,*args):
        if name in self.wip:raise ValueError('Recover Hopper')
    def unused(self,code):
        if not code.startswith('NEW') or self.resolve(code):raise ValueError('unused Main tag required')
    def compatible(self,source,destination):
        for field in ('process_certificate_set','expiry_date','certificate_root'):
            if source.get(field)!=destination.get(field):raise ValueError('certificate/expiry mismatch')
    def inherit(self, source,destination,qty,key,**kw):
        self.certificate_calls.append((source.name,destination.name,qty,kw))
        if self.fail_certificate:raise ValueError('certificate coverage')
    def record(self, event_type, **kw):return self.doc(dict(doctype=EVENT,idempotency_key=kw['idempotency_key'],payload_json=json.dumps(kw['payload'],default=str))).insert()
    def set_value(self, doctype, name, values, **kw):self.data[doctype][name].update(values)
    def get_value(self,doctype,filters,field,**kw):
        rows = self.data.get(doctype,{})
        if isinstance(filters,str):return rows.get(filters,{}).get(field)
        return next((row.get(field) for row in rows.values() if all(row.get(k)==v for k,v in filters.items())),None)
    def get_all(self, doctype, filters=None, **kw):return [Row(copy.deepcopy(row)) for row in self.data[doctype].values() if all(row.get(k)==v for k,v in filters.items())]
    def sql(self, query, args=None, as_dict=False):
        if 'where origin_reference_doctype=' in query:
            return [Row(copy.deepcopy(row)) for row in self.data[HU].values()
                    if row.get('origin_reference_doctype')==args[0] and row.get('origin_reference_name')==args[1]]
        if 'select * from `tabCFG Kanban Handling Unit`' in query:
            return [Row(copy.deepcopy(self.data[HU][name])) for name in sorted(set(args)) if name in self.data[HU]]
        if 'select current_qty, reserved_qty from' in query:
            unit=self.data[HU].get(args);return [(unit.current_qty,unit.reserved_qty)] if unit else []
        if 'select name' in query and 'tabCFG Kanban Handling Unit`' in query:return [(name,) for name in args if name in self.data[HU]]
        if 'select payload_json' in query:return [(row.payload_json,) for row in self.data[EVENT].values() if row.idempotency_key==args]
        if 'select * from `tabCFG Kanban Container Content`' in query:
            return self.members(args, 'content_handling_unit' if 'where content_handling_unit' in query else 'container_handling_unit')
        if 'Operation Hopper Fill' in query:return [('WIP',)] if self.wip.intersection(args) else []
        if 'tabCFG Kanban Manifest Line' in query or 'tabCFG Kanban Delivery Allocation' in query:
            return [('OPEN',)] if self.open_movement.intersection(args) else []
        raise AssertionError((query,args))
    def members(self,name,field):return [Row(copy.deepcopy(row)) for row in self.data[CONTENT].values() if row.get(field)==name and row.state=='Loaded']
    def move(self,**kw):
        args=dict(source_scan='S',source_stock='S',destination_scan='B',qty=3,reason='Repack physical stock',event_token='E',operator_session_token='TOKEN');args.update(kw)
        return self.service.move_container_stock(**args)
    def total(self):return sum(row.current_qty for row in self.data[HU].values() if row.tag_kind!='Reusable Container')


class TestContainerRepacking(RepackHarness):
    def test_whole_tag_moves_from_a_to_b_without_changing_stock(self):
        old=self.load('A','S');result=self.move(source_scan='A',qty=10)
        self.assertTrue(result['whole_tag_moved']);self.assertEqual(result['destination_stock'],'S')
        self.assertEqual(self.membership('S').container_handling_unit,'B');self.assertFalse(self.contents('A'))
        self.assertEqual(self.data[CONTENT][old.name].state,'Unloaded');self.assertEqual(self.total(),10)
        self.assertFalse(self.data[LEDGER]);self.assertFalse(self.certificate_calls)

    def test_ordinary_stock_tag_loads_into_empty_container(self):
        self.move(qty=10);self.assertEqual(self.membership('S').container_handling_unit,'B')

    def test_partial_to_new_preprinted_tag_keeps_original_metadata_and_exact_balance(self):
        self.load('A','S');result=self.move(source_scan='A',new_tag='NEW001',qty=3)
        destination=self.data[HU][result['destination_stock']]
        self.assertEqual(destination.handling_unit_id,'NEW001');self.assertEqual(destination.current_qty,3)
        self.assertEqual(self.data[HU]['S'].current_qty,7);self.assertEqual(self.total(),10)
        self.assertEqual(self.membership('S').container_handling_unit,'A')
        self.assertEqual(self.membership(destination.name).container_handling_unit,'B')
        for field in ('item_code','batch_no','stock_uom','expiry_date','process_certificate_set','work_order','kanban_cycle','short_description'):
            self.assertEqual(destination[field],self.data[HU]['S'][field])
        self.assertEqual(self.certificate_calls[0][3],{'replacement':False})

    def test_partial_into_permanent_quantity_bin_creates_internal_fill(self):
        self.container('B','Logistics Quantity Bin');result=self.move()
        row=self.data[HU][result['destination_stock']]
        self.assertEqual(row.virtual_content,1);self.assertEqual(row.physical_container,'B');self.assertEqual(self.total(),10)

    def test_internal_fill_can_move_into_preprinted_tag_in_new_container(self):
        self.container('A','Production Output Container');self.data[HU]['S'].update(virtual_content=1,physical_container='A');self.load('A','S')
        result=self.move(source_scan='A',qty=10,new_tag='NEW01')
        destination=self.data[HU][result['destination_stock']]
        self.assertEqual(destination.virtual_content,0);self.assertIsNone(destination.physical_container)
        self.assertEqual(self.data[HU]['S'].identity_state,'Empty');self.assertFalse(self.contents('A'))
        self.assertEqual(self.total(),10);self.assertEqual(self.certificate_calls[0][3],{'replacement':True})

    def test_existing_destination_uses_its_tag_and_combines_quantity(self):
        self.stock('D',5);self.load('B','D');result=self.move(destination_stock='D')
        self.assertEqual(result['destination_stock'],'D');self.assertEqual(result['destination_qty'],8)
        self.assertTrue(result['existing_tag_used']);self.assertEqual(self.total(),15)
        self.assertEqual(len(self.contents('B')),1);self.assertEqual(self.data[HU]['S'].current_qty,7)

    def test_existing_destination_rejects_new_tag_and_missing_selection(self):
        self.stock('D',5);self.load('B','D')
        for kw in ({'new_tag':'NEW1','destination_stock':'D'},{}):
            with self.assertRaises(ValueError):self.move(**kw)
        self.assertFalse(self.data[LEDGER]);self.assertEqual(self.total(),15)

    def test_multiple_fills_require_exact_source_and_destination_selection(self):
        self.stock('S2',2);self.load('A','S');self.load('A','S2')
        rows=self.service.repack_source_context('A','TOKEN')['options'];self.assertEqual(len(rows),2)
        with self.assertRaisesRegex(ValueError,'Source contents changed'):self.move(source_scan='B',new_tag='NEW1')
        self.stock('D',5);self.stock('D2',2);self.load('B','D');self.load('B','D2')
        with self.assertRaisesRegex(ValueError,'Select the exact'):self.move(source_scan='A')
        self.move(source_scan='A',destination_stock='D2');self.assertEqual(self.data[HU]['D2'].current_qty,5)
        self.assertEqual(self.data[HU]['D'].current_qty,5)

    def test_incompatible_existing_contents_rejected_before_quantity_change(self):
        self.stock('D',5);self.load('B','D')
        for field,value in [('item_code','OTHER'),('batch_no','OTHER'),('stock_uom','Nos'),('inventory_company','OTHER'),('current_warehouse','OTHER'),('expiry_date','2028-01-01'),('process_certificate_set','OTHER'),('current_operation','OTHER'),('packed_on','2026-10-01'),('certificate_root','OTHER')]:
            with self.subTest(field=field):
                old=self.data[HU]['D'].get(field);self.data[HU]['D'][field]=value
                with self.assertRaises(ValueError):self.move(destination_stock='D')
                self.data[HU]['D'][field]=old
        self.assertFalse(self.data[LEDGER]);self.assertEqual(self.total(),15)

    def test_reserved_open_movement_material_run_and_wip_rejected(self):
        self.data[HU]['S'].reserved_qty=1
        with self.assertRaises(ValueError):self.move(new_tag='NEW1')
        self.data[HU]['S'].reserved_qty=0;self.open_movement.add('B')
        with self.assertRaises(ValueError):self.move(new_tag='NEW1')
        self.open_movement.clear();self.draws['S']=1
        with self.assertRaisesRegex(ValueError,'Material Run'):self.move(new_tag='NEW1')
        self.draws.clear();self.wip.add('B')
        with self.assertRaisesRegex(ValueError,'Recover Hopper'):self.move(new_tag='NEW1')
        self.assertFalse(self.data[LEDGER]);self.assertEqual(self.total(),10)

    def test_same_warehouse_required_and_blank_container_location_adopted(self):
        self.data[HU]['B'].current_warehouse='OTHER'
        with self.assertRaises(ValueError):self.move(qty=10)
        self.data[HU]['B'].update(inventory_company=None,current_warehouse=None)
        self.move(qty=10);self.assertEqual(self.data[HU]['B'].current_warehouse,'STORE')

    def test_exact_retry_after_full_source_emptied_does_not_move_twice(self):
        self.load('A','S');first=self.move(source_scan='A',qty=10,new_tag='NEW1')
        retry=self.move(source_scan='A',qty=10,new_tag='NEW1')
        self.assertTrue(retry['duplicate']);self.assertEqual(retry['destination_stock'],first['destination_stock'])
        self.assertEqual(len(self.data[LEDGER]),1);self.assertEqual(len(self.data[EVENT]),1);self.assertEqual(self.total(),10)
        with self.assertRaisesRegex(ValueError,'different repacking'):self.move(source_scan='A',qty=9,new_tag='NEW1')

    def test_exact_retry_after_whole_membership_move_is_acknowledged(self):
        self.load('A','S');self.move(source_scan='A',qty=10)
        self.assertTrue(self.move(source_scan='A',qty=10)['duplicate']);self.assertEqual(len(self.contents('B')),1)

    def test_locked_balance_wins_over_stale_doc_snapshot(self):
        original=self.service._lock_units
        def locked(names):
            self.data[HU]['S'].update(current_qty=2,available_qty=2)
            return original(names)
        self.service['move_container_stock'].__globals__['_lock_units']=locked
        with self.assertRaisesRegex(ValueError,'exceeds'):self.move(new_tag='NEW1')
        self.assertFalse(self.data[LEDGER])

    def test_destination_change_during_lock_wait_requires_reload(self):
        original=self.service._lock_units
        def locked(names):
            self.stock('D',2);self.load('B','D');return original(names)
        self.service['move_container_stock'].__globals__['_lock_units']=locked
        with self.assertRaisesRegex(ValueError,'Destination contents changed'):self.move(new_tag='NEW1')
        self.assertFalse(self.data[LEDGER])

    def test_authorization_and_invalid_quantity(self):
        for qty in ('nan','inf',0,-1,'bad'):
            with self.assertRaises(ValueError):self.move(qty=qty)
        self.retag_auth.side_effect=ValueError('responsibility')
        with self.assertRaisesRegex(ValueError,'responsibility'):self.move(qty=10)
        self.assertFalse(self.data[EVENT]);self.assertFalse(self.data[LEDGER])

    def test_receipt_cannot_be_cancelled_while_received_physical_tag_loaded(self):
        self.load('B','S')
        with self.assertRaisesRegex(ValueError,'Unload/reconcile'):
            self.service.protect_receipt_cancellation(Row(doctype='Purchase Receipt',name='PR-1'))
        self.data[HU]['S'].update(virtual_content=1,physical_container='B')
        self.service.protect_receipt_cancellation(Row(doctype='Purchase Receipt',name='PR-1'))

    def test_ledger_uses_current_sql_balance_instead_of_stale_get_value(self):
        self.data[HU]['S'].update(current_qty=4,available_qty=4)
        self.frappe.db.get_value=Mock(return_value=(10,0))
        updates=self.service._calculate_updates(['S'],'S',None,event_deltas('Production Consume',3))
        self.assertEqual(updates['S']['current_qty'],1);self.frappe.db.get_value.assert_not_called()

    def test_production_output_container_resolves_physical_tag_and_rejects_other_virtual_owner(self):
        self.container('B','Production Output Container');self.load('B','S')
        ns=dict(frappe=self.frappe,cint=lambda value:int(value or 0),_=lambda value:value,active_container_contents=self.contents)
        subject=functions('services/container_contents.py',{'production_output_content'},ns)
        self.assertEqual(subject.production_output_content('B')[1].name,'S')
        self.data[HU]['S'].update(virtual_content=1,physical_container='A')
        with self.assertRaisesRegex(ValueError,'invalid production fill'):subject.production_output_content('B')

    def test_physical_production_fill_unload_and_native_reversal_restore(self):
        self.container('B','Production Output Container');self.move(qty=10)
        ns=dict(self.service)
        ns.update(cint=lambda value:int(value or 0),_=lambda value:value,
                  _lock_units=lambda *names:None, record=lambda *args,**kw:None)
        subject=functions('services/container_contents.py',{
            'production_output_content','load_production_output_content',
            'unload_production_output_content','restore_production_output_content',
            'validate_production_container_location'},ns)
        # Native creation remains internal-only; explicit stock movement established membership.
        with self.assertRaisesRegex(ValueError,'does not belong'):
            subject.load_production_output_content('B','S',reference_name='NEW',reason='Native manufacture')
        self.service.post_quantity_event(event_type='Production Consume',qty=10,stock_uom='Kg',
            idempotency_key='CONSUME',source_handling_unit='S')
        native=functions('services/production_trace.py',{'_mark_empty_if_needed'},
                         dict(frappe=self.frappe,flt=lambda value:float(value or 0),TOLERANCE=0.000001))
        with patch.dict(sys.modules, {'cfg_kanban.services.container_contents':types.SimpleNamespace(
                unload_production_output_content=subject.unload_production_output_content)}):
            native._mark_empty_if_needed('S',reference_name='CONSUME')
        self.assertFalse(self.contents('B'));self.assertEqual(self.data[HU]['S'].identity_state,'Empty')
        self.service.post_quantity_event(event_type='Production Consume Reversal',qty=10,stock_uom='Kg',
            idempotency_key='REVERSE',destination_handling_unit='S')
        self.data[HU]['S'].update(identity_state='Active',movement_state='Received')
        subject.restore_production_output_content('B','S',reference_name='CANCEL-CONSUME',reason='ERP cancellation')
        self.assertEqual(subject.production_output_content('B')[1].name,'S')
        self.assertEqual(len(self.contents('B')),1)

    def test_real_certificate_engine_repack_and_merge_keeps_original_evidence(self):
        from cfg_kanban.tests.test_logistics_stock_identity import TestLogisticsStockIdentity
        identity=TestLogisticsStockIdentity();identity.setUp();self.addCleanup(identity.doCleanups)
        identity.units=self.data[HU];identity.proof.handling_unit='S';identity.proof.certificate_set='CERTSET'
        identity.proof.certified_qty=10;identity.proof.item_code='PRODUCT';identity.serials=[]
        engine=identity.service
        ns=self.service.move_container_stock.__globals__
        ns.update(inherit_split_certificates=engine.inherit_split_certificates,
                  assert_merge_compatible=engine.assert_merge_compatible,
                  identity_snapshot=engine.identity_snapshot)
        first=self.move(qty=3,new_tag='NEW001');destination=first['destination_stock']
        self.assertEqual(engine.certificate_quantity_coverage(self.doc(HU,destination),'TYPE'),3)
        self.assertEqual(engine.certificate_quantity_coverage(self.doc(HU,'S'),'TYPE'),7)
        self.move(qty=2,destination_stock=destination,event_token='SECOND')
        self.assertEqual(self.data[HU][destination].current_qty,5)
        self.assertEqual(engine.certificate_quantity_coverage(self.doc(HU,destination),'TYPE'),5)
        for proof in identity.proofs.values():
            self.assertEqual(proof.valid_until,identity.proof.valid_until)
            self.assertEqual(proof.evidence_references,identity.proof.evidence_references)
        self.assertEqual(self.data[HU][destination].expiry_date,'2027-01-31')

    def test_real_fefo_candidate_sql_includes_repacked_physical_production_fill(self):
        import re
        import sqlite3
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.row_factory=sqlite3.Row
        db.create_function('greatest',2,max)
        db.executescript("""
            create table `tabCFG Kanban Handling Unit` (
                name text, handling_unit_id text, batch_no text, expiry_date text,
                packed_on text, creation text, available_qty real, physical_container text,
                inventory_company text, item_code text, current_warehouse text, stock_uom text,
                process_certificate_set text, identity_state text, quality_state text,
                tag_kind text, current_qty real, movement_state text, virtual_content integer,
                reusable_container_role text);
            create table tabBatch (name text, expiry_date text, item text, disabled integer);
            create table `tabCFG Kanban Container Content` (name text, content_handling_unit text, container_handling_unit text, state text);
            create table `tabCFG Kanban Operation Material Draw` (source_handling_unit text, used_qty real, remaining_qty real, material_trace text, status text);
            create table `tabCFG Kanban Manifest Line` (handling_unit text, parent text);
            create table `tabCFG Kanban Movement Manifest` (name text, state text);
        """)
        self.container('B','Production Output Container')
        for unit in self.data[HU].values():
            fields=[row[1] for row in db.execute('pragma table_info(`tabCFG Kanban Handling Unit`)')]
            db.execute('insert into `tabCFG Kanban Handling Unit` values ('+','.join('?' for _ in fields)+')',[unit.get(field) for field in fields])
        db.execute("insert into `tabCFG Kanban Container Content` values ('M','S','B','Loaded')")
        def query(sql,args,**kw):
            return [Row(dict(row)) for row in db.execute(re.sub(r'%\((\w+)\)s',r':\1',sql),args)]
        subject=functions('services/material_rotation.py',{'_rotation_candidates'},dict(frappe=Row(db=Row(sql=query))))
        rows=subject._rotation_candidates(self.doc(HU,'S'))
        self.assertEqual([(row.name,row.scan_code) for row in rows],[('S','B')])
        db.execute("update `tabCFG Kanban Handling Unit` set reusable_container_role='Logistics Container' where name='B'")
        self.assertFalse(subject._rotation_candidates(self.doc(HU,'S')))
        db.execute("update `tabCFG Kanban Handling Unit` set reusable_container_role='Production Output Container' where name='B'")
        db.execute("update `tabCFG Kanban Handling Unit` set virtual_content=1, physical_container='B' where name='S'")
        self.assertEqual(subject._rotation_candidates(self.doc(HU,'S'))[0].scan_code,'B')

    def test_whole_number_uom_and_internal_identity_scans_are_enforced(self):
        original=self.frappe.db.get_value
        self.frappe.db.get_value=lambda doctype,*args,**kw:1 if doctype=='UOM' else original(doctype,*args,**kw)
        with self.assertRaisesRegex(ValueError,'whole-number'):self.move(qty=1.5,new_tag='NEW1')
        self.data[HU]['S'].update(virtual_content=1,physical_container='A');self.load('A','S')
        with self.assertRaisesRegex(ValueError,'physical container QR'):self.move(qty=2,new_tag='NEW1')
        with self.assertRaisesRegex(ValueError,'physical container QR'):self.service.repack_source_context('S')
        self.assertFalse(self.data[LEDGER])

    def test_same_action_token_cannot_be_reused_for_a_different_source(self):
        self.move(qty=10)
        self.stock('OTHER',4);self.container('C')
        with self.assertRaisesRegex(ValueError,'different repacking data'):
            self.move(source_scan='OTHER',source_stock='OTHER',destination_scan='C',qty=4)
        self.assertEqual(self.data[HU]['OTHER'].current_qty,4);self.assertFalse(self.contents('C'))

if __name__ == '__main__':unittest.main()

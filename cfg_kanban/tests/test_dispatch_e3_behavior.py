"""Actual E3 control flow with an in-memory store; no MariaDB/ERP/concurrency acceptance."""
import ast
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
PLAN='CFG Kanban Dispatch Plan'
ALLOC='CFG Kanban Dispatch Allocation'
MANIFEST='CFG Kanban Movement Manifest'
LINE='CFG Kanban Dispatch Plan Line'
MLINE='CFG Kanban Manifest Line'
HU='CFG Kanban Handling Unit'

class Row(dict):
    __getattr__=dict.get
    __setattr__=dict.__setitem__

class Doc(Row):
    def db_set(self,field,value=None,**kwargs):
        self.update(field if isinstance(field,dict) else {field:value})
    def reload(self): pass
    def append(self,field,value):
        self.setdefault(field,[]).append(Doc(value))
    def insert(self,**kwargs):
        table=self._store.setdefault(self.doctype,{})
        self.name=f'M-{len(table)+1}'
        table[self.name]=self
        for i,line in enumerate(self.lines or [],1):
            line.name=f'{self.name}-L{i}';line.parent=self.name
            self._store.setdefault(MLINE,{})[line.name]=line
        return self

class TestDispatchE3Behavior(unittest.TestCase):
    def setUp(self):
        self.data={}
        self.plan=self.add(PLAN,'PLAN',state='Ready for Vehicle',company='B',source_warehouse='SOURCE',
            logistics_route='ROUTE',fulfilment_mode='Vehicle Delivery',dispatch_responsibility='Dispatch',
            total_requested_qty=5,destination_assignment_policy='Select Before Dispatch',lines=[])
        self.plan.lines=[self.add(LINE,'LINE',item_code='ITEM',stock_uom='Nos',requested_qty=5)]
        self.unit=self.add(HU,'TAG',handling_unit_id='TAG1',tag_kind='Stock Tag',current_qty=5,reserved_qty=5,
            inventory_company='B',current_warehouse='SOURCE',item_code='ITEM',stock_uom='Nos')
        self.allocation=self.add(ALLOC,'ALLOC',dispatch_plan='PLAN',dispatch_plan_line='LINE',state='Reserved',
            allocation_kind='Tagged Stock',handling_unit='TAG',visible_code='TAG1',allocated_qty=5,
            item_code='ITEM',stock_uom='Nos',source_company='B',source_warehouse='SOURCE',load_confirmed=0)
        self.route=self.add('CFG Kanban Logistics Route','ROUTE',active=1,route_type='Internal Warehouse Transfer',
            internal_transfer_mode='Direct Transfer',source_company='B',destination_company='B',
            source_warehouse='SOURCE',dispatch_responsibility='Dispatch')
        for i in (1,2):
            self.add('Warehouse',f'LORRY{i}',company='B',disabled=0,is_group=0,cfg_is_vehicle_warehouse=1,cfg_vehicle_reference=f'VEHICLE{i}')
            self.add('CFG Kanban Card',f'CARD{i}',qr_code=f'QR{i}',active=1,blocked=0,card_type='Location Card',
                location_purpose='Warehouse Operations',company='B',current_warehouse=f'LORRY{i}')
        self.operator=Row(employee='EMP',kanban_role='Operator',responsibilities=[Row(responsibility='Dispatch')])
        self.session=Row(name='SESSION',terminal_user='terminal')
        self.sql=Mock();self.erp_stock=Mock();self.untagged=Mock();self.events=Mock()
        frappe=Row(get_doc=self.get_doc,get_all=self.get_all,PermissionError=PermissionError,DuplicateEntryError=KeyError,
            throw=lambda msg,*args:(_ for _ in ()).throw(ValueError(msg)),
            db=Row(get_value=self.get_value,set_value=self.set_value,sql=self.sql,
                   count=lambda dt,filters:len(self.get_all(dt,filters=filters))))
        ns=dict(frappe=frappe,flt=lambda n:float(n or 0),cint=lambda n:int(n or 0),
            canonical_key=lambda *p:hashlib.sha256(json.dumps(p,default=str).encode()).hexdigest(),
            now_datetime=lambda:'2026-11-19 12:00:00',record=self.events,
            resolve_logistics_scan=lambda value:({'identity_type':'Handling Unit','name':'TAG'} if value=='TAG1' else None),
            require_operator=Mock(return_value=(self.operator,self.session)),
            assert_erp_stock=self.erp_stock,_assert_untagged_allocation_available=self.untagged,
            get_dispatch_plan=lambda name,token:dict(self.data[PLAN][name]),
            _manifest_result=lambda name,token:dict(self.data[MANIFEST][name]))
        names={'claim_dispatch_vehicle','_locked_authorized_plan','_assert_plan_authorized','_responsibilities','_view_all',
            '_vehicle_warehouse_from_scan','_vehicle_warehouse','_vehicle_loading_route','_assert_e3_allocations_ready',
            '_create_vehicle_manifest','confirm_plan_tag_loaded','confirm_dispatch_untagged_loaded',
            '_locked_plan_manifest','_confirm_allocation_loading','validate_plan_manifest_for_prepare',
            'mark_plan_manifest_prepared','mark_plan_dispatch_pending','mark_plan_loaded','release_vehicle_claim','_require_event_token'}
        nodes=[]
        for node in ast.parse((ROOT/'services/dispatch_planning.py').read_text()).body:
            if isinstance(node,ast.FunctionDef) and node.name in names:
                node.decorator_list=[];nodes.append(node)
            elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VEHICLE_LOADING_STATES' for t in node.targets): nodes.append(node)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'dispatch_planning.py','exec'),ns)
        self.fn=ns

    def add(self,doctype,name,**values):
        doc=Doc(doctype=doctype,name=name,**values);doc._store=self.data
        self.data.setdefault(doctype,{})[name]=doc;return doc

    def matches(self,row,filters):
        for key,expected in (filters or {}).items():
            actual=row.get(key)
            if isinstance(expected,list):
                op,value=expected
                if op=='!=' and actual==value:return False
            elif actual!=expected:return False
        return True

    def get_all(self,doctype,filters=None,pluck=None,**kwargs):
        rows=[row for row in self.data.get(doctype,{}).values() if self.matches(row,filters)]
        return [r.get(pluck) for r in rows] if pluck else rows

    def get_doc(self,doctype,name=None):
        if isinstance(doctype,dict):return Doc(doctype,_store=self.data)
        return self.data[doctype][name]

    def get_value(self,doctype,name,fields,**kwargs):
        if doctype=='Item':return 1
        rows=self.get_all(doctype,filters=name) if isinstance(name,dict) else [self.data.get(doctype,{}).get(name)]
        row=next((r for r in rows if r is not None),None)
        if row is None:return None
        return row if isinstance(fields,list) else row.get(fields)

    def set_value(self,doctype,name,field,value=None,**kwargs):
        for row in self.get_all(doctype,filters=name) if isinstance(name,dict) else [self.data[doctype][name]]:
            row.update(field if isinstance(field,dict) else {field:value})

    def claim(self,qr='QR1',token='CLAIM'):
        return self.fn['claim_dispatch_vehicle']('PLAN',qr,token,'SESSION')

    def manifest(self):return self.data[MANIFEST][self.plan.movement_manifest]
    def load(self):
        return self.fn['confirm_plan_tag_loaded'](self.plan.movement_manifest,'TAG1','LOAD','SESSION')

    def test_claim_creates_one_manifest_and_does_not_move_stock(self):
        self.claim();self.assertEqual(self.plan.state,'Vehicle Claimed')
        self.assertEqual(self.plan.vehicle_warehouse,'LORRY1')
        self.assertEqual(len(self.manifest().lines),1)
        self.assertEqual(self.manifest().lines[0].dispatch_qty,5)
        self.assertEqual(self.manifest().lines[0].destination_warehouse,'LORRY1')
        self.assertEqual(self.unit.current_warehouse,'SOURCE');self.assertEqual(self.unit.reserved_qty,5)
        self.assertEqual(self.sql.call_args_list[0].args[1],'PLAN')
        self.assertIn('for update',self.sql.call_args_list[0].args[0])
        self.assertNotIn('Stock Entry',self.data)

    def test_same_vehicle_replay_reuses_manifest(self):
        self.claim();first=self.plan.movement_manifest;self.claim(token='RETRY')
        self.assertEqual(self.plan.movement_manifest,first);self.assertEqual(len(self.data[MANIFEST]),1)

    def test_second_vehicle_is_rejected_after_first_claim(self):
        self.claim()
        with self.assertRaisesRegex(ValueError,'already claimed'):self.claim('QR2')
        self.assertEqual(len(self.data[MANIFEST]),1)

    def test_wrong_company_card_and_non_vehicle_are_rejected(self):
        self.data['CFG Kanban Card']['CARD1'].company='A'
        with self.assertRaisesRegex(ValueError,'belongs to A'):self.claim()
        self.data['CFG Kanban Card']['CARD1'].company='B'
        self.data['Warehouse']['LORRY1'].cfg_is_vehicle_warehouse=0
        with self.assertRaisesRegex(ValueError,'lorry Warehouse'):self.claim()
        self.assertEqual(self.plan.state,'Ready for Vehicle')

    def test_wrong_route_and_unassigned_responsibility_reject(self):
        self.route.source_company='A'
        with self.assertRaisesRegex(ValueError,'does not match'):self.claim()
        self.route.source_company='B';self.operator.responsibilities=[]
        with self.assertRaisesRegex(ValueError,'responsibility'):self.claim()
        self.assertNotIn(MANIFEST,self.data)

    def test_incomplete_plan_and_partly_reserved_tag_reject(self):
        self.allocation.allocated_qty=4
        with self.assertRaisesRegex(ValueError,'fully reserved'):self.claim()
        self.allocation.allocated_qty=5;self.unit.current_qty=6
        with self.assertRaisesRegex(ValueError,'partly reserved'):self.claim()

    def test_fixed_destination_and_git_are_not_silently_overridden(self):
        self.plan.destination_assignment_policy='Fixed';self.plan.destination_warehouse='LORRY2'
        with self.assertRaisesRegex(ValueError,'fixed to'):self.claim()
        self.plan.destination_assignment_policy='Select at Receipt'
        with self.assertRaisesRegex(ValueError,'Goods-in-Transit'):self.claim()

    def test_physical_tag_loading_is_recorded_without_second_reservation(self):
        self.claim();self.load()
        self.assertEqual(self.plan.state,'Loading');self.assertEqual(self.allocation.load_confirmed,1)
        self.assertEqual(self.manifest().lines[0].loading_confirmed,1)
        self.assertEqual(self.allocation.loaded_by_operator,'EMP')
        self.assertEqual(self.unit.reserved_qty,5);self.assertEqual(self.unit.current_warehouse,'SOURCE')
        self.assertEqual(len(self.data[ALLOC]),1)
        self.load();self.assertEqual(len(self.data[ALLOC]),1)

    def test_unreserved_or_changed_tag_is_rejected(self):
        self.claim()
        with self.assertRaisesRegex(ValueError,'exact reserved'):self.fn['confirm_plan_tag_loaded'](self.plan.movement_manifest,'OTHER','LOAD','SESSION')
        self.unit.current_qty=6
        with self.assertRaisesRegex(ValueError,'quantity changed'):self.load()
        self.assertFalse(self.allocation.load_confirmed)

    def test_prepare_requires_all_physical_confirmations(self):
        self.claim()
        with self.assertRaisesRegex(ValueError,'Confirm physical loading'):
            self.fn['validate_plan_manifest_for_prepare'](self.manifest(),self.operator)
        self.load();self.fn['validate_plan_manifest_for_prepare'](self.manifest(),self.operator)
        self.fn['mark_plan_manifest_prepared'](self.manifest().name)
        self.assertEqual(self.plan.state,'Ready to Dispatch')
        self.fn['mark_plan_dispatch_pending'](self.manifest().name)
        self.assertEqual(self.plan.state,'Dispatch Pending')
        self.assertEqual(self.unit.current_warehouse,'SOURCE')

    def test_tag_changes_after_loading_block_prepare(self):
        self.claim();self.load();self.unit.current_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'changed after loading'):
            self.fn['validate_plan_manifest_for_prepare'](self.manifest(),self.operator)

    def test_submitted_feedback_marks_loaded_and_clears_allocation_key(self):
        self.claim();self.load()
        self.fn['mark_plan_loaded'](self.manifest().name,'STE-SUBMITTED')
        self.assertEqual(self.plan.state,'Loaded');self.assertEqual(self.plan.total_loaded_qty,5)
        self.assertEqual(self.allocation.state,'Loaded');self.assertIsNone(self.allocation.active_handling_unit_key)
        self.assertEqual(self.plan.lines[0].loaded_qty,5)
        # This function is the downstream notification, not the ERP submission/tag-location hook.
        self.assertEqual(self.unit.current_warehouse,'SOURCE')

    def test_unconfirmed_feedback_is_rejected(self):
        self.claim()
        with self.assertRaisesRegex(ValueError,'not physically confirmed'):
            self.fn['mark_plan_loaded'](self.manifest().name,'STE')
        self.assertEqual(self.allocation.state,'Reserved')

    def test_release_claim_preserves_reservations_and_allows_new_lorry(self):
        self.claim();self.load();manifest=self.manifest()
        self.fn['release_vehicle_claim'](manifest,self.operator,self.session,'Wrong vehicle','CANCEL')
        self.assertEqual(manifest.state,'Cancelled');self.assertEqual(self.plan.state,'Ready for Vehicle')
        self.assertIsNone(self.plan.vehicle_warehouse);self.assertFalse(self.allocation.load_confirmed)
        self.assertEqual(self.allocation.state,'Reserved');self.assertEqual(self.unit.reserved_qty,5)
        self.claim('QR2');self.assertEqual(self.plan.vehicle_warehouse,'LORRY2')
        self.assertEqual(len(self.data[MANIFEST]),2)

    def test_erp_document_blocks_shortcut_claim_release(self):
        self.claim();self.manifest().dispatch_stock_entry='STE-DRAFT'
        with self.assertRaisesRegex(ValueError,'ERP document'):
            self.fn['release_vehicle_claim'](self.manifest(),self.operator,self.session,'Wrong vehicle','CANCEL')
        self.assertEqual(self.plan.state,'Vehicle Claimed')

    def test_untagged_requires_separate_physical_pick(self):
        self.allocation.update(allocation_kind='ERP Stock without Physical Tag',handling_unit=None,visible_code='ERP STOCK')
        self.claim();self.assertFalse(self.allocation.load_confirmed)
        self.fn['confirm_dispatch_untagged_loaded'](self.manifest().name,self.manifest().lines[0].name,'PICK','SESSION')
        self.assertTrue(self.allocation.load_confirmed);self.assertGreaterEqual(self.untagged.call_count,2)
        self.assertNotIn('Stock Entry',self.data)

    def test_blank_event_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Event Token'):self.claim(token='')
        self.assertNotIn(MANIFEST,self.data)

    def test_loading_manifest_must_belong_to_current_claim(self):
        self.claim();self.plan.movement_manifest='OTHER'
        with self.assertRaisesRegex(ValueError,'no longer identifies'):
            self.fn['confirm_plan_tag_loaded'](next(iter(self.data[MANIFEST])),'TAG1','LOAD','SESSION')

if __name__=='__main__':unittest.main()

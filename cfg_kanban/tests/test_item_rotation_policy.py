"""Offline whole-Batch selection isolation; explicit scans are tested in material_rotation."""
import re
import sqlite3
import sys
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests.test_material_actuals_yield import Row,functions


class TestBatchRotationPolicy(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.execute('create table `tabBatch` (name text,item text,cfg_rotation_excluded integer,cfg_rotation_reason text,modified text)')
        self.db.execute('insert into `tabBatch` values ("ISOLATED","RAW",1,"Set aside for later","2026-11-16")')
        self.db.execute('insert into `tabBatch` values ("AVAILABLE","RAW",0,"Released","2026-11-16")')
        self.frappe=types.ModuleType('frappe');self.frappe.PermissionError=ValueError
        self.frappe.get_meta=lambda _:Row(has_field=lambda field:True)
        self.frappe.get_roles=lambda:['Stock Manager'];self.frappe.session=Row(user='manager@example.test')
        self.frappe.throw=lambda text,*args:(_ for _ in ()).throw(ValueError(text))
        self.queries=[]
        def sql(query,values,as_dict=False):
            self.queries.append(query)
            rows=self.db.execute(query.replace('%s','?').replace(' for update',''),(values,)).fetchall()
            return [Row(row) for row in rows]
        self.frappe.db=Row(sql=sql)
        self.events=Mock()
        self.ns=functions('services/batch_rotation.py',['_installed','batch_rotation_exclusion','automatic_batch_condition','_changed','validate_batch_exclusion','audit_batch_exclusion'],{
            'frappe':self.frappe,'cint':lambda value:int(value or 0),'record':self.events,'canonical_key':lambda *x:str(x)})
    def test_isolated_and_available_batches_are_independent(self):
        self.assertEqual(self.ns['batch_rotation_exclusion']('ISOLATED')['batch'],'ISOLATED')
        self.assertIsNone(self.ns['batch_rotation_exclusion']('AVAILABLE'))
    def test_release_restores_batch_to_automatic_pool(self):
        self.db.execute('update `tabBatch` set cfg_rotation_excluded=0 where name="ISOLATED"')
        self.assertIsNone(self.ns['batch_rotation_exclusion']('ISOLATED'))
    def test_confirmation_reads_current_flag(self):
        self.ns['batch_rotation_exclusion']('ISOLATED',current=True)
        self.assertTrue(self.queries[-1].endswith(' for update'))
    def test_no_batch_or_unmigrated_schema_keeps_existing_behavior(self):
        self.assertIsNone(self.ns['batch_rotation_exclusion'](None))
        self.frappe.get_meta=lambda _:Row(has_field=lambda field:False)
        self.assertIsNone(self.ns['batch_rotation_exclusion']('ISOLATED'))
        self.assertEqual(self.ns['automatic_batch_condition']('unit'),'')
    def doc(self,old_flag=0,new_flag=1,reason='Set aside'):
        before=Row(cfg_rotation_excluded=old_flag,cfg_rotation_reason='Original isolation' if old_flag else '')
        return Row(name='ISOLATED',item='RAW',modified='NOW',cfg_rotation_excluded=new_flag,cfg_rotation_reason=reason,
                   is_new=lambda:False,get_doc_before_save=lambda:before)
    def test_only_manager_can_change_isolation(self):
        self.frappe.get_roles=lambda:['Stock User']
        with self.assertRaisesRegex(ValueError,'Manager'):self.ns['validate_batch_exclusion'](self.doc())
    def test_release_requires_new_reason(self):
        with self.assertRaisesRegex(ValueError,'new release reason'):
            self.ns['validate_batch_exclusion'](self.doc(1,0,'Original isolation'))
        self.ns['validate_batch_exclusion'](self.doc(1,0,'Available for general use'))
    def test_audit_records_actor_batch_and_before_after(self):
        self.ns['audit_batch_exclusion'](self.doc())
        data=self.events.call_args.kwargs
        self.assertEqual(data['reference_name'],'ISOLATED')
        self.assertEqual(data['payload']['isolated_before'],0)
        self.assertEqual(data['payload']['isolated_after'],1)
        self.assertEqual(data['terminal_user'],'manager@example.test')
    def test_dispatch_suggestions_skip_all_tags_of_isolated_batch(self):
        self.db.execute('create table `tabCFG Kanban Handling Unit` (name text,handling_unit_id text,batch_no text,current_qty real,available_qty real,stock_uom text,packed_on text,expiry_date text,creation text,identity_state text,quality_state text,inventory_company text,current_warehouse text,item_code text,reserved_qty real)')
        self.db.execute('create table `tabCFG Kanban Manifest Line` (handling_unit text,parent text)')
        self.db.execute('create table `tabCFG Kanban Movement Manifest` (name text,state text)')
        for name,batch,date in [('A','ISOLATED','2026-01-01'),('B','ISOLATED','2026-01-02'),('C','AVAILABLE','2026-02-01')]:
            self.db.execute('insert into `tabCFG Kanban Handling Unit` values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(name,name,batch,5,5,'Nos',date,date,date,'Active','Released','COMP','WH','RAW',0))
        module=types.ModuleType('cfg_kanban.services.batch_rotation');module.automatic_batch_condition=self.ns['automatic_batch_condition'];module.automatic_tag_condition=lambda alias:''
        frappe=types.ModuleType('frappe');frappe.db=Row(sql=lambda query,values,**kw:self.db.execute(re.sub(r'%\((\w+)\)s',r':\1',query),values).fetchall())
        fn=functions('services/dispatch_planning.py',['_suggested_tags'],{'frappe':frappe})['_suggested_tags']
        with patch.dict(sys.modules,{module.__name__:module}):
            for mode in ('FIFO','FEFO'):
                rows=fn(Row(stock_rotation_policy=mode,company='COMP',source_warehouse='WH'),Row(item_code='RAW',stock_uom='Nos',batch_no=None))
                self.assertEqual([row[0] for row in rows],['C'])

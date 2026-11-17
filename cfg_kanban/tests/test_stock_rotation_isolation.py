"""Offline tag/bin isolation service, SQL selection, propagation and FEFO tests.

No real Frappe hooks, MariaDB locking/rollback, ERP stock or kiosk acceptance.
"""
import copy
import json
import re
import sqlite3
import sys
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests.test_container_repacking import RepackHarness,Row,functions,HU,CONTENT,EVENT

POLICY_FUNCTIONS={'_tag_installed','tag_rotation_exclusions','automatic_tag_condition','validate_handling_unit_isolation'}

class TestStockRotationIsolation(RepackHarness):
    def setUp(self):
        super().setUp()
        self.frappe.get_meta=lambda dt:Row(has_field=lambda field:True)
        self.frappe.only_for=Mock();self.frappe.session=Row(user='manager')
        self.profile=Row(employee='SUP',kanban_role='Supervisor',allowed_operations=[],allowed_workstations=[])
        self.auth=Mock(return_value=(self.profile,Row(name='SESSION',terminal_user='terminal')))
        self.policy=functions('services/batch_rotation.py',POLICY_FUNCTIONS,dict(
            frappe=self.frappe,cint=lambda value:int(value or 0),TAG_FLAG='rotation_excluded',TAG_REASON='rotation_isolation_reason'))
        ns=dict(self.service)
        ns.update(_tag_installed=self.policy._tag_installed,tag_rotation_exclusions=self.policy.tag_rotation_exclusions,
                  batch_rotation_exclusion=lambda batch,**kw: {'batch':batch,'reason':'Batch isolated'} if batch=='ISOLATED' else None,
                  require_operator=self.auth,cint=lambda value:int(value or 0))
        self.isolation=functions('services/rotation_isolation.py',None,ns)
        for row in self.data[HU].values():row.update(rotation_excluded=0,rotation_isolation_reason=None)

    def sql(self,query,args=None,as_dict=False):
        if query.startswith('select content_handling_unit, loaded_on from'):
            return [Row(content_handling_unit=row.content_handling_unit,loaded_on=row.loaded_on) for row in self.contents(args)]
        if query.startswith('select content_handling_unit, container_handling_unit'):
            return [Row(content_handling_unit=row.content_handling_unit,container_handling_unit=row.container_handling_unit)
                    for row in self.data[CONTENT].values() if row.content_handling_unit in args and row.state=='Loaded']
        if query.startswith('select name, handling_unit_id,'):
            return [Row(copy.deepcopy(self.data[HU][name])) for name in args if name in self.data[HU]]
        if query.startswith('select tag_kind, rotation_excluded'):
            return [Row(copy.deepcopy(self.data[HU][args]))] if args in self.data[HU] else []
        return super().sql(query,args,as_dict)

    def context(self,scan='S'):return self.isolation.get_rotation_isolation_context(scan,'TOKEN')
    def change(self,scan='S',target=None,excluded=1,reason='Set aside for later',token='ISO',context=None):
        context=context or self.context(scan)
        return self.isolation.set_rotation_isolation(scan,target or context['targets'][0]['name'],excluded,reason,context['signature'],token,'TOKEN')

    def test_nonbatch_tag_isolated_and_released_without_balance_or_identity_change(self):
        self.data[HU]['S'].batch_no=None;before=copy.deepcopy(self.data[HU]['S'])
        result=self.change();self.assertTrue(result['excluded'])
        self.assertIn('S',self.policy.tag_rotation_exclusions(['S']))
        self.change(excluded=0,reason='Ready for general use',token='RELEASE')
        self.assertFalse(self.policy.tag_rotation_exclusions(['S']))
        for field in ('current_qty','available_qty','expiry_date','process_certificate_set','batch_no','item_code','quality_state'):
            self.assertEqual(self.data[HU]['S'][field],before[field])
        self.assertEqual(len(self.data[EVENT]),2)
        self.auth.assert_any_call('TOKEN','override')

    def test_tag_exclusion_is_local_not_the_whole_item_or_batch(self):
        self.stock('S2',3);self.change()
        self.assertEqual(set(self.policy.tag_rotation_exclusions(['S','S2'])),{'S'})

    def test_bin_rule_affects_current_and_future_loads_but_not_stock_moved_out(self):
        self.load('A','S');self.change(scan='A',target='A')
        self.assertEqual(self.data[HU]['A'].rotation_excluded,1)
        rules=self.policy.tag_rotation_exclusions(['S'])['S']['rules']
        self.assertEqual(rules[0]['scope'],'Bin');self.assertEqual(rules[0]['handling_unit'],'A')
        self.stock('NEWLOAD',2);self.load('A','NEWLOAD')
        self.assertIn('NEWLOAD',self.policy.tag_rotation_exclusions(['NEWLOAD']))
        self.service._close(self.membership('S'),{},'MOVE','Moved out of bin')
        self.assertNotIn('S',self.policy.tag_rotation_exclusions(['S']))
        self.assertIn('NEWLOAD',self.policy.tag_rotation_exclusions(['NEWLOAD']))
        self.assertEqual(self.data[HU]['S'].get('rotation_excluded',0),0)

    def test_release_bin_does_not_release_a_local_tag_or_batch_rule(self):
        self.data[HU]['S'].batch_no='ISOLATED';self.load('A','S')
        self.change(scan='A',target='A');self.change(scan='A',target='S',token='TAG')
        self.change(scan='A',target='A',excluded=0,reason='Bin available',token='RELEASE')
        target=next(row for row in self.context('A')['targets'] if row['name']=='S')
        self.assertTrue(target['excluded']);self.assertTrue(target['effective_isolation']);self.assertTrue(target['batch_isolation'])
        self.change(scan='A',target='S',excluded=0,reason='Tag available',token='RELEASE-TAG')
        target=next(row for row in self.context('A')['targets'] if row['name']=='S')
        self.assertFalse(target['effective_isolation']);self.assertTrue(target['batch_isolation'])

    def test_empty_bin_can_be_isolated_before_it_receives_stock(self):
        self.change(scan='B');self.load('B','S')
        self.assertIn('S',self.policy.tag_rotation_exclusions(['S']))

    def test_same_event_replays_after_flag_changes_and_changed_payload_is_rejected(self):
        context=self.context();first=self.change(context=context)
        self.assertTrue(self.change(context=context)['duplicate']);self.assertEqual(len(self.data[EVENT]),1)
        self.assertEqual(first['name'],'S')
        with self.assertRaisesRegex(ValueError,'different isolation data'):self.change(reason='Different',context=context)

    def test_stale_context_wrong_target_and_changed_contents_rejected(self):
        context=self.context();self.data[HU]['S'].current_qty=9
        with self.assertRaisesRegex(ValueError,'reread'):self.change(context=context)
        with self.assertRaisesRegex(ValueError,'displayed'):self.change(target='B')
        self.load('A','S');context=self.context('A');self.stock('MORE',1);self.load('A','MORE')
        with self.assertRaisesRegex(ValueError,'reread'):self.change(scan='A',context=context)

    def test_release_requires_new_reason_and_bad_role_cannot_change(self):
        self.change()
        with self.assertRaisesRegex(ValueError,'new release reason'):self.change(excluded=0,token='REL')
        self.profile.kanban_role='Operator'
        with self.assertRaisesRegex(ValueError,'Supervisor'):self.change(excluded=0,token='REL',reason='Done')
        self.profile.kanban_role='Supervisor';self.profile.allowed_operations=[Row(operation='Pack')]
        with self.assertRaisesRegex(ValueError,'unrestricted'):self.context()

    def test_bin_targets_include_exact_each_fill_and_refuse_other_wip_roles(self):
        self.load('A','S');self.stock('S2',3);self.load('A','S2')
        self.assertEqual([row['name'] for row in self.context('A')['targets']],['A','S','S2'])
        self.data[HU]['A'].reusable_container_role='Standard Quantity WIP Bin'
        with self.assertRaisesRegex(ValueError,'separate operation WIP'):self.context('A')

    def test_existing_doc_cannot_bypass_controlled_action_by_saving_fields(self):
        before=Row(rotation_excluded=0,rotation_isolation_reason=None)
        doc=Row(rotation_excluded=1,rotation_isolation_reason='Bypass',is_new=lambda:False,get_doc_before_save=lambda:before)
        with self.assertRaisesRegex(ValueError,'FEFO / FIFO Isolation'):self.policy.validate_handling_unit_isolation(doc)

    def test_new_split_and_replacement_inherit_local_tag_rule(self):
        self.change()
        for source in ({'parent_handling_unit':'S'},{'replacement_of':'S'},{'origin_reference_doctype':HU,'origin_reference_name':'S'}):
            with self.subTest(source=source):
                child=Row(tag_kind='Main Stock Tag',rotation_excluded=0,is_new=lambda:True,**source)
                self.policy.validate_handling_unit_isolation(child)
                self.assertEqual(child.rotation_excluded,1);self.assertEqual(child.rotation_isolation_reason,'Set aside for later')

    def test_bin_rule_is_not_copied_to_stock_when_new_load_is_created(self):
        self.change(scan='A')
        child=Row(tag_kind='Main Stock Tag',origin_reference_doctype=HU,origin_reference_name='A',is_new=lambda:True)
        self.policy.validate_handling_unit_isolation(child);self.assertEqual(child.rotation_excluded,0)

    def test_real_repacking_keeps_isolation_and_rejects_merging_with_nonisolated_tag(self):
        from cfg_kanban.tests.test_logistics_stock_identity import TestLogisticsStockIdentity
        fx=TestLogisticsStockIdentity();fx.setUp();self.addCleanup(fx.doCleanups)
        self.change();first=self.move(qty=3,new_tag='NEW1')
        destination=self.data[HU][first['destination_stock']];self.assertEqual(destination.rotation_excluded,1)
        with self.assertRaisesRegex(ValueError,'isolated and non-isolated'):
            fx.service.assert_merge_compatible(self.doc(HU,'S'),Row(rotation_excluded=0))
        with self.assertRaisesRegex(ValueError,'isolated and non-isolated'):
            fx.service.inherit_split_certificates(self.doc(HU,'S'),Row(rotation_excluded=0,process_certificate_set='CERTSET'),1,'MERGE')

    def test_nonbatch_fefo_omits_isolated_earlier_tag_but_accepts_explicit_valid_scan(self):
        from cfg_kanban.tests.test_material_rotation_behavior import TestMaterialRotationBehavior
        fx=TestMaterialRotationBehavior();fx.setUp();self.addCleanup(fx.doCleanups)
        fx.batch_controlled=False;fx.unit.batch_no=None
        for row in fx.candidates:row.batch_no=None
        self.stock('TAG-EARLY',5);self.stock('TAG-LATE',5)
        self.data[HU]['TAG-EARLY'].update(rotation_excluded=1,rotation_isolation_reason='Set aside')
        fx.service.tag_rotation_exclusions=self.policy.tag_rotation_exclusions
        result=fx.service.validate_material_rotation(fx.execution,fx.unit,current=True)
        self.assertIsNone(result['rotation_override'])
        self.data[HU]['TAG-EARLY'].rotation_excluded=0
        with self.assertRaisesRegex(ValueError,'FEFO requires'):fx.service.validate_material_rotation(fx.execution,fx.unit)
        self.data[HU]['TAG-LATE'].update(rotation_excluded=1,rotation_isolation_reason='Deliberate use later')
        result=fx.service.validate_material_rotation(fx.execution,fx.unit)
        self.assertEqual(result['rotation_exemption']['tag'],'TAG-LATE');self.assertIsNone(result['rotation_override'])
        fx.unit.expiry_date='2026-11-01'
        with self.assertRaisesRegex(ValueError,'expired'):fx.service.validate_material_rotation(fx.execution,fx.unit)

    def test_current_reads_lock_both_stock_and_loaded_bin_rules(self):
        self.load('A','S');self.change(scan='A')
        original=self.frappe.db.sql;queries=[]
        def query(sql,*args,**kw):queries.append(sql);return original(sql,*args,**kw)
        self.frappe.db.sql=query
        self.policy.tag_rotation_exclusions(['S'],current=True)
        self.assertEqual(len(queries),3)
        self.assertTrue(all(sql.endswith(' for update') for sql in queries))

    def test_flag_changed_while_waiting_for_lock_rejects_stale_confirmation(self):
        context=self.context();original=self.frappe.db.sql
        def query(sql,*args,**kw):
            if sql.startswith('select * from `tabCFG Kanban Handling Unit`'):
                self.data[HU]['S'].update(rotation_excluded=1,rotation_isolation_reason='Another supervisor')
            return original(sql,*args,**kw)
        self.frappe.db.sql=query
        with self.assertRaisesRegex(ValueError,'reread'):self.change(context=context)
        self.assertEqual(self.data[HU]['S'].rotation_isolation_reason,'Another supervisor')
        self.assertFalse(self.data[EVENT])

    def test_desk_manager_path_and_override_permission_rejection(self):
        context=self.isolation.get_rotation_isolation_context('S')
        self.isolation.set_rotation_isolation('S','S',1,'Manager decision',context['signature'],'DESK')
        self.frappe.only_for.assert_called_with(('Stock Manager','Manufacturing Manager','System Manager'))
        audit=json.loads(next(iter(self.data[EVENT].values())).payload_json)
        self.assertEqual(audit['reason_after'],'Manager decision')
        self.auth.side_effect=ValueError('not authorized to override')
        with self.assertRaisesRegex(ValueError,'override'):
            self.isolation.set_rotation_isolation('S','S',0,'Release','OLD','DENIED','TOKEN')

    def test_matching_printed_expiry_suggestions_skip_tag_and_bin_isolation(self):
        from cfg_kanban.tests.test_manufacture_expiry import TestManufactureExpiryAndCohorts
        fx=TestManufactureExpiryAndCohorts();fx.setUp();self.addCleanup(fx.doCleanups)
        fx.cycles['PROCESS-CYCLE']=[fx.cohort('2027-01-01')]
        fx.fx.proofs.append(Row(fx.fx.proof,name='EARLY-CERT',handling_unit='EARLY',kanban_cycle='EARLY-CYCLE',source_reference_name='EARLY-REPACK'))
        fx.fx.runs.append(Row(fx.fx.run,name='EARLY-RUN',output_handling_unit='EARLY',kanban_cycle='EARLY-CYCLE',repack_stock_entry='EARLY-REPACK',printed_expiry='2027-01-01'))
        rotation=types.ModuleType('cfg_kanban.services.material_rotation')
        rotation._rotation_candidates=lambda unit:[Row(name='EARLY',scan_code='SHOULD-NOT-SUGGEST',batch_no=None,expiry_date=None,batch_expiry=None)]
        policy=types.ModuleType('cfg_kanban.services.batch_rotation');policy.tag_rotation_exclusions=self.policy.tag_rotation_exclusions
        self.stock('EARLY',2);self.load('A','EARLY');self.change(scan='A')
        with patch.dict(sys.modules,{rotation.__name__:rotation,policy.__name__:policy}):
            with self.assertRaises(ValueError) as caught:fx.check()
        self.assertIn('none available',str(caught.exception));self.assertNotIn('SHOULD-NOT-SUGGEST',str(caught.exception))

    def test_fill_choices_include_physical_source_expiry_and_loaded_time(self):
        self.stock('ORIGIN',2)
        self.data[HU]['S'].update(virtual_content=1,physical_container='A',origin_reference_doctype=HU,origin_reference_name='ORIGIN')
        self.load('A','S')
        target=self.context('A')['targets'][1]
        self.assertEqual(target['visible_code'],'A');self.assertEqual(target['source_code'],'ORIGIN')
        self.assertEqual(target['expiry_date'],'2027-01-31');self.assertTrue(target['loaded_on'])


class TestIsolationSelectionSQL(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('''
            create table `tabCFG Kanban Handling Unit` (name text,handling_unit_id text,tag_kind text,rotation_excluded integer,rotation_isolation_reason text,modified text,item_code text,batch_no text,current_qty real,available_qty real,stock_uom text,packed_on text,expiry_date text,creation text,identity_state text,quality_state text,inventory_company text,current_warehouse text,reserved_qty real);
            create table `tabCFG Kanban Container Content` (name text,content_handling_unit text,container_handling_unit text,state text);
            create table tabBatch (name text,item text,cfg_rotation_excluded integer,cfg_rotation_reason text,modified text);
            create table `tabCFG Kanban Manifest Line` (handling_unit text,parent text);
            create table `tabCFG Kanban Movement Manifest` (name text,state text);
            insert into tabBatch values ('BATCH','RAW',1,'Batch isolated','NOW');
        ''')
        self.frappe=Row(get_meta=lambda dt:Row(has_field=lambda field:True),throw=lambda message:(_ for _ in ()).throw(ValueError(message)))
        def sql(query,values,**kw):
            query=re.sub(r'%\((\w+)\)s',r':\1',query).replace('%s','?').replace(' for update','')
            if not isinstance(values,(dict,list,tuple)):values=(values,)
            return [Row(dict(row)) for row in self.db.execute(query,values)]
        self.frappe.db=Row(sql=sql)
        self.policy=functions('services/batch_rotation.py',POLICY_FUNCTIONS|{'_installed','batch_rotation_exclusion','automatic_batch_condition'},dict(frappe=self.frappe,cint=lambda value:int(value or 0),TAG_FLAG='rotation_excluded',TAG_REASON='rotation_isolation_reason'))
        for name,kind,isolated,batch in [('BIN','Reusable Container',1,None),('TAG','Main Stock Tag',1,None),('IN-BIN','Main Stock Tag',0,None),('NORMAL','Main Stock Tag',0,None),('BATCHTAG','Main Stock Tag',0,'BATCH')]:
            self.db.execute('insert into `tabCFG Kanban Handling Unit` values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(name,name,kind,isolated,'Set aside' if isolated else None,'NOW','RAW',batch,5,5,'Nos','2026-01-01','2027-01-01','2026-01-01','Active','Released','TEST','WH',0))
        self.db.execute("insert into `tabCFG Kanban Container Content` values ('M','IN-BIN','BIN','Loaded')")

    def test_actual_dispatch_sql_combines_batch_tag_and_bin_exclusions(self):
        module=types.ModuleType('cfg_kanban.services.batch_rotation');module.automatic_batch_condition=self.policy.automatic_batch_condition;module.automatic_tag_condition=self.policy.automatic_tag_condition
        subject=functions('services/dispatch_planning.py',{'_suggested_tags'},dict(frappe=self.frappe))
        with patch.dict(sys.modules,{module.__name__:module}):
            for mode in ('FIFO','FEFO'):
                rows=subject._suggested_tags(Row(stock_rotation_policy=mode,company='TEST',source_warehouse='WH'),Row(item_code='RAW',stock_uom='Nos',batch_no=None))
                self.assertEqual([row.name for row in rows],['NORMAL'])

    def test_effective_rules_keep_independent_tag_and_active_bin_evidence(self):
        self.db.execute("update `tabCFG Kanban Handling Unit` set rotation_excluded=1,rotation_isolation_reason='Tag also isolated' where name='IN-BIN'")
        rules=self.policy.tag_rotation_exclusions(['IN-BIN'],current=True)['IN-BIN']['rules']
        self.assertEqual([rule['scope'] for rule in rules],['Tag','Bin'])
        self.db.execute("update `tabCFG Kanban Container Content` set state='Unloaded'")
        rules=self.policy.tag_rotation_exclusions(['IN-BIN'])['IN-BIN']['rules']
        self.assertEqual([rule['scope'] for rule in rules],['Tag'])

    def test_unmigrated_schema_does_not_issue_new_field_sql(self):
        self.frappe.get_meta=lambda dt:Row(has_field=lambda field:False)
        self.assertEqual(self.policy.tag_rotation_exclusions(['TAG']),{})
        self.assertEqual(self.policy.automatic_tag_condition('unit'),'')

if __name__=='__main__':unittest.main()

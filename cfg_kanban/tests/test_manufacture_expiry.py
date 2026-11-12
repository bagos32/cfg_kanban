"""Offline expiry selection and Process Card cycle cohort tests."""
from datetime import date,timedelta
import json
import sys
import types
import unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests import test_certificate_print_identity as printing_fixture
from cfg_kanban.tests.test_material_actuals_yield import ROOT,Row,functions,frappe_double
from cfg_kanban.tests.test_material_run_receipts import Document


class TestManufactureExpiryAndCohorts(unittest.TestCase):
    def setUp(self):
        self.fx=printing_fixture.TestCertificatePrintIdentity();self.fx.setUp()
        self.frappe=self.fx.frappe;self.fx.unit.inventory_company='CFG'
        self.pending=[];self.posted=[Row(handling_unit='RM00005',certificate_set='SET',item_code='BAG',stock_uom='Nos')]
        self.cycles={};self.commands=[];self.batch_expiry='2027-06-01'
        self.frappe.get_meta=lambda doctype:Row(has_field=lambda field:True)
        self.frappe.get_all.side_effect=self.get_all
        self.frappe.get_doc.side_effect=self.get_doc
        self.frappe.db.get_value.side_effect=self.get_value
        self.frappe.db.sql.side_effect=self.sql
        self.ns=functions('services/manufacture_expiry.py',[
            'manufacture_printed_expiry_sources','selected_manufacture_printed_expiry',
            'validate_manufacture_printed_expiry','assert_process_cycle_printed_expiry'],{
                'frappe':self.frappe,'certificate_output_evidence':self.fx.ns['certificate_output_evidence'],
                'printed_expiry_dates':self.fx.ns['printed_expiry_dates'],
                'cint':lambda x:int(x or 0),'getdate':lambda x:x if isinstance(x,date) else date.fromisoformat(str(x)[:10]),
                'today':lambda:'2026-11-12'})
        self.execution=Row(name='EXEC',kanban_cycle='PROCESS-CYCLE')

    def get_all(self,doctype,**kwargs):
        if doctype=='CFG Kanban Operation Material Draw':return [row for row in self.pending if row.used_qty>0 and row.status in ('Used','Partially Used','Carry Forward')]
        if doctype=='CFG ERP Command':return self.commands
        return self.fx.get_all(doctype,**kwargs)

    def get_doc(self,doctype,name):
        if doctype=='CFG Kanban Handling Unit':return self.fx.unit
        if doctype=='Work Order':return Row(production_item='FG')
        return self.fx.proof

    def get_value(self,doctype,name,fields=None,**kwargs):
        if doctype=='Batch':return self.batch_expiry
        return self.fx.get_value(doctype,name,fields,**kwargs)

    def sql(self,query,params,**kwargs):
        if 'from `tabCFG Kanban Operation Material Draw`' in query:return self.cycles.get(params,[])
        return self.posted

    def choose(self):return self.ns['selected_manufacture_printed_expiry']('WO','CFG')
    def check(self,current=False):return self.ns['assert_process_cycle_printed_expiry'](self.execution,self.fx.unit,current=current)
    def cohort(self,expiry='2027-06-01',item='BAG'):
        return Row(source_handling_unit='OLD',item_code=item,stock_uom='Nos',material_rotation_evidence=json.dumps({'printed_expiry_date':expiry}))

    def test_new_floor_controls_have_global_dispatch_labels_and_native_validation(self):
        api=(ROOT/'api/operator.py').read_text()
        panel=(ROOT/'cfg_kanban/page/kanban_operator/kanban_operator.js').read_text()
        for command in ('RECEIPT_USE_PRINTED_EXPIRY','RECEIPT_STANDARD_EXPIRY','RECEIPT_BATCH'):
            self.assertIn('CFG:CMD:'+command,api)
            self.assertIn(command+': () => receipt_expiry_command(',panel)
        feedback=(ROOT/'integrations/erp_feedback.py').read_text()
        self.assertIn('validate_manufacture_printed_expiry(doc)',feedback)

    def test_finished_batch_date_comes_from_actual_consumption(self):
        expiry,evidence=self.choose();self.assertEqual(expiry,'2027-06-01')
        self.assertEqual(evidence[0]['handling_unit'],'RM00005')

    def test_unused_draws_and_cancelled_work_do_not_supply_expiry(self):
        self.posted=[]
        self.pending=[Row(used_qty=0,status='Carry Forward'),Row(used_qty=10,status='Cancelled')]
        with self.assertRaisesRegex(ValueError,'No posted printing expiry'):self.choose()

    def test_revoked_printing_remains_visible_for_fefo_but_cannot_supply_new_batch(self):
        self.fx.proof.status='Revoked'
        self.assertEqual(self.fx.evidence()[0]['printed_expiry'],'2027-06-01')
        with self.assertRaisesRegex(ValueError,'provenance is revoked'):self.choose()

    def test_positive_pending_receipt_usage_supplies_expiry(self):
        self.posted=[]
        self.pending=[Row(name='DRAW',used_qty=10,status='Used',source_handling_unit='RM00005',item_code='BAG',stock_uom='Nos')]
        self.assertEqual(self.choose()[0],'2027-06-01')

    def test_native_usage_uses_its_saved_certificate_dimension(self):
        self.fx.unit.process_certificate_set='OTHER-CURRENT-SET'
        self.assertEqual(self.choose()[0],'2027-06-01')

    def test_mixed_dates_and_expired_printing_are_rejected(self):
        self.fx.progress=[Row(name='P1',sequence=1,certificate_process_run='RUN',status='ERP Posted',printed_expiry='2027-07-01')]
        with self.assertRaisesRegex(ValueError,'different printed expiries'):self.choose()
        self.fx.progress=[];self.fx.run.printed_expiry='2026-11-11'
        with self.assertRaisesRegex(ValueError,'has passed'):self.choose()

    def test_first_source_sets_cycle_evidence_and_same_date_can_continue(self):
        self.assertEqual(self.check()['printed_expiry_date'],'2027-06-01')
        self.cycles['PROCESS-CYCLE']=[self.cohort()]
        self.assertEqual(self.check()['printed_expiry_cycle'],'PROCESS-CYCLE')

    def test_next_process_card_cycle_can_use_a_different_expiry(self):
        self.cycles['PROCESS-CYCLE']=[self.cohort('2027-01-01')]
        self.execution.kanban_cycle='NEW-PROCESS-CYCLE'
        self.assertEqual(self.check()['printed_expiry_date'],'2027-06-01')

    def test_different_date_suggests_matching_source_or_close_cycle(self):
        self.cycles['PROCESS-CYCLE']=[self.cohort('2027-01-01')]
        self.fx.proofs.append(Row(self.fx.proof,name='EARLY-CERT',handling_unit='EARLY',kanban_cycle='EARLY-CYCLE',source_reference_name='EARLY-REPACK'))
        self.fx.runs.append(Row(self.fx.run,name='EARLY-RUN',output_handling_unit='EARLY',kanban_cycle='EARLY-CYCLE',repack_stock_entry='EARLY-REPACK',printed_expiry='2027-01-01'))
        rotation=types.ModuleType('cfg_kanban.services.material_rotation')
        rotation._rotation_candidates=Mock(return_value=[Row(name='EARLY',scan_code='RM-MATCH',batch_no=None,expiry_date=None,batch_expiry=None)])
        with patch.dict(sys.modules,{rotation.__name__:rotation}):
            with self.assertRaisesRegex(ValueError,'RM-MATCH.*close the current cycle/batch'):self.check()
        self.assertEqual(self.frappe.db.sql.call_args.args[1],'PROCESS-CYCLE')

    def test_preview_does_not_take_the_confirmation_lock(self):
        self.check();self.assertNotIn('for update',self.frappe.db.sql.call_args.args[0])
        self.check(current=True);self.assertIn('for update',self.frappe.db.sql.call_args.args[0])

    def test_plain_other_material_does_not_need_a_packaging_print_date(self):
        self.cycles['PROCESS-CYCLE']=[self.cohort()]
        self.fx.unit.item_code='OTHER-MATERIAL'
        self.assertIsNone(self.check()['printed_expiry_date'])

    def test_same_packaging_item_cannot_drop_its_printed_evidence_mid_cycle(self):
        self.cycles['PROCESS-CYCLE']=[self.cohort()]
        self.fx.unit.process_certificate_set=None
        with self.assertRaisesRegex(ValueError,'matching printed expiry'):self.check()

    def test_native_submit_rechecks_selected_date_and_existing_finished_batch(self):
        expiry,evidence=self.choose()
        self.commands=[Row(request_payload=json.dumps({'use_printed_expiry':1,'printed_expiry':expiry,'printed_expiry_evidence':evidence}))]
        doc=Document(name='RECEIPT',purpose='Manufacture',cfg_kanban_cycle='MAIN-CYCLE',work_order='WO',company='CFG',
            items=[Row(item_code='FG',s_warehouse=None,t_warehouse='FG STORE',batch_no='FG-BATCH')])
        self.ns['validate_manufacture_printed_expiry'](doc)
        self.batch_expiry='2027-08-01'
        with self.assertRaisesRegex(ValueError,'Finished Batch expiry'):self.ns['validate_manufacture_printed_expiry'](doc)
        self.batch_expiry=expiry;self.fx.run.printed_expiry='2027-07-01'
        with self.assertRaisesRegex(ValueError,'evidence changed'):self.ns['validate_manufacture_printed_expiry'](doc)

    def test_read_only_context_stays_available_when_consumption_needs_recovery(self):
        self.posted=[];self.fx.unit.inventory_company='OTHER'
        self.pending=[Row(name='DRAW',used_qty=10,status='Used',source_handling_unit='RM00005',item_code='BAG',stock_uom='Nos')]
        self.assertEqual(self.ns['manufacture_printed_expiry_sources']('WO','CFG',strict=False)['dates'],[])
        with self.assertRaisesRegex(ValueError,'source identity changed'):self.choose()

    def test_gateway_creates_native_output_batch_with_recomputed_printed_expiry(self):
        expiry,evidence=self.choose()
        created=[]
        entry=Document(name='RECEIPT',company='CFG',work_order='WO',docstatus=0,purpose='Manufacture',
            items=[Row(name='OUT',item_code='FG',s_warehouse=None,t_warehouse='FG STORE',batch_no=None)])
        entry.insert=Mock(return_value=entry);entry.submit=Mock()
        def document(doctype,name=None):
            if isinstance(doctype,Document):return doctype
            if isinstance(doctype,dict):
                created.append(doctype)
                return Row(insert=lambda **kwargs:Row(name=doctype['batch_id']))
            if doctype=='Work Order':return Row(name='WO',docstatus=1,production_item='FG',company='CFG')
            return self.get_doc(doctype,name)
        original_get_value=self.get_value
        def value(doctype,name,fields=None,**kwargs):
            if doctype=='Batch' and isinstance(fields,list):return None
            if doctype=='Item':return Row(has_batch_no=1,shelf_life_in_days=30)
            return original_get_value(doctype,name,fields,**kwargs)
        self.frappe.get_doc.side_effect=document;self.frappe.db.get_value.side_effect=value
        mapper=types.ModuleType('erpnext.manufacturing.doctype.work_order.work_order');mapper.make_stock_entry=Mock(return_value=entry)
        actuals=types.ModuleType('cfg_kanban.services.material_run_receipts');actuals.reconcile_manufacture_material_runs=Mock()
        printing=types.ModuleType('cfg_kanban.services.manufacture_expiry');printing.selected_manufacture_printed_expiry=self.ns['selected_manufacture_printed_expiry']
        ns=functions('integrations/erp_gateway.py',['create_production_manufacture_receipt','_resolve_manufacture_batch'],{
            'frappe':self.frappe,'flt':lambda x:float(x or 0),'cint':lambda x:int(x or 0),'cstr':lambda x:str(x or ''),
            'getdate':self.ns['getdate'],'today':self.ns['today'],
            '_exclude_submitted_wip_bin_returns':Mock()})
        with patch.dict(sys.modules,{mapper.__name__:mapper,actuals.__name__:actuals,printing.__name__:printing}):
            result=ns['create_production_manufacture_receipt'](Row(kanban_cycle='CYCLE',source_signal=None),{
                'work_order':'WO','output_qty':5,'target_warehouse':'FG STORE','batch_no':'FINISHED-NEW',
                'use_printed_expiry':1,'printed_expiry':expiry,'printed_expiry_evidence':evidence})
        self.assertEqual(created[0]['expiry_date'],'2027-06-01')
        self.assertEqual(result.items[0].batch_no,'FINISHED-NEW')
        entry.insert.assert_called_once();entry.submit.assert_not_called()

    def test_standard_receipt_does_not_change_expiry_policy(self):
        self.commands=[Row(request_payload=json.dumps({'use_printed_expiry':0}))]
        doc=Document(name='RECEIPT',purpose='Manufacture',cfg_kanban_cycle='MAIN-CYCLE')
        self.ns['validate_manufacture_printed_expiry'](doc)
        self.frappe.db.sql.assert_not_called()


class TestFinishedBatchPrintedExpiry(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double();self.existing=None;self.created=[]
        self.item=Row(has_batch_no=1,shelf_life_in_days=30)
        self.frappe.db.get_value.side_effect=lambda doctype,*args,**kwargs:self.existing if doctype=='Batch' else self.item
        def create(values):
            self.created.append(values)
            return Row(insert=lambda **kwargs:Row(name=values['batch_id']))
        self.frappe.get_doc.side_effect=create
        self.ns=functions('integrations/erp_gateway.py',['_resolve_manufacture_batch'],{
            'frappe':self.frappe,'cstr':lambda x:str(x or ''),'cint':lambda x:int(x or 0),
            'getdate':lambda x:x if isinstance(x,date) else date.fromisoformat(str(x)[:10]),
            'today':lambda:'2026-11-12','add_days':lambda day,n:str(date.fromisoformat(day)+timedelta(days=n))})

    def test_new_batch_uses_selected_printed_expiry_instead_of_default_shelf_life(self):
        self.ns['_resolve_manufacture_batch']('FG','NEW','2027-06-01')
        self.assertEqual(self.created[0]['expiry_date'],'2027-06-01')

    def test_standard_choice_preserves_native_shelf_life_default(self):
        self.ns['_resolve_manufacture_batch']('FG','NEW')
        self.assertEqual(self.created[0]['expiry_date'],'2026-12-12')

    def test_existing_batch_must_match_and_is_never_rewritten(self):
        self.existing=Row(name='EXISTING',item='FG',expiry_date='2027-06-01')
        self.assertEqual(self.ns['_resolve_manufacture_batch']('FG','EXISTING','2027-06-01'),'EXISTING')
        self.existing.expiry_date=None
        with self.assertRaisesRegex(ValueError,'different or blank expiry'):self.ns['_resolve_manufacture_batch']('FG','EXISTING','2027-06-01')
        self.assertEqual(self.created,[])

    def test_batch_tracking_and_explicit_identity_are_required(self):
        with self.assertRaisesRegex(ValueError,'Finished Batch is required'):self.ns['_resolve_manufacture_batch']('FG','','2027-06-01')
        self.item.has_batch_no=0
        with self.assertRaisesRegex(ValueError,'not configured for Batch tracking'):self.ns['_resolve_manufacture_batch']('FG','NEW','2027-06-01')


if __name__=='__main__':unittest.main()

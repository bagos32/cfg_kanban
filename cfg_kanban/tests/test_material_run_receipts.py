"""Offline receipt actual-use regression checks, not live ERP stock acceptance."""
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock, patch
from cfg_kanban.tests.test_material_actuals_yield import ROOT, Row, functions, frappe_double


class Document:
    def __init__(self, **values):self.__dict__.update(values)
    def get(self,key,default=None):return getattr(self,key,default)
    def remove(self,row):self.items.remove(row)


class TestMaterialRunReceiptActuals(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double();self.frappe.as_json=json.dumps
        self.order=Document(name='WO',company='CFG',docstatus=1,skip_transfer=1,qty=5,
            required_items=[Row(item_code='RAW',source_warehouse='Store',stock_uom='Kg',required_qty=5,operation='Cook')])
        self.job=Row(name='JC',operation='Cook',docstatus=1,status='Completed',for_quantity=5)
        self.rule=dict(rule_row='RULE',item_code='RAW',operation='Cook',scan_warehouse='Store',stock_uom='Kg',qty_per_output=1)
        self.execution=Row(name='EXEC',job_card='JC',operation='Cook',material_run_control='Required Before Progress',
            material_run_rules_json=json.dumps([self.rule]),material_run_settlement_timing='At Job Card End')
        self.draw=Row(name='DRAW',process_execution='EXEC',job_card='JC',operation='Cook',material_flow_rule_row='RULE',
            status='Bound to ERP',item_code='RAW',source_warehouse='Store',stock_uom='Kg',source_handling_unit='TAG',used_qty=3,
            material_trace='TRACE-SETTLED',material_trace_line='LINE-SETTLED')
        self.draws=[self.draw];self.jobs=[self.job];self.executions=[self.execution];self.open_runs=[]
        self.native=Document(name='CONSUMPTION',work_order='WO',company='CFG',purpose='Material Consumption for Manufacture',docstatus=1)
        self.settled_line=Row(name='LINE-SETTLED',direction='Input',handling_unit='TAG',item_code='RAW',warehouse='Store',stock_uom='Kg',qty=3,status='Confirmed')
        self.settled_trace=Document(name='TRACE-SETTLED',stock_entry='CONSUMPTION',lines=[self.settled_line])
        self.current_trace=None;self.posted_qty=3;self.stored_docstatus=0
        self.entry=Document(name='RECEIPT',purpose='Manufacture',work_order='WO',company='CFG',cfg_kanban_cycle='CYCLE',docstatus=0,fg_completed_qty=5,
            items=[self.input(2),Row(name='FG',item_code='FG',s_warehouse=None,t_warehouse='Finished',qty=5,transfer_qty=5,conversion_factor=1,stock_uom='Nos')])
        self.frappe.get_all.side_effect=self.get_all
        self.frappe.get_doc.side_effect=self.get_doc
        self.frappe.db.get_value.side_effect=self.get_value
        self.frappe.db.sql.side_effect=lambda *args,**kwargs:[Row(item_code='RAW',warehouse='Store',stock_uom='Kg',qty=self.posted_qty)]
        source=ROOT/'services/material_run_receipts.py'
        import ast
        names=[node.name for node in ast.parse(source.read_text()).body if isinstance(node,ast.FunctionDef)]
        self.ns=functions('services/material_run_receipts.py',names,{
            'frappe':self.frappe,'math':math,'flt':lambda value:float(value or 0),'TOLERANCE':0.000001,
            'record':Mock(),'canonical_key':lambda *args:str(args)})

    def input(self,qty,name='RAW-ROW',item='RAW',warehouse='Store',uom='Kg',conversion=1):
        return Row(name=name,item_code=item,s_warehouse=warehouse,t_warehouse=None,qty=qty/conversion,transfer_qty=qty,stock_uom=uom,conversion_factor=conversion)

    def get_all(self,doctype,**kwargs):
        if doctype=='Job Card':return self.jobs
        if doctype=='CFG Kanban Process Execution':return self.executions
        if doctype=='CFG Kanban Operation Material Run':return self.open_runs
        if doctype=='CFG Kanban Operation Material Draw':
            return [draw for draw in self.draws if draw.status!='Cancelled' and draw.used_qty>0]
        raise AssertionError(doctype)

    def get_doc(self,doctype,name):
        if doctype=='Work Order':return self.order
        if doctype=='Stock Entry':return self.native if name=='CONSUMPTION' else self.entry
        if doctype=='CFG Kanban Material Trace':
            return self.settled_trace if name=='TRACE-SETTLED' else self.current_trace
        raise AssertionError((doctype,name))

    def get_value(self,doctype,name,fields):
        if doctype=='Stock Entry':return self.stored_docstatus
        if doctype=='CFG Kanban Cycle':return 'WO'
        if doctype=='CFG Kanban Material Trace':return self.current_trace.name if self.current_trace else None
        raise AssertionError((doctype,name,fields))

    def reconcile(self):return self.ns['reconcile_manufacture_material_runs'](self.entry)
    def pending(self,qty=3):
        self.draw.status='Used';self.draw.used_qty=qty;self.draw.material_trace=None;self.draw.material_trace_line=None
        self.execution.material_run_settlement_timing='At Work Order Manufacture Receipt';self.posted_qty=0

    def test_job_end_actual_three_excludes_unused_two_without_touching_output(self):
        changes=self.reconcile()
        self.assertEqual([row.item_code for row in self.entry.items],['FG'])
        self.assertEqual(self.entry.items[0].qty,5)
        self.assertEqual(changes[0]['mapped_qty'],2);self.assertEqual(changes[0]['actual_pending_qty'],0)
        self.assertEqual(changes[0]['material_draws'],['DRAW'])
        self.ns['record'].assert_called_once()

    def test_receipt_timing_uses_three_instead_of_five_mapped(self):
        self.pending();self.entry.items[0]=self.input(5)
        self.reconcile();self.assertEqual(self.entry.items[0].transfer_qty,3)
        self.assertEqual(self.entry.items[0].qty,3)

    def test_receipt_timing_also_preserves_over_bom_actual_five(self):
        self.pending(5);self.entry.items[0]=self.input(3)
        self.reconcile();self.assertEqual(self.entry.items[0].transfer_qty,5)

    def test_actuals_and_uom_conversion_are_idempotent(self):
        self.pending();self.entry.items[0]=self.input(5,conversion=10)
        self.reconcile();self.assertEqual(self.entry.items[0].qty,0.3)
        self.assertEqual(self.reconcile(),[]);self.ns['record'].assert_called_once()

    def test_existing_receipt_trace_keeps_allocated_row_and_drops_unallocated_residual(self):
        self.pending();self.entry.items=[self.input(3),self.input(2,name='UNUSED'),self.entry.items[-1]]
        self.draw.material_trace='TRACE-CURRENT';self.draw.material_trace_line='LINE-CURRENT'
        line=Row(self.settled_line,name='LINE-CURRENT',status='Reserved',stock_entry_detail='RAW-ROW')
        self.current_trace=Document(name='TRACE-CURRENT',stock_entry='RECEIPT',lines=[line])
        self.reconcile();self.assertEqual([row.name for row in self.entry.items],['RAW-ROW','FG'])
        self.assertEqual(self.entry.items[0].qty,3)
        self.assertEqual(self.reconcile(),[])

    def test_cannot_silently_remove_an_existing_physical_allocation(self):
        self.pending();self.entry.items[0]=self.input(5)
        self.current_trace=Document(name='TRACE-CURRENT',stock_entry='RECEIPT',lines=[Row(
            direction='Input',status='Reserved',stock_entry_detail='RAW-ROW',qty=4)])
        with self.assertRaisesRegex(ValueError,'cancel the affected trace'):self.reconcile()
        self.assertEqual(self.entry.items[0].qty,5)

    def test_untracked_component_and_another_warehouse_stay_native(self):
        extra=self.input(4,name='BAG',item='BAG',uom='Nos');other=self.input(2,name='OTHER',warehouse='Other Store')
        self.entry.items.extend([extra,other]);self.reconcile()
        self.assertIn(extra,self.entry.items);self.assertIn(other,self.entry.items)
        self.assertEqual(extra.qty,4);self.assertEqual(other.qty,2)

    def test_missing_usage_or_partial_snapshot_coverage_never_removes_bom_input(self):
        for mode in ('no draws','untracked','partial ratio'):
            with self.subTest(mode=mode):
                self.draws=[self.draw];self.execution.material_run_rules_json=json.dumps([self.rule])
                if mode=='no draws':self.draws=[]
                if mode=='untracked':self.execution.material_run_rules_json='[]'
                if mode=='partial ratio':self.execution.material_run_rules_json=json.dumps([dict(self.rule,qty_per_output=0.5)])
                self.assertEqual(self.reconcile(),[]);self.assertEqual(self.entry.items[0].qty,2)

    def test_incomplete_job_card_or_missing_other_lane_evidence_keeps_native_balance(self):
        self.job.docstatus=0;self.assertEqual(self.reconcile(),[])
        self.job.docstatus=1;self.jobs.append(Row(self.job,name='JC-OTHER'))
        self.assertEqual(self.reconcile(),[]);self.assertEqual(self.entry.items[0].qty,2)

    def test_open_run_must_close_before_receipt(self):
        self.open_runs=['OPEN']
        with self.assertRaisesRegex(ValueError,'Close or cancel'):self.reconcile()

    def test_posted_consumption_requires_matching_live_trace(self):
        for field,value in (('docstatus',2),('company','OTHER'),('work_order','OTHER')):
            with self.subTest(field=field):
                old=getattr(self.native,field);setattr(self.native,field,value)
                with self.assertRaises(ValueError):self.reconcile()
                setattr(self.native,field,old)
        self.posted_qty=2
        with self.assertRaisesRegex(ValueError,'differs from Material Run actuals'):self.reconcile()

    def test_draft_job_end_settlement_is_not_a_submitted_consumption(self):
        self.draw.status='Used';self.native.docstatus=0;self.settled_line.status='Reserved'
        with self.assertRaisesRegex(ValueError,'earlier Material Run Draft'):self.reconcile()

    def test_submitted_manufacture_is_never_modified(self):
        self.stored_docstatus=1
        self.assertEqual(self.reconcile(),[]);self.assertEqual(self.entry.items[0].qty,2)
        self.frappe.get_doc.assert_not_called()

    def test_cross_company_receipt_is_rejected(self):
        self.entry.company='OTHER'
        with self.assertRaisesRegex(ValueError,'Company'):self.reconcile()

    def test_read_only_summary_distinguishes_used_settled_and_pending(self):
        result=self.ns['material_run_receipt_summary'](self.order)[0]
        self.assertEqual((result['used_qty'],result['settled_qty'],result['pending_qty']),(3,3,0))
        self.pending();result=self.ns['material_run_receipt_summary'](self.order)[0]
        self.assertEqual((result['used_qty'],result['settled_qty'],result['pending_qty']),(3,0,3))
        self.ns['record'].assert_not_called()

    def test_prior_manufacture_consumption_is_not_requested_again(self):
        self.native.purpose='Manufacture'
        self.reconcile()
        self.assertEqual([row.item_code for row in self.entry.items],['FG'])

    def test_card_summary_remains_read_only_when_draw_evidence_needs_recovery(self):
        self.draw.material_flow_rule_row='MISSING-OLD-RULE'
        self.assertEqual(self.ns['material_run_receipt_summary'](self.order),[])
        with self.assertRaisesRegex(ValueError,'snapshotted material rule'):self.reconcile()

    def test_managed_native_rows_need_no_duplicate_operator_confirmation(self):
        utils=types.ModuleType('erpnext.stock.utils');utils.get_stock_balance=lambda *args:100
        ns=functions('integrations/erp_gateway.py',['_apply_confirmed_production_lines'],{'frappe':self.frappe,'flt':lambda x:float(x or 0)})
        self.entry.items[0]=self.input(3)
        self.entry.items.append(self.input(4,item='BAG',name='BAG',uom='Nos'))
        with patch.dict(sys.modules,{utils.__name__:utils}):
            ns['_apply_confirmed_production_lines'](self.entry,[{'item_code':'BAG','source_warehouse':'Store','qty':4}],input_only=True,server_managed_keys={('RAW','Store','Kg')})
        self.assertEqual(self.entry.items[0].qty,3)
        with self.assertRaisesRegex(ValueError,'recorded actual use'):
            ns['_apply_confirmed_production_lines'](self.entry,[{'item_code':'RAW','source_warehouse':'Store','qty':2}],input_only=True,server_managed_keys={('RAW','Store','Kg')})


    def test_real_gateway_reconciles_before_operator_lines_and_native_insert(self):
        mapper=types.ModuleType('erpnext.manufacturing.doctype.work_order.work_order')
        mapper.make_stock_entry=Mock(return_value=self.entry)
        stock=types.ModuleType('erpnext.stock.utils');stock.get_stock_balance=lambda *args:100
        actuals=types.ModuleType('cfg_kanban.services.material_run_receipts')
        actuals.reconcile_manufacture_material_runs=self.ns['reconcile_manufacture_material_runs']
        self.order.production_item='FG'
        self.entry.items.append(self.input(5,item='BAG',name='BAG',uom='Nos'))
        self.entry.insert=Mock(return_value=self.entry);self.entry.submit=Mock()
        original_get_doc=self.get_doc
        self.frappe.get_doc.side_effect=lambda doctype,name=None:doctype if isinstance(doctype,Document) else original_get_doc(doctype,name)
        ns=functions('integrations/erp_gateway.py',['create_production_manufacture_receipt','_apply_confirmed_production_lines'],{
            'frappe':self.frappe,'flt':lambda x:float(x or 0),
            '_exclude_submitted_wip_bin_returns':Mock(),'_resolve_manufacture_batch':lambda *args:None})
        with patch.dict(sys.modules,{mapper.__name__:mapper,stock.__name__:stock,actuals.__name__:actuals}):
            result=ns['create_production_manufacture_receipt'](Row(kanban_cycle='CYCLE',source_signal=None),{
                'work_order':'WO','output_qty':5,'target_warehouse':'Finished',
                'lines':[{'item_code':'BAG','source_warehouse':'Store','qty':5}]})
        self.assertIs(result,self.entry)
        self.assertEqual([row.item_code for row in result.items],['FG','BAG'])
        self.entry.insert.assert_called_once();self.entry.submit.assert_not_called()

    def test_native_draft_save_reconciles_without_disabling_tag_validation(self):
        gateway=types.ModuleType('cfg_kanban.integrations.erp_gateway');gateway._exclude_submitted_wip_bin_returns=Mock()
        actuals=types.ModuleType('cfg_kanban.services.material_run_receipts')
        actuals.reconcile_manufacture_material_runs=self.ns['reconcile_manufacture_material_runs']
        self.entry.meta=Row(has_field=lambda field:False)
        self.frappe.db.exists.return_value=True
        self.frappe.db.get_value.side_effect=lambda doctype,name,fields,**kwargs: (
            Row(name='CYCLE',work_order='WO',signal=None) if doctype=='CFG Kanban Cycle' and isinstance(fields,list)
            else self.get_value(doctype,name,fields))
        ns=functions('integrations/erp_feedback.py',['prepare_stock_entry'],{
            'frappe':self.frappe,'_cycle':lambda entry:'CYCLE','_link_value':lambda value:value})
        with patch.dict(sys.modules,{gateway.__name__:gateway,actuals.__name__:actuals}):
            ns['prepare_stock_entry'](self.entry);ns['prepare_stock_entry'](self.entry)
        self.assertEqual([row.item_code for row in self.entry.items],['FG'])
        self.ns['record'].assert_called_once()

    def test_submit_scanner_refreshes_old_draft_after_authorization_before_posting(self):
        trace=types.ModuleType('cfg_kanban.services.production_trace');trace._lock_stock_entry=Mock()
        actuals=types.ModuleType('cfg_kanban.services.material_run_receipts')
        actuals.reconcile_manufacture_material_runs=self.ns['reconcile_manufacture_material_runs']
        self.entry.reload=Mock();self.entry.save=Mock(return_value=self.entry);self.entry.modified='NOW'
        ns=functions('services/production_material_flow.py',['submit_production_stock_entry'],{
            'frappe':self.frappe,'_production_context':lambda cycle:(Row(name='CYCLE',kanban_card='CARD',signal=None),None,self.order),
            'require_operator':Mock(return_value=(Row(employee='EMP'),Row(name='SESSION',terminal_user='terminal'))),
            'canonical_key':lambda *args:str(args),'now_datetime':lambda:'NOW',
            'insert_once':Mock(return_value=(Row(name='COMMAND'),True)),
            'execute_command':Mock(return_value=Row(name='RECEIPT',docstatus=1)),'record':Mock()})
        original_get_doc=self.get_doc
        self.frappe.get_doc.side_effect=lambda doctype,name=None:Row(doctype) if isinstance(doctype,dict) else original_get_doc(doctype,name)
        with patch.dict(sys.modules,{trace.__name__:trace,actuals.__name__:actuals}):
            result=ns['submit_production_stock_entry']('RECEIPT',operator_session_token='SESSION')
        self.assertEqual(result['docstatus'],1)
        self.assertEqual([row.item_code for row in self.entry.items],['FG'])
        trace._lock_stock_entry.assert_called_once_with('RECEIPT')
        self.entry.save.assert_called_once_with(ignore_permissions=True)
        ns['execute_command'].assert_called_once_with('COMMAND')


if __name__=='__main__':unittest.main()

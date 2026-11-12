"""Offline actual-use/yield regression tests, not Frappe/ERP transaction acceptance."""
import ast
import json
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]

class Row(dict):
    __getattr__=dict.get
    __setattr__=dict.__setitem__
    def as_dict(self):return dict(self)

def functions(path,names,namespace):
    nodes=[node for node in ast.parse((ROOT/path).read_text()).body
           if isinstance(node,ast.FunctionDef) and node.name in names]
    for node in nodes:node.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/path),'exec'),namespace)
    return namespace

def frappe_double():
    frappe=types.ModuleType('frappe')
    frappe.throw=Mock(side_effect=lambda message:(_ for _ in ()).throw(ValueError(message)))
    frappe.parse_json=json.loads
    frappe.db=Row(sql=Mock(),get_value=Mock(return_value='SOURCE'),exists=Mock(return_value=False))
    frappe.get_doc=Mock()
    frappe.get_all=Mock()
    return frappe

class TestActualMaterialPlan(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double()
        self.frappe.get_all.return_value=[Row(name='DRAW',material_run='RUN',remaining_qty=3)]
        self.execution=Row(name='EXEC',status='In Progress',material_run_control='Required Before Progress',allow_material_carry_forward=1)
        self.run=Row(name='RUN',status='Open',process_execution='EXEC',reload=Mock())
        self.rule=Row(rule_row='RULE',qty_per_output=1,stock_uom='Kg',item_code='RAW')
        self.control=types.ModuleType('cfg_kanban.services.material_quantity_control')
        self.control.active_work_order_yield_override=Mock(return_value=None)
        self.control._assert_material_visible=Mock()
        self.ns=functions('services/operation_material_runs.py',['validate_progress_materials'],{
            'frappe':self.frappe,'flt':lambda x:float(x or 0),'TOLERANCE':0.000001,'_':lambda x:x,
            'material_run_rules':lambda x:[self.rule],'assert_material_not_expired':Mock(),
            'ACTIVE_EXECUTION_STATES':{'In Progress','Paused'}})

    def plan(self,output,actuals=None):
        with patch.dict(sys.modules,{'cfg_kanban.services.material_quantity_control':self.control}):
            return self.ns['validate_progress_materials'](self.execution,self.run,output,actuals)

    def test_three_raw_does_not_support_five_output_without_approval(self):
        with self.assertRaisesRegex(ValueError,'only 3.0 is scanned'):
            self.plan(5)

    def test_full_work_order_approval_records_three_actual_for_five_output(self):
        self.control.active_work_order_yield_override.return_value=Row(name='WO-APPROVAL')
        result=self.plan(5)
        self.assertEqual(sum(row['qty'] for row in result),3)
        self.assertEqual(result[0]['yield_override'],'WO-APPROVAL')
        self.assertEqual(result[0]['bom_required_qty'],5)

    def test_five_bags_used_for_five_output_remains_five(self):
        self.rule.stock_uom='Nos';self.rule.item_code='BAG'
        self.frappe.get_all.return_value[0].remaining_qty=5
        self.assertEqual(sum(row['qty'] for row in self.plan(5,{'RULE':5})),5)

    def test_lower_yield_can_record_more_input_than_bom_default(self):
        result=self.plan(2,{'RULE':3})
        self.assertEqual(result[0]['qty'],3)

    def test_actual_cannot_exceed_the_scanned_available_quantity(self):
        with self.assertRaisesRegex(ValueError,'only 3.0 is scanned'):
            self.plan(5,{'RULE':5})

    def test_declared_low_input_requires_yield_approval(self):
        with self.assertRaisesRegex(ValueError,'yield approval'):
            self.plan(5,{'RULE':3})

    def test_zero_unknown_or_nonfinite_actuals_are_rejected(self):
        for value in ({'RULE':0},{'OTHER':3},{'RULE':float('nan')}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.plan(2,value)

class Entry:
    def __init__(self,rows):self.items=rows;self.saved=0
    def remove(self,row):self.items.remove(row)
    def append(self,table,values):
        row=Row(values,name='NEW-'+str(len(self.items)))
        self.items.append(row);return row
    def save(self,**kwargs):self.saved+=1
    def reload(self):pass

class TestActualDraftQuantities(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double()
        self.ns=functions('services/operation_material_runs.py',[
            '_prepare_material_draw_rows','_entry_row_stock_qty','_cloned_entry_input_row'],
            {'frappe':self.frappe,'flt':lambda x:float(x or 0),'TOLERANCE':0.000001,'_':lambda x:x})

    def test_actual_five_preserved_when_erp_maps_three(self):
        for transfer_qty in (3,0,None):
            with self.subTest(transfer_qty=transfer_qty):
                row=Row(name='ERP-ROW',s_warehouse='Store',item_code='BAG',stock_uom='Nos',qty=3,transfer_qty=transfer_qty,conversion_factor=1)
                entry=Entry([row])
                draw=Row(name='DRAW',item_code='BAG',source_warehouse='Store',stock_uom='Nos',batch_no=None,used_qty=5)
                result=self.ns['_prepare_material_draw_rows'](entry,[draw])
                self.assertEqual(entry.items[0].qty,5)
                self.assertEqual(entry.items[0].transfer_qty,5)
                self.assertEqual(result['DRAW'],'ERP-ROW')
                self.assertEqual(entry.saved,1)

    def test_uom_conversion_preserved_when_actual_stock_use_exceeds_bom(self):
        row=Row(name='ERP-ROW',s_warehouse='Store',item_code='BAG',stock_uom='Nos',qty=0.3,transfer_qty=3,conversion_factor=10)
        entry=Entry([row]);draw=Row(name='DRAW',item_code='BAG',source_warehouse='Store',stock_uom='Nos',batch_no=None,used_qty=5)
        self.ns['_prepare_material_draw_rows'](entry,[draw])
        self.assertEqual(row.qty,0.5);self.assertEqual(row.transfer_qty,5)

    def test_actual_batches_are_not_clipped_to_the_original_erp_quantity(self):
        row=Row(name='ERP-ROW',s_warehouse='Store',item_code='RAW',stock_uom='Kg',qty=3,transfer_qty=3,conversion_factor=1)
        entry=Entry([row])
        draws=[Row(name='D1',item_code='RAW',source_warehouse='Store',stock_uom='Kg',batch_no='B1',used_qty=3),
               Row(name='D2',item_code='RAW',source_warehouse='Store',stock_uom='Kg',batch_no='B2',used_qty=2)]
        result=self.ns['_prepare_material_draw_rows'](entry,draws)
        self.assertEqual(sum(row.transfer_qty for row in entry.items),5)
        self.assertEqual({row.batch_no for row in entry.items},{'B1','B2'})
        self.assertTrue(all(result[draw.name] for draw in draws))

class TestProgressQuantities(unittest.TestCase):
    def test_good_cannot_be_higher_than_explicit_processed_output(self):
        frappe=frappe_double();frappe.get_doc.return_value=Row(processed_qty=0,target_qty=100)
        namespace=functions('services/progress.py',['report'],{'frappe':frappe,'math':math,'flt':lambda x:float(x or 0)})
        with self.assertRaisesRegex(ValueError,'cannot exceed Processed'):
            namespace['report']('EXEC',5,processed_qty=3,source='ERP Feedback')

class TestMaterialUseCorrections(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double()
        self.draw=Row(name='DRAW',doctype='CFG Kanban Operation Material Draw',work_order='WO',job_card='JC',
            material_trace=None,status='Carry Forward',drawn_qty=5,used_qty=3,remaining_qty=2,item_code='BAG',material_run='RUN')
        self.draw.db_set=lambda values:self.draw.update(values)
        self.frappe.get_doc.side_effect=lambda doctype,name:self.draw if doctype=='CFG Kanban Operation Material Draw' else Row(name='RUN')
        utils=types.ModuleType('frappe.utils');utils.flt=lambda x:float(x or 0)
        runs=types.ModuleType('cfg_kanban.services.operation_material_runs');runs._refresh_run_totals=Mock()
        self.modules={'frappe.utils':utils,'cfg_kanban.services.operation_material_runs':runs}
        self.ns=functions('services/material_quantity_control.py',['correct_material_use'],{
            'frappe':self.frappe,'math':math,'canonical_key':lambda *parts:str(parts),'_retry':Mock(return_value=False),
            '_correction_actor':Mock(return_value=(Row(name='EXEC',job_card='JC'),Row(name='WO'),Row(employee='SUP'),Row(name='SESSION',terminal_user='terminal'))),
            '_assert_material_visible':Mock(),'record':Mock()})

    def correct(self,qty):
        with patch.dict(sys.modules,self.modules):
            return self.ns['correct_material_use']('EXEC','DRAW:DRAW',qty,'Actual five bags','TOKEN','session')

    def test_supervisor_can_correct_used_three_to_five_with_before_after_audit(self):
        result=self.correct(5)
        self.assertEqual(self.draw.used_qty,5);self.assertEqual(self.draw.remaining_qty,0)
        self.assertEqual(result['before'],3)
        payload=self.ns['record'].call_args.kwargs['payload']
        self.assertEqual(payload['before'],3);self.assertEqual(payload['after'],5)

    def test_correction_above_scanned_quantity_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'physically scanned'):self.correct(6)
        self.assertEqual(self.draw.used_qty,3)

    def test_adopted_or_posted_draw_cannot_be_silently_edited(self):
        self.draw.material_trace='TRACE'
        with self.assertRaisesRegex(ValueError,'linked ERP Draft'):self.correct(5)
        self.assertEqual(self.draw.used_qty,3)

    def test_correction_cannot_target_another_job_card(self):
        self.draw.job_card='OTHER'
        with self.assertRaisesRegex(ValueError,'outside this Job Card'):self.correct(5)

class TestDraftTraceCorrection(unittest.TestCase):
    def test_supervisor_changes_trace_three_to_five_and_native_row_five(self):
        frappe=frappe_double()
        original=Row(name='LINE',parent='TRACE',direction='Input',status='Reserved',qty=3,
            item_code='BAG',handling_unit='TAG',stock_entry_detail='ROW',physical_container=None)
        row=Row(name='ROW',s_warehouse='Store',t_warehouse=None,qty=3,transfer_qty=3,conversion_factor=1)
        values={'name':'SE','docstatus':0,'work_order':'WO','purpose':'Material Consumption for Manufacture',
                'items':[row],'cfg_kanban_job_card':'JC','save':Mock(),'reload':Mock()}
        entry=types.SimpleNamespace(**values,get=values.get)
        docs={'CFG Kanban Material Trace Line':original,'CFG Kanban Material Trace':Row(stock_entry='SE'),
              'Stock Entry':entry,'CFG Kanban Handling Unit':Row(handling_unit_id='TAG-CODE')}
        frappe.get_doc.side_effect=lambda doctype,name:docs[doctype]
        trace=types.ModuleType('cfg_kanban.services.production_trace')
        trace._lock_stock_entry=Mock();trace.cancel_trace_line=Mock();trace.allocate_input_tag=Mock()
        utils=types.ModuleType('frappe.utils');utils.flt=lambda x:float(x or 0)
        ns=functions('services/material_quantity_control.py',['correct_material_use'],{
            'frappe':frappe,'math':math,'canonical_key':lambda *parts:str(parts),'_retry':Mock(return_value=False),
            '_correction_actor':Mock(return_value=(Row(name='EXEC',job_card='JC'),Row(name='WO'),Row(employee='SUP'),Row(name='SESSION',terminal_user='terminal'))),
            '_assert_material_visible':Mock(),'record':Mock()})
        with patch.dict(sys.modules,{'frappe.utils':utils,'cfg_kanban.services.production_trace':trace}):
            ns['correct_material_use']('EXEC','TRACE:LINE',5,'Counted five bags','TOKEN','session')
        self.assertEqual(row.qty,5);self.assertEqual(row.transfer_qty,5)
        trace.cancel_trace_line.assert_called_once_with('SE','LINE','session',None)
        trace.allocate_input_tag.assert_called_once_with('SE','ROW','TAG-CODE',5,'session',None)
        self.assertEqual(ns['record'].call_args.kwargs['payload']['before'],3)

    def test_correction_retry_fingerprint_rejects_changed_request(self):
        frappe=frappe_double();frappe.db.get_value.return_value=Row(payload_json='{"request":"ORIGINAL"}')
        ns=functions('services/material_quantity_control.py',['_retry'],{'frappe':frappe})
        self.assertTrue(ns['_retry']('KEY','ORIGINAL'))
        with self.assertRaisesRegex(ValueError,'different actual quantities'):
            ns['_retry']('KEY','CHANGED')

class TestAutomaticTraceQuantity(unittest.TestCase):
    def test_auto_trace_does_not_silently_reduce_five_to_three(self):
        tree=ast.parse((ROOT/'services/production_trace.py').read_text())
        fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='allocate_input_tag')
        fn.decorator_list=[]
        prefix=[]
        for node in fn.body:
            if isinstance(node,ast.ImportFrom) and node.module=='cfg_kanban.services.serial_evidence':break
            prefix.append(node)
        fn.body=prefix+[ast.Return(value=ast.Name(id='qty',ctx=ast.Load()))]
        frappe=frappe_double();frappe.get_doc.return_value=Row(company='TEST')
        unit=Row(current_qty=5,available_qty=5,handling_unit_id='TAG')
        ns={'frappe':frappe,'flt':lambda x:float(x or 0),'TOLERANCE':0.000001,'NO_TAG':'No Tag',
            '_lock_stock_entry':Mock(),'_authorize_trace_access':Mock(),'_assert_editable':Mock(),
            'resolve_logistics_scan':lambda value:{'identity_type':'Handling Unit','name':'TAG'},
            '_production_input_unit':lambda value:(unit,None),'_ensure_trace':Mock(),
            '_resolve_input_row':Mock(return_value=Row(item_code='BAG')),'_bind_scanned_input_batch':Mock(),
            'effective_trace_policy':lambda *args:Row(production_input_tag_policy='Required'),
            '_tag_batch_no':Mock(),'_validate_input_unit':Mock(),'_remaining_row_qty':Mock(return_value=3),
            '_is_transfer_purpose':lambda doc:False}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'trace-quantity-prefix','exec'),ns)
        with self.assertRaisesRegex(ValueError,'actual Material Quantity'):
            ns['allocate_input_tag']('SE',scan_value='TAG',qty=0)
        self.assertEqual(ns['allocate_input_tag']('SE',scan_value='TAG',qty=3),3)

class TestWorkOrderVariance(unittest.TestCase):
    def test_over_bom_actuals_require_live_work_order_approval_before_posting(self):
        frappe=frappe_double();frappe.db.table_exists=lambda *args:True
        order=Row(name='WO',required_items=[Row(item_code='BAG',required_qty=3)])
        frappe.get_doc.return_value=order
        ns=functions('services/material_quantity_control.py',['validate_material_variance'],{'frappe':frappe,'OVERRIDE_DOCTYPE':'CFG Kanban Work Order Yield Override'})
        values={'doctype':'Stock Entry','cfg_kanban_controlled':1,'work_order':'WO','company':'TEST',
                'purpose':'Material Consumption for Manufacture','items':[Row(item_code='BAG',s_warehouse='Store',t_warehouse=None,transfer_qty=5)]}
        doc=types.SimpleNamespace(**values,get=values.get)
        utils=types.ModuleType('frappe.utils');utils.flt=lambda x:float(x or 0)
        with patch.dict(sys.modules,{'frappe.utils':utils}):
            frappe.db.sql.return_value=[]
            with self.assertRaisesRegex(ValueError,'Work Order-wide yield/quantity approval'):ns['validate_material_variance'](doc)
            frappe.db.sql.return_value=[('WO-APPROVAL',)]
            ns['validate_material_variance'](doc)

class TestQuantityControlsContract(unittest.TestCase):
    def test_full_work_order_approval_is_distinct_from_fefo_and_scanner_accessible(self):
        service=(ROOT/'services/material_quantity_control.py').read_text()
        self.assertIn('CFG Kanban Work Order Yield Override',service)
        self.assertNotIn('tabCFG Kanban Material Rotation Override',service)
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_work_order_yield_override/cfg_kanban_work_order_yield_override.json').read_text())
        self.assertEqual(next(field for field in schema['fields'] if field['fieldname']=='active_work_order_key')['unique'],1)
        api=(ROOT/'api/operator.py').read_text();panel=(ROOT/'cfg_kanban/page/kanban_operator/kanban_operator.js').read_text()
        for command in ('APPROVE_WO_YIELD','REVOKE_WO_YIELD','CORRECT_MATERIAL_USE'):
            self.assertIn('CFG:CMD:'+command,api);self.assertIn(command,panel)


class TestProductionCardYieldCompanyContext(unittest.TestCase):
    """Run the real card execution projection through the real yield lookup.

    A full execution fixture would conceal a missing field in get_card_context.
    Database doubles below return only the fields that query actually requests.
    """
    def setUp(self):
        self.frappe = frappe_double()
        self.order = Row(name="WO", company="CFG", docstatus=1, status="In Process")
        self.stored_execution = Row(name="EXEC", kanban_master="MASTER-CFG", job_card="JC")
        self.approvals = []
        self.frappe.db.table_exists = Mock(return_value=True)
        self.frappe.db.get_value.side_effect = self.get_value
        self.frappe.db.sql.side_effect = self.sql
        self.frappe.get_doc.side_effect = self.get_doc
        self.frappe.get_all.side_effect = self.get_all
        self.service = types.ModuleType("cfg_kanban.services.material_quantity_control")
        self.service.frappe = self.frappe
        self.service._ = lambda message: message
        self.service.OVERRIDE_DOCTYPE = "CFG Kanban Work Order Yield Override"
        self.service.TERMINAL_WORK_ORDER_STATES = ("Completed", "Closed", "Stopped", "Cancelled")
        functions("services/material_quantity_control.py",
                  ["_work_order", "active_work_order_yield_override"], self.service.__dict__)
        self.api = functions("api/operator.py", ["_work_order_yield_context"], {"frappe": self.frappe})

    def get_value(self, doctype, name, fields=None, as_dict=False):
        if doctype == "Job Card":
            self.assertEqual(name, "JC")
            self.assertEqual(fields, "work_order")
            return self.order.name
        if doctype == "Work Order":
            self.assertEqual(name, self.order.name)
            self.assertEqual(fields, ["docstatus", "status"])
            return Row(docstatus=self.order.docstatus, status=self.order.status)
        if doctype == "CFG Kanban Master":
            self.assertEqual(fields, "company")
            # Frappe's unfiltered get_value can pick the first record. An unrelated
            # first Master deliberately belongs to a different Company.
            return {None: "OTHER", "MASTER-CFG": "CFG"}[name]
        raise AssertionError((doctype, name, fields))

    def get_doc(self, doctype, name):
        self.assertEqual((doctype, name), ("Work Order", self.order.name))
        return self.order

    def get_all(self, doctype, *, fields, filters, **kwargs):
        self.assertEqual(doctype, "CFG Kanban Process Execution")
        self.assertEqual(filters, {"kanban_cycle": "CYCLE", "job_card": ["in", ["JC"]]})
        return [Row({field: self.stored_execution.get(field) for field in fields})]

    def sql(self, query, params, **kwargs):
        self.assertIn("tabCFG Kanban Work Order Yield Override", query)
        self.assertEqual(params, (self.order.name, "CFG"))
        return self.approvals

    def card_execution(self):
        tree = ast.parse((ROOT / "api/operator.py").read_text())
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "get_card_context")
        queries = [node for node in ast.walk(fn) if isinstance(node, ast.Assign)
                   and isinstance(node.value, ast.Call)
                   and isinstance(node.value.func, ast.Attribute)
                   and node.value.func.attr == "get_all" and node.value.args
                   and isinstance(node.value.args[0], ast.Constant)
                   and node.value.args[0].value == "CFG Kanban Process Execution"]
        self.assertEqual(len(queries), 1)
        namespace = {"frappe": self.frappe, "cycle": Row(name="CYCLE"), "effective_jobs": ["JC"]}
        exec(compile(ast.Module(body=queries, type_ignores=[]), "card execution query", "exec"), namespace)
        return namespace["executions"][0]

    def context(self, execution=None):
        if execution is None:
            execution = self.card_execution()
        with patch.dict(sys.modules, {self.service.__name__: self.service}):
            return self.api["_work_order_yield_context"](execution)

    def test_existing_production_card_without_approval_uses_its_exact_company(self):
        self.assertIsNone(self.context())
        self.frappe.db.get_value.assert_any_call("CFG Kanban Master", "MASTER-CFG", "company")

    def test_existing_production_card_displays_same_company_approval(self):
        approval = Row(name="APPROVAL", work_order="WO", company="CFG")
        self.approvals.append(approval)
        self.assertEqual(self.context(), approval)

    def test_a_genuine_work_order_company_mismatch_still_fails(self):
        self.order.company = "OTHER-COMPANY"
        with self.assertRaisesRegex(ValueError, "belongs to another Company"):
            self.context()
        self.frappe.db.sql.assert_not_called()

    def test_terminal_work_orders_do_not_gain_active_yield_authority(self):
        for status in self.service.TERMINAL_WORK_ORDER_STATES:
            with self.subTest(status=status):
                self.order.status = status
                self.assertIsNone(self.context())
        self.frappe.db.sql.assert_not_called()

    def test_card_without_job_card_needs_no_yield_lookup(self):
        self.stored_execution.job_card = None
        self.assertIsNone(self.context())
        self.frappe.db.get_value.assert_not_called()

if __name__=='__main__':unittest.main()

"""Offline live-execution queue and completion snapshot regression cases."""
import unittest
from unittest.mock import Mock
from cfg_kanban.tests.test_material_actuals_yield import Row,functions,frappe_double

class TestWorkstationQueueReadiness(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double();self.frappe._dict=Row
        self.execution=Row(name='EXEC',kanban_cycle='CYCLE',kanban_master='MASTER',job_card='JOB',operation='Pack',workstation='WS',status='Ready',target_qty=5,good_qty=0,processed_qty=0,reject_qty=0)
        self.projections=[];self.profile=Row(allowed_operations=[])
        self.frappe.get_all=Mock(side_effect=self.get_all)
        self.ns=functions('api/operator.py',['_workstation_queue_context'],{'frappe':self.frappe,'flt':lambda x:float(x or 0)})
    def get_all(self,doctype,**kwargs):
        if doctype=='CFG Kanban Process Execution':return [self.execution] if self.execution.status not in ('Completed','Cancelled') else []
        if doctype=='CFG Kanban Dispatch Queue':return self.projections
        if doctype=='CFG Kanban Master':return [Row(name='MASTER',company='COMP')]
        if doctype=='CFG Kanban Cycle':return [Row(name='CYCLE',kanban_card='CARD',status='Released',priority='Normal',work_order='WO',item_code='PRODUCT')]
        if doctype=='CFG Kanban Card':return [Row(name='CARD',card_number='CARD1',qr_code='QR')]
        raise AssertionError(doctype)
    def context(self,company='COMP'):return self.ns['_workstation_queue_context'](Row(current_station='WS',queue_company=company),self.profile)
    def test_ready_execution_without_projection_is_visible_without_writes(self):
        result=self.context();self.assertEqual(result['queue'][0].process_execution,'EXEC');self.assertEqual(result['queue'][0].work_order,'WO');self.assertEqual(result['queue'][0].readiness,'Ready')
        self.frappe.get_doc.assert_not_called();self.frappe.db.sql.assert_not_called()
    def test_stale_projection_does_not_hide_ready_execution_or_lose_supervisor_priority(self):
        self.projections=[Row(name='QUEUE',process_execution='EXEC',dispatch_status='Completed',queue_position=2,supervisor_priority='High',sequence_source='Supervisor Override')]
        row=self.context()['queue'][0];self.assertEqual(row.dispatch_status,'Ready');self.assertEqual(row.queue_position,2);self.assertEqual(row.priority,'High')
    def test_live_progress_and_pause_determine_queue_group(self):
        self.execution.status='In Progress';self.assertEqual(self.context()['active'][0].process_execution,'EXEC')
        self.execution.status='Paused';self.assertEqual(self.context()['paused'][0].process_execution,'EXEC')
        self.execution.status='Completed';self.assertEqual(self.context()['total'],0)
    def test_company_and_operation_scope_still_filter_work(self):
        self.assertEqual(self.context('OTHER')['total'],0)
        self.profile.allowed_operations=[Row(operation='Rinse')];self.assertEqual(self.context()['total'],0)

class TestMirroredCompletionRule(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double();self.created=[];self.writes=[];self.existing=False
        self.profile=Row(operation='Pack',sequence=1,completion_rule='Operator Complete')
        self.master=Row(name='MASTER',operation_profiles=[self.profile],certificate_requirements=[],certificate_output_rules=[])
        self.frappe.get_all=Mock(return_value=[Row(name='JOB',operation='Pack',workstation='WS',status='Open',for_quantity=5)])
        self.frappe.db.set_value=lambda *args,**kw:self.writes.append(args)
        self.frappe.db.get_value=lambda dt,key,*args,**kw:('EXISTING' if self.existing else None) if isinstance(key,dict) else 'Ready'
        def doc(value,name=None):
            if value=='CFG Kanban Master':return self.master
            values=Row(value);values.setdefault('completion_rule','Full Qty');self.created.append(values)
            return Row(insert=lambda **kw:Row(values,name='NEW'))
        self.frappe.get_doc=doc
        self.ns=functions('integrations/erp_feedback.py',['_sync_job_cards'],dict(frappe=self.frappe,_runtime_card=lambda cycle:False,
            ensure_summary=lambda *args:Row(name='SUMMARY'),_profile_execution_mode=lambda profile:'Single Workstation',
            _execution_status=lambda *args,**kw:'Ready',recalculate=lambda *args:None,
            build_material_run_rule_snapshot=lambda *args:'[]',_validate_operation_allocation=Mock(),ready_executions=Mock()))
    def sync(self):self.ns['_sync_job_cards'](Row(name='WO'),Row(name='CYCLE',kanban_master='MASTER',signal='SIGNAL'))
    def test_new_mirrored_execution_snapshots_operator_complete(self):
        self.sync();self.assertEqual(self.created[0].completion_rule,'Operator Complete')
    def test_missing_profile_rule_retains_full_quantity_default(self):
        self.profile.completion_rule=None;self.sync();self.assertEqual(self.created[0].completion_rule,'Full Qty')
    def test_resync_does_not_rewrite_existing_release_snapshot(self):
        self.existing=True;self.sync();self.assertFalse(self.created)
        self.assertTrue(all('completion_rule' not in args[2] for args in self.writes if isinstance(args[2],dict)))

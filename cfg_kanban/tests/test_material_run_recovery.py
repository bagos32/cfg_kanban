"""Offline recovery regression cases; no live site or ERP transaction acceptance."""
import json
from unittest.mock import Mock
from cfg_kanban.tests.test_operation_hoppers import HopperHarness, Doc, Row


class TestMaterialRunRecovery(HopperHarness):
    def setUp(self):
        super().setUp()
        self.frappe._dict=Row;self.frappe.parse_json=json.loads
        Doc.as_dict=lambda doc:dict(doc)
        self.recovery=self.load('material_run_recovery')
        self.audit={};old_get=self.frappe.db.get_value;old_sql=self.frappe.db.sql
        self.frappe.db.get_value=lambda doctype,name,field,*a,**k:(self.audit.get(name.get('idempotency_key')) if doctype=='CFG Kanban Event' else old_get(doctype,name,field,*a,**k))
        def sql(query,values=None,as_dict=False):
            if 'from `tabCFG Kanban Event`' in query:return [(self.audit[values],)] if values in self.audit else []
            if 'select name from `tabCFG Kanban Operation Material Run`' in query:
                return [(row.name,) for row in self.data['CFG Kanban Operation Material Run'].values() if row.process_execution==values[0] and row.name!=values[1] and row.status=='Open']
            if 'from `tabWork Order`' in query:return [Row(self.order)]
            if 'from `tabJob Card`' in query:return self.get_all('Job Card',filters={'work_order':values[0],'operation':values[1]})
            if 'select * from `tabCFG Kanban Operation Material Run`' in query:return [Row(self.data['CFG Kanban Operation Material Run'][values])]
            if 'from `tabCFG Kanban Operation Material Draw`' in query and 'material_run=%s' in query:
                return [Row(row) for row in self.data.get('CFG Kanban Operation Material Draw',{}).values() if row.material_run==values and row.remaining_qty>0 and row.status in ('Open','Carry Forward','Used','Bound to ERP')]
            return old_sql(query,values,as_dict)
        self.frappe.db.sql=sql
        self.recovery.record=lambda event,**kw:self.audit.update({kw['idempotency_key']:json.dumps(kw['payload'])})
        self.source_run=self.make_run('OLD-RUN',self.rinse)
        self.source_run.status='Progress Posted';self.source_run.progress='OLD-PROGRESS'
        self.doc('CFG Kanban Operation Progress','OLD-PROGRESS',process_execution='RINSE',material_run=self.source_run.name,good_qty=5)
        self.rinse.handoff_mode='Digital Quantity Handoff';self.rinse.good_qty=5;self.rinse.released_qty=5
        self.data['CFG Kanban Cycle']['RINSE'].stock_uom='Nos'
        self.data['CFG Kanban Master']['MASTER'].operation_profiles=[
            Row(operation='Rinse',material_run_hopper_mode='Fill Hopper',destination_operation='Pack',material_run_hopper_warehouse='Production'),
            Row(operation='Pack',material_run_hopper_mode='Consume Hopper',dependency_operation='Rinse')]
        self.data['Job Card']['JC-PACK'].operation='Pack'
        self.data['Job Card']['JC-PACK'].total_completed_qty=0
    def call(self,action='Release unused',**kw):
        return self.recovery.recover_material_run('OLD-RUN',action,'Physical reconciliation','TOKEN',**kw)
    def draw(self,used=2,remaining=1):
        return self.doc('CFG Kanban Operation Material Draw','D',material_run='OLD-RUN',process_execution='RINSE',
            drawn_qty=used+remaining,used_qty=used,remaining_qty=remaining,released_qty=0,status='Carry Forward')
    def test_release_only_unused_preserves_used_and_original_draw(self):
        draw=self.draw();result=self.call()
        self.assertEqual((draw.drawn_qty,draw.used_qty,draw.remaining_qty,draw.released_qty),(3,2,0,1))
        self.assertEqual(result['released_qty'],1)
    def test_identical_retry_returns_audited_result_without_second_release(self):
        self.draw();self.call();result=self.call()
        self.assertTrue(result['duplicate']);self.assertEqual(len(self.audit),1)
    def test_token_cannot_be_reused_for_different_payload(self):
        self.draw();self.call()
        with self.assertRaisesRegex(ValueError,'different recovery data'):self.call(physical_qty=1)
    def test_other_open_run_blocks_release_of_its_carry(self):
        self.draw();self.make_run('CURRENT',self.rinse)
        with self.assertRaisesRegex(ValueError,'other open Material Run'):self.call()
    def test_reconstruction_links_original_progress_without_reporting_again(self):
        result=self.call('Reconstruct hopper',hopper_scan='HOPPER_1',physical_qty=5)
        fill=self.data['CFG Kanban Operation Hopper Fill'][result['hopper_fill']]
        self.assertEqual((fill.source_progress,fill.source_material_run,fill.qty),('OLD-PROGRESS','OLD-RUN',5))
        self.assertEqual(len(self.data['CFG Kanban Operation Progress']),1)
        self.assertEqual(self.rinse.good_qty,5)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_qty,5)
        self.assertNotIn('Stock Entry',self.data)
    def test_reconstruction_retry_does_not_create_another_fill(self):
        args=dict(hopper_scan='HOPPER_1',physical_qty=5)
        self.call('Reconstruct hopper',**args);self.assertTrue(self.call('Reconstruct hopper',**args)['duplicate'])
        self.assertEqual(len(self.data['CFG Kanban Operation Hopper Fill']),1)
    def test_partial_physical_balance_is_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'Physical quantity must match'):
            self.call('Reconstruct hopper',hopper_scan='HOPPER_1',physical_qty=4)
    def test_prior_packing_requires_explicit_historical_reconciliation(self):
        self.data['Job Card']['JC-PACK'].total_completed_qty=1
        with self.assertRaisesRegex(ValueError,'Packing already has output'):
            self.call('Reconstruct hopper',hopper_scan='HOPPER_1',physical_qty=5)
    def test_closed_wo_cannot_reconstruct_but_can_release_unused(self):
        self.order.status='Completed';self.draw()
        with self.assertRaisesRegex(ValueError,'active Work Order'):
            self.call('Reconstruct hopper',hopper_scan='HOPPER_1',physical_qty=5)
        self.assertEqual(self.call()['released_qty'],1)
    def test_unreleased_output_cannot_be_reconstructed(self):
        self.rinse.released_qty=4
        with self.assertRaisesRegex(ValueError,'fully released'):
            self.call('Reconstruct hopper',hopper_scan='HOPPER_1',physical_qty=5)
    def test_unauthorized_operator_cannot_preview_or_mutate(self):
        self.modules['cfg_kanban.services.operator_auth'].require_operator.side_effect=ValueError('Not authorized')
        with self.assertRaisesRegex(ValueError,'Not authorized'):self.call()
    def test_release_open_run_cancels_preparation_and_returns_hopper_reservation(self):
        self.source_run.status='Open';self.source_run.progress=None;self.rinse.open_material_run=self.source_run.name
        self.hoppers.prepare_run_hopper(self.rinse,self.source_run,'HOPPER_1');self.draw(used=0,remaining=3)
        result=self.call()
        self.assertEqual((self.source_run.status,result['released_qty']),('Cancelled',3))
        self.assertIsNone(self.data['CFG Kanban Operation Hopper Fill'][self.source_run.operation_hopper_fill].active_hopper_key)

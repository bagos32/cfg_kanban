"""Offline carry-in workflows with native-document doubles, not ERP/MariaDB acceptance."""
import json
import sys
from unittest.mock import patch
from cfg_kanban.tests.test_operation_hoppers import HopperHarness, Row, Doc


class NativeJob(Doc):
    def set(self, key, value):
        self[key]=value
    def get_overlap_for(self,args,open_job_cards=None):
        return {'name':'BUSY-WORKSTATION'}
    def append(self, field, value):
        self.setdefault(field, []).append(Row(value))
    def save(self, **kwargs):
        self.owner.carry.prepare_carry_credit_validation(self)
        for log in self.time_logs:
            if self.get_overlap_for(log):raise ValueError('Native workstation overlap')
        self.total_completed_qty=sum(float(row.completed_qty or 0) for row in self.time_logs)
        self.status='Work In Progress'
        # Emulate cumulative native feedback, including its duplicate-release guard.
        execution=self.owner.data['CFG Kanban Process Execution'][self.name]
        execution.good_qty=self.total_completed_qty
        if self.total_completed_qty > float(execution.released_qty or 0):
            self.owner.wip.append(('UNEXPECTED MIRRORED RELEASE',self.total_completed_qty-execution.released_qty))
        return self
    def submit(self):
        if abs(self.total_completed_qty-self.for_quantity)>0.000001:
            raise ValueError('Native quantity is not complete')
        self.docstatus=1;self.status='Completed'
        self.owner.data['CFG Kanban Process Execution'][self.name].status='Completed'
        return self


class TestHopperCarryIn(HopperHarness):
    def setUp(self):
        super().setUp()
        self.modules['frappe.utils'].get_datetime=lambda value:value
        self.frappe.ValidationError=ValueError;self.frappe._dict=Row;self.frappe.parse_json=json.loads;self.frappe.as_json=json.dumps
        self.carry=self.load('hopper_carry_in');self.recovery=self.load('hopper_recovery');self.receipts=self.load('material_run_receipts')
        self.module_patch=patch.dict(sys.modules,{'cfg_kanban.services.hopper_carry_in':self.carry,
            'cfg_kanban.services.material_run_receipts':self.receipts})
        self.module_patch.start();self.addCleanup(self.module_patch.stop)
        import types
        cancellation=types.ModuleType('cfg_kanban.services.production_cancellation');cancellation.assert_cycle_not_under_cancellation=lambda name:None
        summary=types.ModuleType('cfg_kanban.services.operation_summary');summary.refresh_destination=lambda *args:None
        self.extra_patch=patch.dict(sys.modules,{cancellation.__name__:cancellation,summary.__name__:summary})
        self.extra_patch.start();self.addCleanup(self.extra_patch.stop)
        self.audit={};old_sql=self.frappe.db.sql
        def sql(query,values=None,as_dict=False):
            if 'from `tabCFG Kanban Event`' in query:return [(self.audit[values],)] if values in self.audit else []
            if 'from `tabWork Order`' in query:return [Row(self.data['Work Order'][values])]
            if 'from `tabStock Entry`' in query:return [Row(self.data['Stock Entry'][values])] if values in self.data.get('Stock Entry',{}) else []
            if 'from `tabJob Card Time Log`' in query:return list(self.data['Job Card'][values].time_logs)
            if 'from `tabJob Card`' in query:return [Row(self.data['Job Card'][values])]
            if 'select * from `tabCFG Kanban Cycle`' in query:return [Row(self.data['CFG Kanban Cycle'][values])]
            if 'select * from `tabCFG Kanban Process Execution`' in query:return [Row(self.data['CFG Kanban Process Execution'][values])]
            if 'from `tabCFG Kanban Operation Material Run`' in query:
                return [(row.name,) for row in self.data.get('CFG Kanban Operation Material Run',{}).values() if row.operation_hopper_fill==values and row.status=='Open']
            if 'from `tabStock Entry Detail`' in query:return []
            if 'from `tabCFG Kanban Hopper Carry In`' in query:return list(self.data.get('CFG Kanban Hopper Carry In',{}).values())
            return old_sql(query,values,as_dict)
        self.frappe.db.sql=sql
        self.recovery.record=lambda event,**kw:self.audit.update({kw['idempotency_key']:json.dumps(kw['payload'],default=str)})
        self.rinse.released_qty=3;self.rinse.material_run_rules_json=json.dumps([self.rule('RAW','Rinse','Kg')])
        run,self.fill=self.load_hopper(qty=3)
        self.doc('CFG Kanban Operation Progress',run.progress,process_execution='RINSE',material_run=run.name,good_qty=3,cancelled=0)
        self.order.update(docstatus=1,status='Closed',production_item='PRODUCT',bom_no='BOM',qty=3)
        self.doc('Stock Entry','OLD-CONSUMPTION',docstatus=1,work_order='WO',company='CFG',purpose='Material Consumption for Manufacture')
        self.doc('CFG Kanban Material Trace','OLD-TRACE',stock_entry='OLD-CONSUMPTION',lines=[Row(name='OLD-LINE',direction='Input',
            handling_unit='RAW-TAG',item_code='RAW',warehouse='Production',stock_uom='Kg',qty=3,status='Confirmed')])
        self.doc('CFG Kanban Operation Material Draw','OLD-DRAW',process_execution='RINSE',work_order='WO',job_card='JC-RINSE',operation='Rinse',
            material_flow_rule_row='RULE-RAW',status='Bound to ERP',item_code='RAW',source_warehouse='Production',stock_uom='Kg',
            source_handling_unit='RAW-TAG',used_qty=3,remaining_qty=0,material_trace='OLD-TRACE',material_trace_line='OLD-LINE')
        self.master=self.data['CFG Kanban Master']['MASTER'];self.master.update(certificate_requirements=[],certificate_output_rules=[])
        self.master.operation_profiles=[Row(operation='Rinse',dependency_operation=None,destination_operation='Pack',handoff_mode='Digital Quantity Handoff',
            material_run_hopper_mode='Fill Hopper',material_run_hopper_warehouse='Production'),
            Row(operation='Pack',dependency_operation='Rinse',material_run_hopper_mode='Consume Hopper',material_run_hopper_warehouse='Production')]
        self.new=self.doc('Work Order','NEW',company='CFG',docstatus=1,status='In Process',production_item='PRODUCT',bom_no='BOM',
            skip_transfer=1,cfg_kanban_controlled=1,cfg_kanban_cycle='NEW-MAIN',qty=3,produced_qty=0,
            required_items=[Row(item_code='RAW',source_warehouse='Production',stock_uom='Kg',required_qty=3,operation='Rinse'),
                Row(item_code='BAG',source_warehouse='Production',stock_uom='Nos',required_qty=3,operation='Pack')])
        self.doc('CFG Kanban Cycle','NEW-MAIN',kanban_master='MASTER',work_order='NEW',status='In Production')
        for operation,mode,item,uom in [('Rinse','Fill Hopper','RAW','Kg'),('Pack','Consume Hopper','BAG','Nos')]:
            name='NEW-'+operation.upper()
            self.data['Job Card'][name]=NativeJob(name=name,doctype='Job Card',owner=self,work_order='NEW',operation=operation,
                workstation='W',docstatus=0,status='Open',for_quantity=3,total_completed_qty=0,time_logs=[],items=[],sub_operations=[])
            self.doc('CFG Kanban Process Execution',name,kanban_master='MASTER',kanban_cycle='NEW-MAIN',job_card=name,operation=operation,
                workstation='W',runtime_allocation=None,status='Ready',target_qty=3,processed_qty=0,good_qty=0,released_qty=0,
                material_run_hopper_mode=mode,material_run_hopper_warehouse='Production',material_run_hopper_source_operation='Rinse' if operation=='Pack' else None,
                material_run_control='Required Before Progress',material_run_rules_json=json.dumps([self.rule(item,operation,uom)]),
                material_run_settlement_timing='At Work Order Manufacture Receipt',destination_operation='Pack' if operation=='Rinse' else None)
    def rule(self,item,operation,uom):
        return dict(rule_row='RULE-'+item,item_code=item,operation=operation,scan_warehouse='Production',stock_uom=uom,qty_per_output=1)
    def call(self,**kw):
        return self.recovery.recover_hopper(self.fill.name,'HOPPER_1','Carry into Work Order',3,'Physical count; inherited WIP','TOKEN',
            target_work_order='NEW',target_job_card='NEW-RINSE',**kw)
    def test_closed_order_carry_credits_native_rinse_without_new_raw_draw_or_work_time(self):
        result=self.call();job=self.data['Job Card']['NEW-RINSE']
        self.assertEqual((job.total_completed_qty,job.docstatus,job.status),(3,1,'Completed'))
        log=job.time_logs[0];self.assertEqual(log.from_time,log.to_time);self.assertIsNone(log.get('employee'))
        self.assertEqual(log.cfg_hopper_carry_in,result['carry_in'])
        self.assertEqual((self.fill.work_order,self.fill.current_work_order,self.fill.source_execution),('WO','NEW','RINSE'))
        self.assertEqual(len(self.data['CFG Kanban Operation Material Draw']),1)
        self.assertEqual(len(self.data['Stock Entry']),1)
        self.assertEqual(len(self.data['CFG Kanban Operation Progress']),1)
        self.assertEqual(self.wip[0][0][1:3],('Adjusted',-3))
        self.assertEqual(self.wip[1][0][1:3],('Released',3))
        self.assertEqual(len(self.wip),2)
    def test_three_carried_into_five_leaves_two_to_rinse(self):
        self.new.qty=5
        for row in self.new.required_items:row.required_qty=5
        job=self.data['Job Card']['NEW-RINSE'];job.for_quantity=5
        self.data['Job Card']['NEW-PACK'].for_quantity=5
        self.call()
        self.assertEqual((job.for_quantity-job.total_completed_qty,job.docstatus),(2,0))
        self.assertEqual(self.data['CFG Kanban Process Execution']['NEW-RINSE'].released_qty,3)
    def test_new_packing_consumes_carried_hopper_but_old_order_cannot(self):
        self.call();pack=self.data['CFG Kanban Process Execution']['NEW-PACK']
        run=self.make_run('NEW-PACK-RUN',pack);run.work_order='NEW'
        self.hoppers.prepare_run_hopper(pack,run,'HOPPER_1')
        self.hoppers.validate_run_hopper(pack,run,2,2)
        self.hoppers.apply_run_hopper(pack,run,Row(name='NEW-PROGRESS',processed_qty=2,good_qty=2))
        use=list(self.data['CFG Kanban Operation Hopper Use'].values())[0]
        self.assertEqual((use.work_order,use.qty),('NEW',2))
        self.assertEqual(self.wip[-1][0][:3],('NEW-MAIN','Consumed',2))
        self.assertEqual(self.wip[-1][1]['source_execution'],'NEW-RINSE')
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_qty,1)
        with self.assertRaisesRegex(ValueError,'remaining operation Hopper WIP'):self.hoppers.assert_no_open_hoppers('NEW')
        self.hoppers.assert_no_open_hoppers('WO')
    def test_retry_has_one_native_credit_one_carry_and_one_transfer_of_wip(self):
        self.call();result=self.call();self.assertTrue(result['duplicate'])
        self.assertEqual(len(self.data['CFG Kanban Hopper Carry In']),1)
        self.assertEqual(len(self.data['Job Card']['NEW-RINSE'].time_logs),1)
        self.assertEqual(len(self.wip),2)
    def test_target_choices_require_explicit_exact_job_card(self):
        result=self.carry.carry_in_targets(self.fill.name,'NEW')
        self.assertEqual([row['name'] for row in result['choices']],['NEW-RINSE'])
        with self.assertRaisesRegex(ValueError,'eligible untouched'):
            self.carry.lock_target(self.fill.name,'NEW','NEW-PACK',None)
    def test_company_item_bom_cycle_and_route_are_enforced(self):
        for field,value in [('company','OTHER'),('production_item','OTHER'),('bom_no','OTHER'),('skip_transfer',0),('produced_qty',1),('status','Closed')]:
            previous=self.new.get(field);self.new[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.call()
            self.new[field]=previous
        self.master.operation_profiles[1].dependency_operation='Other'
        with self.assertRaisesRegex(ValueError,'two-operation'):self.call()
    def test_source_must_be_terminal_and_original_inputs_must_still_be_posted(self):
        self.order.status='In Process'
        with self.assertRaisesRegex(ValueError,'completed or closed'):self.call()
        self.order.status='Closed';self.data['Stock Entry']['OLD-CONSUMPTION'].docstatus=2
        with self.assertRaisesRegex(ValueError,'cancelled'):self.call()
        self.assertEqual(len(self.data['Job Card']['NEW-RINSE'].time_logs),0)
    def test_target_source_gate_and_unproven_bom_coverage_are_not_bypassed(self):
        self.master.certificate_requirements=[Row(operation='Rinse')]
        with self.assertRaisesRegex(ValueError,'certificate/task gates'):self.call()
        self.master.certificate_requirements=[];self.new.required_items[0].required_qty=4
        with self.assertRaisesRegex(ValueError,'full BOM input scope'):self.call()
    def test_over_demand_and_unsettled_source_are_rejected_before_native_credit(self):
        self.data['Job Card']['NEW-RINSE'].for_quantity=2
        with self.assertRaisesRegex(ValueError,'remaining demand'):self.call()
        self.data['Job Card']['NEW-RINSE'].for_quantity=3
        self.data['CFG Kanban Operation Material Draw']['OLD-DRAW'].status='Used'
        with self.assertRaisesRegex(ValueError,'settlements'):self.call()
        self.assertEqual(len(self.data['Job Card']['NEW-RINSE'].time_logs),0)
    def test_used_target_job_and_existing_stock_draft_are_rejected(self):
        self.data['Job Card']['NEW-RINSE'].time_logs=[Row(completed_qty=1)]
        with self.assertRaisesRegex(ValueError,'eligible untouched'):self.call()
        self.data['Job Card']['NEW-RINSE'].time_logs=[]
        self.doc('Stock Entry','NEW-DRAFT',work_order='NEW',docstatus=0)
        with self.assertRaisesRegex(ValueError,'stock draft'):self.call()
    def test_cancelled_native_credit_cannot_be_used_for_packing(self):
        self.call();self.data['Job Card']['NEW-RINSE'].docstatus=2
        pack=self.data['CFG Kanban Process Execution']['NEW-PACK'];run=self.make_run('P',pack)
        with self.assertRaisesRegex(ValueError,'native credit was changed'):
            self.hoppers.prepare_run_hopper(pack,run,'HOPPER_1')
    def test_active_carry_in_cannot_be_erased_by_confirm_empty(self):
        self.call()
        with self.assertRaisesRegex(ValueError,'credits an active Work Order'):
            self.recovery.recover_hopper(self.fill.name,'HOPPER_1','Confirm physically empty',0,'Physical check','OTHER-TOKEN')
    def test_receipt_excludes_inherited_raw_and_consumes_only_new_bags(self):
        self.call()
        self.doc('CFG Kanban Operation Hopper Use','CARRIED-USE',hopper_fill=self.fill.name,work_order='NEW',qty=3)
        pack=self.data['Job Card']['NEW-PACK'];pack.docstatus=1;pack.status='Completed';pack.total_completed_qty=3
        self.data['CFG Kanban Process Execution']['NEW-PACK'].status='Completed'
        self.doc('CFG Kanban Operation Material Draw','BAGS',process_execution='NEW-PACK',work_order='NEW',job_card='NEW-PACK',operation='Pack',
            material_flow_rule_row='RULE-BAG',status='Used',item_code='BAG',source_warehouse='Production',stock_uom='Nos',
            source_handling_unit='BAG-TAG',used_qty=3,remaining_qty=0,material_trace=None,material_trace_line=None)
        class Entry(Row):
            def remove(self,row):self['items'].remove(row)
            @property
            def items(self):return self['items']
        entry=Entry(name='NEW-RECEIPT',purpose='Manufacture',cfg_kanban_cycle='NEW-MAIN',work_order='NEW',company='CFG',docstatus=0,fg_completed_qty=3,
            items=[Row(name='RAW',item_code='RAW',s_warehouse='Production',t_warehouse=None,stock_uom='Kg',qty=3,transfer_qty=3,conversion_factor=1),
                Row(name='BAG',item_code='BAG',s_warehouse='Production',t_warehouse=None,stock_uom='Nos',qty=3,transfer_qty=3,conversion_factor=1),
                Row(name='FG',item_code='PRODUCT',s_warehouse=None,t_warehouse='FG',stock_uom='Nos',qty=3,transfer_qty=3,conversion_factor=1)])
        adjustments=self.receipts.reconcile_manufacture_material_runs(entry)
        self.assertEqual([row.item_code for row in entry.items],['BAG','PRODUCT'])
        self.assertEqual(entry.items[0].qty,3)
        self.assertEqual(adjustments[0]['actual_pending_qty'],0)
        self.assertEqual(self.receipts.reconcile_manufacture_material_runs(entry),[])
        self.assertEqual(self.data['CFG Kanban Operation Material Draw']['OLD-DRAW'].used_qty,3)
    def test_source_cancellation_is_blocked_while_receiving_order_exists(self):
        self.call()
        for doc in [self.order,self.data['Stock Entry']['OLD-CONSUMPTION']]:
            with self.subTest(doctype=doc.doctype),self.assertRaisesRegex(ValueError,'downstream Work Order'):
                self.carry.protect_source_cancellation(doc)
        self.new.docstatus=2
        self.carry.protect_source_cancellation(self.order)

    def test_receipt_blocks_native_packing_credit_without_real_hopper_consumption(self):
        self.call()
        with self.assertRaisesRegex(ValueError,'Consume the carried Hopper WIP'):
            self.carry.receipt_evidence(self.new,list(self.get_all('Job Card',{'work_order':'NEW'})))

    def test_read_only_summary_does_not_block_recovery_when_native_credit_is_inconsistent(self):
        self.call()
        job=self.data['Job Card']['NEW-PACK'];job.docstatus=1;job.status='Completed'
        self.assertEqual(self.receipts.material_run_receipt_summary(self.new),[])

    def test_unrelated_packing_certificate_rules_remain_configured(self):
        self.master.certificate_requirements=[Row(operation='Pack',certificate_type='EXPIRY')]
        self.call()
        self.assertEqual(self.master.certificate_requirements[0].certificate_type,'EXPIRY')

    def test_new_packing_input_availability_uses_native_credit_once(self):
        from cfg_kanban.tests.test_material_actuals_yield import functions
        self.call();old_sql=self.frappe.db.sql
        def sql(query,values=None,**kwargs):
            if 'from `tabJob Card`' in query:
                return [(sum(float(job.total_completed_qty or 0) for job in self.get_all('Job Card',
                    {'work_order':values[0],'operation':values[1]})),)]
            return [(0,)]
        self.frappe.db.sql=sql
        try:
            ns=functions('services/runtime_selector.py',['_available_input'],{'frappe':self.frappe,'flt':lambda x:float(x or 0)})
            profile=Row(dependency_operation='Rinse',start_rule='Minimum Qty Available')
            job=Row(work_order='NEW',remaining_qty=5)
            self.assertEqual(ns['_available_input'](job,self.master,profile,0,0),3)
            self.assertEqual(ns['_available_input'](job,self.master,profile,2,0),1)
            self.assertEqual(ns['_available_input'](job,self.master,profile,0,3),0)
        finally:self.frappe.db.sql=old_sql

    def test_partial_carry_receipt_keeps_only_two_new_raw_and_five_new_bags(self):
        self.new.qty=5
        for row in self.new.required_items:row.required_qty=5
        rinse=self.data['Job Card']['NEW-RINSE'];pack=self.data['Job Card']['NEW-PACK']
        rinse.for_quantity=5;pack.for_quantity=5;self.call()
        rinse.append('time_logs',dict(completed_qty=2,cfg_kanban_progress='NEW-RAW-PROGRESS'))
        rinse.total_completed_qty=5;rinse.docstatus=1;rinse.status='Completed'
        pack.total_completed_qty=5;pack.docstatus=1;pack.status='Completed'
        self.doc('CFG Kanban Operation Hopper Use','CARRIED-USE',hopper_fill=self.fill.name,work_order='NEW',qty=3)
        for item,operation,uom,qty in [('RAW','Rinse','Kg',2),('BAG','Pack','Nos',5)]:
            self.doc('CFG Kanban Operation Material Draw','NEW-'+item,process_execution='NEW-'+operation.upper(),work_order='NEW',
                job_card='NEW-'+operation.upper(),operation=operation,material_flow_rule_row='RULE-'+item,status='Used',
                item_code=item,source_warehouse='Production',stock_uom=uom,source_handling_unit=item+'-TAG',used_qty=qty,
                remaining_qty=0,material_trace=None,material_trace_line=None)
        class Entry(Row):
            def remove(self,row):self['items'].remove(row)
            @property
            def items(self):return self['items']
        entry=Entry(name='NEW-RECEIPT',purpose='Manufacture',cfg_kanban_cycle='NEW-MAIN',work_order='NEW',company='CFG',docstatus=0,fg_completed_qty=5,
            items=[Row(name='RAW',item_code='RAW',s_warehouse='Production',t_warehouse=None,stock_uom='Kg',qty=5,transfer_qty=5,conversion_factor=1),
                Row(name='BAG',item_code='BAG',s_warehouse='Production',t_warehouse=None,stock_uom='Nos',qty=5,transfer_qty=5,conversion_factor=1),
                Row(name='FG',item_code='PRODUCT',s_warehouse=None,t_warehouse='FG',stock_uom='Nos',qty=5,transfer_qty=5,conversion_factor=1)])
        self.receipts.reconcile_manufacture_material_runs(entry)
        self.assertEqual([(row.item_code,row.qty) for row in entry.items],[('RAW',2),('BAG',5),('PRODUCT',5)])

    def test_verified_zero_duration_credit_alone_is_exempt_from_busy_workstation(self):
        self.call();job=self.data['Job Card']['NEW-RINSE']
        self.assertEqual(job.get_overlap_for(job.time_logs[0]),{})
        self.assertEqual(job.get_overlap_for(Row(cfg_kanban_progress='ACTUAL-WORK')),{'name':'BUSY-WORKSTATION'})

    def test_native_saves_cannot_rewrite_credit_quantity_employee_or_duration(self):
        self.call();job=self.data['Job Card']['NEW-RINSE'];log=job.time_logs[0]
        for key,value in [('completed_qty',4),('employee','OTHER'),('to_time','2026-11-16 13:00:00')]:
            previous=log.get(key);log[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'evidence was changed'):
                self.carry.prepare_carry_credit_validation(job)
            log[key]=previous

    def test_current_locked_native_child_rows_prevent_overwriting_concurrent_real_work(self):
        sql=self.frappe.db.sql
        def concurrent(query,values=None,as_dict=False):
            if 'select * from `tabJob Card`' in query and values=='NEW-RINSE':
                return [Row(self.data['Job Card'][values],total_completed_qty=1)]
            if 'from `tabJob Card Time Log`' in query:
                return [Row(completed_qty=1,cfg_kanban_progress='CONCURRENT-ACTUAL')]
            return sql(query,values,as_dict)
        self.frappe.db.sql=concurrent
        with self.assertRaisesRegex(ValueError,'changed; reload'):self.call()
        self.assertEqual(self.data['Job Card']['NEW-RINSE'].total_completed_qty,1)
        self.assertNotIn('CFG Kanban Hopper Carry In',self.data)

    def test_current_fill_owner_must_match_the_owner_used_to_prepare_target(self):
        target=self.carry.lock_target(self.fill.name,'NEW','NEW-RINSE',None)
        self.fill.current_work_order='ANOTHER-OWNER'
        with self.assertRaisesRegex(ValueError,'ownership changed'):
            self.carry.apply_carry(self.fill,target,3,'Physical count',Row(employee='EMP'))
        self.assertNotIn('CFG Kanban Hopper Carry In',self.data)

    def test_second_hopper_can_complete_the_remaining_two_unit_native_credit(self):
        self.new.qty=5
        for row in self.new.required_items:row.required_qty=5
        self.data['Job Card']['NEW-RINSE'].for_quantity=5
        self.data['Job Card']['NEW-PACK'].for_quantity=5
        self.call()
        self.doc('CFG Kanban Operation Material Run','SECOND-RUN',work_order='WO',process_execution='RINSE',status='Progress Posted',progress='SECOND-P')
        self.doc('CFG Kanban Operation Progress','SECOND-P',process_execution='RINSE',material_run='SECOND-RUN',good_qty=2,cancelled=0)
        second=self.doc('CFG Kanban Operation Hopper Fill','SECOND-FILL',handling_unit='HU-2',active_hopper_key='HU-2',work_order='WO',
            company='CFG',warehouse='Production',stock_uom='Nos',source_operation='Rinse',destination_operation='Pack',source_execution='RINSE',
            source_material_run='SECOND-RUN',source_progress='SECOND-P',qty=2,used_qty=0,reserved_qty=0,status='Ready')
        self.recovery.recover_hopper(second.name,'HOPPER_2','Carry into Work Order',2,'Other physical load','SECOND-TOKEN',
            target_work_order='NEW',target_job_card='NEW-RINSE')
        job=self.data['Job Card']['NEW-RINSE']
        self.assertEqual((job.total_completed_qty,job.docstatus,len(job.time_logs)),(5,1,2))
        self.assertEqual(len(self.wip),4)

    def test_target_choices_omit_workstations_outside_supervisor_scope(self):
        auth=self.modules['cfg_kanban.services.operator_auth'].require_operator
        auth.return_value=(Row(employee='EMP',allowed_workstations=[Row(workstation='OTHER-STATION')]),Row(name='SESSION'))
        self.assertEqual(self.carry.carry_in_targets(self.fill.name,'NEW')['choices'],[])

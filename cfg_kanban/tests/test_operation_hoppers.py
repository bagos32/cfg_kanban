"""Offline workflow tests with in-memory Frappe doubles; not site/DB isolation acceptance."""
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Doc(Row):
    def db_set(self, values, value=None, **kwargs):
        self.update(values if isinstance(values, dict) else {values:value})
    def insert(self, **kwargs):
        self.setdefault('name', self.doctype + '-' + str(len(self.owner.data.get(self.doctype, {}))+1))
        if self.doctype == 'CFG Kanban Operation Hopper Fill':
            for row in self.owner.data.get(self.doctype, {}).values():
                if self.active_hopper_key and row.active_hopper_key == self.active_hopper_key:
                    raise ValueError('Hopper already has an active fill')
        if self.doctype == 'CFG Kanban Operation Hopper Use':
            for row in self.owner.data.get(self.doctype, {}).values():
                if row.material_run == self.material_run:
                    raise ValueError('Material Run already consumed Hopper WIP')
        self.owner.data.setdefault(self.doctype,{})[self.name]=self
        return self
    def reload(self):return self


class HopperHarness(unittest.TestCase):
    def setUp(self):
        self.data={};self.events=[];self.native={};self.wip=[]
        frappe=types.ModuleType('frappe');self.frappe=frappe
        frappe.whitelist=lambda *args,**kwargs:lambda fn:fn
        frappe.throw=lambda message:(_ for _ in ()).throw(ValueError(message))
        frappe.get_doc=self.get_doc;frappe.get_all=self.get_all
        frappe.db=Row(sql=self.sql,get_value=self.get_value,set_value=self.set_value,
                      exists=self.exists,table_exists=lambda name:True)
        utils=types.ModuleType('frappe.utils');utils.flt=lambda x:float(x or 0)
        utils.now_datetime=lambda:'2026-11-16 12:00:00'
        events=types.ModuleType('cfg_kanban.services.events')
        events.record=lambda event,**values:self.events.append((event,values))
        idem=types.ModuleType('cfg_kanban.services.idempotency')
        idem.canonical_key=lambda *values:hashlib.sha256(json.dumps(values).encode()).hexdigest()
        auth=types.ModuleType('cfg_kanban.services.operator_auth')
        auth.require_operator=Mock(return_value=(Row(employee='EMP'),Row(name='SESSION')))
        scans=types.ModuleType('cfg_kanban.services.logistics_foundation')
        scans.resolve_logistics_scan=lambda value:next((dict(identity_type='Handling Unit',name=row.name)
            for row in self.data['CFG Kanban Handling Unit'].values() if row.handling_unit_id==value),None)
        containers=types.ModuleType('cfg_kanban.services.container_contents')
        containers.active_container_contents=lambda name:self.native.get(name,[])
        containers.assert_container_not_in_open_manifest=Mock()
        crew=types.ModuleType('cfg_kanban.services.crew_authorization')
        crew.release_execution_wip_if_authorized=Mock(return_value=True);self.crew=crew
        wip=types.ModuleType('cfg_kanban.services.wip');wip.append_entry=lambda *args,**kwargs:self.wip.append((args,kwargs))
        runs=types.ModuleType('cfg_kanban.services.operation_material_runs');runs._refresh_run_totals=self.refresh
        self.modules={'frappe':frappe,'frappe.utils':utils,events.__name__:events,idem.__name__:idem,
            auth.__name__:auth,scans.__name__:scans,containers.__name__:containers,crew.__name__:crew,
            wip.__name__:wip,runs.__name__:runs}
        self.patcher=patch.dict(sys.modules,self.modules);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.hoppers=self.load('operation_hoppers')
        sys.modules['cfg_kanban.services.operation_hoppers']=self.hoppers
        self.addCleanup(lambda:sys.modules.pop('cfg_kanban.services.operation_hoppers',None))
        self.release=self.load('material_run_release')
        self.order=self.doc('Work Order','WO',company='CFG',docstatus=1,status='In Process',cfg_kanban_cycle='MAIN')
        self.doc('CFG Kanban Master','MASTER',company='CFG',stock_uom='Nos')
        self.doc('Warehouse','Production',company='CFG')
        for name in ('RINSE','PACK'):
            self.doc('Job Card','JC-'+name,work_order='WO')
            self.doc('CFG Kanban Cycle',name,work_order='WO',status='In Production')
        self.rinse=self.execution('RINSE','Fill Hopper',destination_operation='Pack',target_qty=20)
        self.pack=self.execution('PACK','Consume Hopper',material_run_hopper_source_operation='Rinse',target_qty=5)
        for number in (1,2):
            self.doc('CFG Kanban Handling Unit','HU-'+str(number),handling_unit_id='HOPPER_'+str(number),
                tag_kind='Reusable Container',handling_unit_type='Hopper',reusable_container_role='Production Output Container',
                inventory_company='CFG',current_warehouse='Production',identity_state='Active',quality_state='Released',
                movement_state='Received',current_qty=0,available_qty=0)

    def load(self,name):
        spec=importlib.util.spec_from_file_location(name+'_subject',ROOT/'services'/str(name+'.py'))
        service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service);return service
    def doc(self,doctype,name,**values):
        row=Doc(values,doctype=doctype,name=name,owner=self);self.data.setdefault(doctype,{})[name]=row;return row
    def execution(self,name,mode,**values):
        return self.doc('CFG Kanban Process Execution',name,kanban_cycle=name,kanban_master='MASTER',job_card='JC-'+name,
            operation='Rinse' if name=='RINSE' else 'Pack',material_run_hopper_mode=mode,
            material_run_hopper_warehouse='Production',processed_qty=0,transfer_multiple=1,**values)
    def make_run(self,name,execution):
        return self.doc('CFG Kanban Operation Material Run',name,process_execution=execution.name,
            work_order='WO',kanban_cycle=execution.kanban_cycle,status='Open',progress=None,
            hopper_reserved_qty=0,hopper_used_qty=0)
    def get_doc(self,doctype,name=None):
        if isinstance(doctype,dict):return Doc(doctype,owner=self)
        return self.data[doctype][name]
    def matches(self,row,filters):
        for name,value in (filters or {}).items():
            if isinstance(value,(tuple,list)):
                op, rhs=value;actual=row.get(name)
                if op=='in' and actual not in rhs:return False
                if op=='>' and float(actual or 0)<=rhs:return False
            elif row.get(name)!=value:return False
        return True
    def get_all(self,doctype,filters=None,fields=None,pluck=None,**kwargs):
        rows=[row for row in self.data.get(doctype,{}).values() if self.matches(row,filters)]
        return [row.get(pluck) for row in rows] if pluck else rows
    def get_value(self,doctype,name,field,*args,**kwargs):
        row=(next(iter(self.get_all(doctype,filters=name)),None) if isinstance(name,dict)
             else self.data.get(doctype,{}).get(name))
        return row.get(field) if row else None
    def set_value(self,doctype,name,values,value=None,**kwargs):
        self.data[doctype][name].db_set(values,value)
    def exists(self,doctype,filters):return bool(self.get_all(doctype,filters=filters))
    def sql(self,query,values=None,as_dict=False):
        if 'from `tabCFG Kanban Operation Hopper Fill`' in query:
            return [Row(row) for row in self.data.get('CFG Kanban Operation Hopper Fill',{}).values() if row.active_hopper_key==values]
        if 'from `tabCFG Kanban Operation Material Draw`' in query:
            return [Row(row) for row in self.data.get('CFG Kanban Operation Material Draw',{}).values()
                    if row.process_execution==values and float(row.remaining_qty or 0)>0.000001
                    and row.status in ('Open','Partially Used','Carry Forward','Used','Bound to ERP')]
        if 'select * from `tabCFG Kanban Handling Unit`' in query:
            return [Row(self.data['CFG Kanban Handling Unit'][values])]
        if 'execution.*, cycle.status' in query:
            row=self.data['CFG Kanban Process Execution'][values]
            return [Row(row,locked_cycle_status=self.data['CFG Kanban Cycle'][row.kanban_cycle].status)]
        if 'select execution.name' in query:
            return [(row.name,) for row in self.data['CFG Kanban Process Execution'].values()
                    if self.data['CFG Kanban Cycle'][row.kanban_cycle].work_order==values
                    and self.data['CFG Kanban Cycle'][row.kanban_cycle].status=='Completed']
        return [] # lock-only query
    def refresh(self,run):
        rows=self.get_all('CFG Kanban Operation Material Draw',{'material_run':run.name})
        run.update(drawn_qty=sum(row.drawn_qty for row in rows),used_qty=sum(row.used_qty for row in rows),
            carry_forward_qty=sum(row.remaining_qty for row in rows),released_qty=sum(row.released_qty or 0 for row in rows))
    def load_hopper(self,hopper='HOPPER_1',qty=5):
        run=self.make_run('RINSE-RUN-'+str(len(self.data.get('CFG Kanban Operation Material Run',{}))),self.rinse)
        self.hoppers.prepare_run_hopper(self.rinse,run,hopper)
        progress=Row(name='P-'+run.name,good_qty=qty,processed_qty=qty)
        self.hoppers.validate_run_hopper(self.rinse,run,qty,qty)
        self.hoppers.apply_run_hopper(self.rinse,run,progress)
        run.db_set({'status':'Progress Posted','progress':progress.name})
        self.rinse.processed_qty+=qty
        return run,self.data['CFG Kanban Operation Hopper Fill'][run.operation_hopper_fill]
    def consume(self,fill_qty,used_qty):
        self.load_hopper(qty=fill_qty)
        run=self.make_run('PACK-RUN',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_1')
        self.hoppers.validate_run_hopper(self.pack,run,used_qty,used_qty)
        self.hoppers.apply_run_hopper(self.pack,run,Row(name='PACK-P',processed_qty=used_qty,good_qty=used_qty))
        self.pack.processed_qty+=used_qty
        return run


class TestOperationHoppers(HopperHarness):
    def test_rinse_loads_good_output_and_packing_consumes_same_wo_without_erp_stock(self):
        self.consume(5,2)
        unit=self.data['CFG Kanban Handling Unit']['HU-1']
        self.assertEqual((unit.operation_wip_qty,unit.operation_wip_available_qty,unit.operation_wip_reserved_qty),(3,3,0))
        self.assertEqual((unit.current_qty,unit.available_qty),(0,0))
        self.assertEqual(unit.movement_state,'Loaded')
        use=list(self.data['CFG Kanban Operation Hopper Use'].values())[0]
        self.assertEqual((use.work_order,use.qty,use.stock_uom),('WO',2,'Nos'))
        self.assertFalse(any(name in self.data for name in ('Stock Entry','Stock Ledger Entry')))
    def test_loaded_and_available_quantities_are_visible_before_confirmation(self):
        self.load_hopper(qty=5)
        result=self.hoppers.preview_scanner_hopper('PACK','HOPPER_1')
        self.assertEqual((result['loaded_qty'],result['available_qty'],result['stock_uom']),(5,5,'Nos'))
    def test_empty_hopper_blocks_consumption(self):
        with self.assertRaisesRegex(ValueError,'no released operation fill'):
            self.hoppers.prepare_run_hopper(self.pack,self.make_run('PACK-RUN',self.pack),'HOPPER_1')
    def test_another_wo_or_route_cannot_consume_the_fill(self):
        _,fill=self.load_hopper();fill.work_order='OTHER'
        with self.assertRaisesRegex(ValueError,'another Work Order'):
            self.hoppers.prepare_run_hopper(self.pack,self.make_run('PACK-RUN',self.pack),'HOPPER_1')
    def test_output_cannot_refill_an_occupied_or_filling_hopper(self):
        first=self.make_run('ONE',self.rinse);self.hoppers.prepare_run_hopper(self.rinse,first,'HOPPER_1')
        with self.assertRaisesRegex(ValueError,'select an empty Hopper'):
            self.hoppers.prepare_run_hopper(self.rinse,self.make_run('TWO',self.rinse),'HOPPER_1')
        self.load_hopper('HOPPER_2',3)
    def test_second_hopper_can_fill_while_first_is_reserved_for_packing(self):
        self.load_hopper(qty=5)
        self.hoppers.prepare_run_hopper(self.pack,self.make_run('PACK-RUN',self.pack),'HOPPER_1')
        self.load_hopper('HOPPER_2',4)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-2'].operation_wip_qty,4)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_reserved_qty,5)
    def test_overdraw_and_second_reservation_are_rejected(self):
        self.load_hopper(qty=3);run=self.make_run('PACK-RUN',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_1')
        with self.assertRaisesRegex(ValueError,'exceeds'):
            self.hoppers.validate_run_hopper(self.pack,run,4,4)
        with self.assertRaisesRegex(ValueError,'no available quantity'):
            self.hoppers.prepare_run_hopper(self.pack,self.make_run('SECOND',self.pack),'HOPPER_1')
    def test_consumed_hopper_can_be_refilled_with_a_new_audited_fill(self):
        self.consume(5,5);_,new_fill=self.load_hopper(qty=3)
        self.assertEqual(new_fill.qty,3)
        self.assertEqual(len(self.data['CFG Kanban Operation Hopper Fill']),2)
    def test_cancelling_output_preparation_releases_empty_hopper_identity(self):
        run=self.make_run('PREPARE',self.rinse);self.hoppers.prepare_run_hopper(self.rinse,run,'HOPPER_1')
        self.hoppers.cancel_run_hopper(run.name,'Mistake')
        fill=self.data['CFG Kanban Operation Hopper Fill'][run.operation_hopper_fill]
        self.assertEqual(fill.status,'Cancelled');self.assertIsNone(fill.active_hopper_key)
        self.hoppers.prepare_run_hopper(self.rinse,self.make_run('RETRY',self.rinse),'HOPPER_1')
    def test_cancelling_consumption_returns_reservation_not_physical_loaded_quantity(self):
        self.load_hopper();run=self.make_run('PACK-RUN',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_1');self.hoppers.cancel_run_hopper(run.name,'Mistake')
        unit=self.data['CFG Kanban Handling Unit']['HU-1']
        self.assertEqual((unit.operation_wip_qty,unit.operation_wip_available_qty),(5,5))
        self.assertNotIn('CFG Kanban Operation Hopper Use',self.data)
    def test_normal_digital_handoff_needs_no_hopper(self):
        self.pack.material_run_hopper_mode='None';run=self.make_run('NORMAL',self.pack)
        self.hoppers.prepare_run_hopper(self.pack,run,None)
        self.hoppers.validate_run_hopper(self.pack,None,5,5)
        self.hoppers.apply_run_hopper(self.pack,run,Row(processed_qty=5))
        self.assertNotIn('CFG Kanban Operation Hopper Fill',self.data)
    def test_cross_company_wrong_warehouse_hold_and_native_stock_block_hopper(self):
        unit=self.data['CFG Kanban Handling Unit']['HU-1']
        for key,value in [('inventory_company','OTHER'),('current_warehouse','OTHER'),('quality_state','Hold'),('movement_state','Internal Transit')]:
            previous=unit.get(key);unit[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.hoppers.preview_scanner_hopper('RINSE','HOPPER_1')
            unit[key]=previous
        self.native[unit.name]=['ERP-FILL']
        with self.assertRaisesRegex(ValueError,'ERP-manufactured'):
            self.hoppers.preview_scanner_hopper('RINSE','HOPPER_1')
    def test_crew_gate_and_transfer_multiple_control_release(self):
        run=self.make_run('RINSE-RUN',self.rinse);self.hoppers.prepare_run_hopper(self.rinse,run,'HOPPER_1')
        self.crew.release_execution_wip_if_authorized.return_value=False
        with self.assertRaisesRegex(ValueError,'crew authorization'):
            self.hoppers.validate_run_hopper(self.rinse,run,5,5)
        self.crew.release_execution_wip_if_authorized.return_value=True
        self.rinse.transfer_multiple=2
        with self.assertRaisesRegex(ValueError,'Transfer Multiple'):
            self.hoppers.validate_run_hopper(self.rinse,run,5,5)
    def test_final_close_blocks_remaining_physical_wip(self):
        self.load_hopper()
        with self.assertRaisesRegex(ValueError,'remaining operation Hopper WIP'):
            self.hoppers.assert_no_open_hoppers('WO')
    def test_manifest_cannot_dispatch_hopper_with_active_operation_wip(self):
        from cfg_kanban.tests.test_material_actuals_yield import functions
        self.load_hopper()
        snapshot=Mock()
        ns=functions('services/logistics_stock_identity.py',['capture_manifest_line'],{
            'frappe':self.frappe,'identity_snapshot':snapshot})
        with self.assertRaisesRegex(ValueError,'active operation WIP'):
            ns['capture_manifest_line'](Row(handling_unit='HU-1'))
        snapshot.assert_not_called()

    def test_closed_cycle_rejects_stale_run_and_progress_requests(self):
        self.data['CFG Kanban Cycle']['RINSE'].status='Completed'
        with self.assertRaisesRegex(ValueError,'Cycle is closed'):
            self.hoppers.lock_execution('RINSE')
    def test_start_requires_a_prepared_hopper_only_in_opt_in_mode(self):
        with self.assertRaisesRegex(ValueError,'Prepare Start Material Run'):
            self.hoppers.assert_hopper_prepared(self.pack)
        self.pack.material_run_hopper_mode='None';self.hoppers.assert_hopper_prepared(self.pack)


class TestMaterialReservationRelease(HopperHarness):
    def draw(self,name,drawn,used,remaining,status='Carry Forward',released=0):
        run=self.data.get('CFG Kanban Operation Material Run',{}).get('RAW-RUN') or self.make_run('RAW-RUN',self.rinse)
        run.status='Progress Posted';run.progress='P'
        return self.doc('CFG Kanban Operation Material Draw',name,material_run=run.name,process_execution='RINSE',
            source_handling_unit='RAW-TAG',work_order='WO',job_card='JC-RINSE',operation='Rinse',workstation='W',
            drawn_qty=drawn,used_qty=used,remaining_qty=remaining,released_qty=released,status=status)
    def close(self):
        self.data['CFG Kanban Cycle']['RINSE'].status='Completed'
        return self.release.release_closed_execution('RINSE','Close operation')
    def test_scan_three_use_two_releases_one_and_preserves_pending_used(self):
        draw=self.draw('DRAW',3,2,1);result=self.close()
        self.assertEqual((draw.drawn_qty,draw.used_qty,draw.remaining_qty,draw.released_qty,draw.status),(3,2,0,1,'Used'))
        self.assertEqual(result['released_qty'],1)
        self.assertEqual(self.data['CFG Kanban Operation Material Run']['RAW-RUN'].carry_forward_qty,0)
        self.assertEqual(self.data['CFG Kanban Operation Material Run']['RAW-RUN'].released_qty,1)
    def test_fully_unused_draw_is_released_not_left_in_an_unusable_closed_execution(self):
        draw=self.draw('DRAW',1,0,1);self.close()
        self.assertEqual((draw.status,draw.used_qty,draw.remaining_qty,draw.released_qty),('Released',0,0,1))
    def test_erp_submission_and_reversal_do_not_re_reserve_released_unused_balance(self):
        from cfg_kanban.tests.test_material_actuals_yield import functions
        draw=self.draw('DRAW',3,2,1);self.close();draw.material_trace='TRACE'
        ns=functions('services/operation_material_runs.py',[
            'confirm_material_run_settlement','reverse_material_run_settlement'],{
            'frappe':self.frappe,'flt':lambda x:float(x or 0),'TOLERANCE':0.000001,
            'ACTIVE_DRAW_STATUSES':('Open','Partially Used','Carry Forward','Used')})
        ns['confirm_material_run_settlement']('TRACE');self.assertEqual(draw.status,'Bound to ERP')
        ns['reverse_material_run_settlement']('TRACE')
        self.assertEqual((draw.status,draw.used_qty,draw.remaining_qty,draw.released_qty),('Used',2,0,1))

    def test_settled_draw_remains_settled_with_original_usage(self):
        draw=self.draw('DRAW',3,2,1,status='Bound to ERP');self.close()
        self.assertEqual((draw.status,draw.used_qty,draw.released_qty),('Bound to ERP',2,1))
    def test_closure_retry_does_not_release_or_audit_twice(self):
        self.draw('DRAW',3,2,1);self.close();count=len(self.events)
        self.assertEqual(self.close()['released_qty'],0);self.assertEqual(len(self.events),count)
    def test_live_cycle_keeps_carry_forward(self):
        draw=self.draw('DRAW',3,2,1)
        with self.assertRaisesRegex(ValueError,'completed operation'):
            self.release.release_closed_execution('RINSE','Too soon')
        self.assertEqual(draw.remaining_qty,1)
    def test_release_never_changes_another_execution(self):
        draw=self.draw('DRAW',3,2,1);other=self.draw('OTHER',4,1,3);other.process_execution='PACK'
        self.close();self.assertEqual(other.remaining_qty,3);self.assertEqual(draw.remaining_qty,0)
    def test_open_unused_next_run_is_cancelled_and_hopper_reservation_returned(self):
        self.load_hopper();run=self.make_run('NEXT-PACK',self.pack);self.pack.open_material_run=run.name
        self.hoppers.prepare_run_hopper(self.pack,run,'HOPPER_1')
        self.data['CFG Kanban Cycle']['PACK'].status='Completed'
        self.release.release_closed_execution('PACK','Close operation')
        self.assertEqual(run.status,'Cancelled')
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_available_qty,5)
        self.assertIsNone(self.pack.open_material_run)
    def test_release_preserves_physical_rinsed_hopper_quantity(self):
        self.load_hopper(qty=2);self.draw('DRAW',3,2,1);self.close()
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU-1'].operation_wip_qty,2)
    def test_inconsistent_legacy_quantities_fail_closed(self):
        self.draw('DRAW',3,2,2)
        with self.assertRaisesRegex(ValueError,'require reconciliation'):self.close()


class TestCarryForwardRunTotals(unittest.TestCase):
    def test_later_run_usage_refreshes_original_run_balance(self):
        from cfg_kanban.tests.test_material_actuals_yield import functions
        frappe=types.ModuleType('frappe');frappe.db=Row(sql=Mock())
        draw=Doc(name='DRAW',material_run='EARLIER',used_qty=2,remaining_qty=1,released_qty=0)
        earlier=Doc(name='EARLIER');current=Doc(name='CURRENT',kanban_cycle='C',process_execution='E',work_order='WO',job_card='JC',operation='Pack',workstation='W')
        frappe.get_doc=lambda doctype,name:draw if doctype.endswith('Material Draw') else {'EARLIER':earlier,'CURRENT':current}[name]
        refreshed=[]
        ns=functions('services/operation_material_runs.py',['apply_progress_material_plan'],{
            'frappe':frappe,'flt':lambda x:float(x or 0),'TOLERANCE':0.000001,'_':lambda x:x,
            '_refresh_run_totals':lambda run:refreshed.append(run.name),'record':Mock(),'canonical_key':lambda *args:str(args)})
        ns['apply_progress_material_plan']([{'draw':'DRAW','qty':1}],Row(name='PROGRESS'),current)
        self.assertEqual(draw.remaining_qty,0)
        self.assertEqual(set(refreshed),{'EARLIER','CURRENT'})


class TestReservationCurrentReads(unittest.TestCase):
    def test_pending_use_remains_reserved_but_released_and_traced_use_are_not_double_counted(self):
        from cfg_kanban.tests.test_material_actuals_yield import functions
        frappe=types.ModuleType('frappe');frappe.db=Row(sql=Mock(return_value=[
            Row(used_qty=2,remaining_qty=0,material_trace=None),
            Row(used_qty=4,remaining_qty=1,material_trace='TRACE')]))
        ns=functions('services/operation_material_runs.py',['_source_reserved_qty'],{
            'frappe':frappe,'flt':lambda x:float(x or 0)})
        self.assertEqual(ns['_source_reserved_qty']('TAG'),3)


class TestClosedCycleRepair(unittest.TestCase):
    def test_patch_selects_only_completed_cycles_and_refreshes_stale_closed_run_totals(self):
        import sqlite3
        from cfg_kanban.tests.test_material_actuals_yield import functions
        connection=sqlite3.connect(':memory:');self.addCleanup(connection.close)
        connection.executescript('''
            create table `tabCFG Kanban Cycle` (name text,status text);
            create table `tabCFG Kanban Process Execution` (name text,kanban_cycle text);
            create table `tabCFG Kanban Operation Material Draw` (process_execution text,remaining_qty real,status text);
            create table `tabCFG Kanban Operation Material Run` (name text,kanban_cycle text,carry_forward_qty real);
            insert into `tabCFG Kanban Cycle` values ('CLOSED','Completed'),('ACTIVE','In Production');
            insert into `tabCFG Kanban Process Execution` values ('OLD','CLOSED'),('CURRENT','ACTIVE');
            insert into `tabCFG Kanban Operation Material Draw` values ('OLD',1,'Carry Forward'),('CURRENT',1,'Carry Forward');
            insert into `tabCFG Kanban Operation Material Run` values ('STALE-OLD','CLOSED',1),('LIVE','ACTIVE',1);
        ''')
        frappe=types.ModuleType('frappe');frappe.db=Row(table_exists=lambda name:True,
            sql=lambda query:connection.execute(query).fetchall())
        frappe.get_doc=lambda doctype,name:Row(name=name)
        release=types.ModuleType('cfg_kanban.services.material_run_release');release.release_closed_execution=Mock()
        runs=types.ModuleType('cfg_kanban.services.operation_material_runs');runs._refresh_run_totals=Mock()
        ns=functions('patches/v1_7/release_closed_cycle_material_reservations.py',['execute'],{'frappe':frappe})
        with patch.dict(sys.modules,{release.__name__:release,runs.__name__:runs}):ns['execute']()
        self.assertEqual([call.args[0] for call in release.release_closed_execution.call_args_list],['OLD'])
        self.assertEqual([call.args[0].name for call in runs._refresh_run_totals.call_args_list],['STALE-OLD'])

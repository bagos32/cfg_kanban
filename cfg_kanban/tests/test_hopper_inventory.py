"""Actual report SQL against SQLite: intermediate WIP is separate from ERP quantities."""
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch
from cfg_kanban.tests.test_material_run_inventory_balance import TestMaterialRunInventoryBalance as InventoryHarness, AttrDict, ROOT


class TestHopperInventory(unittest.TestCase):
    sql = InventoryHarness.sql
    table_exists = InventoryHarness.table_exists
    add_tag = InventoryHarness.add_tag
    result = InventoryHarness.result
    tearDown = InventoryHarness.tearDown
    def setUp(self):
        InventoryHarness.setUp(self)
        self.db.executescript('''
          alter table `tabCFG Kanban Handling Unit` add column operation_hopper_fill text;
          create table `tabWork Order` (name text,production_item text,status text);
          create table `tabCFG Kanban Process Execution` (name text,kanban_master text);
          create table `tabCFG Kanban Master` (name text,item_code text);
          create table `tabCFG Kanban Operation Hopper Fill` (
             name text,handling_unit text,current_handling_unit text,active_hopper_key text,
             work_order text,company text,warehouse text,source_operation text,destination_operation text,
             source_execution text,source_material_run text,source_progress text,stock_uom text,
             status text,qty real,used_qty real,cleared_qty real,reserved_qty real,
             current_work_order text,current_source_execution text,carry_in text);
          insert into `tabWork Order` values ('OLD-WO','PRODUCT','Closed');
          insert into `tabCFG Kanban Process Execution` values ('RINSE','MASTER');
          insert into `tabCFG Kanban Master` values ('MASTER','PRODUCT');
          insert into `tabItem` values ('PRODUCT','Cendol WIP',1);
          insert into `tabCFG Kanban Handling Unit`
             (name,handling_unit_id,inventory_company,current_warehouse,tag_kind,identity_state,quality_state,movement_state,operation_hopper_fill)
             values ('HU-1','HOPPER_3','TEST','Production','Reusable Container','Active','Released','Loaded','FILL');
          insert into `tabCFG Kanban Operation Hopper Fill` values
             ('FILL','HU-1',null,'HU-1','OLD-WO','TEST','Production','Rinse','Pack','RINSE','RUN','P','Nos','Ready',5,2,0,1,null,null,null);
        ''')
        frappe=self.report.frappe;frappe.throw=lambda msg:(_ for _ in ()).throw(ValueError(msg))
        utils=types.ModuleType('frappe.utils');utils.flt=lambda x:float(x or 0)
        spec=importlib.util.spec_from_file_location('cfg_kanban.services.hopper_inventory',ROOT/'services/hopper_inventory.py')
        self.inventory=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'frappe':frappe,'frappe.utils':utils}):spec.loader.exec_module(self.inventory)
        self.modules=patch.dict(sys.modules,{'cfg_kanban.services.hopper_inventory':self.inventory});self.modules.start();self.addCleanup(self.modules.stop)
    def wip(self,mode='Summary',**filters):
        return [row for row in self.result(mode,**filters)[1] if row.certificate_posting_status=='Operation WIP']
    def test_closed_wo_shows_item_and_remaining_in_both_report_modes(self):
        for mode in ('Summary','Tag Detail'):
            row=self.wip(mode)[0]
            self.assertEqual((row.item_code,row.work_order,row.work_order_status),('PRODUCT','OLD-WO','Closed'))
            self.assertEqual((row.operation_wip_qty,row.operation_wip_reserved_qty,row.operation_wip_available_qty),(3,1,2))
            self.assertEqual((row.current_qty,row.operational_qty,row.material_run_pending_consumed_qty),(0,0,0))
    def test_default_operational_filter_includes_wip_but_erp_only_does_not(self):
        self.assertEqual(len(self.wip(inventory_control_mode='Kanban Operational Inventory')),1)
        self.assertEqual(self.wip(inventory_control_mode='ERP Stock'),[])
        self.assertEqual(self.wip(certificate_posting_status='ERP Posted'),[])
        self.assertEqual(self.wip(certificate_posting_status='Pending ERP Consolidation'),[])
    def test_hopper_filter_and_wip_only_filter_do_not_leak_posted_stock(self):
        for mode in ('Summary','Tag Detail'):
            for filters in ({'operation_hopper':'HU-1'},{'inventory_control_mode':'Operation WIP'},{'certificate_posting_status':'Operation WIP'}):
                self.assertEqual(len(self.result(mode,**filters)[1]),1)
            self.assertEqual(self.result(mode,operation_hopper='MISSING')[1],[])
    def test_normal_filters_and_quality_restrictions_apply_to_wip(self):
        for filters in ({'company':'OTHER'},{'warehouse':'Raw Store'},{'item_code':'RAW'},{'stock_uom':'Kg'},{'quality_state':'Hold'}):
            self.assertEqual(self.wip(**filters),[])
        self.db.execute("update `tabCFG Kanban Handling Unit` set quality_state='Hold' where name='HU-1'")
        self.assertEqual(self.wip()[0].operation_wip_available_qty,0)
    def test_report_summaries_keep_wip_out_of_erp_tag_totals(self):
        summary={row['label']:row['value'] for row in self.result()[4]}
        self.assertEqual(summary['Operation WIP Hoppers'],1)
        self.assertEqual(summary['Operation WIP (Nos)'],3)
        self.assertEqual(summary['WIP Reserved (Nos)'],1)
        self.assertEqual(summary['WIP Available (Nos)'],2)
        self.assertEqual(summary['ERP-Posted Tags Included'],1)
    def test_current_physical_hopper_after_transfer_is_shown_once(self):
        self.db.execute("insert into `tabCFG Kanban Handling Unit` (name,handling_unit_id,current_warehouse,identity_state,quality_state) values ('HU-2','HOPPER_4','Production','Active','Released')")
        self.db.execute("update `tabCFG Kanban Operation Hopper Fill` set current_handling_unit='HU-2',active_hopper_key='HU-2'")
        self.assertEqual(self.wip()[0].operation_hopper,'HU-2')
        self.assertEqual(self.wip(operation_hopper='HU-1'),[])
    def test_clear_removes_balance_and_include_empty_can_show_audit_quantity(self):
        self.db.execute("update `tabCFG Kanban Operation Hopper Fill` set cleared_qty=3,reserved_qty=0,status='Empty',active_hopper_key=null")
        self.assertEqual(self.wip(),[])
        row=self.wip(include_zero_balance=1)[0]
        self.assertEqual((row.operation_wip_qty,row.used_qty,row.cleared_qty),(0,2,3))
        self.assertIsNone(self.inventory.hopper_snapshot(AttrDict(name='HU-1',tag_kind='Reusable Container')))
    def test_lookup_snapshot_includes_closed_wo_without_writing_native_stock(self):
        row=self.inventory.hopper_snapshot(AttrDict(name='HU-1',tag_kind='Reusable Container'))
        self.assertEqual((row.item_code,row.operation_wip_qty),('PRODUCT',3))
        self.assertEqual(self.db.execute("select current_qty from `tabCFG Kanban Handling Unit` where name='HU-1'").fetchone()[0],None)

    def lookup_payload(self):
        """Exercise actual API wiring with the same real WIP query as the report."""
        from cfg_kanban.tests.test_material_actuals_yield import functions
        from unittest.mock import Mock
        frappe=self.report.frappe
        unit=AttrDict(dict(self.db.execute("select * from `tabCFG Kanban Handling Unit` where name='HU-1'").fetchone()))
        containers=types.ModuleType('cfg_kanban.services.container_contents')
        containers.container_status_for_unit=lambda doc:{'mode':'container','current_contents':[],
            'content_summary':{'tag_count':0,'item_codes':[],'by_uom':[]}}
        serials=types.ModuleType('cfg_kanban.services.serial_evidence');serials.active_serials_for_unit=lambda name:[]
        frappe.get_doc=lambda *args:unit;frappe.get_all=lambda *args,**kwargs:[]
        actual_sql=frappe.db.sql
        frappe.db.sql=lambda query,*args,**kwargs:[] if 'Handling Unit Quantity Ledger' in query else actual_sql(query,*args,**kwargs)
        try:
            ns=functions('api/logistics.py',['lookup_logistics_tag'],{
                'frappe':frappe,'require_operator':lambda token:(AttrDict(can_start=1),None),
                '_resolve_kanban_card_scan':lambda scan:None,
                'resolve_logistics_scan':lambda scan:{'identity_type':'Handling Unit','name':'HU-1'},
                '_can_view_all':lambda profile:True,'can_stock_retag':lambda profile:False,
                '_authorized_route_names':lambda profile:[],})
            with patch.dict(sys.modules,{containers.__name__:containers,serials.__name__:serials}):
                return ns['lookup_logistics_tag']('HOPPER_3','SESSION')
        finally:
            frappe.db.sql=actual_sql

    def test_real_logistics_lookup_includes_wip_even_when_native_container_is_empty(self):
        result=self.lookup_payload()
        self.assertEqual(result['operation_wip'].item_code,'PRODUCT')
        self.assertEqual(result['operation_wip'].operation_wip_qty,3)
        self.assertEqual(result['operation_wip'].work_order_status,'Closed')
        self.assertEqual(result['container_status']['current_contents'],[])
        self.assertIsNone(result['handling_unit']['item_code'])

    def test_carry_in_shows_current_order_and_original_provenance_without_adding_stock(self):
        self.db.execute("insert into `tabWork Order` values ('NEW-WO','PRODUCT','In Process')")
        self.db.execute("update `tabCFG Kanban Operation Hopper Fill` set current_work_order='NEW-WO',carry_in='CARRY-1'")
        row=self.wip()[0]
        self.assertEqual((row.work_order,row.original_work_order,row.carry_in),('NEW-WO','OLD-WO','CARRY-1'))
        self.assertEqual((row.operation_wip_qty,row.total_qty,row.erp_actual_qty),(3,0,None))

"""Read-only lorry/floor behaviour, using actual application functions offline."""
import ast
import datetime
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]

class Row(dict):
    def __getattr__(self,name):
        if name.startswith('__'):raise AttributeError(name)
        return self.get(name)
    def __setattr__(self,name,value):self[name]=value
    def check_permission(self,ptype):
        if self.get('_denied'):raise PermissionError('Read denied')


def load(path,namespace):
    body=[]
    for node in ast.parse((ROOT/path).read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef,ast.Assign)):
            if isinstance(node,ast.FunctionDef):node.decorator_list=[]
            body.append(node)
    exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),namespace)
    return namespace


class TestVehicleOverview(unittest.TestCase):
    def setUp(self):
        self.data={};self.read_warehouse=True;self.hidden_items=set();self.balances={('BAG','LOT'):2,('RAW',''):4}
        self.queries=[];self.roles=['Stock User'];self.stock_reads=[]
        self.operator=Row(employee='DRIVER',responsibilities=[Row(responsibility='Dispatch')])
        self.profile=Row(name='LOGISTICS',active=1,profile_name='Lorry Queue',view_type='Logistics and Delivery',
            access_mode='Read Only',company='B',refresh_interval_seconds=30,column_count='3',queue_depth=5,show_statistics=1)
        self.add('Company','B');self.add('Company','A')
        self.add('Warehouse','LORRY',company='B',cfg_is_vehicle_warehouse=1,cfg_vehicle_reference='TRUCK1',disabled=0,is_group=0)
        self.add('Warehouse','SOURCE',company='B',disabled=0,is_group=0)
        self.add('Warehouse','OTHER-LORRY',company='A',cfg_is_vehicle_warehouse=1,cfg_vehicle_reference='TRUCK1',disabled=0,is_group=0)
        self.add('Item','BAG',item_name='Plastic Bag',stock_uom='Nos',is_stock_item=1)
        self.add('Item','RAW',item_name='Raw',stock_uom='Kg',is_stock_item=1)
        self.add('Batch','LOT',item='BAG',expiry_date='2027-01-01')
        self.add('CFG Kanban Handling Unit','TAG',handling_unit_id='RM1',item_code='BAG',batch_no='LOT',stock_uom='Nos',
            inventory_company='B',current_warehouse='LORRY',current_qty=2,reserved_qty=1,available_qty=1,identity_state='Active',
            expiry_date='2027-01-01',quality_state='Released',movement_state='Received',process_certificate_set='CERT')
        self.add('CFG Kanban Logistics Route','ROUTE',active=1,source_company='B',destination_company='B',dispatch_responsibility='Dispatch')
        self.plan=self.add_plan('DPL',state='Loaded',vehicle_warehouse='LORRY',vehicle_reference='TRUCK1',fulfilment_status='Not Started')
        self.add('CFG Kanban Dispatch Plan Line','LINE',parent='DPL',idx=1,item_code='BAG',stock_uom='Nos',requested_qty=5,loaded_qty=5)
        self.add('CFG Kanban Route Stop','STOP',dispatch_plan='DPL',planned_sequence=1,site_name='Shop',customer='CUST',
            customer_scan_point='SITE',customer_address='ADDR',state='Planned')
        self.frappe=Row(get_all=self.get_all,get_list=self.get_list,get_doc=self.get_doc,get_roles=lambda:self.roles,
            has_permission=lambda *a,**k:self.read_warehouse,throw=lambda msg,*a:(_ for _ in ()).throw(ValueError(msg)),
            only_for=self.only_for)
        planning=Row(_view_all=lambda operator:bool(operator.get('view_all')),
            _responsibilities=lambda operator:{row.responsibility for row in operator.responsibilities},
            _vehicle_warehouse=lambda name:self.data['Warehouse'][name])
        common=dict(frappe=self.frappe,flt=lambda value:float(value or 0),now_datetime=lambda:datetime.datetime(2026,11,20,12),
                    require_operator=Mock(return_value=(self.operator,Row())))
        self.ns=load('services/vehicle_overview.py',dict(common))
        self.ns['_planning']=lambda:planning
        self.mod=types.ModuleType('cfg_kanban.services.vehicle_overview');self.mod.__dict__.update(self.ns)
        ledger=types.ModuleType('cfg_kanban.services.route_reconciliation')
        def balances(*args):self.stock_reads.append(args);return dict(self.balances)
        ledger._erp_balances=balances
        sheets=types.ModuleType('cfg_kanban.services.route_sheets');sheets.vehicle_sheets=lambda *args:[]
        p=patch.dict(sys.modules,{self.mod.__name__:self.mod,ledger.__name__:ledger,sheets.__name__:sheets});p.start();self.addCleanup(p.stop)
        self.dashboard=load('api/dashboard.py',dict(common,overlay_dispatch=Mock(side_effect=AssertionError('Production queue called for logistics'))))
        self.data['CFG Kanban Dashboard Profile']={'LOGISTICS':self.profile}

    def add(self,doctype,name,**values):
        row=Row(doctype=doctype,name=name,**values);self.data.setdefault(doctype,{})[name]=row;return row
    def add_plan(self,name,**values):
        base=dict(company='B',source_warehouse='SOURCE',fulfilment_mode='Vehicle Delivery',business_label='Route stock',
            plan_type='Open Route Stock',dispatch_responsibility='Dispatch',priority='Normal',logistics_route='ROUTE',
            destination_assignment_policy='Select Before Dispatch',trip_date='2026-11-20')
        base.update(values);return self.add('CFG Kanban Dispatch Plan',name,**base)
    def only_for(self,roles):
        if not set(self.roles).intersection(roles):raise PermissionError('Role denied')
    def get_doc(self,dt,name):return self.data[dt][name]
    def matches(self,row,filters):
        for key,value in filters.items():
            actual=row.get(key)
            if isinstance(value,(tuple,list)):
                op,expected=value
                if op=='in' and actual not in expected:return False
                if op=='not in' and actual in expected:return False
                if op=='>' and float(actual or 0)<=expected:return False
            elif actual!=value:return False
        return True
    def get_all(self,dt,filters=None,fields=None,**kwargs):
        self.queries.append((dt,dict(filters or {})))
        # Catch application queries for columns absent from CFG schemas.
        slug=dt.lower().replace(' ','_');schema=ROOT/'cfg_kanban/doctype'/slug/(slug+'.json')
        if schema.exists():
            known={field['fieldname'] for field in json.loads(schema.read_text())['fields']}|{'name','parent','idx','modified','creation'}
            self.assertTrue(set(fields or []).issubset(known),(dt,set(fields or [])-known))
        return [Row({field:row.get(field) for field in fields}) if fields else Row(row)
            for row in self.data.get(dt,{}).values() if self.matches(row,filters or {})]
    def get_list(self,dt,**kwargs):
        rows=self.get_all(dt,**kwargs)
        return [row for row in rows if not(dt=='Item' and row.name in self.hidden_items)]
    def overview(self):return self.ns['vehicle_context']('LORRY',self.operator)

    def test_loaded_stock_remains_visible_after_loading_manifest_is_received(self):
        result=self.overview();self.assertEqual(result['assigned_plans'][0].state,'Loaded')
        self.assertEqual(result['assigned_plans'][0].lines[0].loaded_qty,5)
        stock={row['item_code']:row for row in result['stock']}
        self.assertEqual(stock['BAG']['erp_qty'],2);self.assertEqual(stock['BAG']['tag_qty'],2)
        self.assertEqual(stock['RAW']['erp_qty'],4);self.assertEqual(stock['RAW']['untagged_qty'],4)
        self.assertEqual(result['assigned_plans'][0].stops[0].site_name,'Shop')
        self.assertEqual(self.stock_reads[0][:2],('B','LORRY'))

    def test_tag_coverage_does_not_add_stock_and_variance_is_explicit(self):
        self.data['CFG Kanban Handling Unit']['TAG'].current_qty=3
        stock=self.overview()['stock'][0]
        self.assertEqual(stock['erp_qty'],2);self.assertEqual(stock['tag_qty'],3);self.assertEqual(stock['untagged_qty'],0)
        self.assertTrue(stock['identity_variance'])

    def test_reservations_and_quality_hold_do_not_hide_physical_stock(self):
        self.data['CFG Kanban Handling Unit']['TAG'].quality_state='Hold'
        result=self.overview();self.assertEqual(result['stock'][0]['erp_qty'],2)
        self.assertEqual(result['tags'][0].quality_state,'Hold');self.assertEqual(result['tags'][0].reserved_qty,1)

    def test_untagged_and_negative_erp_balances_are_visible(self):
        self.balances={('RAW',''):-1};self.data['CFG Kanban Handling Unit']={}
        row=self.overview()['stock'][0];self.assertEqual(row['erp_qty'],-1);self.assertEqual(row['tag_qty'],0)

    def test_company_specific_lorry_does_not_mix_another_company(self):
        self.add_plan('OTHER',company='A',state='Loaded',vehicle_warehouse='OTHER-LORRY')
        self.add('CFG Kanban Handling Unit','OTHER-TAG',inventory_company='A',current_warehouse='LORRY',
            identity_state='Active',current_qty=10,item_code='RAW')
        result=self.overview();self.assertEqual([row.name for row in result['assigned_plans']],['DPL'])
        self.assertEqual([row.name for row in result['tags']],['TAG'])

    def test_closed_plan_does_not_hide_remaining_lorry_stock(self):
        self.plan.state='Reconciled';result=self.overview();self.assertFalse(result['assigned_plans']);self.assertEqual(result['stock'][0]['erp_qty'],2)

    def test_multi_day_and_overnight_loaded_plan_stays_visible(self):
        self.plan.trip_date='2026-11-17';self.plan.dispatch_review_state='Overnight'
        self.assertEqual(self.overview()['assigned_plans'][0].name,'DPL')

    def test_read_permissions_hide_whole_view_before_reading_inventory(self):
        self.read_warehouse=False;result=self.overview();self.assertFalse(result['can_view_stock']);self.assertFalse(result['assigned_plans']);self.assertFalse(self.stock_reads)

    def test_item_user_restrictions_hide_erp_and_tag_rows_together(self):
        self.hidden_items={'BAG'};result=self.overview();self.assertTrue(result['item_rows_restricted'])
        self.assertEqual([row['item_code'] for row in result['stock']],['RAW']);self.assertFalse(result['tags'])

    def test_unauthorized_operator_cannot_read_stock_or_other_plan_assignments(self):
        self.operator.responsibilities=[Row(responsibility='Unrelated')];result=self.overview()
        self.assertFalse(result['can_view_stock']);self.assertFalse(result['assigned_plans']);self.assertFalse(result['stock'])

    def test_ready_and_upcoming_loads_remain_separate_and_honor_fixed_vehicle(self):
        self.add_plan('READY',state='Ready for Vehicle',priority='Urgent')
        self.add_plan('PICK',state='Picking')
        self.add_plan('WRONG',state='Ready for Vehicle',destination_assignment_policy='Fixed',destination_warehouse='OTHER-LORRY')
        result=self.overview();self.assertEqual([row.name for row in result['ready_plans']],['READY'])
        self.assertEqual([row.name for row in result['upcoming_plans']],['PICK'])

    def test_physical_container_code_and_certificate_remain_visible(self):
        self.add('CFG Kanban Handling Unit','BIN',handling_unit_id='BIN1')
        self.data['CFG Kanban Handling Unit']['TAG'].physical_container='BIN'
        row=self.overview()['tags'][0];self.assertEqual(row.physical_scan_code,'BIN1');self.assertEqual(row.process_certificate_set,'CERT')

    def test_multiple_stock_uoms_are_not_summed_as_a_single_quantity(self):
        self.add('CFG Kanban Dispatch Plan Line','LINE2',parent='DPL',idx=2,item_code='RAW',stock_uom='Kg',requested_qty=3,loaded_qty=3)
        qty=self.overview()['assigned_plans'][0].quantities_by_uom
        self.assertEqual(qty['Nos']['loaded'],5);self.assertEqual(qty['Kg']['loaded'],3)

    def test_public_read_endpoint_uses_authenticated_operator(self):
        result=self.ns['get_vehicle_overview']('LORRY','TOKEN');self.assertEqual(result['company'],'B')
        self.ns['require_operator'].assert_called_once_with('TOKEN')

    def test_logistics_floor_branch_never_queries_production_workstation_queue(self):
        result=self.dashboard['get_dashboard']('LOGISTICS');self.assertEqual(result['mode'],'logistics')
        self.assertEqual(result['vehicles'][0]['plans'][0].name,'DPL')
        self.dashboard['overlay_dispatch'].assert_not_called()

    def test_stock_user_sees_only_logistics_profiles_and_cannot_open_production_view(self):
        self.dashboard['get_profiles']();self.assertEqual(self.queries[-1][1]['view_type'],'Logistics and Delivery')
        self.profile.view_type='Station Display'
        with self.assertRaises(PermissionError):self.dashboard['get_dashboard']('LOGISTICS')

    def test_floor_requires_company_and_rejects_other_company_warehouse(self):
        self.profile.company=None
        with self.assertRaises(ValueError):self.ns['floor_context'](self.profile)
        self.profile.company='B';self.profile.warehouse='OTHER-LORRY'
        with self.assertRaises(ValueError):self.ns['floor_context'](self.profile)

    def test_single_lorry_floor_excludes_loads_fixed_to_another_vehicle(self):
        self.profile.warehouse='LORRY'
        self.add_plan('MINE',state='Ready for Vehicle',destination_assignment_policy='Fixed',destination_warehouse='LORRY')
        self.add_plan('WRONG',state='Ready for Vehicle',destination_assignment_policy='Fixed',destination_warehouse='OTHER-LORRY')
        self.add_plan('OPEN',state='Ready for Vehicle')
        result=self.ns['floor_context'](self.profile)
        self.assertEqual({row.name for row in result['preparing']},{'MINE','OPEN'})

    def test_floor_shows_ready_and_upcoming_without_workstations(self):
        self.add_plan('READY',state='Ready for Vehicle');self.add_plan('PICK',state='Picking')
        result=self.dashboard['get_dashboard']('LOGISTICS')
        self.assertEqual({row.name for row in result['preparing']},{'READY','PICK'})
        self.assertNotIn('stations',result);self.assertEqual(result['profile']['access_mode'],'Read Only')

if __name__=='__main__':unittest.main()

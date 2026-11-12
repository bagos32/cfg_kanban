"""Offline relational tests: execute actual report SQL against SQLite fixtures.

This exercises joins, grouping, filtering and arithmetic, not MariaDB/Frappe transactions.
"""
import importlib.util
import re
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class AttrDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class TestMaterialRunInventoryBalance(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("greatest", -1, max)
        hu_fields = {
            "name": "text", "handling_unit_id": "text", "inventory_company": "text",
            "current_warehouse": "text", "item_code": "text", "stock_uom": "text",
            "process_certificate_set": "text", "tag_kind": "text", "identity_state": "text",
            "quality_state": "text", "current_qty": "real", "reserved_qty": "real",
            "available_qty": "real", "last_reconciled_on": "text", "virtual_content": "integer",
            "physical_container": "text", "container_reference": "text", "short_description": "text",
            "batch_no": "text", "movement_state": "text", "physical_custodian": "text",
            "source_location": "text", "destination_location": "text", "last_scan_time": "text",
        }
        self.db.execute('create table `tabCFG Kanban Handling Unit` (' + ','.join(
            f'{name} {kind}' for name, kind in hu_fields.items()) + ')')
        self.db.execute('create table `tabItem` (name text, item_name text, is_stock_item integer)')
        self.db.execute('insert into `tabItem` values ("RAW", "Raw material", 1)')
        self.db.execute('create table `tabCFG Process Certificate Set` (name text, set_name text, member_codes text)')
        self.db.execute('create table `tabCFG Kanban Operation Material Draw` '
                        '(source_handling_unit text, status text, drawn_qty real, used_qty real, '
                        'remaining_qty real, material_trace text)')
        frappe = types.ModuleType("frappe")
        frappe._dict = AttrDict
        frappe._ = lambda value: value
        frappe.db = types.SimpleNamespace(sql=self.sql, table_exists=self.table_exists,
                                         get_value=lambda *args, **kwargs: 1000)
        utils = types.ModuleType("frappe.utils")
        utils.flt = lambda value: float(value or 0)
        utils.cint = lambda value: int(value or 0)
        path = ROOT / "cfg_kanban/report/kanban_operational_inventory_balance/kanban_operational_inventory_balance.py"
        spec = importlib.util.spec_from_file_location("inventory_balance_subject", path)
        self.report = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
            spec.loader.exec_module(self.report)
        self.add_tag()

    def tearDown(self):
        self.db.close()

    def sql(self, query, values=None, as_dict=False):
        query = re.sub(r'%\((\w+)\)s', r':\1', query)
        if isinstance(values, tuple):
            query = query.replace('%s', '?')
        rows = self.db.execute(query, values or {}).fetchall()
        return [AttrDict(dict(row)) if as_dict else tuple(row) for row in rows]

    def table_exists(self, name):
        return bool(self.db.execute('select name from sqlite_master where name=?',
                                    ('tab' + name,)).fetchone())

    def add_tag(self, name='TAG-1', current=1000, reserved=0, quality='Released', uom='Kg'):
        row = dict(name=name, handling_unit_id=name, inventory_company='TEST',
                   current_warehouse='Raw Store', item_code='RAW', stock_uom=uom,
                   process_certificate_set=None, tag_kind='Stock Tag', identity_state='Active',
                   quality_state=quality, current_qty=current, reserved_qty=reserved,
                   available_qty=current-reserved)
        self.db.execute('insert into `tabCFG Kanban Handling Unit` (' + ','.join(row) +
                        ') values (' + ','.join('?' for _ in row) + ')', tuple(row.values()))

    def draw(self, used=0, remaining=100, status='Open', trace=None, tag='TAG-1'):
        self.db.execute('insert into `tabCFG Kanban Operation Material Draw` values (?,?,?,?,?,?)',
                        (tag, status, used+remaining, used, remaining, trace))

    def result(self, mode='Summary', **filters):
        return self.report.execute(dict(display_mode=mode, **filters))

    def assert_quantities(self, row, reserved, consumed, remaining, available):
        self.assertEqual(row.material_run_reserved_qty, reserved)
        self.assertEqual(row.material_run_pending_consumed_qty, consumed)
        self.assertEqual(row.operational_qty, remaining)
        self.assertEqual(row.operational_available_qty, available)

    def test_open_reservation_visible_in_summary_and_tag_detail(self):
        self.draw()
        for mode in ('Summary', 'Tag Detail'):
            row = self.result(mode)[1][0]
            self.assert_quantities(row, 100, 0, 1000, 900)
            self.assertEqual(row.available_qty, 1000)

    def test_progress_reduces_operational_remaining_without_posting_erp_stock(self):
        self.draw(used=60, remaining=40, status='Carry Forward')
        for mode in ('Summary', 'Tag Detail'):
            row = self.result(mode)[1][0]
            self.assert_quantities(row, 40, 60, 940, 900)
            self.assertEqual(row.get('total_qty', row.get('current_qty')), 1000)

    def test_draft_trace_used_reservation_is_not_deducted_twice(self):
        self.db.execute('update `tabCFG Kanban Handling Unit` set reserved_qty=60, available_qty=940')
        self.draw(used=60, remaining=40, status='Carry Forward', trace='TRACE-1')
        for mode in ('Summary', 'Tag Detail'):
            self.assert_quantities(self.result(mode)[1][0], 40, 60, 940, 900)

    def test_bound_to_erp_draw_is_not_deducted_again(self):
        self.db.execute('update `tabCFG Kanban Handling Unit` set current_qty=940, available_qty=940')
        self.draw(used=60, remaining=40, status='Bound to ERP', trace='TRACE-1')
        self.assert_quantities(self.result()[1][0], 0, 0, 940, 940)

    def test_cancelled_draw_releases_operational_reservation(self):
        self.draw(status='Cancelled')
        self.assert_quantities(self.result()[1][0], 0, 0, 1000, 1000)

    def test_erp_cancellation_restores_draw_visibility_without_double_count(self):
        self.draw(used=60, remaining=40, status='Bound to ERP', trace='TRACE-1')
        self.db.execute('update `tabCFG Kanban Operation Material Draw` set status="Carry Forward", material_trace=null')
        self.assert_quantities(self.result()[1][0], 40, 60, 940, 900)

    def test_draft_abandonment_preserves_operational_availability(self):
        self.db.execute('update `tabCFG Kanban Handling Unit` set reserved_qty=60, available_qty=940')
        self.draw(used=60, remaining=40, status='Carry Forward', trace='TRACE-1')
        before = self.result()[1][0].operational_available_qty
        self.db.execute('update `tabCFG Kanban Operation Material Draw` set material_trace=null')
        self.db.execute('update `tabCFG Kanban Handling Unit` set reserved_qty=0, available_qty=1000')
        self.assertEqual(self.result()[1][0].operational_available_qty, before)

    def test_multiple_draws_do_not_multiply_tag_total(self):
        self.draw(used=60, remaining=40, status='Carry Forward')
        self.draw(used=20, remaining=30, status='Carry Forward')
        row = self.result()[1][0]
        self.assertEqual(row.total_qty, 1000)
        self.assertEqual(row.tag_count, 1)
        self.assert_quantities(row, 70, 80, 920, 850)

    def test_filters_apply_to_same_source_tag_scope(self):
        self.add_tag('TAG-HOLD', quality='Hold')
        self.draw(tag='TAG-HOLD', used=50, remaining=50, status='Carry Forward')
        self.assert_quantities(self.result(quality_state='Released')[1][0], 0, 0, 1000, 1000)
        self.assertEqual(self.result(warehouse='OTHER')[1], [])
        self.assertEqual(self.result(company='OTHER')[1], [])
        self.assertEqual(self.result(stock_uom='Nos')[1], [])
        self.assertEqual(self.result(inventory_control_mode='Kanban Operational Inventory')[1], [])

    def test_clamp_is_per_tag_not_per_summary_group(self):
        self.add_tag('TAG-2', current=100)
        self.draw(used=1100, remaining=0, status='Used')
        self.assert_quantities(self.result()[1][0], 0, 1100, 100, 100)

    def test_missing_draw_table_preserves_existing_report(self):
        self.db.execute('drop table `tabCFG Kanban Operation Material Draw`')
        self.assert_quantities(self.result()[1][0], 0, 0, 1000, 1000)

    def test_mixed_uoms_have_no_misleading_combined_quantity_cards(self):
        self.add_tag('TAG-2', current=100, uom='Nos')
        summary = self.result()[4]
        self.assertFalse(any(row.get('datatype') == 'Float' for row in summary))


class TestMaterialRotationCandidateSQL(unittest.TestCase):
    def setUp(self):
        from cfg_kanban.tests.test_material_rotation_behavior import load_service
        self.balance = TestMaterialRunInventoryBalance()
        self.balance.setUp()
        self.db = self.balance.db
        for field in ('packed_on', 'creation', 'expiry_date', 'reusable_container_role'):
            self.db.execute(f'alter table `tabCFG Kanban Handling Unit` add column {field} text')
        self.db.execute('create table `tabBatch` (name text, item text, disabled integer, expiry_date text)')
        self.db.execute('create table `tabCFG Kanban Container Content` '
                        '(container_handling_unit text, content_handling_unit text, state text)')
        self.db.execute('create table `tabCFG Kanban Manifest Line` (handling_unit text, parent text)')
        self.db.execute('create table `tabCFG Kanban Movement Manifest` (name text, state text)')
        self.service, frappe = load_service()
        frappe.db = AttrDict(sql=self.balance.sql)
        self.unit = AttrDict(inventory_company='TEST', item_code='RAW', current_warehouse='Raw Store',
                             stock_uom='Kg', process_certificate_set=None)

    def tearDown(self):
        self.balance.tearDown()

    def rows(self):
        self.db.execute("update `tabCFG Kanban Handling Unit` set movement_state='At Source' where movement_state is null")
        return self.service._rotation_candidates(self.unit)

    def test_candidate_query_is_local_to_item_company_warehouse_uom_and_certificate(self):
        for field, value in [('item_code','OTHER'), ('inventory_company','OTHER'),
                             ('current_warehouse','OTHER'), ('stock_uom','Nos'),
                             ('process_certificate_set','OTHER')]:
            name='OTHER-'+field
            self.balance.add_tag(name)
            self.db.execute(f'update `tabCFG Kanban Handling Unit` set {field}=? where name=?', (value,name))
        self.assertEqual([row.name for row in self.rows()], ['TAG-1'])

    def test_candidate_query_subtracts_draws_and_avoids_draft_trace_double_reservation(self):
        self.balance.draw(used=600, remaining=400, status='Carry Forward')
        self.assertEqual(self.rows(), [])
        self.db.execute('update `tabCFG Kanban Operation Material Draw` set used_qty=60, remaining_qty=40, drawn_qty=100, material_trace="TRACE"')
        self.db.execute('update `tabCFG Kanban Handling Unit` set reserved_qty=60, available_qty=940')
        self.assertEqual(self.rows()[0].effective_available, 900)

    def test_transit_hold_inactive_and_active_manifest_stock_are_not_candidates(self):
        self.balance.add_tag('HELD', quality='Hold')
        self.balance.add_tag('INACTIVE')
        self.db.execute('update `tabCFG Kanban Handling Unit` set identity_state="Retired" where name="INACTIVE"')
        self.balance.add_tag('TRANSIT')
        self.db.execute('update `tabCFG Kanban Handling Unit` set movement_state="Internal Transit" where name="TRANSIT"')
        self.db.execute('insert into `tabCFG Kanban Manifest Line` values ("TAG-1","MANIFEST")')
        self.db.execute('insert into `tabCFG Kanban Movement Manifest` values ("MANIFEST","Loaded")')
        self.assertEqual(self.rows(), [])
        self.db.execute('update `tabCFG Kanban Movement Manifest` set state="Closed"')
        self.assertEqual([row.name for row in self.rows()], ['TAG-1'])

    def test_single_valid_loaded_production_fill_uses_its_physical_container_code(self):
        self.balance.add_tag('CONTAINER')
        self.db.execute('update `tabCFG Kanban Handling Unit` set tag_kind="Reusable Container", '
                        'reusable_container_role="Production Output Container" where name="CONTAINER"')
        self.db.execute('update `tabCFG Kanban Handling Unit` set virtual_content=1, physical_container="CONTAINER" where name="TAG-1"')
        self.db.execute('insert into `tabCFG Kanban Container Content` values ("CONTAINER","TAG-1","Loaded")')
        self.assertEqual(self.rows()[0].scan_code, 'CONTAINER')
        self.db.execute('insert into `tabCFG Kanban Container Content` values ("CONTAINER","OTHER","Loaded")')
        self.assertEqual(self.rows(), [])

    def test_nonvirtual_tag_loaded_into_another_container_is_not_directly_eligible(self):
        self.db.execute('insert into `tabCFG Kanban Container Content` values ("CONTAINER","TAG-1","Loaded")')
        self.assertEqual(self.rows(), [])


if __name__ == '__main__':
    unittest.main()

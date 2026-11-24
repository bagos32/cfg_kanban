"""Install ordering/module-discovery contracts with explicit offline native doubles.

No Frappe site, SQL DDL, existing app upgrade or production installation is run.
"""
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_vehicle_overview import Row, load


APP = Path(__file__).resolve().parents[1]


class TestInstallation(unittest.TestCase):
    def setUp(self):
        self.modules = [name.strip() for name in (APP / 'modules.txt').read_text().splitlines() if name.strip()]
        self.stale = {'frappe': ['core'], 'erpnext': ['manufacturing']}
        self.cached = {'app_modules': copy.deepcopy(self.stale)}
        self.local = Row(app_modules=copy.deepcopy(self.stale), module_app={'manufacturing': 'erpnext'})
        self.doctypes = set()
        self.fields = {('Sales Invoice', 'unrelated_field'): {'options': 'UNCHANGED'}}
        self.property_setters = {}
        self.calls = []
        self.frappe = Row(local=self.local, cache=Row(delete_value=self.delete_cache),
            setup_module_map=self.setup_module_map, get_module_list=lambda app:self.modules,
            scrub=lambda value:value.lower().replace(' ', '_'), throw=self.throw,
            db=Row(exists=self.exists), flags=Row(in_migrate=False),
            get_meta=self.get_meta,
            get_doc=Mock(side_effect=AssertionError('Unexpected insert')))
        self.install = load('install.py', dict(frappe=self.frappe))
        self.ensure_dimension = self.install['_ensure_process_certificate_inventory_dimension']
        self.install['_ensure_responsibilities'] = Mock()
        self.install['_ensure_process_certificate_inventory_dimension'] = Mock()
        native_fields = types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        native_fields.create_custom_fields = self.create_fields
        native_properties = types.ModuleType('frappe.custom.doctype.property_setter.property_setter')
        native_properties.make_property_setter = self.make_property_setter
        patcher = patch.dict(sys.modules, {
            native_fields.__name__:native_fields, native_properties.__name__:native_properties})
        patcher.start(); self.addCleanup(patcher.stop)

    @staticmethod
    def throw(message):
        raise ValueError(message)

    def exists(self, doctype, name):
        if doctype == 'DocType':
            return name in self.doctypes
        return doctype == 'Role'

    def delete_cache(self, key):
        self.calls.append(('delete_cache', key))
        self.cached.pop(key, None)

    def setup_module_map(self, include_all_apps=True):
        self.calls.append(('setup_module_map', include_all_apps))
        modules = self.cached.get('app_modules')
        if modules is None:
            modules = copy.deepcopy(self.stale)
            modules['cfg_kanban'] = [self.frappe.scrub(name) for name in self.modules]
            self.cached['app_modules'] = modules
        self.local.app_modules = copy.deepcopy(modules)

    def sync_app_schema(self):
        # Frappe v15 sync_for iterates this in-process map, not modules.txt.
        # Here schema creation is a set update, never an actual database import.
        for module in self.local.app_modules.get('cfg_kanban') or []:
            for path in (APP / module / 'doctype').glob('*/*.json'):
                self.doctypes.add(json.loads(path.read_text())['name'])

    def create_fields(self, fields, **kwargs):
        self.calls.append(('create_custom_fields', kwargs))
        for doctype, rows in fields.items():
            for row in rows:
                if row.get('fieldtype') == 'Link' and (row.get('options') or '').startswith('CFG '):
                    if row['options'] not in self.doctypes:
                        raise ValueError(doctype + ': Options must be a valid DocType for field ' + row['label'])
                self.fields[(doctype, row['fieldname'])] = copy.deepcopy(row)

    def get_meta(self, doctype):
        def get_field(fieldname):
            values = self.fields.get((doctype, fieldname))
            if values is None:
                return None
            field = Row(copy.deepcopy(values))
            for (dt, name, prop), value in self.property_setters.items():
                if (dt, name) == (doctype, fieldname):
                    field[prop] = value
            return field
        return Row(get_field=get_field)

    def make_property_setter(self, doctype, fieldname, prop, value, property_type):
        self.calls.append(('make_property_setter', doctype, fieldname, prop, value, property_type))
        self.property_setters[(doctype, fieldname, prop)] = value

    def test_stale_module_map_reproduces_no_schema_discovery(self):
        self.sync_app_schema()
        self.assertNotIn('CFG Kanban Cycle', self.doctypes)
        with self.assertRaisesRegex(ValueError, 'Options must be a valid DocType'):
            self.create_fields(self.install['_custom_fields'](), update=True)

    def test_before_install_rebuilds_module_map_before_native_schema_discovery(self):
        self.install['before_install']()
        self.assertEqual(self.calls, [('delete_cache', 'app_modules'), ('setup_module_map', True)])
        self.assertEqual(self.local.app_modules['cfg_kanban'], ['cfg_kanban', 'cfg_kanban_pilot'])
        self.assertEqual(self.local.app_modules['erpnext'], self.stale['erpnext'])
        self.assertFalse(self.fields.get(('Work Order', 'cfg_kanban_cycle')))
        self.sync_app_schema()
        self.install['after_install']()
        self.assertEqual(self.fields[('Work Order', 'cfg_kanban_cycle')]['options'], 'CFG Kanban Cycle')
        self.assertEqual(self.fields[('Sales Invoice', 'unrelated_field')], {'options': 'UNCHANGED'})
        self.assertIn('CFG Action Pilot Submission', self.doctypes)

    def test_incomplete_schema_stops_before_custom_fields_and_setup_writes(self):
        before = copy.deepcopy(self.fields)
        with self.assertRaisesRegex(ValueError, 'schema is incomplete.*CFG Kanban Cycle'):
            self.install['after_install']()
        self.assertEqual(self.fields, before)
        self.assertFalse(any(row[0] == 'create_custom_fields' for row in self.calls))
        self.frappe.get_doc.assert_not_called()
        self.install['_ensure_responsibilities'].assert_not_called()
        self.install['_ensure_process_certificate_inventory_dimension'].assert_not_called()

    def test_rebuilt_map_must_include_every_declared_module(self):
        self.frappe.setup_module_map = lambda **kwargs:None
        with self.assertRaisesRegex(ValueError, 'module map'):
            self.install['before_install']()
        self.assertFalse(self.doctypes)

    def test_repeated_install_setup_and_migrate_preserve_unrelated_fields(self):
        self.install['before_install'](); self.sync_app_schema(); self.install['after_install']()
        original = copy.deepcopy(self.fields)
        self.install['before_install'](); self.sync_app_schema(); self.install['after_migrate']()
        self.assertEqual(self.fields, original)
        self.assertTrue(all(row[1] == {'update': True} for row in self.calls if row[0] == 'create_custom_fields'))

    def test_new_install_exempts_only_the_four_logistics_audit_fields(self):
        self.install['before_install'](); self.sync_app_schema(); self.install['after_install']()
        ignored = {key for key, field in self.fields.items() if field.get('ignore_user_permissions')}
        self.assertEqual(ignored, {
            (doctype, fieldname) for doctype in ('Delivery Note', 'Purchase Receipt')
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company')})
        for doctype, fieldname in ignored:
            field = self.fields[(doctype, fieldname)]
            target = 'Employee' if fieldname == 'cfg_requested_operator' else 'Company'
            self.assertEqual((field['fieldtype'], field['options'], field['read_only']), ('Link', target, 1))
        self.assertFalse(self.property_setters)

    def test_migration_updates_existing_logistics_audit_fields_without_changing_other_fields(self):
        self.install['before_install'](); self.sync_app_schema(); self.install['after_install']()
        original = copy.deepcopy(self.fields)
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company'):
                self.fields[(doctype, fieldname)]['ignore_user_permissions'] = 0
        self.install['after_migrate']()
        self.assertEqual(self.fields, original)
        self.install['after_migrate']()
        self.assertEqual(self.fields, original)

    def test_shadowing_property_setter_is_repaired_only_for_logistics_audit_permissions(self):
        self.install['before_install'](); self.sync_app_schema()
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company'):
                self.property_setters[(doctype, fieldname, 'ignore_user_permissions')] = 0
                self.property_setters[(doctype, fieldname, 'label')] = 'Office audit label'
            self.property_setters[(doctype, 'company', 'ignore_user_permissions')] = 0
        before = copy.deepcopy(self.property_setters)
        self.install['after_migrate']()
        expected = copy.deepcopy(before)
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company'):
                expected[(doctype, fieldname, 'ignore_user_permissions')] = 1
                self.assertEqual(self.get_meta(doctype).get_field(fieldname).ignore_user_permissions, 1)
        self.assertEqual(self.property_setters, expected)
        writes = [row for row in self.calls if row[0] == 'make_property_setter']
        self.assertEqual({row[1:] for row in writes}, {
            (doctype, fieldname, 'ignore_user_permissions', 1, 'Check')
            for doctype in ('Delivery Note', 'Purchase Receipt')
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company')})
        self.install['after_migrate']()
        self.assertEqual([row for row in self.calls if row[0] == 'make_property_setter'], writes)

    def test_existing_manual_field_exemption_and_customizations_are_preserved(self):
        self.install['before_install'](); self.sync_app_schema()
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company'):
                self.property_setters[(doctype, fieldname, 'ignore_user_permissions')] = 1
        original = copy.deepcopy(self.property_setters)
        self.install['after_install'](); self.install['after_migrate']()
        self.assertEqual(self.property_setters, original)
        self.assertFalse(any(row[0] == 'make_property_setter' for row in self.calls))

    def test_audit_repair_rejects_missing_or_mistyped_field_without_broad_exemption(self):
        self.install['before_install'](); self.sync_app_schema(); self.install['after_install']()
        for fieldname in ('cfg_requested_operator', 'cfg_counterpart_company'):
            original = copy.deepcopy(self.fields[('Delivery Note', fieldname)])
            for changed in (None, dict(original, fieldtype='Data'), dict(original, options='Customer')):
                with self.subTest(fieldname=fieldname, field=changed):
                    if changed is None:
                        del self.fields[('Delivery Note', fieldname)]
                    else:
                        self.fields[('Delivery Note', fieldname)] = changed
                    with self.assertRaisesRegex(ValueError, 'must remain a Link to'):
                        self.install['_ensure_logistics_audit_user_permissions']()
                    self.fields[('Delivery Note', fieldname)] = copy.deepcopy(original)
        self.assertFalse(self.property_setters)

    def test_preflight_requires_custom_field_sources_and_certificate_schema(self):
        self.install['before_install'](); self.sync_app_schema()
        for missing in ('CFG Kanban Master', 'CFG Process Certificate Set', 'CFG Kanban Delivery Session'):
            self.doctypes.remove(missing)
            with self.subTest(doctype=missing), self.assertRaisesRegex(ValueError, missing):
                self.install['after_install']()
            self.doctypes.add(missing)
        self.assertFalse(any(row[0] == 'create_custom_fields' for row in self.calls))

    def test_hook_registers_before_install_without_changing_native_post_install_lifecycle(self):
        hooks = load('hooks.py', {})
        self.assertEqual(hooks['before_install'], 'cfg_kanban.install.before_install')
        self.assertEqual(hooks['after_install'], 'cfg_kanban.install.after_install')
        self.assertEqual(hooks['after_migrate'], 'cfg_kanban.install.after_migrate')

    def test_inventory_dimension_waits_for_native_migration_and_does_not_change_flags(self):
        self.install['before_install'](); self.sync_app_schema(); self.install['after_install']()
        self.install['_ensure_process_certificate_inventory_dimension'].assert_not_called()
        self.assertFalse(self.frappe.flags.in_migrate)
        self.frappe.flags.in_migrate = True
        self.install['after_migrate']()
        self.install['_ensure_process_certificate_inventory_dimension'].assert_called_once_with()
        self.assertTrue(self.frappe.flags.in_migrate)

    def test_direct_dimension_setup_cannot_bypass_native_migration_context(self):
        with self.assertRaisesRegex(ValueError, 'requires native site migration'):
            self.ensure_dimension()
        self.frappe.get_doc.assert_not_called()
        self.assertFalse(self.frappe.flags.in_migrate)

    def dimension_fixture(self, existing=True):
        self.frappe.flags.in_migrate = True
        self.doctypes.add('Inventory Dimension')
        self.frappe.db.table_exists = lambda name:name == 'CFG Process Certificate Set'
        metadata = Row(reference_document='CFG Process Certificate Set',
            source_fieldname='process_certificate_set', target_fieldname='cfg_process_certificate_set')
        self.frappe.db.get_value = lambda dt, filters, field, **kwargs:('Process Certificate Set' if existing else None) if field == 'name' else metadata
        native = Row()
        native.insert = Mock(return_value=native)
        native.add_custom_fields = Mock()
        self.frappe.get_doc = Mock(return_value=native)
        return metadata, native

    def test_existing_partly_created_dimension_uses_native_field_completion_each_migration(self):
        metadata, native = self.dimension_fixture()
        before = copy.deepcopy(metadata)
        self.ensure_dimension(); self.ensure_dimension()
        self.assertEqual(metadata, before)
        self.assertEqual(native.add_custom_fields.call_count, 2)
        self.frappe.get_doc.assert_called_with('Inventory Dimension', 'Process Certificate Set')
        native.insert.assert_not_called()

    def test_dimension_reference_or_field_collision_stops_before_native_field_creation(self):
        metadata, native = self.dimension_fixture()
        for field, invalid in [('reference_document', 'Item'), ('source_fieldname', 'other_field'),
                               ('target_fieldname', 'other_field')]:
            original = metadata[field]; metadata[field] = invalid
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'collision'):
                self.ensure_dimension()
            metadata[field] = original
        native.add_custom_fields.assert_not_called(); native.insert.assert_not_called()

    def test_new_dimension_keeps_native_creation_and_validation_settings(self):
        _metadata, native = self.dimension_fixture(existing=False)
        self.ensure_dimension()
        values = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(values['reference_document'], 'CFG Process Certificate Set')
        self.assertEqual(values['validate_negative_stock'], 1)
        self.assertEqual(values['apply_to_all_doctypes'], 1)
        native.insert.assert_called_once_with(ignore_permissions=True)

    def test_ledger_identity_remains_hidden_mandatory_and_unique(self):
        schema = json.loads((APP / 'cfg_kanban' / 'doctype' / 'cfg_kanban_handling_unit_quantity_ledger' /
            'cfg_kanban_handling_unit_quantity_ledger.json').read_text())
        key = next(field for field in schema['fields'] if field['fieldname'] == 'idempotency_key')
        self.assertEqual((key['hidden'], key['reqd'], key['unique']), (1, 1, 1))


if __name__ == '__main__':
    unittest.main()

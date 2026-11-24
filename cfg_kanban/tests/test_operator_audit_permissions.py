"""Native Frappe document/list permissions with isolated metadata and stock-user fixtures.

Requires installed Frappe. List SQL runs only against a temporary in-memory SQLite
fixture, never a Frappe site/database, site migration or real ERP insert.
Installation/migration coverage without Frappe is in test_installation.py.
"""
import copy
import sqlite3
import unittest
from unittest.mock import patch

from cfg_kanban.tests.test_vehicle_overview import Row, load

try:
    import frappe as native_frappe
    import frappe.permissions as native_permissions
    import frappe.model.db_query as native_query
    import frappe.share as native_share
    from frappe.core.doctype.user_permission import user_permission as native_user_permissions
except ModuleNotFoundError as error:
    if not (error.name or '').startswith('frappe'):
        raise
    native_frappe = native_permissions = native_query = native_share = native_user_permissions = None


class AuditPermissionFixtures:
    def setUp(self):
        self.user = 'ordinary-stock-user@example.com'
        self.strict = True
        self.allowed = {'Employee': [Row(doc='EMP-SELF')]}
        self.roles = ['Stock User']
        self.meta = {}
        self.native_permissions = Row(role='Stock User', permlevel=0, read=1, create=1, write=1, submit=1)
        self.custom_fields = load('install.py', {})['_custom_fields']()
        self.flags = Row(has_permission_check_logs=[])
        patches = [
            patch.object(native_frappe, 'get_meta', side_effect=lambda doctype:self.meta[doctype]),
            patch.object(native_frappe, 'get_system_settings', side_effect=lambda key:self.strict),
            patch.object(native_frappe, 'get_roles', side_effect=lambda user:self.roles),
            patch.object(native_frappe, 'get_hooks', return_value={}),
            patch.object(native_frappe, 'flags', self.flags),
            patch.object(native_frappe, 'local', Row(role_permissions={})),
            patch.object(native_permissions, '_', side_effect=lambda text, **kwargs:text),
            patch.object(native_user_permissions, 'get_user_permissions', side_effect=lambda user:self.allowed),
        ]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    def field(self, name, target, **values):
        return Row(fieldname=name, label=name, fieldtype='Link', options=target,
                   ignore_user_permissions=0, **values)

    def metadata(self, doctype, fields):
        meta = Row(name=doctype, issingle=0, istable=0, is_tree=0, is_submittable=1, allow_import=0,
                   fields=fields, permissions=[copy.deepcopy(self.native_permissions)])
        meta.get_link_fields = lambda:[field for field in fields if field.fieldtype == 'Link']
        self.meta[doctype] = meta
        return meta

    def document(self, doctype, operator=None):
        party = 'customer' if doctype == 'Delivery Note' else 'supplier'
        fields = [self.field('company', 'Company'), self.field(party, party.title())]
        fields.extend(Row(field) for field in self.custom_fields[doctype] if field['fieldtype'] == 'Link')
        meta = self.metadata(doctype, fields)
        child_type = doctype + ' Item'
        child_meta = self.metadata(child_type, [self.field('item_code', 'Item'),
            self.field('warehouse', 'Warehouse'), self.field('batch_no', 'Batch')])
        child = Row(doctype=child_type, meta=child_meta, parentfield='items', idx=1,
                    item_code='ITEM', warehouse='WAREHOUSE', batch_no='LOT')
        doc = Row(doctype=doctype, name=None, owner=self.user, company='COMPANY',
                  cfg_requested_operator=operator, meta=meta, **{party:'PARTY'})
        doc.get_all_children = lambda:[child]
        return doc, child

    def permissions(self, doc):
        return native_permissions.get_doc_permissions(doc, user=self.user, ptype='create')

    def restrict(self, target, value):
        self.allowed[target] = [Row(doc=value)]


@unittest.skipUnless(native_permissions, 'Frappe is not installed; native permission engine not run')
class TestOperatorAuditPermissions(AuditPermissionFixtures, unittest.TestCase):
    def test_blank_operator_allows_normal_delivery_note_and_purchase_receipt(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for blank in (None, ''):
                with self.subTest(doctype=doctype, blank=blank):
                    doc, _ = self.document(doctype, blank)
                    result = self.permissions(doc)
                    self.assertTrue(result.get('create'))
                    self.assertTrue(result.get('read'))
                    self.assertTrue(result.get('submit'))
                    self.assertEqual(doc.cfg_requested_operator, blank)

    def test_old_metadata_reproduces_the_reported_empty_employee_rejection(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                next(field for field in doc.meta.fields if field.fieldname == 'cfg_requested_operator').ignore_user_permissions = 0
                self.assertFalse(self.permissions(doc).get('create'))
                self.assertTrue(any("Employee 'empty'" in message and 'Requested by Kanban Operator' in message
                    for message in self.flags.has_permission_check_logs))

    def test_other_operator_audit_identity_is_retained_without_own_employee_restriction(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype, 'EMP-ACTUAL-OPERATOR')
                self.assertTrue(self.permissions(doc).get('create'))
                self.assertEqual(doc.cfg_requested_operator, 'EMP-ACTUAL-OPERATOR')
                self.assertEqual(next(field for field in doc.meta.fields
                    if field.fieldname == 'cfg_requested_operator').read_only, 1)

    def test_existing_ordinary_documents_can_be_read_without_an_operator(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.name = 'EXISTING-ERP-DOCUMENT'
                self.assertTrue(self.permissions(doc).get('read'))
                self.assertIsNone(doc.cfg_requested_operator)

    def test_missing_native_create_role_is_still_denied(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.meta.permissions[0].create = 0
                self.assertFalse(self.permissions(doc).get('create'))

    def test_missing_native_read_role_is_still_denied(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.meta.permissions[0].read = 0
                self.assertFalse(self.permissions(doc).get('read'))

    def test_missing_native_submit_role_is_still_denied(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.meta.permissions[0].submit = 0
                self.assertFalse(self.permissions(doc).get('submit'))

    def test_native_controller_denial_is_preserved(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            doc, _ = self.document(doctype)
            with self.subTest(doctype=doctype), patch.object(native_frappe, 'get_hooks',
                    return_value={doctype:['site_specific_permission']}), patch.object(native_frappe, 'call', return_value=False):
                self.assertFalse(self.permissions(doc).get('create'))

    def test_owning_company_restriction_is_preserved(self):
        self.restrict('Company', 'COMPANY')
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            doc, _ = self.document(doctype)
            self.assertTrue(self.permissions(doc).get('create'))
            doc.company = 'OTHER-COMPANY'
            self.assertFalse(self.permissions(doc).get('create'))

    def test_customer_and_supplier_restrictions_are_preserved(self):
        for doctype, party in (('Delivery Note', 'customer'), ('Purchase Receipt', 'supplier')):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                self.restrict(party.title(), 'PARTY')
                self.assertTrue(self.permissions(doc).get('create'))
                doc[party] = 'OTHER-PARTY'
                self.assertFalse(self.permissions(doc).get('create'))

    def test_child_warehouse_item_and_batch_restrictions_are_preserved(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for field, target in (('warehouse', 'Warehouse'), ('item_code', 'Item'), ('batch_no', 'Batch')):
                with self.subTest(doctype=doctype, field=field):
                    doc, child = self.document(doctype)
                    self.restrict(target, child[field])
                    self.assertTrue(self.permissions(doc).get('create'))
                    child[field] = 'OTHER'
                    self.assertFalse(self.permissions(doc).get('create'))

    def test_other_employee_field_and_employee_records_remain_restricted(self):
        doc, _ = self.document('Delivery Note')
        doc.meta.fields.append(self.field('site_approver', 'Employee'))
        doc.site_approver = 'EMP-OTHER'
        self.assertFalse(self.permissions(doc).get('create'))
        meta = self.metadata('Employee', [])
        employee = Row(doctype='Employee', name='EMP-OTHER', meta=meta, get_all_children=lambda:[])
        self.assertFalse(self.permissions(employee).get('read'))

    def test_document_specific_user_permission_is_preserved(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                self.restrict(doctype, 'ALLOWED-EXISTING-DOCUMENT')
                doc.name = 'DIFFERENT-DOCUMENT'
                self.assertFalse(self.permissions(doc).get('read'))

    def test_counterpart_company_is_audit_data_while_owning_company_stays_restricted(self):
        self.restrict('Company', 'COMPANY')
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            for counterpart in (None, '', 'COMPANY', 'OTHER-COMPANY'):
                with self.subTest(doctype=doctype, counterpart=counterpart):
                    doc, _ = self.document(doctype)
                    doc.cfg_counterpart_company = counterpart
                    self.assertTrue(self.permissions(doc).get('create'))
                    self.assertEqual(doc.cfg_counterpart_company, counterpart)
                    doc.company = 'OTHER-COMPANY'
                    self.assertFalse(self.permissions(doc).get('create'))

    def test_other_business_company_field_and_company_record_remain_restricted(self):
        self.restrict('Company', 'COMPANY')
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.meta.fields.append(self.field('site_billing_company', 'Company'))
                doc.site_billing_company = 'OTHER-COMPANY'
                self.assertFalse(self.permissions(doc).get('read'))
        meta = self.metadata('Company', [])
        company = Row(doctype='Company', name='OTHER-COMPANY', meta=meta, get_all_children=lambda:[])
        self.assertFalse(self.permissions(company).get('read'))


@unittest.skipUnless(native_query, 'Frappe is not installed; native list-query engine not run')
class TestOperatorAuditListPermissions(AuditPermissionFixtures, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.restrict('Company', 'COMPANY')

        def throw(message, exception=PermissionError):
            raise exception(message)

        database = Row(db_type='mariadb', escape=lambda value, **kwargs:"'" + value.replace("'", "''") + "'")
        patches = [patch.object(native_frappe, 'db', database, create=True),
            patch.object(native_frappe, 'throw', side_effect=throw),
            patch.object(native_share, 'get_shared', return_value=[]),
            patch.object(native_query, 'get_server_script_map', return_value={}),
            patch.object(native_query, '_', side_effect=lambda text, **kwargs:text)]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    def rows(self, doctype):
        party = 'customer' if doctype == 'Delivery Note' else 'supplier'
        return [
            Row(name='ORDINARY', company='COMPANY', cfg_requested_operator=None,
                cfg_counterpart_company=None, **{party:'PARTY'}),
            Row(name='KANBAN', company='COMPANY', cfg_requested_operator='EMP-ACTUAL-OPERATOR',
                cfg_counterpart_company='OTHER-COMPANY', **{party:'PARTY'}),
            Row(name='FOREIGN', company='OTHER-COMPANY', cfg_requested_operator='EMP-SELF',
                cfg_counterpart_company='COMPANY', **{party:'PARTY'}),
        ]

    def visible(self, doctype, rows):
        # Use the real native match-condition builder. Only its external lookups
        # are mocked; evaluate the resulting predicates against explicit fixtures.
        query = native_query.DatabaseQuery(doctype, user=self.user)
        query.tables = ['`tab' + doctype + '`']
        condition = query.build_match_conditions()
        columns = ['name', 'owner'] + [field.fieldname for field in self.meta[doctype].get_link_fields()]
        with sqlite3.connect(':memory:') as db:
            table = '`tab' + doctype + '`'
            db.execute('CREATE TABLE ' + table + ' (' + ', '.join('`' + name + '` TEXT' for name in columns) + ')')
            placeholders = ', '.join('?' for _ in columns)
            db.executemany('INSERT INTO ' + table + ' VALUES (' + placeholders + ')',
                [[row.get(name) for name in columns] for row in rows])
            names = db.execute('SELECT name FROM ' + table + (' WHERE ' + condition if condition else '')).fetchall()
        return {row[0] for row in names}, condition

    def test_normal_and_kanban_lists_keep_owning_company_filter_only(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                self.document(doctype)
                visible, condition = self.visible(doctype, self.rows(doctype))
                self.assertEqual(visible, {'ORDINARY', 'KANBAN'})
                self.assertIn('`company`', condition)
                self.assertNotIn('cfg_counterpart_company', condition)
                self.assertNotIn('cfg_requested_operator', condition)

    def test_previous_counterpart_metadata_reproduces_empty_list(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                next(field for field in doc.meta.fields if field.fieldname == 'cfg_counterpart_company').ignore_user_permissions = 0
                visible, condition = self.visible(doctype, self.rows(doctype))
                self.assertEqual(visible, set())
                self.assertIn('cfg_counterpart_company', condition)

    def test_previous_operator_metadata_still_filters_other_employee_or_blank(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                next(field for field in doc.meta.fields if field.fieldname == 'cfg_requested_operator').ignore_user_permissions = 0
                visible, condition = self.visible(doctype, self.rows(doctype))
                self.assertEqual(visible, set())
                self.assertIn('cfg_requested_operator', condition)

    def test_customer_and_supplier_list_restrictions_are_preserved(self):
        for doctype, party in (('Delivery Note', 'customer'), ('Purchase Receipt', 'supplier')):
            with self.subTest(doctype=doctype):
                self.document(doctype)
                self.restrict(party.title(), 'PARTY')
                rows = self.rows(doctype)
                rows.append(Row(rows[0], name='OTHER-PARTY', **{party:'OTHER'}))
                visible, condition = self.visible(doctype, rows)
                self.assertEqual(visible, {'ORDINARY', 'KANBAN'})
                self.assertIn('`' + party + '`', condition)

    def test_document_specific_list_restriction_is_preserved(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                self.document(doctype)
                self.restrict(doctype, 'ORDINARY')
                visible, condition = self.visible(doctype, self.rows(doctype))
                self.assertEqual(visible, {'ORDINARY'})
                self.assertIn('`name`', condition)

    def test_missing_native_read_role_still_rejects_the_list(self):
        for doctype in ('Delivery Note', 'Purchase Receipt'):
            with self.subTest(doctype=doctype):
                doc, _ = self.document(doctype)
                doc.meta.permissions[0].read = 0
                with self.assertRaises(native_frappe.PermissionError):
                    self.visible(doctype, self.rows(doctype))


if __name__ == '__main__':
    unittest.main()

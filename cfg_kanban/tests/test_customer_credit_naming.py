"""Native-default delegation for customer credits; no live ERP/database acceptance.

The gateway tests execute application functions with document/ERP doubles. The
optional naming-engine tests use installed Frappe with database counters replaced;
they remain skipped when Frappe is unavailable and do not test native insertion.
"""
import ast
import datetime
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

try:
    import frappe as native_frappe
    from frappe.model import naming as native_naming
    from frappe.core.doctype.document_naming_rule.document_naming_rule import DocumentNamingRule
except ModuleNotFoundError as error:
    if not (error.name or '').startswith('frappe'):
        raise
    native_frappe = native_naming = DocumentNamingRule = None


class Doc(dict):
    def __getattribute__(self, name):
        if not name.startswith('_') and name in self:
            return self[name]
        return super().__getattribute__(name)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

    def set(self, field, value):
        self[field] = value

    def db_set(self, fields, **kwargs):
        self.update(fields)


def gateway_functions(namespace):
    names = {'create_customer_credit_return', '_remaining_sales_invoice_quantities',
             '_apply_native_naming_series_default', 'get_required_erp_inputs',
             '_is_missing_required_value', '_required_field_descriptor'}
    body = []
    for node in ast.parse((ROOT / 'integrations/erp_gateway.py').read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), 'erp_gateway.py', 'exec'), namespace)
    return namespace


class TestCustomerCreditNaming(unittest.TestCase):
    def setUp(self):
        self.default = 'SITE-DEFAULT-'
        self.fallback = 'FIRST-OPTION-'
        self.field = Doc(fieldname='naming_series', fieldtype='Select', reqd=1,
                         options='FIRST-OPTION-\nSITE-DEFAULT-', default=self.default)
        self.meta = Doc(fields=[self.field], get_field=lambda name: self.field if name == 'naming_series' else None)
        self.case = Doc(name='CASE', return_flow='Customer Return for QC',
                        state='QC Completed - Accounting Pending', selling_company='B', customer='CUSTOMER')
        self.source = Doc(name='ORIGINAL', docstatus=1, is_return=0, company='B', customer='CUSTOMER',
                          naming_series='ORIGINAL-INVOICE-', items=[Doc(item_code='ITEM', stock_qty=10)])
        self.credit = Doc(doctype='Sales Invoice', meta=self.meta, is_return=1, return_against='ORIGINAL',
                          items=[Doc(item_code='ITEM', stock_qty=-10, qty=-5, conversion_factor=2)], docstatus=0)
        self.inserts = []
        self.generated_name = 'NATIVE-RULE-CREDIT-00003'
        def insert(**kwargs):
            self.inserts.append((kwargs, dict(self.credit)))
            self.credit.name = self.generated_name
            return self.credit
        self.credit.insert = Mock(side_effect=insert)
        self.credit.submit = Mock(side_effect=AssertionError('Accounting must retain the Draft'))
        self.existing = None
        self.frappe = Doc(get_doc=self.get_doc, throw=self.throw,
            new_doc=Mock(side_effect=lambda doctype: Doc(doctype=doctype, naming_series=self.default)),
            db=Doc(sql=Mock(return_value=[]), get_value=self.get_value),
            session=Doc(user='accountant@example.com'))
        self.ns = gateway_functions(dict(frappe=self.frappe, flt=lambda value: float(value or 0),
            now_datetime=lambda: datetime.datetime(2026, 11, 20, 12),
            get_default_naming_series=Mock(side_effect=lambda doctype: self.fallback)))
        mapper = types.ModuleType('erpnext.controllers.sales_and_purchase_return')
        self.map_return = mapper.make_return_doc = Mock(return_value=self.credit)
        self.module_patch = patch.dict(sys.modules, {mapper.__name__: mapper})
        self.module_patch.start(); self.addCleanup(self.module_patch.stop)
        self.command = Doc(return_case='CASE', idempotency_key='COMMAND', terminal_user='accountant@example.com')
        self.payload = dict(source_sales_invoice='ORIGINAL', accepted_items={'ITEM': 2},
                            source_basis='Exact Sales Invoice', decision_notes='QC accepted', accounting_revision=0)

    @staticmethod
    def throw(message):
        raise ValueError(message)

    def get_doc(self, doctype, name):
        if doctype == 'CFG Kanban Return Case':
            return self.case
        if name == 'ORIGINAL':
            return self.source
        if self.existing and name == self.existing.name:
            return self.existing
        raise AssertionError((doctype, name))

    def get_value(self, doctype, name, field):
        if self.existing and name == self.existing.name:
            return self.existing.get(field)
        raise AssertionError((doctype, name, field))

    def create(self):
        return self.ns['create_customer_credit_return'](self.command, self.payload)

    def preflight(self, series=None, doctype='Sales Invoice'):
        doc = Doc(doctype=doctype, meta=self.meta, naming_series=series)
        requirements = self.ns['get_required_erp_inputs'](doc)
        return doc, requirements

    def test_preflight_uses_native_document_default_before_first_series_option(self):
        doc, requirements = self.preflight()
        self.assertEqual(doc.naming_series, self.default)
        self.assertEqual(requirements, [])
        self.frappe.new_doc.assert_called_once_with('Sales Invoice')
        self.ns['get_default_naming_series'].assert_not_called()
        self.assertFalse(doc.name)

    def test_empty_native_default_falls_back_to_native_naming_series_resolver(self):
        self.default = ''
        doc, requirements = self.preflight()
        self.assertEqual(doc.naming_series, self.fallback)
        self.assertEqual(requirements, [])
        self.ns['get_default_naming_series'].assert_called_once_with('Sales Invoice')

    def test_explicit_mapped_series_is_preserved(self):
        doc, _requirements = self.preflight('MAPPED-SERIES-')
        self.assertEqual(doc.naming_series, 'MAPPED-SERIES-')
        self.frappe.new_doc.assert_not_called()
        self.ns['get_default_naming_series'].assert_not_called()

    def test_doctype_without_series_field_does_not_resolve_numbering(self):
        self.meta.fields = []
        self.meta.get_field = lambda name: None
        doc, requirements = self.preflight(doctype='Work Order')
        self.assertEqual(requirements, [])
        self.assertIsNone(doc.naming_series)
        self.frappe.new_doc.assert_not_called()
        self.ns['get_default_naming_series'].assert_not_called()

    def test_credit_resolves_missing_default_before_native_insert(self):
        result = self.create()
        self.assertIs(result, self.credit)
        self.assertEqual(self.inserts[0][1].get('naming_series'), self.default)
        self.map_return.assert_called_once_with('Sales Invoice', 'ORIGINAL')
        self.credit.insert.assert_called_once_with(ignore_permissions=True)
        self.credit.submit.assert_not_called()
        self.assertTrue(self.credit.is_return)
        self.assertEqual(self.credit.update_stock, 0)
        self.assertEqual((self.credit.items[0].qty, self.credit.items[0].stock_qty), (-1, -2))
        self.assertEqual(self.credit.cfg_return_case, 'CASE')
        self.assertEqual(self.case.credit_document, self.generated_name)

    def test_credit_preserves_series_chosen_by_native_mapper_or_hooks(self):
        self.credit.naming_series = 'MAPPED-CREDIT-'
        self.create()
        self.assertEqual(self.inserts[0][1]['naming_series'], 'MAPPED-CREDIT-')
        self.frappe.new_doc.assert_not_called()

    def test_result_records_native_document_number_separately_from_series_field(self):
        self.credit.naming_series = 'NORMAL-DEFAULT-'
        result = self.create()
        self.assertEqual(result.name, self.generated_name)
        self.assertEqual(result.naming_series, 'NORMAL-DEFAULT-')
        self.assertEqual(result._cfg_command_result['name'], self.generated_name)
        self.assertEqual(result._cfg_command_result['naming_series'], 'NORMAL-DEFAULT-')
        self.assertEqual(result._cfg_command_result['is_return'], 1)

    def test_retry_reuses_existing_draft_or_submitted_credit_without_naming_again(self):
        for status in (0, 1):
            with self.subTest(status=status):
                self.existing = Doc(name='ALREADY-CREATED', docstatus=status, naming_series='OLD-')
                self.case.credit_document = self.existing.name
                self.assertIs(self.create(), self.existing)
        self.map_return.assert_not_called()
        self.frappe.new_doc.assert_not_called()
        self.credit.insert.assert_not_called()

    def test_same_source_replacement_retains_native_amendment_lineage(self):
        self.existing = Doc(name='CANCELLED-CREDIT', docstatus=2, return_against='ORIGINAL')
        self.case.credit_document = self.existing.name
        self.create()
        self.assertEqual(self.inserts[0][1]['amended_from'], 'CANCELLED-CREDIT')
        self.assertEqual(self.credit._cfg_command_result['amended_from'], 'CANCELLED-CREDIT')

    def test_changed_source_replacement_does_not_amend_unrelated_credit(self):
        self.existing = Doc(name='CANCELLED-CREDIT', docstatus=2, return_against='OTHER-INVOICE')
        self.case.credit_document = self.existing.name
        self.create()
        self.assertFalse(self.credit.amended_from)

    def test_invalid_source_company_rejected_before_mapper_and_numbering(self):
        self.source.company = 'A'
        with self.assertRaisesRegex(ValueError, 'Company and Customer'):
            self.create()
        self.map_return.assert_not_called()
        self.frappe.new_doc.assert_not_called()
        self.credit.insert.assert_not_called()

    def test_uncreditable_quantity_rejected_before_mapper_and_numbering(self):
        self.payload['accepted_items'] = {'ITEM': 11}
        with self.assertRaisesRegex(ValueError, 'insufficient uncredited'):
            self.create()
        self.map_return.assert_not_called()
        self.frappe.new_doc.assert_not_called()
        self.credit.insert.assert_not_called()


@unittest.skipUnless(native_naming, 'Frappe is not installed; native naming engine not run')
class TestInstalledFrappeCreditNaming(unittest.TestCase):
    """Real installed naming/rule functions, with no database/counter mutations."""
    def setUp(self):
        self.counters = {}
        self.series_counters = {}
        self.rules = []
        self.meta = Doc(autoname='naming_series:', issingle=0,
            get_naming_series_options=lambda: ['DEFAULT-'],
            has_field=lambda name: name in ('is_return', 'company'),
            get_field=lambda name: Doc(fieldtype='Check' if name == 'is_return' else 'Link'),
            get_table_fields=lambda: [])
        self.doc = Doc(doctype='Sales Invoice', meta=self.meta, naming_series='DEFAULT-',
                       company='B', is_return=1, run_method=Mock())
        self.map_rules = Mock(side_effect=lambda *args, **kwargs: [Doc(name=row.name)
            for row in sorted(self.rules, key=lambda r: -r.priority)])
        fake_db = Doc(get_value=self.value, set_value=self.set_value, db_type='mariadb')
        patches = [patch.object(native_frappe, 'flags', Doc(in_import=False)),
            patch.object(native_frappe, 'db', fake_db),
            patch.object(native_frappe, 'get_meta', return_value=self.meta),
            patch.object(native_frappe, 'get_cached_doc', side_effect=lambda dt, name: next(row for row in self.rules if row.name == name)),
            patch.object(native_frappe, 'get_hooks', return_value={}),
            patch.object(native_frappe.cache_manager, 'get_doctype_map', self.map_rules),
            patch.object(native_naming, 'getseries', side_effect=self.series)]
        for item in patches:
            item.start(); self.addCleanup(item.stop)

    def value(self, doctype, name, field, **kwargs):
        if doctype == 'Document Naming Rule':
            return self.counters.get(name, 0)
        if doctype == 'Amended Document Naming Settings':
            return 'Amend Counter'
        return None

    def set_value(self, doctype, name, field, value):
        self.counters[name] = value

    def series(self, prefix, digits):
        self.series_counters[prefix] = self.series_counters.get(prefix, 0) + 1
        return str(self.series_counters[prefix]).zfill(digits)

    def rule(self, name='CREDIT', priority=10, company=None):
        conditions = [Doc(field='is_return', condition='=', value='1')]
        if company:
            conditions.append(Doc(field='company', condition='=', value=company))
        row = Doc(doctype='Document Naming Rule', name=name, document_type='Sales Invoice',
                  prefix=name+'-', prefix_digits=5, priority=priority, conditions=conditions)
        row.apply = lambda doc: DocumentNamingRule.apply(row, doc)
        self.rules.append(row)
        return row

    def test_matching_return_rule_controls_id_without_rewriting_series_field(self):
        self.rule()
        native_naming.set_new_name(self.doc)
        self.assertEqual(self.doc.name, 'CREDIT-00001')
        self.assertEqual(self.doc.naming_series, 'DEFAULT-')
        self.assertEqual(self.counters, {'CREDIT': 1})
        self.assertFalse(self.series_counters)

    def test_higher_priority_matching_company_rule_wins(self):
        self.rule('GENERAL', 1); self.rule('COMPANY', 20, company='B')
        native_naming.set_new_name(self.doc)
        self.assertEqual(self.doc.name, 'COMPANY-00001')
        self.assertEqual(self.counters, {'COMPANY': 1})
        self.assertEqual(self.map_rules.call_args.kwargs['order_by'], 'priority desc')
        self.assertEqual(self.map_rules.call_args.kwargs['filters']['disabled'], 0)

    def test_unmatched_company_rule_uses_native_series_fallback(self):
        self.rule(company='OTHER')
        native_naming.set_new_name(self.doc)
        self.assertEqual(self.doc.name, 'DEFAULT-00001')
        self.assertFalse(self.counters)

    def test_non_return_does_not_take_return_rule(self):
        self.rule(); self.doc.is_return = 0
        native_naming.set_new_name(self.doc)
        self.assertEqual(self.doc.name, 'DEFAULT-00001')
        self.assertFalse(self.counters)

    def test_native_amendment_policy_precedes_new_rule_number(self):
        self.rule(); self.doc.amended_from = 'OLD-CREDIT-00007'
        native_naming.set_new_name(self.doc)
        self.assertEqual(self.doc.name, 'OLD-CREDIT-00007-1')
        self.assertFalse(self.counters or self.series_counters)

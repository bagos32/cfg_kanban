"""Execute direct intake and the existing QC/accounting/disposition functions offline.

Dependency doubles verify behaviour, not live MariaDB locks or native ERP posting.
"""
import ast
import copy
import datetime
import hashlib
import json
import math
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
CASE = 'CFG Kanban Return Case'


def load(path, namespace):
    body = []
    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)):
            if isinstance(node, ast.FunctionDef):
                node.decorator_list = []
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), path, 'exec'), namespace)
    return types.SimpleNamespace(**namespace)


class Doc(dict):
    def __getattr__(self, key):
        if key.startswith('__'):
            raise AttributeError(key)
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def as_dict(self):
        def clean(value):
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items() if not key.startswith('_')}
            if isinstance(value, list):
                return [clean(row) for row in value]
            return value
        return clean(self)

    def check_permission(self, permission):
        if self.get('_denied'):
            raise PermissionError('Read denied for ' + self.name)

    def db_set(self, field, value=None, **kwargs):
        self.update(field if isinstance(field, dict) else {field: value})

    def reload(self):
        return self

    def set(self, field, value):
        self[field] = [Doc(row) for row in value] if isinstance(value, list) else value

    def save(self, **kwargs):
        self.validate()
        return self

    def is_new(self):
        return not self.name

    def get_doc_before_save(self):
        return self.get('_before')


class TestDirectCustomerReturns(unittest.TestCase):
    def setUp(self):
        self.data = {}
        self.events = []
        self.sql_calls = []
        self.current_read_required = True
        self.enabled = True
        self.start = True
        self.roles = True
        self.profile = Doc(employee='EMP1', can_start=1, kanban_role='Operator',
            responsibilities=[Doc(responsibility='Customer Return')])
        self.session = Doc(name='SESSION1', terminal_user='terminal@example.com')
        self.frappe = Doc(get_doc=self.get_doc, parse_json=json.loads,
            throw=self.throw, PermissionError=PermissionError, only_for=self.only_for,
            session=Doc(user='accountant@example.com'), get_cached_value=self.cached,
            db=Doc(get_value=self.get_value, exists=self.exists,
                   get_single_value=lambda *args: self.enabled, sql=self.sql))
        common = dict(frappe=self.frappe, flt=lambda n: float(n or 0),
            getdate=lambda n: datetime.date.fromisoformat(str(n)[:10]),
            now_datetime=lambda: datetime.datetime(2026, 11, 20, 12),
            isfinite=math.isfinite, _=lambda message: message,
            canonical_key=lambda namespace, *args: hashlib.sha256(json.dumps(
                [namespace, *args], sort_keys=True, default=str).encode()).hexdigest(),
            insert_once=self.insert_once, require_operator=self.operator, record=self.record,
            execute_command=Mock(side_effect=AssertionError('Intake must not execute ERP commands')))
        load('cfg_kanban/doctype/cfg_kanban_return_case/cfg_kanban_return_case.py',
            ns := dict(common, Document=Doc, validate_warehouse_company=Mock()))
        self.controller = ns['CFGKanbanReturnCase']
        self.controller.meta = Doc(get_label=lambda name: name)
        self.schema = json.loads((ROOT / 'cfg_kanban/doctype/cfg_kanban_return_case/cfg_kanban_return_case.json').read_text())
        self.returns = load('services/customer_returns.py', dict(common))
        self.direct = load('services/direct_customer_returns.py', dict(common))
        # Functions resolve globals through their actual namespace, not SimpleNamespace.
        self.direct._returns.__globals__['_returns'] = lambda: self.returns
        self.disposition = load('services/return_disposition.py', dict(common,
            validate_warehouse_company=Mock()))
        self.add('Company', 'A', is_group=0)
        self.add('Company', 'B', is_group=0)
        self.add('Customer', 'CUST', customer_name='Selected Customer', disabled=0)
        self.add('Customer', 'OTHER', customer_name='Other Customer', disabled=0)
        self.add('Location', 'QC BAY')
        self.add('Location', 'BAY B', company='B')
        self.add('Address', 'CUST ADDRESS')
        self.add('Dynamic Link', 'ADDR LINK', parenttype='Address', parent='CUST ADDRESS',
            link_doctype='Customer', link_name='CUST')
        self.add('Item', 'BAG', stock_uom='Nos', disabled=0)
        self.add('Item', 'RAW', stock_uom='Kg', disabled=0)
        self.add('Batch', 'LOT1', item='BAG')
        self.args = dict(company='B', customer='CUST', inspection_location='QC BAY',
            customer_return_reason='Damaged packaging', customer_address='CUST ADDRESS',
            customer_acknowledgement_name='Customer Rep',
            lines=[dict(item_code='BAG', batch_no='LOT1', expiry_date='2027-02-01',
                claimed_qty=3, condition='Damaged', original_visible_code='TAG1', details='Seal opened')],
            operator_session_token='TOKEN')

    @staticmethod
    def throw(message, error=ValueError):
        raise error(message)

    def only_for(self, roles):
        if not self.roles:
            raise PermissionError('Role denied')

    def cached(self, doctype, name, field):
        return int(doctype == 'UOM' and name == 'Nos' and field == 'must_be_whole_number')

    def operator(self, token, action=None):
        if token != 'TOKEN' or (action == 'start' and not self.start):
            raise PermissionError('Operator action denied')
        return self.profile, self.session

    def add(self, doctype, name, **fields):
        doc = Doc(doctype=doctype, name=name, **fields)
        self.data.setdefault(doctype, {})[name] = doc
        return doc

    def get_doc(self, doctype, name=None, **kwargs):
        if isinstance(doctype, dict):
            values = copy.deepcopy(doctype)
            cls = self.controller if values['doctype'] == CASE else Doc
            doc = cls(values)
            for field in ('lines', 'disposition_lines'):
                doc[field] = [Doc(row) for row in doc.get(field) or []]
            return doc
        return self.data[doctype][name]

    def get_value(self, doctype, filters, field, **kwargs):
        if isinstance(filters, str):
            return self.data.get(doctype, {}).get(filters, {}).get(field)
        if self.current_read_required and doctype in (CASE, 'CFG Kanban Event'):
            self.assertTrue(kwargs.get('for_update'))
        for row in self.data.get(doctype, {}).values():
            if all(row.get(key) == value for key, value in filters.items()):
                return row.get(field)
        return None

    def exists(self, doctype, filters):
        if isinstance(filters, str):
            return filters in self.data.get(doctype, {})
        return bool(self.get_value(doctype, filters, 'name'))

    def sql(self, query, values, **kwargs):
        self.sql_calls.append((query, values))
        self.assertIn('for update', query.lower())
        return []

    def insert_once(self, doc, key, **kwargs):
        for existing in self.data.get(doc.doctype, {}).values():
            if existing.idempotency_key == key:
                return existing, False
        doc.idempotency_key = key
        if doc.doctype == CASE:
            doc.validate()
            for field in self.schema['fields']:
                if field.get('reqd') and not doc.get(field['fieldname']):
                    raise ValueError('Mandatory field: ' + field['fieldname'])
        doc.name = 'RETURN-' + str(len(self.data.get(doc.doctype, {})) + 1)
        for index, row in enumerate(doc.get('lines') or [], 1):
            row.name = 'LINE-' + str(index)
        self.data.setdefault(doc.doctype, {})[doc.name] = doc
        return doc, True

    def record(self, event_type, **kwargs):
        key = kwargs.get('idempotency_key')
        if key and any(event.get('idempotency_key') == key for event in self.events):
            return
        self.events.append(Doc(event_type=event_type, **kwargs))
        self.add('CFG Kanban Event', 'EVENT-' + str(len(self.events)), **kwargs)

    def create(self, **changes):
        args = copy.deepcopy(self.args)
        args['event_token'] = 'EVENT1'
        args.update(changes)
        return self.direct.create_direct_customer_return(**args)

    def case(self):
        return next(iter(self.data[CASE].values()))

    def test_preview_selects_customer_and_company_without_creating_custody(self):
        result = self.direct.preview_direct_customer_return(**self.args)
        self.assertEqual((result['company'], result['customer'], result['customer_name']),
            ('B', 'CUST', 'Selected Customer'))
        self.assertEqual(result['lines'][0]['stock_uom'], 'Nos')
        self.assertNotIn(CASE, self.data)
        self.assertFalse(self.events)

    def test_creates_existing_qc_case_without_site_or_erp_posting(self):
        result = self.create()
        case = self.case()
        self.assertEqual(result['status'], 'Recorded')
        self.assertEqual(case.intake_method, 'Direct Customer')
        self.assertEqual((case.selling_company, case.customer, case.customer_address), ('B', 'CUST', 'CUST ADDRESS'))
        self.assertFalse(case.customer_scan_point or case.site_code or case.site_name)
        self.assertEqual(case.state, 'Awaiting QC Receipt')
        self.assertEqual(case.inspection_location, 'QC BAY')
        self.assertEqual((case.claimed_total_qty, case.accepted_total_qty), (3, 0))
        self.assertEqual(case.lines[0].expiry_date, '2027-02-01')
        self.assertEqual(case.lines[0].original_visible_code, 'TAG1')
        self.assertEqual(case.customer_acknowledgement_name, 'Customer Rep')
        self.assertEqual(case.created_by_operator, 'EMP1')
        self.assertEqual(len(self.events), 1)
        self.assertTrue(all('tabEmployee' in query for query, _ in self.sql_calls))
        self.assertEqual(set(self.data) - {CASE, 'CFG Kanban Event'},
            {'Company', 'Customer', 'Location', 'Address', 'Dynamic Link', 'Item', 'Batch'})

    def test_exact_retry_reopens_same_case_and_never_duplicates_event(self):
        first = self.create()
        self.enabled = False
        self.data['Customer']['CUST'].disabled = 1
        second = self.create()
        self.assertEqual(first, second)
        self.assertEqual(len(self.data[CASE]), 1)
        self.assertEqual(len(self.events), 1)
        receipt = self.direct.get_direct_return_receipt('EVENT1', 'TOKEN')
        self.assertEqual(receipt['return_case']['name'], first['return_case']['name'])

    def test_same_action_cannot_change_customer_company_or_quantity(self):
        self.create()
        error = self.direct.create_direct_customer_return.__globals__['DirectReturnReplayError']
        for changes in ({'company': 'A'}, {'customer': 'OTHER'},
                        {'lines': [dict(item_code='BAG', claimed_qty=4)]}):
            with self.subTest(changes=changes), self.assertRaises(error):
                self.create(**changes)
        self.assertEqual(len(self.data[CASE]), 1)

    def test_operator_scopes_receipts_and_event_tokens(self):
        self.create()
        self.profile.employee = 'EMP2'
        self.assertEqual(self.direct.get_direct_return_receipt('EVENT1', 'TOKEN')['status'], 'Not Recorded')
        self.create(customer='OTHER', customer_address=None)
        self.assertEqual(len(self.data[CASE]), 2)

    def test_global_enable_and_operator_authority_are_required_for_new_intake(self):
        for kind in ('enabled', 'start', 'responsibility', 'token'):
            with self.subTest(kind=kind):
                self.enabled = kind != 'enabled'
                self.start = kind != 'start'
                self.profile.responsibilities = [] if kind == 'responsibility' else [Doc(responsibility='Customer Return')]
                with self.assertRaises((ValueError, PermissionError)):
                    self.create(operator_session_token='BAD' if kind == 'token' else 'TOKEN')
        self.assertNotIn(CASE, self.data)

    def test_setup_and_receipt_allow_reconciliation_after_start_is_revoked(self):
        self.create()
        self.start = False
        self.profile.can_start = 0
        self.enabled = False
        setup = self.direct.get_direct_return_setup('TOKEN')
        self.assertFalse(setup['enabled'] or setup['can_start'])
        self.assertEqual(self.direct.get_direct_return_receipt('EVENT1', 'TOKEN')['status'], 'Recorded')

    def test_company_specific_custody_address_and_batch_scope_are_validated(self):
        for changes, text in (({'company': 'A', 'inspection_location': 'BAY B'}, 'Company'),
                ({'customer': 'OTHER'}, 'linked'),
                ({'lines': [dict(item_code='RAW', batch_no='LOT1', claimed_qty=2)]}, 'does not belong')):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, text):
                self.create(**changes)
        self.assertNotIn(CASE, self.data)

    def test_native_read_permissions_are_checked_for_selected_masters(self):
        for doctype, name in (('Company', 'B'), ('Customer', 'CUST'), ('Location', 'QC BAY'),
                             ('Address', 'CUST ADDRESS'), ('Item', 'BAG'), ('Batch', 'LOT1')):
            with self.subTest(doctype=doctype):
                self.data[doctype][name]._denied = True
                with self.assertRaises(PermissionError):
                    self.create()
                self.data[doctype][name]._denied = False
        self.assertNotIn(CASE, self.data)

    def test_disabled_masters_and_group_company_are_rejected(self):
        for doctype, name, field in (('Company', 'B', 'is_group'), ('Customer', 'CUST', 'disabled'),
                                    ('Item', 'BAG', 'disabled'), ('Location', 'QC BAY', 'disabled'),
                                    ('Address', 'CUST ADDRESS', 'disabled')):
            with self.subTest(doctype=doctype):
                self.data[doctype][name][field] = 1
                with self.assertRaises(ValueError):
                    self.create()
                self.data[doctype][name][field] = 0

    def test_missing_headers_and_reason_are_rejected(self):
        for field in ('company', 'customer', 'inspection_location', 'customer_return_reason'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.create(**{field: '   '})
        with self.assertRaisesRegex(ValueError, 'stable event token'):
            self.direct.create_direct_customer_return(**self.args, event_token='')

    def test_invalid_quantity_shape_and_conditions_never_create_a_case(self):
        for value in (0, -1, 'abc', float('nan'), float('inf'), 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.create(lines=[dict(item_code='BAG', claimed_qty=value)])
        for rows in ({}, [], [None], [{'claimed_qty': 1}], [dict(item_code='BAG', claimed_qty=1, condition='Not Allowed')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.create(lines=rows)
        self.assertNotIn(CASE, self.data)

    def test_multiple_items_decimal_stock_uom_and_json_rows_are_retained(self):
        rows = self.args['lines'] + [dict(item_code='RAW', claimed_qty='2.25'), {}]
        result = self.create(lines=json.dumps(rows))['return_case']
        self.assertEqual(len(result['lines']), 2)
        self.assertEqual(result['claimed_total_qty'], 5.25)
        self.assertEqual(result['lines'][1]['stock_uom'], 'Kg')

    def test_reviewed_stock_uom_change_requires_new_review(self):
        reviewed = self.direct.preview_direct_customer_return(**self.args)
        self.data['Item']['BAG'].stock_uom = 'Kg'
        with self.assertRaisesRegex(ValueError, 'UOM changed'):
            self.create(lines=reviewed['lines'])
        self.assertNotIn(CASE, self.data)

    def test_unrecorded_receipt_does_not_implicitly_abandon_a_request(self):
        self.assertEqual(self.direct.get_direct_return_receipt('EVENT1', 'TOKEN')['status'], 'Not Recorded')
        self.assertEqual(self.create()['status'], 'Recorded')

    def test_void_tombstone_prevents_late_creation_and_is_audited_once(self):
        for _ in range(2):
            self.assertEqual(self.direct.void_unrecorded_direct_return('EVENT1', 'Correct quantity', 'TOKEN')['status'], 'Voided')
        self.assertEqual(len(self.events), 1)
        error = self.direct.create_direct_customer_return.__globals__['DirectReturnVoidedError']
        with self.assertRaises(error):
            self.create()
        self.assertNotIn(CASE, self.data)
        self.assertEqual(self.direct.get_direct_return_receipt('EVENT1', 'TOKEN')['status'], 'Voided')
        self.assertEqual(self.create(event_token='EVENT2')['status'], 'Recorded')

    def test_void_requires_reason_and_never_voids_an_already_recorded_note(self):
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.direct.void_unrecorded_direct_return('EVENT1', ' ', 'TOKEN')
        self.create()
        result = self.direct.void_unrecorded_direct_return('EVENT1', 'Response lost', 'TOKEN')
        self.assertEqual(result['status'], 'Recorded')
        self.assertEqual(len(self.events), 1)

    def test_direct_case_uses_existing_qc_accounting_and_disposition_workflow(self):
        self.create()
        case = self.case()
        self.profile.responsibilities = [Doc(responsibility='Customer Return QC')]
        self.returns.start_qc_inspection(case.name, 'STARTQC', 'TOKEN')
        self.returns.complete_qc_inspection(case.name, [dict(name=case.lines[0].name,
            received_qty=3, accepted_qty=2, rejected_qty=1, qc_disposition='Accept for Disposal')],
            'QC evidence reviewed', 'COMPLETEQC', 'TOKEN')
        self.assertEqual(case.state, 'QC Completed - Accounting Pending')
        self.assertEqual(case.accepted_total_qty, 2)
        self.returns.prepare_accounting_decision(case.name, 'No Credit', 'Claim rejected by accounting')
        self.assertEqual(case.state, 'Accounting Completed')
        result = self.disposition.prepare_stock_disposition(case.name,
            [dict(return_line=case.lines[0].name, qty=2, disposition='Dispose Without Stock Receipt', reason='Unsafe')],
            'Physical disposal confirmed')
        self.assertTrue(result['completed'])
        self.assertEqual(case.state, 'Closed')
        self.assertFalse(case.customer_scan_point or case.stock_disposition_entry or case.credit_document)

    def test_controller_preserves_site_gate_and_separates_delivery_correction(self):
        self.create()
        case = self.case()
        for changes in ({'customer_scan_point': 'SITE'}, {'site_code': 'FAKE'},
                        {'return_flow': 'Delivery Note Correction'}, {'selling_company': None},
                        {'intake_method': 'Unknown'}, {'intake_method': 'Customer Site'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.controller(dict(case, name=None, **changes)).validate()
        site = self.controller(dict(case, name=None, intake_method='Customer Site', customer_scan_point='SITE', site_code='SITE-QR', site_name='Existing Site'))
        site.validate()

    def test_intake_identity_and_claims_remain_immutable_after_creation(self):
        self.create()
        case = self.case()
        before = self.controller(copy.deepcopy(dict(case)))
        for changes in ({'customer': 'OTHER'}, {'intake_payload_hash': 'altered'},
                        {'inspection_location': 'OTHER BAY'}, {'claimed_total_qty': 4}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'immutable'):
                self.controller(dict(case, _before=before, **changes)).validate()
        altered = self.controller(dict(case, _before=before))
        altered.lines = [Doc(dict(case.lines[0], claimed_qty=4))]
        with self.assertRaisesRegex(ValueError, 'immutable'):
            altered.validate()

    def test_legacy_site_intake_still_snapshots_site_and_uses_same_qc_case(self):
        self.current_read_required = False  # The unchanged legacy service uses its original reads.
        site = self.add('CFG Kanban Customer Scan Point', 'SITE',
            site_code='SITEQR', site_name='Site', selling_company='A', customer='CUST',
            customer_address='CUST ADDRESS', enable_customer_return_qc=1,
            return_inspection_location='QC BAY')
        self.returns.create_qc_return_case.__globals__['_resolve_site'] = lambda scan: site
        result = self.returns.create_qc_return_case('SITEQR', 'Unwanted',
            self.args['lines'], 'SITE-EVENT', 'TOKEN')
        self.assertEqual(result['customer_scan_point'], 'SITE')
        self.assertEqual(result['selling_company'], 'A')
        self.assertEqual((result['site_code'], result['site_name']), ('SITEQR', 'Site'))
        self.assertEqual(result['state'], 'Awaiting QC Receipt')
        self.assertEqual(result['claimed_total_qty'], 3)

    def test_legacy_missing_method_normalizes_to_customer_site_on_later_save(self):
        self.create()
        case = self.case()
        before = self.controller(dict(case, intake_method=None, customer_scan_point='SITE',
            site_code='SITEQR', site_name='Site'))
        current = self.controller(dict(before, _before=before, intake_method='Customer Site'))
        current.validate()
        current.intake_method = 'Direct Customer'
        with self.assertRaises(ValueError):
            current.validate()

    def test_schema_keeps_site_requirements_conditional_and_print_supports_direct(self):
        fields = {row['fieldname']: row for row in self.schema['fields']}
        for field in ('customer_scan_point', 'site_code', 'site_name'):
            self.assertFalse(fields[field].get('reqd'))
            self.assertIn('Direct Customer', fields[field]['mandatory_depends_on'])
        self.assertEqual(len(self.schema['field_order']), len(set(self.schema['field_order'])))
        html = json.loads((ROOT / 'cfg_kanban/print_format/cfg_temporary_return_note/cfg_temporary_return_note.json').read_text())['html']
        self.assertIn('Direct Customer Return', html)
        self.assertIn('Intake Method', html)
        self.assertIn('NOT A TAX CREDIT NOTE', html)


if __name__ == '__main__':
    unittest.main()

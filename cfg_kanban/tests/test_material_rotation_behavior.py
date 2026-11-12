"""Offline FEFO/Work Order approval behavior with Frappe dependency doubles.

Does not establish MariaDB isolation, ERP ledger or live scanner acceptance.
"""
import datetime
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


def load_service():
    frappe = types.ModuleType('frappe')
    frappe._ = lambda value: value
    frappe.whitelist = lambda *a, **k: lambda fn: fn
    frappe.throw = Mock(side_effect=lambda message: (_ for _ in ()).throw(ValueError(message)))
    utils = types.ModuleType('frappe.utils')
    utils.cint = lambda value: int(value or 0)
    utils.flt = lambda value: float(value or 0)
    utils.getdate = lambda value: value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])
    utils.today = lambda: '2026-11-12'
    utils.now_datetime = lambda: '2026-11-12 12:00:00'
    events = types.ModuleType('cfg_kanban.services.events')
    events.record = Mock()
    auth = types.ModuleType('cfg_kanban.services.operator_auth')
    auth.require_operator = Mock(return_value=(
        Row(employee='SUPERVISOR', allowed_operations=[], allowed_workstations=[]),
        Row(name='SUPERVISOR-SESSION', terminal_user='terminal@example.test'),
    ))
    idem = types.ModuleType('cfg_kanban.services.idempotency')
    idem.canonical_key = lambda *parts: hashlib.sha256(json.dumps(parts).encode()).hexdigest()
    modules = {'frappe': frappe, 'frappe.utils': utils,
               'cfg_kanban.services.events': events, 'cfg_kanban.services.operator_auth': auth,
               'cfg_kanban.services.idempotency': idem}
    spec = importlib.util.spec_from_file_location('material_rotation_subject', ROOT/'services/material_rotation.py')
    service = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(service)
    return service, frappe


class TestMaterialRotationBehavior(unittest.TestCase):
    def setUp(self):
        self.service, self.frappe = load_service()
        self.execution = Row(name='EXEC-1', job_card='JOB-1', kanban_master='MASTER',
                             operation='Print', workstation='Station A')
        self.order = Row(name='WO-1', company='TEST', docstatus=1, status='In Process',
                         operations=[Row(operation='Print', workstation='Station A'),
                                     Row(operation='Pack', workstation='Station B')])
        self.unit = Row(name='TAG-LATE', handling_unit_id='RAW-LATE', batch_no='BATCH-LATE',
                        item_code='RAW', expiry_date='2027-01-01', inventory_company='TEST',
                        current_warehouse='Raw Store', stock_uom='Kg', process_certificate_set=None)
        self.batch = {'BATCH-LATE': Row(item='RAW', disabled=0, expiry_date='2027-01-01')}
        self.batch_controlled = True
        self.approvals = []
        self.candidates = [self.candidate('TAG-EARLY', expiry='2026-12-01'),
                           self.candidate('TAG-LATE', expiry='2027-01-01')]
        self.frappe.db = Row(get_value=Mock(side_effect=self.get_value),
                             sql=Mock(side_effect=self.sql), set_value=Mock(side_effect=self.set_value),
                             table_exists=lambda doctype: True)
        self.frappe.get_doc = Mock(side_effect=self.get_doc)
        self.frappe.get_all = Mock(return_value=self.order.operations)

    def candidate(self, name, expiry=None, received='2026-01-01', batch='BATCH', available=100):
        return Row(name=name, handling_unit_id=name, batch_no=batch, expiry_date=expiry,
                   batch_expiry=expiry, batch_item='RAW' if batch else None, batch_disabled=0,
                   received_on=received, effective_available=available, scan_code='SCAN-'+name)

    def get_value(self, doctype, name, fields=None, as_dict=False):
        if doctype == 'Job Card':
            return 'WO-OTHER' if name == 'JOB-OTHER' else self.order.name
        if doctype == 'Item':
            return self.batch_controlled
        if doctype == 'Batch':
            return self.batch.get(name)
        if doctype == 'CFG Kanban Master':
            return 'TEST'
        if doctype == self.service.OVERRIDE_DOCTYPE:
            return next((row for row in self.approvals if all(row.get(k) == v for k,v in name.items())), None)
        raise AssertionError((doctype, name, fields))

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            row = Row(doctype, name='APPROVAL-'+str(len(self.approvals)+1))
            row.insert = lambda **kwargs: self.insert(row)
            return row
        if doctype == 'Work Order':
            return Row(self.order, name=name)
        if doctype == 'CFG Kanban Process Execution':
            return self.execution if name == 'EXEC-1' else Row(self.execution, name=name, job_card='JOB-2',
                                                              operation='Pack', workstation='Station B')
        raise AssertionError((doctype, name))

    def insert(self, row):
        self.approvals.append(row)
        return row

    def set_value(self, doctype, name, changes):
        self.approvals[next(i for i,row in enumerate(self.approvals) if row.name == name)].update(changes)

    def sql(self, query, params=None, **kwargs):
        if 'from `tabWork Order`' in query:
            return [self.order]
        if 'Material Rotation Override` approval' in query:
            return [row for row in self.approvals if row.status == 'Active' and row.work_order == params[0]
                    and row.company == params[1] and self.order.status not in self.service.TERMINAL_WORK_ORDER_STATES]
        if 'from `tabCFG Kanban Handling Unit` hu' in query:
            return self.candidates
        raise AssertionError(query)

    def approve(self, token='approval-token', reason='Approved whole order exception'):
        return self.service.approve_work_order_material_rotation('EXEC-1', reason, token, 'supervisor-session')

    def test_later_expiry_requires_full_work_order_approval(self):
        with self.assertRaisesRegex(ValueError, 'FEFO requires source tag SCAN-TAG-EARLY'):
            self.service.validate_material_rotation(self.execution, self.unit)
        self.approve()
        result = self.service.validate_material_rotation(self.execution, self.unit)
        self.assertEqual(result['rotation_override'], 'APPROVAL-1')
        self.assertEqual(result['override_work_order'], 'WO-1')

    def test_one_approval_covers_next_runs_and_other_operation_cards_of_same_wo(self):
        self.approve()
        other_execution = Row(self.execution, name='EXEC-2', job_card='JOB-2', operation='Pack', workstation='Station B')
        for execution in (self.execution, other_execution, self.execution):
            result = self.service.validate_material_rotation(execution, self.unit)
            self.assertEqual(result['rotation_override'], 'APPROVAL-1')
        self.assertEqual(len(self.approvals), 1)

    def test_approval_does_not_leak_to_another_work_order(self):
        self.approve()
        other = Row(self.execution, job_card='JOB-OTHER')
        with self.assertRaisesRegex(ValueError, 'FEFO requires'):
            self.service.validate_material_rotation(other, self.unit)

    def test_expired_batch_cannot_be_overridden_or_hidden_by_later_tag_date(self):
        self.approve()
        self.batch['BATCH-LATE'].expiry_date='2026-11-11'
        with self.assertRaisesRegex(ValueError, 'expired on 2026-11-11'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_expired_tag_cannot_be_hidden_by_later_batch_date(self):
        self.unit.expiry_date='2026-11-11'
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_today_is_valid_and_expired_candidates_do_not_block_it(self):
        self.unit.expiry_date='2026-11-12'
        self.candidates = [self.candidate('OLD', expiry='2026-11-11'),
                           self.candidate(self.unit.name, expiry='2026-11-12')]
        result = self.service.validate_material_rotation(self.execution, self.unit)
        self.assertIsNone(result['rotation_override'])

    def test_equal_expiry_uses_receipt_order_then_identity(self):
        self.candidates = [self.candidate('TAG-EARLY', expiry='2027-01-01', received='2025-01-01'),
                           self.candidate(self.unit.name, expiry='2027-01-01')]
        with self.assertRaisesRegex(ValueError, 'SCAN-TAG-EARLY'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_undated_stock_sorts_after_dated_stock(self):
        self.batch_controlled=False
        self.unit.batch_no=None
        self.unit.expiry_date=None
        self.candidates = [self.candidate(self.unit.name, batch=None),
                           self.candidate('DATED', expiry='2027-01-01', batch=None)]
        with self.assertRaisesRegex(ValueError, 'SCAN-DATED'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_small_earlier_balance_is_not_silently_skipped(self):
        self.candidates[0].effective_available=2
        with self.assertRaisesRegex(ValueError, '2 available'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_disabled_missing_wrong_item_and_missing_required_batch_are_rejected(self):
        for batch in (None, Row(item='RAW', disabled=1), Row(item='OTHER', disabled=0)):
            self.batch['BATCH-LATE'] = batch
            with self.assertRaisesRegex(ValueError, 'missing, disabled or incompatible'):
                self.service.assert_material_not_expired(self.unit)
        self.unit.batch_no=None
        with self.assertRaisesRegex(ValueError, 'requires a Batch'):
            self.service.assert_material_not_expired(self.unit)

    def test_ineligible_selected_source_is_rejected_even_with_override(self):
        self.approve(); self.candidates = [self.candidates[0]]
        with self.assertRaisesRegex(ValueError, 'no longer eligible'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_invalid_candidate_batch_is_not_prioritized(self):
        self.candidates[0].batch_disabled=1
        self.assertIsNone(self.service.validate_material_rotation(self.execution, self.unit)['rotation_override'])

    def test_revoke_restores_fefo_for_subsequent_runs(self):
        self.approve()
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Restore rotation', 'revoke-token', 'session', approval_name='APPROVAL-1')
        self.assertEqual(self.approvals[0].status, 'Revoked')
        self.assertIsNone(self.approvals[0].active_work_order_key)
        with self.assertRaisesRegex(ValueError, 'FEFO requires'):
            self.service.validate_material_rotation(self.execution, self.unit)

    def test_approval_and_revocation_retries_do_not_create_extra_authority(self):
        self.approve(); self.approve()
        self.assertEqual(len(self.approvals), 1)
        with self.assertRaisesRegex(ValueError, 'different reason'):
            self.approve(reason='Changed reason')
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'revoke', 'session', approval_name='APPROVAL-1')
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'revoke', 'session', approval_name='APPROVAL-1')
        self.assertEqual(self.service.record.call_count, 2)

    def test_old_revocation_retry_does_not_revoke_a_new_approval(self):
        self.approve()
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'revoke', 'session', approval_name='APPROVAL-1')
        self.approve(token='new-approval')
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'revoke', 'session', approval_name='APPROVAL-1')
        self.assertEqual(self.approvals[1].status, 'Active')

    def test_stale_revocation_cannot_target_a_replacement_approval(self):
        self.approve()
        self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'old-revoke', 'session',
                                                        approval_name='APPROVAL-1')
        self.approve(token='new-approval')
        with self.assertRaisesRegex(ValueError, 'approval changed'):
            self.service.revoke_work_order_material_rotation('EXEC-1', 'Stop', 'fresh-stale-request', 'session',
                                                            approval_name='APPROVAL-1')
        self.assertEqual(self.approvals[1].status, 'Active')

    def test_approval_without_reason_creates_no_authority(self):
        with self.assertRaisesRegex(ValueError, 'reason and stable event token'):
            self.approve(reason='   ')
        self.assertEqual(self.approvals, [])

    def test_scoped_or_unauthorized_supervisor_cannot_grant_wo_wide_authority(self):
        profile, session = self.service.require_operator.return_value
        profile.allowed_operations=[Row(operation='Print')]
        with self.assertRaisesRegex(ValueError, 'unrestricted'):
            self.approve()
        self.assertEqual(len(self.approvals), 0)
        self.service.require_operator.side_effect=PermissionError('denied')
        with self.assertRaises(PermissionError):
            self.approve()

    def test_terminal_or_cross_company_work_orders_cannot_use_approval(self):
        self.approve()
        for status in self.service.TERMINAL_WORK_ORDER_STATES:
            self.order.status=status
            with self.assertRaisesRegex(ValueError, 'active submitted'):
                self.service.validate_material_rotation(self.execution, self.unit)
        self.order.status='In Process'; self.order.company='OTHER'
        with self.assertRaisesRegex(ValueError, 'another Company'):
            self.service.validate_material_rotation(self.execution, self.unit)


class TestMaterialRotationEntryGuards(unittest.TestCase):
    def setUp(self):
        rotation, frappe = load_service()
        frappe.parse_json = json.loads
        frappe.as_json = json.dumps
        frappe.db = Row(sql=Mock())
        frappe.get_doc = Mock()
        utils = types.ModuleType('frappe.utils')
        utils.flt = lambda value: float(value or 0)
        utils.now_datetime = lambda: '2026-11-12 12:00:00'
        events = types.ModuleType('cfg_kanban.services.events'); events.record = Mock()
        idem = types.ModuleType('cfg_kanban.services.idempotency')
        idem.canonical_key = rotation.canonical_key; idem.get_existing = Mock()
        auth = types.ModuleType('cfg_kanban.services.operator_auth')
        auth.require_operator = rotation.require_operator
        spec = importlib.util.spec_from_file_location('material_run_guard_subject', ROOT/'services/operation_material_runs.py')
        self.service = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': frappe, 'frappe.utils': utils,
            'cfg_kanban.services.events': events, 'cfg_kanban.services.idempotency': idem,
            'cfg_kanban.services.operator_auth': auth, 'cfg_kanban.services.material_rotation': rotation}):
            spec.loader.exec_module(self.service)
        self.frappe = frappe
        self.unit = Row(name='TAG-1', reload=Mock())
        self.rule = Row(rule_row='RULE-1')
        self.service._resolve_material_source = Mock(return_value=(self.unit, None))
        self.service._match_source_rule = Mock(return_value=self.rule)
        self.service._assert_enabled = Mock()
        self.service._operationally_available_source_qty = Mock(return_value=100)
        self.service.validate_material_rotation = Mock(side_effect=ValueError('FEFO blocked'))

    def test_preview_checks_fefo_without_inserting_material_draw(self):
        self.frappe.get_doc.return_value=Row(name='EXEC-1')
        with self.assertRaisesRegex(ValueError, 'FEFO blocked'):
            self.service.preview_material_draw('EXEC-1', 'TAG-1', 10, 'session')
        self.service.validate_material_rotation.assert_called_once()
        self.assertEqual(self.frappe.get_doc.call_count, 1)

    def test_start_confirmation_rechecks_fefo_after_lock_and_reload(self):
        with self.assertRaisesRegex(ValueError, 'FEFO blocked'):
            self.service._create_material_draws(Row(), Row(), [{'scan_value':'TAG-1','qty':10}],
                profile=Row(), session=Row(), event_token='token')
        self.unit.reload.assert_called_once()
        self.assertIn('for update', self.frappe.db.sql.call_args.args[0])
        self.service.validate_material_rotation.assert_called_once()
        self.frappe.get_doc.assert_not_called()

    def test_confirmation_rejects_a_container_whose_fill_changed_after_lock(self):
        self.service._resolve_material_source.side_effect=[(self.unit,None), (Row(name='NEW-FILL'),None)]
        with self.assertRaisesRegex(ValueError, 'container source changed'):
            self.service._create_material_draws(Row(), Row(), [{'scan_value':'CONTAINER','qty':10}],
                profile=Row(), session=Row(), event_token='token')
        self.service.validate_material_rotation.assert_not_called()
        self.frappe.get_doc.assert_not_called()

    def test_carry_forward_cannot_start_a_new_run_with_expired_material(self):
        self.frappe.get_all=Mock(return_value=['OLD-TAG'])
        self.service.assert_material_not_expired=Mock(side_effect=ValueError('expired'))
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.service._assert_carry_forward_expiry(Row(name='EXEC-1', allow_material_carry_forward=1))
        self.frappe.get_doc.assert_called_once_with('CFG Kanban Handling Unit','OLD-TAG')


if __name__ == '__main__':
    unittest.main()

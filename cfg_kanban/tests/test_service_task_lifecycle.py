"""Exercise real Service Task functions with offline documents and permission/action doubles.

These checks do not replace Frappe database, browser, or kiosk acceptance.
"""
import ast
import copy
import datetime
import json
import secrets
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class Doc(dict):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

    def set(self, name, value):
        self[name] = value

    def append(self, name, value):
        self.setdefault(name, []).append(Doc(value))

    def save(self, **kwargs):
        self._saves.append(copy.deepcopy(dict(self)))
        return self


def load(relative, namespace):
    source = ast.parse((ROOT / relative).read_text())
    nodes = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.Assign))]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), namespace)
    return namespace


class TestServiceTaskLifecycle(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 11, 20, 9)
        self.profile = Doc(employee='OP', kanban_role='Operator', responsibilities=[],
                           allowed_workstations=[], can_verify_tasks=0, view_all_responsibilities=0)
        self.session = Doc(name='SESSION', terminal_user='floor@example.test')
        self.task = Doc(doctype='CFG Kanban Task', name='KTASK-1', status='Due',
                        assigned_employee='OP', responsible_role=None, workstation='WS',
                        started_on=None, started_by=None, task_schedule='SCHEDULE',
                        execution_values=[], checklist='Clean\nInspect', checklist_evidence=[],
                        checklist_results=None, completed_by=None, completed_on=None,
                        completion_notes=None, verification_required=0, verification_status='Not Required',
                        verified_by=None, verified_on=None, verification_notes=None,
                        doctype_action_profile=None, doctype_action_trigger=None,
                        doctype_action_run=None, doctype_action_required=0,
                        doctype_action_pending_status=None, progress_count=0, _saves=[])
        self.run = Doc(name='RUN-1', state='Form Pending', mapping_snapshot=json.dumps(
            {'configuration': {'posting_policy': 'Save Draft'}}))
        self.record = Mock()
        self.resolve = Mock(return_value={'name': self.run.name})
        self.validate_values = Mock()
        self.definitions = {'Start': [], 'Progress': [], 'Complete': []}
        frappe = Doc(get_doc=lambda doctype, name: self.task if doctype == 'CFG Kanban Task' else self.run,
                     throw=self.throw, parse_json=json.loads, as_json=json.dumps,
                     db=Doc(exists=lambda *args: True, get_value=lambda *args, **kw: 'Operator'))
        common = dict(frappe=frappe, cint=lambda value: int(value or 0),
                      now_datetime=lambda: self.now, json=json, secrets=secrets, _=lambda value: value,
                      record=self.record, resolve_task_run=self.resolve)
        access = load('services/task_access.py', dict(common))
        binding = load('services/doctype_action_tasks.py', dict(common))
        self.ns = load('services/standalone_tasks.py', dict(common,
            require_operator=Mock(side_effect=lambda *args, **kwargs: (self.profile, self.session)),
            assert_service_task_access=access['assert_service_task_access'],
            assert_service_task_execution_access=access['assert_service_task_execution_access'],
            assert_responsibility=access['assert_responsibility'],
            resolve_for_task_event=binding['resolve_for_task_event'],
            apply_required_gate=binding['apply_required_gate'], cancel_task_action=Mock(),
            standalone_definitions=lambda schedule, stage: self.definitions.get(stage, []),
            validate_values=self.validate_values,
            normalized_values=lambda rows, supplied: [dict(row) for row in supplied]))

    @staticmethod
    def throw(message):
        raise ValueError(message)

    def complete(self):
        return self.ns['complete_task']('KTASK-1', 'TOKEN',
            values=[{'field_key': 'result', 'value': 'OK'}],
            checklist_results=[{'item': item, 'completed': 1} for item in ('Clean', 'Inspect')],
            notes='Done')

    def started(self, status='In Progress'):
        self.task.started_on = self.now
        self.task.started_by = 'OP'
        self.task.status = status

    def assert_no_completion_effects(self, before):
        self.assertEqual(self.task, before)
        self.resolve.assert_not_called()
        self.record.assert_not_called()
        self.validate_values.assert_not_called()

    def test_unstarted_completion_rejected_before_any_side_effect(self):
        for status in ('Planned', 'Due', 'Assigned', 'Overdue', 'In Progress', 'Correction Required'):
            for trigger in (None, 'On Task Start', 'On Task Complete'):
                with self.subTest(status=status, trigger=trigger):
                    self.task.status = status
                    self.task.doctype_action_profile = 'PROFILE' if trigger else None
                    self.task.doctype_action_trigger = trigger
                    before = copy.deepcopy(self.task)
                    with self.assertRaisesRegex(ValueError, '^Start the Service Task before completing it$'):
                        self.complete()
                    self.assert_no_completion_effects(before)

    def test_started_pre_start_statuses_still_cannot_complete(self):
        for status in ('Planned', 'Due', 'Assigned'):
            with self.subTest(status=status):
                self.started(status)
                before = copy.deepcopy(self.task)
                with self.assertRaisesRegex(ValueError, 'Task cannot complete while'):
                    self.complete()
                self.assert_no_completion_effects(before)

    def test_start_then_complete_records_evidence_and_lifecycle(self):
        self.task.assigned_employee = None
        self.ns['start_task']('KTASK-1', 'TOKEN')
        self.assertEqual((self.task.status, self.task.started_on, self.task.assigned_employee),
                         ('In Progress', self.now, 'OP'))
        self.complete()
        self.assertEqual((self.task.status, self.task.completed_by), ('Completed', 'OP'))
        self.assertEqual(len(self.task.checklist_evidence), 2)
        self.assertEqual(self.task.execution_values[0].capture_on, 'Complete')
        self.assertEqual([call.args[0] for call in self.record.call_args_list],
                         ['Standalone Task Started', 'Standalone Task Completed'])

    def test_started_overdue_can_complete(self):
        self.started('Overdue')
        self.complete()
        self.assertEqual(self.task.status, 'Completed')

    def test_correction_resubmission_preserves_start_and_requests_verification(self):
        self.started('Correction Required')
        self.task.verification_required = 1
        self.task.verification_status = 'Rejected'
        self.task.verification_notes = 'Correct this'
        self.task.verified_by = 'SUP'
        self.complete()
        self.assertEqual(self.task.status, 'Awaiting Verification')
        self.assertEqual(self.task.verification_status, 'Pending')
        self.assertEqual(self.task.started_on, self.now)
        self.assertIsNone(self.task.verified_by)
        self.assertIsNone(self.task.verification_notes)

    def test_supervisor_with_full_access_still_must_wait_for_start(self):
        self.profile.update(employee='SUP', kanban_role='Supervisor', view_all_responsibilities=1)
        before = copy.deepcopy(self.task)
        with self.assertRaisesRegex(ValueError, 'Start the Service Task before completing it'):
            self.complete()
        self.assert_no_completion_effects(before)
        self.started()
        self.complete()
        self.assertEqual((self.task.assigned_employee, self.task.completed_by), ('OP', 'SUP'))

    def test_scoped_supervisor_assists_only_started_operator_work(self):
        self.profile.update(employee='SUP', kanban_role='Supervisor')
        with self.assertRaisesRegex(ValueError, 'Task is assigned to Employee OP'):
            self.complete()
        self.started()
        self.complete()
        self.assertEqual((self.task.assigned_employee, self.task.completed_by), ('OP', 'SUP'))
        self.assertEqual(self.record.call_args.kwargs['operator'], 'SUP')

    def test_another_operator_cannot_complete_started_work(self):
        self.started()
        self.profile.employee = 'OTHER'
        before = copy.deepcopy(self.task)
        with self.assertRaisesRegex(ValueError, 'Task is assigned'):
            self.complete()
        self.assert_no_completion_effects(before)

    def test_start_action_gate_remains_before_evidence(self):
        self.started()
        self.task.update(doctype_action_profile='PROFILE', doctype_action_trigger='On Task Start')
        before = copy.deepcopy(self.task)
        with self.assertRaisesRegex(ValueError, 'before completing its On Task Start action'):
            self.complete()
        self.assert_no_completion_effects(before)

    def test_required_complete_action_preserves_pending_document_gate(self):
        self.started()
        self.task.update(doctype_action_profile='PROFILE', doctype_action_trigger='On Task Complete',
                         doctype_action_required=1)
        self.complete()
        self.resolve.assert_called_once()
        self.assertEqual((self.task.status, self.task.doctype_action_run,
                          self.task.doctype_action_pending_status),
                         ('Pending Document Posting', 'RUN-1', 'Completed'))
        self.assertEqual(self.record.call_args.args[0], 'Standalone Task Pending Document Posting')

    def test_satisfied_start_action_can_complete(self):
        self.started()
        self.task.update(doctype_action_profile='PROFILE', doctype_action_trigger='On Task Start',
                         doctype_action_run='RUN-1', doctype_action_required=1)
        self.run.state = 'Draft Created'
        self.complete()
        self.assertEqual(self.task.status, 'Completed')

    def test_required_progress_still_blocks_completion(self):
        self.started()
        self.definitions['Progress'] = [Doc(field_key='temperature', mandatory=1,
                                             label='Temperature', field_type='Float')]
        with self.assertRaisesRegex(ValueError, 'Report mandatory Progress fields'):
            self.complete()
        self.assertEqual(self.task.status, 'In Progress')
        self.assertEqual(self.task.checklist_evidence, [])
        self.resolve.assert_not_called()
        self.record.assert_not_called()

    def test_unstarted_progress_rejected_without_evidence(self):
        self.task.status = 'Overdue'
        before = copy.deepcopy(self.task)
        with self.assertRaisesRegex(ValueError, 'Start the Service Task before reporting progress'):
            self.ns['progress_task']('KTASK-1', 'TOKEN', values=[{'field_key': 'x', 'value': 1}])
        self.assert_no_completion_effects(before)

    def test_started_progress_is_preserved(self):
        self.started()
        self.ns['progress_task']('KTASK-1', 'TOKEN', values=[{'field_key': 'x', 'value': 0}])
        self.assertEqual(self.task.progress_count, 1)
        self.assertEqual(self.task.execution_values[0].capture_on, 'Progress')
        self.assertEqual(self.task.status, 'In Progress')

    def test_unstarted_supervisor_cancel_and_bypass_remain_available(self):
        self.profile.update(kanban_role='Supervisor', can_verify_tasks=1)
        for disposition in ('Cancelled', 'Bypassed'):
            with self.subTest(disposition=disposition):
                self.task.status = 'Due'
                self.ns['disposition_task']('KTASK-1', 'TOKEN', disposition, 'Holiday')
                self.assertEqual(self.task.status, disposition)
                self.assertIsNone(self.task.started_on)
                self.assertIsNone(self.task.completed_on)

    def test_completed_retry_does_not_duplicate_evidence_or_events(self):
        self.started()
        self.complete()
        before = copy.deepcopy(self.task)
        count = self.record.call_count
        self.complete()
        self.assertEqual(self.task, before)
        self.assertEqual(self.record.call_count, count)

    def test_cancelled_bypassed_and_verification_states_cannot_complete(self):
        for status in ('Cancelled', 'Bypassed', 'Awaiting Verification', 'Pending Document Posting'):
            with self.subTest(status=status):
                self.started(status)
                before = copy.deepcopy(self.task)
                with self.assertRaisesRegex(ValueError, 'Task cannot complete while'):
                    self.complete()
                self.assert_no_completion_effects(before)


if __name__ == '__main__':
    unittest.main()

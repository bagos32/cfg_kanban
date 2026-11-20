"""Location Card lookup and real Service Task access filtering, with offline DB doubles."""
import ast
import copy
import hashlib
import re
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, unquote, urlparse

from cfg_kanban.tests.test_service_task_lifecycle import Doc, load

ROOT = Path(__file__).resolve().parents[1]


def functions(relative, names, namespace):
    nodes = [node for node in ast.parse((ROOT / relative).read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), namespace)
    return namespace


class TestServiceLocationScans(unittest.TestCase):
    def setUp(self):
        self.card = Doc(doctype='CFG Kanban Card', name='KCRD-LOCATION', card_number='SERVICE-01',
                        qr_code='location-uuid', uuid='card-uuid', card_type='Location Card',
                        location_purpose='General Service Point', location_reference='RINSE BAY',
                        company='CFG', active=1, blocked=0)
        self.profile = Doc(employee='OP', kanban_role='Operator', responsibilities=[Doc(responsibility='Cleaning')],
                           allowed_workstations=[Doc(workstation='WS-1')], can_verify_tasks=0,
                           view_all_responsibilities=0)
        self.rows = []
        self.queries = []
        self.get_doc = Mock(side_effect=self.document)
        self.frappe = None
        self.write = Mock()
        frappe = Doc(get_doc=self.get_doc, get_all=self.get_all, throw=self.throw,
                     db=Doc(get_value=self.get_value, set_value=self.write, count=lambda *args: 1))
        self.frappe = frappe
        common = dict(frappe=frappe, cint=lambda value: int(value or 0), hashlib=hashlib, now_datetime=lambda: '2026-11-20')
        access = load('services/task_access.py', dict(common))
        self.access = access
        scan = functions('services/doctype_action_runs.py', {'_scan_identity'},
                         dict(re=re, urlparse=urlparse, parse_qs=parse_qs, unquote=unquote))
        self.profile_revision = '2026-11-20 10:00:00'
        self.require_operator = Mock(side_effect=self.operator)
        self.api = functions('api/task.py', {'get_open_tasks', 'get_service_tasks_live_revision', '_service_identity_card', '_service_card_scope', 'get_task_form', 'get_task_progress',
                                            'resolve_service_card_scan', 'get_service_tasks_live_revision'},
                             dict(access, require_operator=self.require_operator,
                                  _scan_identity=scan['_scan_identity'], hashlib=hashlib, now_datetime=lambda: '2026-11-20 10:00:00'))

    @staticmethod
    def throw(message):
        raise ValueError(message)

    def operator(self, token, *args, **kwargs):
        if token != 'SESSION':
            raise ValueError('Operator session required')
        return self.profile, Doc(name='SESSION')

    def document(self, doctype, name):
        if doctype == 'CFG Kanban Task':
            return next(row for row in self.rows if row.name == name)
        if doctype == 'CFG Kanban Card' and name == self.card.name:
            return self.card
        raise AssertionError((doctype, name))

    @staticmethod
    def matches(row, filters):
        for key, expected in filters.items():
            value = row.get(key)
            if isinstance(expected, (tuple, list)):
                operator, values = expected
                if (operator == 'in' and value not in values) or (operator == 'not in' and value in values):
                    return False
            elif value != expected:
                return False
        return True

    def get_value(self, doctype, filters, fieldname, **kwargs):
        if fieldname == 'max(modified)':
            return self.profile_revision if doctype == 'CFG Kanban Operator Profile' else 'unchanged'
        if doctype == 'CFG Kanban Card':
            return self.card.name if self.matches(self.card, filters) else None
        if doctype == 'CFG Kanban Operator Profile':
            return 'Operator'
        raise AssertionError((doctype, filters, fieldname))

    def get_all(self, doctype, filters, fields, **kwargs):
        self.queries.append((doctype, copy.deepcopy(filters), kwargs))
        if doctype == 'CFG Kanban Task':
            rows = [Doc(row) for row in self.rows if self.matches(row, filters)]
            limit = kwargs.get('limit_page_length')
            return rows[:limit] if limit else rows
        if doctype == 'CFG Kanban Operator Profile':
            return [Doc(employee=employee, kanban_role='Operator') for employee in filters['employee'][1]]
        if doctype == 'CFG Kanban DocType Action Run':
            return []
        raise AssertionError(doctype)

    def task(self, name='TASK-1', **values):
        row = Doc(name=name, location='RINSE BAY', company='CFG', assigned_employee='OP',
                  workstation='WS-1', responsible_role='Cleaning', status='Due', started_on=None,
                  doctype_action_run=None)
        row.update(values)
        self.rows.append(row)
        return row

    def scan(self, value='location-uuid', token='SESSION'):
        return self.api['resolve_service_card_scan'](value, token)

    def tasks(self, card='KCRD-LOCATION', token='SESSION'):
        return self.api['get_open_tasks'](token, service_card=card)

    def test_profile_access_change_invalidates_live_task_revision_without_touching_activity(self):
        first = self.api['get_service_tasks_live_revision']('SESSION')['revision']
        self.profile_revision = '2026-11-20 10:01:00'
        second = self.api['get_service_tasks_live_revision']('SESSION')['revision']
        self.assertNotEqual(first, second)
        self.require_operator.assert_called_with('SESSION', touch_activity=False)

    def test_printed_qr_uuid_card_number_and_document_name_resolve(self):
        before = copy.deepcopy(self.card)
        for value in ('location-uuid', 'card-uuid', 'SERVICE-01', 'KCRD-LOCATION'):
            with self.subTest(value=value):
                result = self.scan(value)
                self.assertTrue(result['matched'])
                self.assertEqual(result['card']['name'], self.card.name)
                self.assertEqual(result['card']['location'], 'RINSE BAY')
        self.assertEqual(self.card, before)
        self.write.assert_not_called()

    def test_existing_card_url_formats_resolve(self):
        for value in ('https://example.test/app/kanban-operator#card=location-uuid',
                      'https://example.test/app/kanban-tasks?card_number=SERVICE-01',
                      'https://example.test/app/cfg-kanban-card/KCRD-LOCATION',
                      'https://example.test/app/kanban-tasks#qr=card-uuid'):
            with self.subTest(value=value):
                self.assertTrue(self.scan(value)['matched'])

    def test_prelogin_recognition_requests_operator_without_returning_card_or_tasks(self):
        result = self.scan(token=None)
        self.assertTrue(result['matched'])
        self.assertTrue(result['requires_operator'])
        self.assertIn('Identify the operator first', result['message'])
        self.assertNotIn('card', result)
        self.assertNotIn('tasks', result)
        self.get_doc.assert_not_called()
        self.require_operator.assert_not_called()

    def test_unknown_and_empty_scans_do_not_claim_to_be_location_cards(self):
        for value in ('', None, 'employee-secret', 'KTASK-1', 'CFG:SERVICE:SCHEDULE:SCH'):
            with self.subTest(value=value):
                self.assertEqual(self.scan(value, token=None), {'matched': False})
        self.require_operator.assert_not_called()

    def test_expired_session_cannot_read_card_context(self):
        with self.assertRaisesRegex(ValueError, 'Operator session required'):
            self.scan(token='EXPIRED')
        self.get_doc.assert_not_called()
        self.assertFalse(self.queries)

    def test_inactive_blocked_wrong_purpose_and_missing_location_rejected(self):
        for field, value, message in [('active', 0, 'inactive'), ('blocked', 1, 'blocked'),
                                      ('location_reference', '', 'Location Reference'),
                                      ('location_reference', '  ', 'Location Reference'),
                                      ('location_purpose', 'Warehouse Operations', 'General Service Point'),
                                      ('location_purpose', 'Supplier Receiving', 'General Service Point'),
                                      ('location_purpose', 'Dispatch Operations', 'General Service Point')]:
            with self.subTest(field=field, value=value):
                old = self.card[field]
                self.card[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.scan()
                self.card[field] = old
        self.write.assert_not_called()

    def test_location_and_company_scope_applied_before_access_and_display_limit(self):
        for index in range(210):
            self.task('OTHER-' + str(index), location='OTHER BAY')
        self.task('OTHER-COMPANY', company='OTHER')
        self.task('MATCH')
        self.assertEqual([row.name for row in self.tasks()], ['MATCH'])
        query = next(row for row in self.queries if row[0] == 'CFG Kanban Task')
        self.assertEqual((query[1]['location'], query[1]['company']), ('RINSE BAY', 'CFG'))
        self.assertEqual(query[2]['limit_page_length'], 0)

    def test_assignment_responsibility_and_workstation_rules_preserved(self):
        self.task('OWN')
        self.task('UNASSIGNED', assigned_employee=None)
        self.task('OTHER-EMPLOYEE', assigned_employee='OTHER')
        self.task('OTHER-ROLE', assigned_employee=None, responsible_role='Maintenance')
        self.task('OTHER-STATION', workstation='WS-2')
        self.assertEqual([row.name for row in self.tasks()], ['OWN', 'UNASSIGNED', 'OTHER-EMPLOYEE', 'OTHER-ROLE'])
        references = [row for row in self.tasks() if row.scan_view_only]
        self.assertEqual([row.name for row in references], ['OTHER-EMPLOYEE', 'OTHER-ROLE'])
        self.assertTrue(all(not row.can_operate and not row.can_assist for row in references))

    def test_scoped_supervisor_assistance_preserved(self):
        self.profile.update(employee='SUP', kanban_role='Supervisor')
        self.task('ACTIVE', status='In Progress', started_on='2026-11-20 09:00:00')
        self.task('UNSTARTED')
        result = self.tasks()
        self.assertEqual([row.name for row in result], ['ACTIVE', 'UNSTARTED'])
        self.assertTrue(result[1].scan_view_only)
        self.assertTrue(result[0].can_assist)
        self.assertFalse(result[0].can_operate)

    def test_empty_location_returns_empty_list_without_generation(self):
        self.task(location='OTHER BAY')
        self.assertEqual(self.tasks(), [])
        self.write.assert_not_called()

    def test_completed_cancelled_and_bypassed_do_not_reappear(self):
        for status in ('Completed', 'Cancelled', 'Bypassed'):
            self.task(status, status=status)
        self.task('OPEN')
        self.assertEqual([row.name for row in self.tasks()], ['OPEN'])

    def test_show_all_without_card_keeps_existing_eligible_scope(self):
        self.task('HERE')
        self.task('ELSEWHERE', location='OTHER BAY')
        self.assertEqual([row.name for row in self.tasks(card=None)], ['HERE', 'ELSEWHERE'])

    def test_direct_scoped_list_requires_valid_operator(self):
        with self.assertRaisesRegex(ValueError, 'Operator session required'):
            self.tasks(token=None)
        self.get_doc.assert_not_called()

    def test_direct_scoped_list_cannot_bypass_card_validation(self):
        self.card.blocked = 1
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.tasks()
        self.assertFalse(self.queries)

    def test_direct_scoped_list_rejects_other_card_types(self):
        self.card.card_type = 'Physical Batch Card'
        with self.assertRaisesRegex(ValueError, 'Service Location, Task or Asset Card'):
            self.tasks()

    def test_large_eligible_location_still_has_200_task_limit(self):
        for index in range(205):
            self.task('TASK-' + str(index))
        self.assertEqual(len(self.tasks()), 200)

    def test_default_queue_requires_matching_responsibility(self):
        self.task('MATCH', assigned_employee=None)
        self.task('OTHER', assigned_employee=None, responsible_role='Maintenance')
        self.assertEqual([row.name for row in self.tasks(card=None)], ['MATCH'])

    def test_empty_responsibilities_no_longer_expose_all_unassigned_roles(self):
        self.profile.responsibilities = []
        self.task('CLEAN', assigned_employee=None)
        self.task('MAINTENANCE', assigned_employee=None, responsible_role='Maintenance')
        self.task('SHARED', assigned_employee=None, responsible_role=None)
        self.task('DIRECTLY-ASSIGNED')
        self.assertEqual([row.name for row in self.tasks(card=None)], ['SHARED', 'DIRECTLY-ASSIGNED'])

    def test_job_code_does_not_grant_service_responsibility(self):
        self.profile.responsibilities = []
        self.profile.job_codes = [Doc(job_code='Cleaning')]
        self.task(assigned_employee=None)
        self.assertEqual(self.tasks(card=None), [])

    def test_scanned_location_reveals_other_role_as_reference_only(self):
        self.profile.responsibilities = []
        self.task('OTHER-ROLE', assigned_employee=None, responsible_role='Maintenance')
        self.assertEqual(self.tasks(card=None), [])
        result = self.tasks()
        self.assertEqual([row.name for row in result], ['OTHER-ROLE'])
        self.assertTrue(result[0].scan_view_only)
        self.assertFalse(result[0].can_operate)
        self.assertFalse(result[0].can_assist)
        self.assertFalse(result[0].can_resume_action)
        self.write.assert_not_called()

    def test_scanned_task_and_asset_cards_use_exact_scope(self):
        for card_type, field, value in [('Task Card', 'task_schedule', 'SCH-1'), ('Asset Card', 'asset', 'ASSET-1')]:
            with self.subTest(card_type=card_type):
                self.rows = []
                self.card.update(card_type=card_type, **{field: value})
                self.task('MATCH', assigned_employee=None, responsible_role='Maintenance', **{field: value})
                self.task('ELSEWHERE', **{field: 'OTHER'})
                self.assertTrue(self.scan()['matched'])
                result = self.tasks()
                self.assertEqual([row.name for row in result], ['MATCH'])
                self.assertTrue(result[0].scan_view_only)

    def test_scanned_task_id_does_not_broaden_queue_or_workstation_scope(self):
        self.task('EXACT', assigned_employee=None, responsible_role='Maintenance')
        self.task('OTHER', assigned_employee=None, responsible_role='Maintenance')
        result = self.api['get_open_tasks']('SESSION', scanned_task='EXACT')
        self.assertEqual([row.name for row in result], ['EXACT'])
        self.assertTrue(result[0].scan_view_only)
        self.rows[0].workstation = 'WS-2'
        self.assertEqual(self.api['get_open_tasks']('SESSION', scanned_task='EXACT'), [])
        self.assertEqual(self.api['get_open_tasks']('SESSION', scanned_task='UNKNOWN'), [])

    def test_scanning_cannot_mix_card_and_exact_task_scope(self):
        with self.assertRaisesRegex(ValueError, 'one Service Card or one exact Service Task'):
            self.api['get_open_tasks']('SESSION', service_card=self.card.name, scanned_task='EXACT')

    def test_matching_tasks_precede_scanned_references_before_200_row_limit(self):
        for index in range(210):
            self.task('OTHER-' + str(index), assigned_employee=None, responsible_role='Maintenance')
        self.task('MATCH', assigned_employee=None)
        result = self.tasks()
        self.assertEqual(len(result), 200)
        self.assertEqual(result[0].name, 'MATCH')
        self.assertFalse(result[0].scan_view_only)

    def test_supervisor_view_all_retains_controlled_default_visibility(self):
        self.profile.update(employee='SUP', kanban_role='Supervisor', view_all_responsibilities=1, responsibilities=[])
        self.task('OTHER-ROLE', assigned_employee='OTHER', responsible_role='Maintenance')
        result = self.tasks(card=None)
        self.assertEqual([row.name for row in result], ['OTHER-ROLE'])
        self.assertTrue(result[0].can_operate)
        self.assertFalse(result[0].scan_view_only)

    def test_reference_scan_cannot_start_task_or_open_progress_completion_media(self):
        self.profile.responsibilities = []
        row = self.task('OTHER-ROLE', assigned_employee=None, responsible_role='Maintenance')
        before = copy.deepcopy(row)
        service = functions('services/standalone_tasks.py', {'start_task', '_validate_assignment'},
                            dict(self.access, require_operator=self.require_operator))
        with self.assertRaisesRegex(ValueError, 'Task responsibility'):
            service['start_task'](row.name, 'SESSION')
        for stage in ('Start', 'Progress', 'Complete', 'Verify'):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, 'Task responsibility'):
                self.api['get_task_form'](row.name, stage, 'SESSION')
        with self.assertRaisesRegex(ValueError, 'Task responsibility'):
            self.api['get_task_progress'](row.name, 'SESSION')
        ns = functions('services/standalone_tasks.py',
                       {'progress_task', 'complete_task', '_validate_execution_assignment'},
                       dict(self.access, require_operator=self.require_operator))
        for method in ('progress_task', 'complete_task'):
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'Task responsibility'):
                ns[method](row.name, 'SESSION')
        self.assertEqual(row, before)
        self.write.assert_not_called()

    def test_schedule_qr_can_read_existing_other_role_but_not_generate_it(self):
        class Record(Doc):
            def as_dict(self):
                return dict(self)
        row = self.task('OTHER-ROLE', assigned_employee=None, responsible_role='Maintenance')
        schedule = Record(name='SCH-1', workstation='WS-1', responsible_role='Maintenance',
                          next_due_on='2026-11-20 09:00:00', active=1)
        self.frappe.get_doc = lambda doctype, name: schedule if doctype == 'CFG Kanban Task Schedule' else row
        self.frappe.db.get_value = Mock(return_value=row.name)
        create = Mock()
        ns = functions('services/standalone_tasks.py', {'resolve_service_point'}, dict(self.access,
            require_operator=self.require_operator, _service_schedule_name=lambda value: 'SCH-1',
            create_from_schedule=create, get_datetime=lambda value: value, now_datetime=lambda: '2026-11-20 10:00:00'))
        result = ns['resolve_service_point']('CFG:SERVICE:SCHEDULE:SCH-1', 'SESSION')
        self.assertEqual(result['task'], {'name': row.name})
        self.assertFalse(result['generated'])
        create.assert_not_called()
        self.frappe.db.get_value.return_value = None
        with self.assertRaisesRegex(ValueError, 'Task responsibility'):
            ns['resolve_service_point']('CFG:SERVICE:SCHEDULE:SCH-1', 'SESSION')
        create.assert_not_called()


if __name__ == '__main__':
    unittest.main()

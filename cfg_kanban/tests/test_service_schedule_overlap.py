"""Actual recurrence and Task close hook with offline documents/clock/database adapters.

These checks do not establish live scheduler timing or database lock behavior.
"""
import ast
import calendar
import copy
import datetime as dt
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = 'CFG Kanban Task Schedule'
TASK = 'CFG Kanban Task'


class Row(dict):
    def __getattr__(self, key):
        if key.startswith('__'):
            raise AttributeError(key)
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value


def load(relative, namespace, classes=False):
    tree = ast.parse((ROOT / relative).read_text())
    kinds = (ast.FunctionDef, ast.Assign, ast.ClassDef) if classes else (ast.FunctionDef, ast.Assign)
    nodes = [node for node in tree.body if isinstance(node, kinds)]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), namespace)
    return namespace


def date(value):
    return dt.datetime.fromisoformat(value) if isinstance(value, str) else value


def add_to_date(value, months=0, **kwargs):
    value = date(value)
    if months:
        assert months == int(months), 'Fixture only supports integral months'
        year, month = divmod(value.year * 12 + value.month - 1 + int(months), 12)
        value = value.replace(year=year, month=month + 1,
                              day=min(value.day, calendar.monthrange(year, month + 1)[1]))
    return value + dt.timedelta(**kwargs)


class TestServiceScheduleOverlap(unittest.TestCase):
    def setUp(self):
        self.now = date('2026-11-28 11:20:00')
        self.tasks = {}
        self.events = []
        self.writes = []
        self.locks = []
        self.busy_tasks = set()
        self.holidays = set()
        fixture = self

        class Doc(Row):
            def is_new(self):
                return bool(self._new)

            def has_value_changed(self, field):
                return self.get(field) != self._previous.get(field)

            def get_doc_before_save(self):
                return self._previous

            def db_set(self, changes, value=None, **kwargs):
                changes = changes if isinstance(changes, dict) else {changes: value}
                self.update(changes)
                if self.doctype == SCHEDULE:
                    fixture.schedule.update(changes)
                fixture.writes.append((self.doctype, self.name, dict(changes)))

            def insert(self, **kwargs):
                self.name = 'KTASK-' + str(len(fixture.tasks) + 1)
                fixture.model.before_save(self)
                self._new = False
                self._previous = Row(status=self.status)
                fixture.tasks[self.name] = self
                return self

            def save(self, **kwargs):
                fixture.model.before_save(self)
                self._previous = Row(status=self.status)
                fixture.writes.append((TASK, self.name, {'status': self.status}))
                return self

            def as_dict(self):
                return dict(self)

        self.Doc = Doc
        self.schedule = Doc(doctype=SCHEDULE, name='KTS-1', active=1, overlap_policy='Skipped While Open',
                            trigger_type='Time Interval', interval_value=1, interval_unit='Hours',
                            calendar_repeat_days=1, next_due_on=date('2026-11-28 10:00:00'),
                            last_generated_on=date('2026-11-28 09:00:00'), default_due_hours=1,
                            holiday_policy='Generate Normally', workstation=None)

        def get_doc(doctype, name=None, **kwargs):
            if isinstance(doctype, dict):
                assert doctype['doctype'] == TASK, 'No manufacturing or stock document is allowed'
                return Doc(doctype, _new=True, _previous=Row())
            if kwargs.get('for_update'):
                self.locks.append((doctype, name))
            if doctype == SCHEDULE:
                return Doc(self.schedule)
            assert doctype == TASK, doctype
            return self.tasks[name]

        def get_value(doctype, filters, field='name', **kwargs):
            if doctype == SCHEDULE:
                self.assertEqual(filters, self.schedule.name)
                return self.schedule.get(field)
            self.assertEqual(doctype, TASK)
            if kwargs.get('for_update'):
                self.locks.append((TASK, 'open lookup'))
            for task in self.tasks.values():
                if kwargs.get('for_update') and kwargs.get('skip_locked') and task.name in self.busy_tasks:
                    continue
                matches = True
                for key, expected in filters.items():
                    actual = task.get(key)
                    if isinstance(expected, (tuple, list)):
                        self.assertEqual(expected[0], 'not in')
                        matches = matches and actual not in expected[1]
                    else:
                        matches = matches and actual == expected
                if matches:
                    return task.get(field)
            return None

        def get_all(doctype, filters, **kwargs):
            self.assertEqual(doctype, SCHEDULE)
            if (self.schedule.active and self.schedule.trigger_type in filters['trigger_type'][1]
                    and self.schedule.next_due_on <= filters['next_due_on'][1]):
                return [Row(name=self.schedule.name, next_due_on=self.schedule.next_due_on)]
            return []

        def exists(doctype, filters):
            if doctype == SCHEDULE:
                return filters == self.schedule.name
            self.assertEqual(doctype, 'Holiday')
            return filters['holiday_date'] in self.holidays

        def record(kind, **kwargs):
            key = kwargs.get('idempotency_key')
            if not key or not any(row.get('idempotency_key') == key for row in self.events):
                self.events.append(Row(event_type=kind, **kwargs))

        self.frappe = Row(get_doc=get_doc, get_all=get_all, throw=self.throw,
                          db=Row(get_value=get_value, exists=exists))
        self.ns = load('services/standalone_tasks.py', dict(
            frappe=self.frappe, now_datetime=lambda: self.now, get_datetime=date,
            add_to_date=add_to_date, record=record, occurrence_snapshot=lambda schedule: {},
            canonical_key=lambda *args: hashlib.sha256(json.dumps(args, default=str).encode()).hexdigest(),
            require_operator=lambda *args, **kwargs: (Row(employee='OP'), Row(name='SESSION')),
            assert_responsibility=lambda *args: None, can_view_service_task=lambda *args: True))
        model = load('cfg_kanban/doctype/cfg_kanban_task/cfg_kanban_task.py', dict(
            Document=object, frappe=self.frappe,
            skip_schedule_on_task_close=self.ns['skip_schedule_on_task_close']), classes=True)
        self.model = model['CFGKanbanTask']

    @staticmethod
    def throw(message):
        raise ValueError(message)

    def open_task(self, status='In Progress'):
        task = self.Doc(doctype=TASK, name='KTASK-1', task_schedule=self.schedule.name,
                        status=status, _new=False, _previous=Row(status=status))
        self.tasks[task.name] = task
        return task

    def create(self, **kwargs):
        return self.ns['create_from_schedule'](self.schedule.name, **kwargs)

    def test_skips_all_elapsed_slots_while_open_and_records_one_audit(self):
        task = self.open_task()
        self.assertEqual(self.ns['generate_due_tasks'](), [])
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(task.status, 'In Progress')
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
        self.assertEqual(self.schedule.last_generated_on, date('2026-11-28 09:00:00'))
        self.assertEqual(len(self.events), 1)
        event = self.events[0]
        self.assertEqual(event.event_type, 'Scheduled Task Skipped While Open')
        self.assertEqual(event.standalone_task, task.name)
        self.assertEqual(event.payload['skipped_count'], 2)
        self.assertEqual(event.payload['first_scheduled_for'], date('2026-11-28 10:00:00'))
        self.assertEqual(event.payload['last_scheduled_for'], date('2026-11-28 11:00:00'))
        self.assertEqual(self.locks[:2], [(SCHEDULE, 'KTS-1'), (TASK, 'open lookup')])

    def test_repeat_scheduler_and_stale_request_do_not_repeat_skip_or_create_task(self):
        self.open_task()
        stale = self.schedule.next_due_on
        self.create(scheduled_for=stale)
        before = copy.deepcopy((self.events, self.writes))
        self.assertIsNone(self.create(scheduled_for=stale))
        self.assertEqual(self.ns['generate_due_tasks'](), [])
        self.assertEqual((self.events, self.writes), before)
        self.assertEqual(len(self.tasks), 1)

    def test_locked_reload_sees_schedule_already_advanced_by_another_request(self):
        get_doc = self.frappe.get_doc
        first_read = True

        def race(doctype, name=None, **kwargs):
            nonlocal first_read
            if doctype == SCHEDULE and not kwargs.get('for_update') and first_read:
                first_read = False
                stale = self.Doc(self.schedule)
                self.schedule.next_due_on = date('2026-11-28 12:00:00')
                return stale
            return get_doc(doctype, name, **kwargs)

        self.frappe.get_doc = race
        self.assertIsNone(self.create(scheduled_for=date('2026-11-28 10:00:00')))
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
        self.assertEqual(self.tasks, {})
        self.assertEqual(self.events, [])

    def test_scheduler_defers_locked_closing_task_without_skip_or_new_occurrence(self):
        task = self.open_task()
        self.busy_tasks.add(task.name)
        self.assertIsNone(self.create())
        self.assertEqual(self.events, [])
        self.assertEqual(self.writes, [])
        self.assertEqual(len(self.tasks), 1)
        # The close hook can now acquire the Schedule after generation returns.
        task.status = 'Completed'
        task.save()
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
        self.assertEqual(len(self.events), 1)

    def test_manual_request_for_busy_task_requires_safe_retry(self):
        task = self.open_task()
        self.busy_tasks.add(task.name)
        with self.assertRaisesRegex(ValueError, 'Service Task is changing; retry this request'):
            self.ns['create_manual']('KTS-1', 'Manual Request', event_token='manual-1')
        self.assertEqual(self.events, [])
        self.assertEqual(self.writes, [])
        self.assertEqual(task.status, 'In Progress')

    def test_completion_between_scheduler_runs_skips_backlog_via_actual_task_hook(self):
        task = self.open_task()
        task.status = 'Completed'
        task.completed_by = 'OP'
        task.save()
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
        self.assertEqual(self.events[0].operator, 'OP')
        self.assertIsNone(self.create(scheduled_for=date('2026-11-28 10:00:00')))
        self.assertEqual(len(self.tasks), 1)
        self.now = date('2026-11-28 12:00:00')
        created = self.create()
        self.assertEqual(created.name, 'KTASK-2')
        self.assertEqual(created.status, 'Due')
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 13:00:00'))
        self.assertEqual([row.event_type for row in self.events],
                         ['Scheduled Task Skipped While Open', 'Standalone Task Created'])

    def test_final_verification_and_document_gate_closure_also_skip_backlog(self):
        for previous in ('Awaiting Verification', 'Pending Document Posting'):
            with self.subTest(previous=previous):
                self.setUp()
                task = self.open_task(previous)
                task.status = 'Completed'
                task.verified_by = 'SUP'
                task.save()
                self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
                self.assertEqual(self.events[0].operator, 'SUP')

    def test_pending_states_remain_open_and_do_not_reschedule_on_save(self):
        for status in ('Planned', 'Due', 'Assigned', 'In Progress', 'Awaiting Verification',
                       'Pending Document Posting', 'Correction Required', 'Overdue', 'Blocked', 'Escalated'):
            with self.subTest(status=status):
                self.setUp()
                task = self.open_task()
                task.status = status
                task.save()
                self.assertEqual(self.schedule.next_due_on, date('2026-11-28 10:00:00'))
                self.assertEqual(self.events, [])
                self.assertIsNone(self.create())
                self.assertEqual(len(self.tasks), 1)

    def test_cancellation_and_bypass_skip_backlog_and_resolve_only_next_due_task(self):
        for terminal in ('Cancelled', 'Bypassed'):
            with self.subTest(terminal=terminal):
                self.setUp()
                task = self.open_task()
                task.status, task.disposition_by = terminal, 'SUP'
                task.save()
                result = self.ns['resolve_service_point']('KTS-1', 'TOKEN')
                self.assertIsNone(result['task'])
                self.assertFalse(result['generated'])
                self.assertIn('12:00:00', result['message'])
                self.now = date('2026-11-28 12:00:00')
                result = self.ns['resolve_service_point']('KTS-1', 'TOKEN')
                self.assertEqual(result['task']['name'], 'KTASK-2')
                self.assertTrue(result['generated'])

    def test_terminal_resave_and_terminal_to_terminal_edit_do_not_skip_new_slots(self):
        task = self.open_task()
        task.status = 'Completed'
        task.save()
        before = copy.deepcopy(self.events)
        self.now = date('2026-11-28 13:20:00')
        task.save()
        task.status = 'Cancelled'
        task.save()
        self.assertEqual(self.events, before)
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))

    def test_close_before_next_due_does_not_reset_interval_from_completion_time(self):
        self.schedule.next_due_on = date('2026-11-28 12:00:00')
        task = self.open_task()
        task.status = 'Completed'
        task.save()
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 12:00:00'))
        self.assertEqual(self.events, [])

    def test_due_exactly_at_closure_is_skipped(self):
        self.now = self.schedule.next_due_on
        task = self.open_task()
        task.status = 'Completed'
        task.save()
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 11:00:00'))
        self.assertEqual(self.events[0].payload['skipped_count'], 1)

    def test_daily_weekly_fractional_and_calendar_recurrence_keep_cadence(self):
        cases = [
            ('Time Interval', 'Hours', 0.5, '2026-11-28 11:30:00', 3),
            ('Time Interval', 'Days', 1, '2026-11-29 10:00:00', 1),
            ('Time Interval', 'Weeks', 1, '2026-12-05 10:00:00', 1),
            ('Calendar Schedule', 'Days', 1, '2026-11-29 10:00:00', 1),
        ]
        for trigger, unit, value, expected, count in cases:
            with self.subTest(trigger=trigger, unit=unit, value=value):
                self.setUp()
                self.schedule.update(trigger_type=trigger, interval_unit=unit, interval_value=value)
                self.open_task()
                self.create()
                self.assertEqual(self.schedule.next_due_on, date(expected))
                self.assertEqual(self.events[0].payload['skipped_count'], count)

    def test_month_end_uses_repeated_native_recurrence_not_completion_date(self):
        self.schedule.update(interval_unit='Months', next_due_on=date('2026-01-31 10:00:00'))
        self.now = date('2026-03-01 11:20:00')
        self.open_task()
        self.create()
        self.assertEqual(self.schedule.next_due_on, date('2026-03-28 10:00:00'))
        self.assertEqual(self.events[0].payload['skipped_count'], 2)

    def test_short_intervals_and_long_backlog_are_counted_without_per_slot_loop(self):
        self.schedule.update(interval_value=1 / 3600, next_due_on=date('2026-11-27 11:20:00'))
        self.open_task()
        self.create()
        self.assertEqual(self.events[0].payload['skipped_count'], 86401)
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 11:20:01'))

    def test_non_advancing_interval_is_rejected_before_schedule_or_audit_change(self):
        self.schedule.interval_value = 1e-20
        self.open_task()
        with self.assertRaisesRegex(ValueError, 'interval must advance Next Due On'):
            self.create()
        self.assertEqual(self.writes, [])
        self.assertEqual(self.events, [])

    def test_prevent_policy_keeps_its_deferred_occurrence_behavior(self):
        self.schedule.overlap_policy = 'Prevent While Open'
        task = self.open_task()
        self.assertIs(self.create(), task)
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 10:00:00'))
        task.status = 'Completed'
        task.save()
        self.assertEqual(self.events, [])
        self.assertEqual(self.create().name, 'KTASK-2')

    def test_parallel_policy_still_generates_an_independent_occurrence(self):
        self.schedule.overlap_policy = 'Allow Parallel Occurrences'
        self.open_task()
        task = self.create()
        self.assertEqual(task.name, 'KTASK-2')
        self.assertEqual(task.status, 'Due')
        self.assertEqual([row.event_type for row in self.events], ['Standalone Task Created'])

    def test_manual_request_resolves_open_work_without_silently_skipping_it(self):
        task = self.open_task()
        self.assertIs(self.ns['create_manual']('KTS-1', 'Emergency Event', event_token='manual-1'), task)
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 10:00:00'))
        self.assertEqual(self.events, [])

    def test_non_recurring_schedule_does_not_advance_on_closure(self):
        self.schedule.trigger_type = 'Manual Request'
        task = self.open_task()
        task.status = 'Completed'
        task.save()
        self.assertEqual(self.events, [])
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 10:00:00'))

    def test_existing_holiday_skip_remains_a_separate_audit_without_new_task(self):
        self.schedule.update(holiday_policy='Skip Listed Holidays', holiday_list='HOLIDAYS')
        self.holidays.add(self.schedule.next_due_on.date())
        self.assertIsNone(self.create())
        self.assertEqual(self.tasks, {})
        self.assertEqual([row.event_type for row in self.events], ['Scheduled Task Skipped for Holiday'])

    def test_inactive_schedule_rejects_generation_and_does_not_reschedule_on_closure(self):
        self.schedule.active = 0
        task = self.open_task()
        task.status = 'Completed'
        task.save()
        with self.assertRaisesRegex(ValueError, 'Task Schedule is inactive'):
            self.create()
        self.assertEqual(self.events, [])
        self.assertEqual(self.schedule.next_due_on, date('2026-11-28 10:00:00'))

    def test_scan_loses_due_generation_race_safely(self):
        def another_request(*args, **kwargs):
            self.schedule.next_due_on = date('2026-11-28 12:00:00')
            return None
        self.ns['create_from_schedule'] = another_request
        result = self.ns['resolve_service_point']('KTS-1', 'TOKEN')
        self.assertFalse(result['generated'])
        self.assertIsNone(result['task'])
        self.assertIn('12:00:00', result['message'])


if __name__ == '__main__':
    unittest.main()

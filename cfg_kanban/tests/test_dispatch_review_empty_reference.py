"""Actual E5 finish/patch against a real nullable UNIQUE SQL column, offline.

SQLite reproduces empty-string/NULL uniqueness here. It is not MariaDB/Frappe
transaction, permissions or live-site acceptance. Native site tests stay pending.
"""
import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_dispatch_reconciliation as e5
from cfg_kanban.tests import test_dispatch_closure as closure
from cfg_kanban.tests.test_vehicle_overview import load

REVIEW = 'CFG Kanban Dispatch Review'
PATCH = 'patches/v1_11/normalize_dispatch_review_movement_reference.py'
ROOT = Path(__file__).resolve().parents[1]


class UniqueReviewSQL:
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.statements = []
        self.connection.execute('''create table `tabCFG Kanban Dispatch Review` (
            name text primary key, movement_stock_entry text unique,
            state text, modified text, closed_on text, reason text,
            closing_snapshot_json text, finish_key text, finish_payload_hash text)''')

    def insert(self, name, movement=None, state='Reviewing'):
        self.connection.execute('''insert into `tabCFG Kanban Dispatch Review`
            values (?,?,?,'original-modified','original-closed','original reason',
                    '{"immutable":true}','original-key','original-hash')''', (name, movement, state))

    def sql(self, query, values=()):
        self.statements.append(query)
        return self.connection.execute(query, values).fetchall()

    def movement(self, name):
        return self.connection.execute('select movement_stock_entry from `tabCFG Kanban Dispatch Review` where name=?', (name,)).fetchone()[0]

    def snapshot(self):
        return self.connection.execute('select * from `tabCFG Kanban Dispatch Review` order by name').fetchall()

    def intercept(self, cls):
        """Keep the real service's db_set value unchanged on its way to SQL."""
        actual = cls.db_set
        database = self
        def db_set(doc, key, value=None, **kwargs):
            values = key if isinstance(key, dict) else {key: value}
            if doc.doctype == REVIEW and 'movement_stock_entry' in values:
                database.connection.execute('''update `tabCFG Kanban Dispatch Review`
                    set movement_stock_entry=? where name=?''', (values['movement_stock_entry'], doc.name))
            return actual(doc, key, value, **kwargs)
        return patch.object(cls, 'db_set', db_set)


class TestReviewEmptyReference(unittest.TestCase):
    def setUp(self):
        self.db = UniqueReviewSQL()
        self.addCleanup(self.db.connection.close)

    def fixture(self):
        subject = e5.TestDispatchReconciliation(); subject.setUp()
        self.addCleanup(subject.doCleanups)
        return subject

    def test_database_reproduces_reported_blank_collision_but_allows_multiple_nulls(self):
        self.db.insert('OLD', '')
        with self.assertRaises(sqlite3.IntegrityError): self.db.insert('DUPLICATE', '')
        self.db.insert('ONE', None); self.db.insert('TWO', None)
        self.assertIsNone(self.db.movement('ONE')); self.assertIsNone(self.db.movement('TWO'))

    def test_manual_fully_delivered_reconciliation_with_http_blank_ignores_legacy_blank_slot(self):
        subject = self.fixture(); subject.deliver(5); subject.begin(); subject.count()
        review = subject.review()
        self.db.insert('LEGACY-COMPLETED', '', 'Completed'); self.db.insert(review.name)
        before = (subject.unit.current_qty, subject.unit.reserved_qty, subject.b.erp_balance, len(subject.b.posted))
        with self.db.intercept(type(review)):
            subject.finish('No Remaining Prepared Stock', movement='')
            subject.finish('No Remaining Prepared Stock', movement='')
        self.assertIsNone(self.db.movement(review.name))
        self.assertEqual(self.db.movement('LEGACY-COMPLETED'), '')
        self.assertEqual((subject.plan.state, subject.plan.dispatch_review_state), ('Reconciled', 'Settled'))
        self.assertEqual(before, (subject.unit.current_qty, subject.unit.reserved_qty, subject.b.erp_balance, len(subject.b.posted)))

    def test_stock_stays_and_overnight_also_write_null_for_empty_form_value(self):
        for index, action in enumerate(('Close Trip - Stock Stays', 'Continue Same Plan Overnight')):
            with self.subTest(action=action):
                subject = self.fixture(); subject.supervisor(); subject.begin(); subject.count()
                review = subject.review()
                # The two stores have independent demo names; the unique SQL guard is shared.
                self.db.connection.execute('delete from `tabCFG Kanban Dispatch Review`')
                self.db.insert('LEGACY', ''); self.db.insert(review.name)
                before = (subject.unit.current_qty, subject.unit.reserved_qty, len(subject.b.posted))
                with self.db.intercept(type(review)):
                    subject.finish(action, movement=' ' if index else '')
                self.assertIsNone(self.db.movement(review.name))
                self.assertEqual(before, (subject.unit.current_qty, subject.unit.reserved_qty, len(subject.b.posted)))
                self.assertEqual(subject.review().state, 'Overnight' if index else 'Completed')

    def test_real_movement_reference_is_preserved_and_cannot_be_reused(self):
        subject = self.fixture(); subject.supervisor(); subject.begin(); subject.move(); subject.count()
        review = subject.review(); self.db.insert('LEGACY', ''); self.db.insert(review.name)
        with self.db.intercept(type(review)):
            subject.finish('Returned to Warehouse', movement='MOVE')
        self.assertEqual(self.db.movement(review.name), 'MOVE')
        with self.assertRaises(sqlite3.IntegrityError): self.db.insert('OTHER-PLAN', 'MOVE')

    def test_document_backed_route_can_settle_multiple_reviews_with_one_legacy_blank(self):
        subject = closure.TestDocumentClosure(); subject.setUp(); self.addCleanup(subject.doCleanups)
        subject.route(); self.db.insert('LEGACY', '')
        for name in ('P1', 'P2'):
            review = subject.review(subject.data[closure.PLAN][name]); self.db.insert(review.name)
        before = subject.snapshot_stock()
        with self.db.intercept(type(subject.data[REVIEW]['REVIEW-P1'])):
            result = subject.close_route()
        self.assertEqual(result['sheet']['state'], 'Completed')
        self.assertIsNone(self.db.movement('REVIEW-P1')); self.assertIsNone(self.db.movement('REVIEW-P2'))
        self.assertEqual(before, subject.snapshot_stock()); self.assertFalse(subject.prohibited)

    def repair(self):
        clear = Mock()
        namespace = load(PATCH, dict(frappe=SimpleNamespace(db=SimpleNamespace(
            sql=self.db.sql, table_exists=lambda name: name == REVIEW), clear_document_cache=clear)))
        return namespace['execute'](), clear

    def test_patch_repairs_only_blank_references_preserving_names_timestamps_and_final_audits(self):
        self.db.insert('BLANK', '', 'Completed'); self.db.insert('SPACES', '   ', 'Resumed')
        self.db.insert('ABSENT'); self.db.insert('REAL', 'STE-EXISTING', 'Completed')
        before = {row[0]: row for row in self.db.snapshot()}
        result, clear = self.repair()
        self.assertEqual(result, {'normalized_empty_references': 2})
        after = {row[0]: row for row in self.db.snapshot()}
        for name in before:
            self.assertEqual(before[name][2:], after[name][2:])
            self.assertEqual(after[name][1], None if name in ('BLANK', 'SPACES') else before[name][1])
        self.assertEqual({call.args for call in clear.call_args_list}, {(REVIEW, 'BLANK'), (REVIEW, 'SPACES')})
        self.assertTrue(all('tabCFG Kanban Dispatch Review' in sql for sql in self.db.statements))
        result, clear = self.repair()
        self.assertEqual(result, {'normalized_empty_references': 0}); clear.assert_not_called()
        with self.assertRaises(sqlite3.IntegrityError): self.db.insert('REUSE', 'STE-EXISTING')

    def test_fresh_install_without_review_table_has_nothing_to_repair(self):
        db = SimpleNamespace(table_exists=lambda name: False, sql=Mock())
        clear = Mock()
        namespace = load(PATCH, dict(frappe=SimpleNamespace(db=db, clear_document_cache=clear)))
        self.assertEqual(namespace['execute'](), {'normalized_empty_references': 0})
        db.sql.assert_not_called(); clear.assert_not_called()

    def test_patch_runs_after_model_sync_and_actual_reference_keeps_unique_constraint(self):
        patches = (ROOT / 'patches.txt').read_text()
        self.assertIn('cfg_kanban.patches.v1_11.normalize_dispatch_review_movement_reference', patches.split('[post_model_sync]')[1])
        schema = json.loads((ROOT / 'cfg_kanban/doctype/cfg_kanban_dispatch_review/cfg_kanban_dispatch_review.json').read_text())
        field = next(row for row in schema['fields'] if row['fieldname'] == 'movement_stock_entry')
        self.assertEqual(field.get('unique'), 1); self.assertFalse(field.get('reqd'))

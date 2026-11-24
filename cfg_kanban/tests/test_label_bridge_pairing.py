"""Pairing endpoint with real P-256 validation and explicit Frappe/DB/Redis doubles.

No native site, real sessions, Redis, MariaDB transactions or companion is exercised.
"""
import base64
import datetime
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ModuleNotFoundError:
    serialization = ec = None

from cfg_kanban.tests.test_vehicle_overview import Row

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(ec, 'cryptography is supplied by the Frappe runtime; real P-256 validation not run')
class TestLabelBridgePairing(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 11, 24, 12)
        self.rows, self.writes, self.sql_calls, self.permissions, self.doc_reads = {}, [], [], [], []
        self.counts = {}
        self.public_key = base64.b64encode(ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode()
        self.frappe = types.ModuleType('frappe')
        self.frappe.session = Row(user='stock@example.com', sid='COOKIE-SESSION-1')
        self.frappe.local = Row(request_ip='192.0.2.10')
        self.frappe.PermissionError = PermissionError
        self.frappe.RateLimitExceededError = RuntimeError
        self.frappe.throw = lambda message, exception=ValueError:(_ for _ in ()).throw(exception(message))
        self.whitelist = []
        def whitelist(**kwargs):
            self.whitelist.append(kwargs)
            return lambda fn:fn
        self.frappe.whitelist = whitelist
        self.frappe.get_doc = self.get_doc
        self.frappe.cache = Row(make_key=lambda key:('SITE|' + key).encode(), eval=self.rate)
        self.frappe.db = Row(get_value=self.get_value, sql=self.sql, set_value=self.set_value)
        utils = types.ModuleType('frappe.utils')
        utils.now_datetime = lambda:self.now
        utils.get_datetime = lambda value:value
        spec = importlib.util.spec_from_file_location('pairing_subject', ROOT/'services/label_bridge_pairing.py')
        self.service = importlib.util.module_from_spec(spec)
        patcher = patch.dict(sys.modules, {'frappe':self.frappe, 'frappe.utils':utils})
        patcher.start(); self.addCleanup(patcher.stop)
        spec.loader.exec_module(self.service)

    def rate(self, script, number, key, seconds):
        self.assertEqual(number, 1)
        self.assertIn("redis.call('INCR'", script)
        self.assertIn("redis.call('EXPIRE'", script)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def get_doc(self, doctype, name=None, **kwargs):
        if isinstance(doctype, dict):
            doc = Row(doctype, flags=Row())
            doc.is_new = lambda:doc.name not in self.rows
            def insert(**kwargs):
                self.assertEqual(kwargs['ignore_permissions'], True)
                self.service.controlled_registration(doc)
                doc.name = kwargs['set_name']; self.rows[doc.name] = doc
                return doc
            doc.insert = insert
            return doc
        if doctype == self.service.REGISTRY:
            self.doc_reads.append((doctype, name, kwargs))
            return self.rows[name]
        doc = types.SimpleNamespace(doctype=doctype, name=name)
        def check(kind):
            self.permissions.append((doctype, name, kind))
            if getattr(self, 'denied', None) == kind:
                raise PermissionError('Native ' + kind + ' denied')
        doc.check_permission = check
        return doc

    def get_value(self, doctype, filters, field):
        self.assertEqual(doctype, self.service.REGISTRY)
        return next((name for name,row in self.rows.items() if all(row.get(k) == v for k,v in filters.items())), None)

    def sql(self, query, values, **kwargs):
        self.sql_calls.append((query, values))
        self.assertIn('FOR UPDATE', query)
        field = 'ticket_hash' if '`ticket_hash`' in query else 'name'
        return [Row(name=name) for name,row in self.rows.items() if row.get(field) == values[0]]

    def set_value(self, doctype, name, values):
        self.writes.append((doctype, name, dict(values)))
        self.rows[name].update(values)

    def create(self, **values):
        return self.service.pairing('create', publicKey=values.get('publicKey', self.public_key),
            document_type='Delivery Note', document_name='DN-ALLOWED')

    def guest(self):
        self.frappe.session = Row(user='Guest', sid='Guest')

    def browser(self, user='stock@example.com', sid='COOKIE-SESSION-1'):
        self.frappe.session = Row(user=user, sid=sid)

    def test_native_endpoint_is_post_only_and_authenticates_browser_actions_explicitly(self):
        self.assertEqual(self.whitelist, [{'allow_guest':True, 'methods':['POST']}])
        self.guest()
        for action in ('create', 'status', 'revoke'):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                self.service.pairing(action, publicKey=self.public_key, kid='a'*32)
        self.assertFalse(self.rows)

    def test_creation_uses_random_ids_leading_zero_code_and_only_hashed_ticket_session(self):
        with patch.object(self.service.secrets, 'randbelow', return_value=12):
            answer = self.create()
        self.assertRegex(answer['ticket'], r'^[0-9a-f]{64}$')
        self.assertRegex(answer['kid'], r'^[0-9a-f]{32}$')
        self.assertEqual(answer['code'], '000012')
        doc = self.rows[answer['kid']]
        self.assertEqual(doc.public_key, self.public_key)
        self.assertEqual(doc.expires_on - self.now, datetime.timedelta(seconds=120))
        self.assertEqual(doc.ticket_hash, hashlib.sha256(answer['ticket'].encode()).hexdigest())
        self.assertNotEqual(doc.session_hash, self.frappe.session.sid)
        self.assertNotIn(answer['ticket'], repr(doc))
        self.assertNotIn('private_key', doc)
        self.assertEqual([row[2] for row in self.permissions], ['read', 'print'])

    def test_guest_device_preview_returns_only_the_native_contract(self):
        answer = self.create(); self.permissions.clear(); self.guest()
        preview = self.service.pairing('preview', ticket=answer['ticket'])
        self.assertEqual(preview, {'kid':answer['kid'], 'publicKey':self.public_key, 'code':answer['code']})
        self.assertLess(len(json.dumps({'message':preview})), 8192)
        self.assertFalse(self.permissions)
        self.assertFalse(self.writes)

    def test_approval_locks_ticket_and_identical_retry_preserves_one_approval_time(self):
        answer = self.create(); self.guest()
        first = self.service.pairing('approve', ticket=answer['ticket'])
        self.now += datetime.timedelta(seconds=10)
        self.assertEqual(self.service.pairing('approve', ticket=answer['ticket']), first)
        self.assertEqual(first, {'kid':answer['kid'], 'status':'approved'})
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(len(self.sql_calls), 2)
        self.assertTrue(all(row[2].get('for_update') for row in self.doc_reads))
        self.assertNotIn(answer['ticket'], repr(self.sql_calls))

    def test_unknown_expired_and_revoked_tickets_never_expose_public_key_or_code(self):
        answer = self.create(); self.guest()
        for ticket in ('B'*64, 'a'*63, '0'*64):
            with self.subTest(ticket_type=len(ticket)), self.assertRaisesRegex(PermissionError, 'unavailable'):
                self.service.pairing('preview', ticket=ticket)
        self.now += datetime.timedelta(seconds=120)
        for action in ('preview', 'approve'):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                self.service.pairing(action, ticket=answer['ticket'])
        self.assertFalse(self.writes)
        self.now -= datetime.timedelta(seconds=120)
        self.browser(); self.service.pairing('revoke', kid=answer['kid']); self.guest()
        for action in ('preview', 'approve'):
            with self.assertRaises(PermissionError):self.service.pairing(action, ticket=answer['ticket'])

    def test_status_and_revoke_require_initiating_user_and_exact_cookie_session(self):
        answer = self.create()
        for user,sid in [('someone@example.com','COOKIE-SESSION-1'),('stock@example.com','DIFFERENT'),('stock@example.com','Guest')]:
            self.browser(user,sid)
            for action in ('status','revoke'):
                with self.subTest(user=user, action=action), self.assertRaises(PermissionError):
                    self.service.pairing(action, kid=answer['kid'])
        self.assertFalse(self.writes)

    def test_native_read_and_print_denial_block_creation_and_status(self):
        for kind in ('read', 'print'):
            self.denied = kind
            with self.subTest(kind=kind), self.assertRaises(PermissionError):self.create()
        self.assertFalse(self.rows)
        self.denied = None; answer = self.create(); self.denied = 'print'
        with self.assertRaises(PermissionError):self.service.pairing('status', kid=answer['kid'])

    def test_status_reports_pending_expired_approved_and_revoked_without_ticket(self):
        answer = self.create()
        self.assertEqual(self.service.pairing('status', kid=answer['kid'])['status'], 'pending')
        self.now += datetime.timedelta(seconds=121)
        self.assertEqual(self.service.pairing('status', kid=answer['kid'])['status'], 'expired')
        self.now -= datetime.timedelta(seconds=121); self.service.pairing('approve', ticket=answer['ticket'])
        self.now += datetime.timedelta(days=1)
        self.assertEqual(self.service.pairing('status', kid=answer['kid'])['status'], 'approved')
        self.service.pairing('revoke', kid=answer['kid'])
        count = len(self.writes); self.service.pairing('revoke', kid=answer['kid'])
        self.assertEqual(len(self.writes), count)
        self.assertEqual(self.service.pairing('status', kid=answer['kid'])['status'], 'revoked')

    def test_invalid_or_off_curve_public_keys_are_rejected(self):
        invalid = ['x', '0'*88, base64.b64encode(b'\x04'+bytes(64)).decode(),
            base64.b64encode(b'\x02'+bytes(64)).decode(), self.public_key[:-1]+'!']
        for value in invalid:
            with self.subTest(length=len(value)), self.assertRaises(ValueError):self.create(publicKey=value)
        self.assertFalse(self.rows)

    def test_create_and_guest_rate_limits_use_atomic_site_scoped_buckets_without_bearers(self):
        for _ in range(6):self.create()
        with self.assertRaises(RuntimeError):self.create()
        self.guest()
        for _ in range(90):
            with self.assertRaises(PermissionError):self.service.pairing('preview', ticket='0'*64)
        with self.assertRaises(RuntimeError):self.service.pairing('preview', ticket='0'*64)
        self.assertTrue(all(key.startswith(b'SITE|cfg_print_pair:') for key in self.counts))
        self.assertNotIn('COOKIE-SESSION-1', repr(self.counts))

    def test_registration_metadata_has_no_guest_or_driver_writes_or_hidden_mandatory_keys(self):
        path = ROOT/'cfg_kanban/doctype/cfg_kanban_print_browser/cfg_kanban_print_browser.json'
        schema = json.loads(path.read_text())
        self.assertEqual(schema['permissions'], [{'role':'System Manager','read':1}])
        self.assertFalse(any(field.get('hidden') and field.get('reqd') and not field.get('default') for field in schema['fields']))
        self.assertFalse(any(field.get('options') in ('Employee','Company') for field in schema['fields']))
        with self.assertRaises(ValueError):self.service.controlled_registration(Row(flags=Row()))
        with self.assertRaises(ValueError):self.service.no_delete()

    def test_existing_registration_identity_cannot_be_edited_even_with_control_flag(self):
        answer = self.create()
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.service.controlled_registration(self.rows[answer['kid']])


if __name__ == '__main__':
    unittest.main()

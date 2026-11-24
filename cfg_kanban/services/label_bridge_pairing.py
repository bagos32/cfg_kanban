"""Label Bridge v2 approval; no private key, receipt images or ERP credentials.

The device uses only the short-lived ticket. Authenticated actions independently
require the initiating ERP session and native read/print permission.
"""
import base64
import binascii
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import frappe
from cryptography.hazmat.primitives.asymmetric import ec
from frappe.utils import get_datetime, now_datetime

REGISTRY = 'CFG Kanban Print Browser'
LIFETIME = 120
_RATE_SCRIPT = """local n=redis.call('INCR',KEYS[1]);
if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"""


def controlled_registration(doc, method=None):
    if not doc.flags.get('cfg_print_pairing'):
        frappe.throw('Use the Label Bridge pairing controls to manage browser approvals')
    if not doc.is_new():
        frappe.throw('Browser approval identities are immutable; use the pairing controls')
    if doc.public_key != _public_key(doc.public_key):
        frappe.throw('Invalid browser public key')


def no_delete(doc=None, method=None):
    frappe.throw('Revoke the browser approval instead of deleting its history')


def _deny():
    frappe.throw('Pairing request unavailable. Start again from ERPNext.', frappe.PermissionError)


def _hex(value, length):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value):
        _deny()
    return value


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _limit(action, identity):
    limit, seconds = (6, 120) if action == 'create' else (90, 60)
    key = frappe.cache.make_key('cfg_print_pair:' + action + ':' + _digest(identity))
    if int(frappe.cache.eval(_RATE_SCRIPT, 1, key, seconds)) > limit:
        frappe.throw('Too many pairing requests. Wait a minute and start again.', frappe.RateLimitExceededError)


def _browser():
    user, sid = frappe.session.user, frappe.session.sid
    if not user or user == 'Guest' or not sid or sid == 'Guest':
        _deny()
    return user, _digest(sid)


def _public_key(value):
    if not isinstance(value, str) or len(value) != 88:
        frappe.throw('Pairing requires a P-256 browser public key')
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 65 or raw[0] != 4 or base64.b64encode(raw).decode('ascii') != value:
            raise ValueError()
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except (ValueError, binascii.Error):
        frappe.throw('Pairing requires a valid uncompressed P-256 public key')
    return value


def _authorize(doctype, name):
    if (not isinstance(doctype, str) or not 1 <= len(doctype) <= 140
            or not isinstance(name, str) or not 1 <= len(name) <= 140):
        frappe.throw('Choose an authorized printable document before pairing')
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    doc.check_permission('print')
    return doc


def _registration(value, by_ticket=False, lock=False):
    field = 'ticket_hash' if by_ticket else 'name'
    if lock:
        rows = frappe.db.sql('SELECT name FROM `tabCFG Kanban Print Browser` WHERE `'
            + field + '`=%s FOR UPDATE', (value,), as_dict=True)
        name = rows[0].name if rows else None
    else:
        name = frappe.db.get_value(REGISTRY, {field:value}, 'name')
    if not name:
        _deny()
    return frappe.get_doc(REGISTRY, name, **({'for_update':True} if lock else {}))


def _owned(doc, user, session_hash):
    if doc.initiating_user != user or not hmac.compare_digest(doc.session_hash or '', session_hash):
        _deny()


def _ticket_request(ticket, lock=False):
    _hex(ticket, 64)
    doc = _registration(_digest(ticket), by_ticket=True, lock=lock)
    if doc.status not in ('Pending', 'Approved') or get_datetime(doc.expires_on) <= now_datetime():
        _deny()
    return doc


@frappe.whitelist(allow_guest=True, methods=['POST'])
def pairing(action, publicKey=None, ticket=None, kid=None, document_type=None, document_name=None):
    """Guest preview/approve are ticket-only; no guest ERP document access."""
    if action in ('preview', 'approve'):
        _limit(action, frappe.local.request_ip or 'unknown')
        doc = _ticket_request(ticket, lock=action == 'approve')
        if action == 'preview':
            return {'kid':doc.name, 'publicKey':doc.public_key, 'code':doc.verification_code}
        if doc.status == 'Pending':
            frappe.db.set_value(REGISTRY, doc.name, {'status':'Approved', 'approved_on':now_datetime()})
        return {'kid':doc.name, 'status':'approved'}

    if action not in ('create', 'status', 'revoke'):
        _deny()
    user, session_hash = _browser()
    _limit(action, user + ':' + session_hash)
    if action == 'create':
        _authorize(document_type, document_name)
        public_key = _public_key(publicKey)
        bearer, key_id = secrets.token_hex(32), secrets.token_hex(16)
        code, created = str(secrets.randbelow(1000000)).zfill(6), now_datetime()
        doc = frappe.get_doc({'doctype':REGISTRY, 'initiating_user':user,
            'session_hash':session_hash, 'ticket_hash':_digest(bearer), 'public_key':public_key,
            'verification_code':code, 'status':'Pending', 'created_on':created,
            'expires_on':created + timedelta(seconds=LIFETIME),
            'document_type':document_type, 'document_name':document_name})
        doc.flags.cfg_print_pairing = True
        doc.insert(ignore_permissions=True, set_name=key_id)
        return {'ticket':bearer, 'kid':key_id, 'code':code, 'expiresIn':LIFETIME, 'status':'pending'}

    doc = _registration(_hex(kid, 32), lock=action == 'revoke')
    _owned(doc, user, session_hash)
    _authorize(document_type or doc.document_type, document_name or doc.document_name)
    if action == 'revoke':
        if doc.status != 'Revoked':
            frappe.db.set_value(REGISTRY, doc.name, {'status':'Revoked', 'revoked_on':now_datetime()})
        return {'kid':doc.name, 'status':'revoked'}
    status = doc.status.lower()
    if doc.status == 'Pending' and get_datetime(doc.expires_on) <= now_datetime():
        status = 'expired'
    return {'kid':doc.name, 'status':status}

import hashlib
import json

import frappe


def canonical_key(namespace: str, *parts) -> str:
    raw = json.dumps([namespace, *parts], separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_existing(doctype: str, key: str):
    name = frappe.db.get_value(doctype, {"idempotency_key": key}, "name")
    return frappe.get_doc(doctype, name) if name else None


def insert_once(doc, key: str):
    """Database unique fields are the final guard when concurrent workers race."""
    existing = get_existing(doc.doctype, key)
    if existing:
        return existing, False
    doc.idempotency_key = key
    try:
        doc.insert()
        return doc, True
    except frappe.UniqueValidationError:
        return get_existing(doc.doctype, key), False


"""Stable private-media references for controlled DocType Action Runs.

The S3 object and its lifecycle remain owned by ``CFG Kanban Media`` and the
source Service Task.  An Action Run stores only a safe, immutable snapshot of
the available media registry identities used when the target was posted.  It
never stores a presigned URL or copies the binary into the destination DocType.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from cfg_kanban.services import media


def evidence_for_operator_form(run, source):
    """Return persisted evidence, or evidence available to this exact source."""
    if run.get("evidence_snapshot_on"):
        return persisted_evidence(run)
    return _source_evidence(run, source)


def snapshot_task_evidence(run, source):
    """Pin available source evidence; direct Cards start with an empty stable set."""
    references = _source_evidence(run, source)
    serialized = json.dumps(
        references, sort_keys=True, separators=(",", ":"), default=str
    )
    values = {
        "evidence_reference_count": len(references),
        "evidence_references": serialized,
        "evidence_snapshot_on": now_datetime(),
    }
    frappe.db.set_value(run.doctype, run.name, values, update_modified=False)
    run.update(values)
    return references


def persisted_evidence(run):
    if not run.get("evidence_references"):
        return []
    try:
        rows = json.loads(run.evidence_references)
    except (TypeError, ValueError):
        frappe.throw(_(
            "Stored Action Run evidence references are unreadable; "
            "supervised reconciliation is required."
        ))
    if not isinstance(rows, list) or len(rows) != cint(run.evidence_reference_count):
        frappe.throw(_(
            "Stored Action Run evidence references failed their integrity check; "
            "supervised reconciliation is required."
        ))
    return rows


def _source_evidence(run, source):
    if source.name != run.source_name or source.doctype != run.source_doctype:
        frappe.throw(_("Action evidence must belong to the Action Run source."))
    # A reusable Card is an identity, not an evidence occurrence. Direct-card
    # upload will be bound to the immutable Action Run in a later media package;
    # never inherit files from the reusable physical Card across occurrences.
    if run.source_doctype == "CFG Kanban Card":
        return []
    if run.source_doctype != "CFG Kanban Task":
        frappe.throw(_("Unsupported Action Run evidence source."))
    task = source
    if task.name != run.source_name:
        frappe.throw(_("Action evidence must belong to the source Service Task."))
    rows = media.list_reference_media(
        "CFG Kanban Task", task.name, permission_checked=True
    )
    output = []
    for row in rows:
        if row.get("status") != "available" or row.get("media_class") != "maintenance-evidence":
            continue
        output.append({
            "media_id": row.get("media_id"),
            "media_class": row.get("media_class"),
            "original_filename": row.get("original_filename"),
            "content_type": row.get("content_type"),
            "size_bytes": cint(row.get("size_bytes")),
            "operator_employee": row.get("operator_employee"),
            "created_at": str(row.get("created_at") or ""),
            "confirmed_at": str(row.get("confirmed_at") or ""),
            "capture_source": row.get("capture_source"),
            "capture_timestamp": row.get("capture_timestamp"),
            "geotag": row.get("geotag"),
            "evidence_kind": row.get("evidence_kind"),
        })
    output.sort(key=lambda row: (row.get("confirmed_at") or "", row["media_id"]))
    return output

"""Stable private-media references for controlled DocType Action Runs.

The S3 object and its lifecycle remain owned by ``CFG Kanban Media``. Service
Task actions reuse evidence owned by their exact Task occurrence. Direct-card
actions own evidence on their immutable Action Run, never on the reusable Card.
The Run stores only a safe snapshot of available registry identities used when
the target was posted; it never stores a presigned URL or binary.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from cfg_kanban.services import media


ACTION_MEDIA_CLASS = "doctype-action-evidence"
ACTION_RUN_DOCTYPE = "CFG Kanban DocType Action Run"
MUTABLE_EVIDENCE_STATES = {"Form In Progress", "Ready to Post", "Failed"}


def action_evidence_controls(run):
    """Describe the evidence mode without granting any additional authority.

    Service Task actions continue to use the Task occurrence's evidence. Direct
    reusable cards receive a fresh evidence area for every immutable Action Run.
    Actual read/write authority is rechecked by every media API call.
    """
    direct_run = run.source_doctype == "CFG Kanban Card"
    locked = bool(run.get("evidence_snapshot_on")) or (
        direct_run and run.state not in MUTABLE_EVIDENCE_STATES
    )
    return {
        "mode": "action-run" if direct_run else "source-task",
        "can_upload": bool(direct_run and not locked),
        "can_archive": bool(direct_run and not locked),
        "camera_capture": bool(direct_run and not locked),
        "locked": bool(locked),
    }


def evidence_for_operator_form(run, source):
    """Return persisted evidence, or evidence available to this exact source."""
    if run.get("evidence_snapshot_on"):
        return persisted_evidence(run)
    if run.source_doctype == "CFG Kanban Card":
        if source.name != run.source_name or source.doctype != run.source_doctype:
            frappe.throw(_("Action evidence must belong to the Action Run source."))
        return action_run_uploads(run)
    return _source_evidence(run, source)


def action_run_uploads(run):
    """Safe upload-state rows used to recover interrupted direct-card uploads."""
    rows = media.list_reference_media(
        ACTION_RUN_DOCTYPE,
        run.name,
        permission_checked=True,
        statuses=("pending", "available", "quarantined", "failed"),
    )
    return [row for row in rows if row.get("media_class") == ACTION_MEDIA_CLASS]


def snapshot_action_evidence(run, source):
    """Freeze the exact available evidence set used by this posting attempt."""
    if run.get("evidence_snapshot_on"):
        return persisted_evidence(run)
    if run.source_doctype == "CFG Kanban Card":
        _assert_no_pending_action_media(run)
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


# Backwards-compatible name retained for callers outside the Action writer.
snapshot_task_evidence = snapshot_action_evidence


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
    # A reusable Card is an identity, not an evidence occurrence. Direct media
    # belongs to this immutable Run so files never leak into another scan/run.
    if run.source_doctype == "CFG Kanban Card":
        return _action_run_evidence(run)
    if run.source_doctype != "CFG Kanban Task":
        frappe.throw(_("Unsupported Action Run evidence source."))
    task = source
    if task.name != run.source_name:
        frappe.throw(_("Action evidence must belong to the source Service Task."))
    rows = media.list_reference_media(
        "CFG Kanban Task", task.name, permission_checked=True
    )
    return _safe_references(rows, expected_class="maintenance-evidence")


def _action_run_evidence(run):
    rows = media.list_reference_media(
        ACTION_RUN_DOCTYPE, run.name, permission_checked=True
    )
    return _safe_references(rows, expected_class=ACTION_MEDIA_CLASS)


def _safe_references(rows, expected_class):
    output = []
    for row in rows:
        if row.get("status") != "available" or row.get("media_class") != expected_class:
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


def _assert_no_pending_action_media(run):
    pending = frappe.get_all(
        "CFG Kanban Media",
        filters={
            "reference_doctype": ACTION_RUN_DOCTYPE,
            "reference_name": run.name,
            "media_class": ACTION_MEDIA_CLASS,
            "status": "pending",
        },
        pluck="media_id",
        limit_page_length=1,
    )
    if pending:
        frappe.throw(_(
            "An Action Run evidence upload is still pending confirmation. "
            "Wait for the upload to finish or remove it before saving the document."
        ))

"""Idempotent, non-posting runtime foundation for DocType Actions.

Gate 1B intentionally stops before constructing or saving a destination ERPNext
document.  It establishes the durable Action Run identity, pinned configuration,
operator/terminal attribution, immutable attempts and controlled recovery states
that the later writer and Service Task integration must reuse.
"""

import hashlib
import json
import re
import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from cfg_kanban.services.doctype_actions import (
    executable_profile_snapshot,
    get_target_policy,
    metadata_fingerprint,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, get_existing, insert_once
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.task_access import (
    can_view_service_task,
    supervisor_assistance_scope_allowed,
    workstation_allowed,
)


ACTION_RUN_STATES = {
    "Form In Progress",
    "Ready to Post",
    "Posting",
    "Draft Created",
    "Submitted",
    "Failed",
    "Skipped by Condition",
    "Needs Reconciliation",
    "Cancelled",
}
TERMINAL_STATES = {"Submitted", "Skipped by Condition", "Cancelled"}
SOURCE_EVENTS = {
    "Activation",
    "Task Start",
    "Task Complete",
    "Supervisor Verification",
}
ALLOWED_TRANSITIONS = {
    "Form In Progress": {
        "Ready to Post", "Failed", "Skipped by Condition",
        "Needs Reconciliation", "Cancelled",
    },
    "Ready to Post": {
        "Form In Progress", "Posting", "Failed", "Skipped by Condition",
        "Needs Reconciliation", "Cancelled",
    },
    "Posting": {"Draft Created", "Submitted", "Failed", "Needs Reconciliation"},
    "Draft Created": {"Submitted", "Failed", "Needs Reconciliation"},
    "Submitted": {"Needs Reconciliation"},
    "Failed": {
        "Form In Progress", "Ready to Post", "Posting",
        "Needs Reconciliation", "Cancelled",
    },
    # Normally terminal. A post-write failure to release a required source-task
    # gate is the one controlled reason it may enter supervised reconciliation.
    "Skipped by Condition": {"Needs Reconciliation"},
    "Needs Reconciliation": {"Form In Progress", "Ready to Post", "Failed"},
    "Cancelled": set(),
}

_SOURCE_ACTION = {
    "Activation": "task_start",
    "Task Start": "task_start",
    "Task Complete": "task_complete",
    "Supervisor Verification": "task_verify",
}
_SENSITIVE_VALUE = re.compile(
    r"(?i)(token|secret|password|passwd|authorization|api[_ -]?key)"
    r"[\"']?\s*[:=]\s*[\"']?[^\"'\s,;}&]+"
)
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def resolve_task_run(task_name, profile_name, source_event, operator_session_token,
                     retry_token, action_slot="primary"):
    """Create or resume the one Phase-1 primary run for a Service Task.

    This method records intent only.  It does not build, insert, save or submit a
    target document.
    """
    if source_event not in SOURCE_EVENTS:
        frappe.throw(_("Unsupported DocType Action source event: {0}").format(source_event))
    if action_slot != "primary":
        frappe.throw(_("Phase 1 Service Tasks support only the primary action slot."))
    _require_retry_token(retry_token)

    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(
        operator_session_token,
        _SOURCE_ACTION[source_event],
        workstation=task.workstation,
    )
    _assert_task_access(task, profile)

    run_key = canonical_key(
        "doctype-action-run-v1", task.doctype, task.name, profile_name, action_slot
    )
    prior_attempt = _attempt_for_retry_token(retry_token)
    if prior_attempt:
        run = frappe.get_doc("CFG Kanban DocType Action Run", prior_attempt.action_run)
        _assert_expected_run(
            run, run_key, task, profile_name, action_slot, source_event
        )
        return _public_run(run, deduplicated=True)

    existing = get_existing("CFG Kanban DocType Action Run", run_key)
    if existing:
        existing = _locked_run(existing.name)
        _assert_expected_run(
            existing, run_key, task, profile_name, action_slot, source_event
        )
        assert_pinned_snapshot_compatible(existing)
        _ensure_task_link(task, existing)
        attempt, created = _record_attempt(
            existing,
            "Resume",
            "Succeeded",
            profile,
            session,
            retry_token,
            previous_state=existing.state,
            result_state=existing.state,
        )
        if created:
            _touch_resume(existing)
            _record_run_event("DocType Action Run Resumed", existing, profile, session)
        return _public_run(existing, deduplicated=not created, attempt=attempt.name)

    action_profile, snapshot, mapping_hash = executable_profile_snapshot(profile_name)
    if action_profile.company and action_profile.company != task.company:
        frappe.throw(_(
            "DocType Action Profile company {0} does not match Service Task company {1}."
        ).format(frappe.bold(action_profile.company), frappe.bold(task.company)))

    run = frappe.get_doc({
        "doctype": "CFG Kanban DocType Action Run",
        "action_id": secrets.token_urlsafe(24),
        "state": "Form In Progress",
        "source_doctype": task.doctype,
        "source_name": task.name,
        "source_event": source_event,
        "action_slot": action_slot,
        "action_profile": action_profile.name,
        "profile_revision": cint(action_profile.configuration_revision),
        "operator_employee": profile.employee,
        "operator_session": session.name,
        "terminal_user": frappe.session.user,
        "posting_identity": "Kanban Employee plus authenticated terminal User",
        "execution_policy": f"Controlled target writer / {action_profile.posting_policy}",
        "target_doctype": action_profile.target_doctype,
        "target_docstatus": 0,
        "created_at": now_datetime(),
        "mapping_hash": mapping_hash,
        "mapping_snapshot": frappe.as_json(snapshot),
    })
    run.flags.doctype_action_engine_insert = True
    run, created = insert_once(run, run_key, ignore_permissions=True)
    run = _locked_run(run.name)
    _assert_expected_run(run, run_key, task, profile_name, action_slot, source_event)
    if not created:
        assert_pinned_snapshot_compatible(run)
    _ensure_task_link(task, run)

    attempt, attempt_created = _record_attempt(
        run,
        "Create" if created else "Resume",
        "Succeeded",
        profile,
        session,
        retry_token,
        previous_state=None if created else run.state,
        result_state=run.state,
    )
    if attempt_created:
        if not created:
            _touch_resume(run)
        _record_run_event(
            "DocType Action Run Created" if created else "DocType Action Run Resumed",
            run,
            profile,
            session,
        )
    return _public_run(run, deduplicated=not attempt_created, attempt=attempt.name)


def cancel_run(run_name, reason, operator_session_token, retry_token):
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Cancellation reason is required."))
    _require_retry_token(retry_token)
    run = _locked_run(run_name)
    profile, session = _authorized_supervisor(run, operator_session_token)

    duplicate = _attempt_for_retry_token(retry_token)
    if duplicate:
        if duplicate.action_run != run.name:
            frappe.throw(_("This action token was already used for a different Action Run."))
        return _public_run(run, deduplicated=True, attempt=duplicate.name)
    if run.state == "Cancelled":
        return _public_run(run, deduplicated=True)
    if run.target_name:
        frappe.throw(_(
            "This Action Run already links to target {0} {1}. Reconcile the linked document; "
            "it cannot be silently cancelled."
        ).format(run.target_doctype, run.target_name))
    if run.state in {"Posting", "Submitted", "Skipped by Condition", "Needs Reconciliation"}:
        frappe.throw(_("Action Run cannot be cancelled while it is {0}.").format(run.state))

    previous = run.state
    _set_state(run, "Cancelled", {
        "cancelled_by": profile.employee,
        "cancelled_on": now_datetime(),
        "cancellation_reason": reason,
    })
    attempt, _created = _record_attempt(
        run, "Cancel", "Succeeded", profile, session, retry_token,
        previous_state=previous, result_state=run.state,
    )
    _record_run_event(
        "DocType Action Run Cancelled", run, profile, session,
        previous_state=previous, notes=reason,
    )
    return _public_run(run, attempt=attempt.name)


def mark_needs_reconciliation(run_name, reason, operator_session_token, retry_token):
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Reconciliation reason is required."))
    _require_retry_token(retry_token)
    run = _locked_run(run_name)
    profile, session = _authorized_supervisor(run, operator_session_token)

    duplicate = _attempt_for_retry_token(retry_token)
    if duplicate:
        if duplicate.action_run != run.name:
            frappe.throw(_("This action token was already used for a different Action Run."))
        return _public_run(run, deduplicated=True, attempt=duplicate.name)
    if run.state in {"Cancelled", "Skipped by Condition"}:
        frappe.throw(_("Action Run cannot require reconciliation while it is {0}.").format(
            run.state
        ))
    if run.state == "Needs Reconciliation":
        return _public_run(run, deduplicated=True)

    previous = run.state
    _set_state(run, "Needs Reconciliation", {
        "reconciliation_by": profile.employee,
        "reconciliation_on": now_datetime(),
        "reconciliation_notes": reason,
    })
    attempt, _created = _record_attempt(
        run, "Reconcile", "Succeeded", profile, session, retry_token,
        previous_state=previous, result_state=run.state,
    )
    _record_run_event(
        "DocType Action Run Needs Reconciliation", run, profile, session,
        previous_state=previous, notes=reason,
    )
    return _public_run(run, attempt=attempt.name)


def transition_run(run_name, new_state, profile, session, retry_token, *,
                   attempt_type="State Transition", error_code=None, error_message=None,
                   values=None):
    """Internal transition primitive shared by the controlled writer and recovery paths."""
    if new_state not in ACTION_RUN_STATES:
        frappe.throw(_("Unsupported DocType Action Run state: {0}").format(new_state))
    _require_retry_token(retry_token)
    run = _locked_run(run_name)
    duplicate = _attempt_for_retry_token(retry_token)
    if duplicate:
        if duplicate.action_run != run.name:
            frappe.throw(_("This action token was already used for a different Action Run."))
        return run, False
    previous = run.state
    changes = dict(values or {})
    if error_code:
        changes["last_error_code"] = str(error_code)[:140]
    if error_message:
        changes["last_error"] = sanitize_error(error_message)
    _set_state(run, new_state, changes)
    _record_attempt(
        run, attempt_type, "Failed" if new_state == "Failed" else "Succeeded",
        profile, session, retry_token, previous_state=previous,
        result_state=run.state, error_code=error_code, error_message=error_message,
    )
    _record_run_event(
        f"DocType Action Run {new_state}", run, profile, session,
        previous_state=previous, notes=error_message,
    )
    return run, True


def sanitize_error(value):
    text = " ".join(str(value or "").split())
    text = _URL.sub("[redacted-url]", text)
    text = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text[:500]


def authorize_run_actor(run, operator_session_token):
    """Recheck the Employee session and source scope for every runtime request."""
    if run.source_doctype != "CFG Kanban Task":
        frappe.throw(_("Gate 1 supports only standalone Service Task Action Runs."))
    task = frappe.get_doc(run.source_doctype, run.source_name)
    action = _SOURCE_ACTION.get(run.source_event)
    if not action:
        frappe.throw(_("Unsupported Action Run source event: {0}").format(run.source_event))
    profile, session = require_operator(
        operator_session_token, action, workstation=task.workstation
    )
    _assert_task_access(task, profile)
    return task, profile, session


def get_locked_run(run_name):
    return _locked_run(run_name)


def get_attempt_for_retry_token(retry_token):
    _require_retry_token(retry_token)
    return _attempt_for_retry_token(retry_token)


def record_run_attempt(run, attempt_type, outcome, profile, session, retry_token, **kwargs):
    return _record_attempt(
        run, attempt_type, outcome, profile, session, retry_token, **kwargs
    )


def public_run(run, *, deduplicated=False, attempt=None):
    return _public_run(run, deduplicated=deduplicated, attempt=attempt)


def _authorized_supervisor(run, operator_session_token):
    profile, session = require_operator(operator_session_token, "override")
    if profile.kanban_role not in ("Supervisor", "Development Proxy"):
        frappe.throw(_("Only an authorized Kanban Supervisor can recover Action Runs."),
                     frappe.PermissionError)
    if run.source_doctype != "CFG Kanban Task":
        frappe.throw(_("Gate 1B recovery supports only standalone Service Task Action Runs."))
    task = frappe.get_doc(run.source_doctype, run.source_name)
    _assert_task_access(task, profile)
    return profile, session


def _assert_task_access(task, profile):
    if can_view_service_task(task, profile):
        return
    if (
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and workstation_allowed(task.workstation, profile)
        and supervisor_assistance_scope_allowed(task.responsible_role, profile)
    ):
        return
    frappe.throw(_("Operator is not authorized for this Service Task Action Run."),
                 frappe.PermissionError)


def _locked_run(run_name):
    rows = frappe.db.sql(
        "SELECT name FROM `tabCFG Kanban DocType Action Run` WHERE name=%s FOR UPDATE",
        (run_name,),
        as_dict=True,
    )
    if not rows:
        frappe.throw(_("DocType Action Run {0} was not found.").format(run_name))
    return frappe.get_doc("CFG Kanban DocType Action Run", rows[0].name)


def _set_state(run, new_state, values=None):
    if new_state != run.state and new_state not in ALLOWED_TRANSITIONS.get(run.state, set()):
        frappe.throw(_("Unsafe DocType Action transition: {0} to {1}").format(
            run.state, new_state
        ))
    changes = dict(values or {})
    changes["state"] = new_state
    changes["last_retry_at"] = now_datetime()
    changes["retry_count"] = cint(run.retry_count) + 1
    frappe.db.set_value(run.doctype, run.name, changes, update_modified=False)
    run.update(changes)


def _record_attempt(run, attempt_type, outcome, profile, session, retry_token, *,
                    previous_state=None, result_state=None, error_code=None,
                    error_message=None):
    retry_hash = _retry_token_hash(retry_token)
    key = canonical_key("doctype-action-attempt-v1", run.name, attempt_type, retry_hash)
    existing = get_existing("CFG Kanban DocType Action Attempt", key)
    if existing:
        return existing, False
    attempt = frappe.get_doc({
        "doctype": "CFG Kanban DocType Action Attempt",
        "attempt_id": secrets.token_urlsafe(18),
        "action_run": run.name,
        "attempt_type": attempt_type,
        "outcome": outcome,
        "occurred_at": now_datetime(),
        "retry_token_hash": retry_hash,
        "operator_employee": profile.employee,
        "operator_session": session.name,
        "terminal_user": frappe.session.user,
        "previous_state": previous_state,
        "result_state": result_state,
        "reference_doctype": run.target_doctype if run.target_name else None,
        "reference_name": run.target_name,
        "error_code": str(error_code)[:140] if error_code else None,
        "error_message": sanitize_error(error_message) if error_message else None,
    })
    attempt.flags.doctype_action_engine_insert = True
    return insert_once(attempt, key, ignore_permissions=True)


def _attempt_for_retry_token(retry_token):
    name = frappe.db.get_value(
        "CFG Kanban DocType Action Attempt",
        {"retry_token_hash": _retry_token_hash(retry_token)},
        "name",
    )
    return frappe.get_doc("CFG Kanban DocType Action Attempt", name) if name else None


def _ensure_task_link(task, run):
    linked = frappe.db.get_value(task.doctype, task.name, "doctype_action_run")
    if linked and linked != run.name:
        frappe.throw(_(
            "Service Task {0} is already linked to Action Run {1}; supervised reconciliation is required."
        ).format(task.name, linked))
    if not linked:
        frappe.db.set_value(task.doctype, task.name, "doctype_action_run", run.name,
                            update_modified=False)


def _assert_expected_run(run, run_key, task, profile_name, action_slot, source_event):
    if run.idempotency_key != run_key or (
        run.source_doctype != task.doctype
        or run.source_name != task.name
        or run.action_profile != profile_name
        or run.action_slot != action_slot
        or run.source_event != source_event
    ):
        frappe.throw(_("Action retry identity does not match the requested Service Task run."),
                     frappe.PermissionError)


def _record_run_event(event_type, run, profile, session, previous_state=None, notes=None):
    record(
        event_type,
        standalone_task=run.source_name if run.source_doctype == "CFG Kanban Task" else None,
        action_run=run.name,
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=frappe.session.user,
        previous_state=previous_state,
        new_state=run.state,
        reference_doctype=run.target_doctype if run.target_name else None,
        reference_name=run.target_name,
        notes=sanitize_error(notes) if notes else None,
    )


def _touch_resume(run):
    current = now_datetime()
    values = {
        "last_retry_at": current,
        "retry_count": cint(run.retry_count) + 1,
    }
    frappe.db.set_value(run.doctype, run.name, values, update_modified=False)
    run.update(values)


def _public_run(run, *, deduplicated=False, attempt=None):
    return {
        "name": run.name,
        "action_id": run.action_id,
        "state": run.state,
        "source_doctype": run.source_doctype,
        "source_name": run.source_name,
        "source_event": run.source_event,
        "action_profile": run.action_profile,
        "profile_revision": cint(run.profile_revision),
        "target_doctype": run.target_doctype,
        "target_name": run.target_name,
        "target_docstatus": cint(run.target_docstatus),
        "deduplicated": bool(deduplicated),
        "attempt": attempt,
    }


def _retry_token_hash(retry_token):
    return hashlib.sha256(str(retry_token).encode("utf-8")).hexdigest()


def _require_retry_token(retry_token):
    if not retry_token or len(str(retry_token)) < 12:
        frappe.throw(_("A fresh opaque action token is required."))


def assert_pinned_snapshot_compatible(run):
    """Validate the immutable snapshot before a later package performs target writes."""
    try:
        snapshot = json.loads(run.mapping_snapshot or "{}")
    except (TypeError, ValueError):
        frappe.throw(_(
            "The pinned Action Run configuration snapshot is unreadable; "
            "supervised reconciliation is required."
        ))
    calculated_hash = hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
    if calculated_hash != run.mapping_hash:
        frappe.throw(_(
            "The pinned Action Run configuration snapshot failed its integrity check; "
            "supervised reconciliation is required."
        ))
    if snapshot.get("metadata_fingerprint") != metadata_fingerprint(
        frappe.get_meta(run.target_doctype)
    ):
        frappe.throw(_(
            "Target metadata changed after this Action Run began; supervised reconciliation is required."
        ))
    get_target_policy(run.target_doctype, "create")
    posting_policy = (snapshot.get("configuration") or {}).get("posting_policy")
    if posting_policy == "Submit When Authorized":
        get_target_policy(run.target_doctype, "submit")
    return snapshot

"""Service Task binding and closure gate for the DocType Action Engine.

Each generated task occurrence carries a snapshot of the schedule binding.  The
profile's validated mapping is pinned separately when the Action Run is created.
This prevents later schedule/profile edits from changing an occurrence already
released to the floor.
"""

import json
import secrets

import frappe
from frappe import _
from frappe.utils import cint

from cfg_kanban.services.doctype_action_runs import cancel_run, resolve_task_run
from cfg_kanban.services.events import record


TRIGGER_TO_SOURCE_EVENT = {
    "On Task Start": "Task Start",
    "On Task Complete": "Task Complete",
    "After Supervisor Verification": "Supervisor Verification",
}
SATISFIED_BY_POSTING_POLICY = {
    "Save Draft": {"Draft Created", "Submitted", "Skipped by Condition"},
    "Submit When Authorized": {"Submitted", "Skipped by Condition"},
}


def assert_schedule_binding_authorized(schedule):
    """Protect action bindings even when a caller bypasses the Desk field UI."""
    fieldnames = (
        "doctype_action_profile", "doctype_action_trigger", "doctype_action_required"
    )
    if schedule.is_new():
        changed = any(schedule.get(fieldname) for fieldname in fieldnames)
    else:
        original = frappe.db.get_value(
            schedule.doctype, schedule.name, list(fieldnames), as_dict=True
        ) or {}
        changed = any(
            (original.get(fieldname) or None) != (schedule.get(fieldname) or None)
            for fieldname in fieldnames
        )
    if changed:
        from cfg_kanban.services.doctype_actions import require_configuration_role
        require_configuration_role()


def validate_schedule_binding(schedule):
    """Validate the optional administrator-configured task/action binding."""
    profile_name = schedule.get("doctype_action_profile")
    trigger = schedule.get("doctype_action_trigger")
    required = cint(schedule.get("doctype_action_required"))
    if not profile_name:
        if trigger or required:
            frappe.throw(_("Select a DocType Action Profile before configuring its trigger or gate."))
        return
    if trigger not in TRIGGER_TO_SOURCE_EVENT:
        frappe.throw(_("Select when the DocType Action must run."))

    profile = frappe.get_doc("CFG Kanban DocType Action Profile", profile_name)
    if not cint(profile.enabled) or profile.validation_status != "Valid":
        frappe.throw(_(
            "DocType Action Profile {0} must be enabled and Valid before it can be assigned."
        ).format(frappe.bold(profile.name)))
    if profile.company and profile.company != schedule.company:
        frappe.throw(_(
            "DocType Action Profile company {0} does not match Task Schedule company {1}."
        ).format(frappe.bold(profile.company), frappe.bold(schedule.company)))
    if trigger == "After Supervisor Verification" and not cint(
        schedule.require_supervisor_verification
    ):
        frappe.throw(_(
            "After Supervisor Verification requires Require Supervisor Verification on the schedule."
        ))
    if profile.verification_policy == "Require Service Task Verification":
        if not cint(schedule.require_supervisor_verification):
            frappe.throw(_(
                "This Action Profile requires Service Task verification; enable supervisor verification."
            ))
        if trigger != "After Supervisor Verification":
            frappe.throw(_(
                "An Action Profile requiring Service Task verification must run After Supervisor Verification."
            ))
    if trigger == "On Task Start" and profile.posting_policy != "Save Draft":
        frappe.throw(_(
            "On Task Start may only Save Draft; submitting before task evidence is complete is not allowed."
        ))
    if (cint(schedule.require_supervisor_verification)
            and trigger == "On Task Complete"
            and profile.posting_policy == "Submit When Authorized"):
        frappe.throw(_(
            "A verified task cannot submit its target On Task Complete. Use After Supervisor Verification."
        ))


def occurrence_snapshot(schedule):
    """Return the immutable binding fields copied onto a generated Task."""
    return {
        "doctype_action_profile": schedule.get("doctype_action_profile"),
        "doctype_action_trigger": schedule.get("doctype_action_trigger"),
        "doctype_action_required": cint(schedule.get("doctype_action_required")),
    }


def resolve_for_task_event(task, trigger, operator_session_token):
    """Create/resume the one Action Run when this task reaches its bound event."""
    if not task.get("doctype_action_profile"):
        return None
    if task.get("doctype_action_trigger") != trigger:
        return None
    result = resolve_task_run(
        task.name,
        task.doctype_action_profile,
        TRIGGER_TO_SOURCE_EVENT[trigger],
        operator_session_token,
        secrets.token_urlsafe(24),
    )
    task.doctype_action_run = result.get("name")
    return result


def apply_required_gate(task, desired_status, *, gate_now):
    """Move a task to an explicit pending state when its target is unresolved."""
    if not cint(task.get("doctype_action_required")) or not gate_now:
        task.doctype_action_pending_status = None
        task.status = desired_status
        return False
    if action_is_satisfied(task.get("doctype_action_run")):
        task.doctype_action_pending_status = None
        task.status = desired_status
        return False
    task.doctype_action_pending_status = desired_status
    task.status = "Pending Document Posting"
    return True


def action_is_satisfied(run_name):
    if not run_name or not frappe.db.exists("CFG Kanban DocType Action Run", run_name):
        return False
    run = frappe.get_doc("CFG Kanban DocType Action Run", run_name)
    snapshot = _mapping_snapshot(run)
    posting_policy = (snapshot.get("configuration") or {}).get("posting_policy")
    return run.state in SATISFIED_BY_POSTING_POLICY.get(posting_policy, set())


def release_task_gate(run, profile, session):
    """Release the source Task after the writer records the required outcome."""
    if run.source_doctype != "CFG Kanban Task":
        return None
    task = frappe.get_doc("CFG Kanban Task", run.source_name)
    if not cint(task.get("doctype_action_required")):
        return task
    if task.get("doctype_action_run") != run.name:
        frappe.throw(_("Task Action Run linkage changed; reconciliation is required."))
    if task.status != "Pending Document Posting":
        return task
    if not action_is_satisfied(run.name):
        return task
    target_status = task.get("doctype_action_pending_status")
    if target_status not in {"Completed", "Awaiting Verification"}:
        frappe.throw(_("Task document-gate destination is invalid; reconciliation is required."))
    previous = task.status
    task.status = target_status
    task.doctype_action_pending_status = None
    task.save(ignore_permissions=True)
    record(
        "Standalone Task Document Gate Released",
        reference_doctype=task.doctype,
        reference_name=task.name,
        standalone_task=task.name,
        action_run=run.name,
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
        previous_state=previous,
        new_state=target_status,
        notes=f"Required DocType Action reached {run.state}",
    )
    return task


def cancel_task_action(task, operator_session_token, reason):
    """Cancel an unposted Action Run when its source task is disposed."""
    if not task.get("doctype_action_run"):
        return None
    run = frappe.get_doc("CFG Kanban DocType Action Run", task.doctype_action_run)
    if run.state in {"Cancelled", "Skipped by Condition"}:
        return run
    result = cancel_run(
        run.name,
        reason,
        operator_session_token,
        secrets.token_urlsafe(24),
    )
    return frappe.get_doc("CFG Kanban DocType Action Run", result["name"])


def _mapping_snapshot(run):
    try:
        return json.loads(run.mapping_snapshot or "{}")
    except (TypeError, ValueError):
        frappe.throw(_("Action Run mapping snapshot is unreadable; reconciliation is required."))

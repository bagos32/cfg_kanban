import frappe

from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.media import list_reference_media
from cfg_kanban.services.process_tasks import (complete_task, ensure_tasks, evaluate_gate,
                                               invalidate_valid_tasks, refresh_task_readiness,
                                               reset_qc_for_retest, start_task, task_form,
                                               verify_task)
from cfg_kanban.services.printing import get_qr_svg


@frappe.whitelist()
def get_cycle_tasks(cycle_name, operator_session_token=None):
    require_operator(operator_session_token)
    ensure_tasks(cycle_name)
    refresh_task_readiness(cycle_name)
    return frappe.get_all(
        "CFG Kanban Process Task", filters={"kanban_cycle": cycle_name},
        fields=["name", "task_key", "task_name", "sequence", "task_category", "task_type",
                "trigger_point", "linked_operation", "status", "mandatory", "blocking",
                "responsible_role", "workstation", "asset", "assigned_employee",
                "started_on", "completed_on", "verification_required", "verified_by",
                "verified_on", "valid_until", "reused_from_task"],
        order_by="sequence asc, creation asc",
    )


@frappe.whitelist()
def get_task_form(task_name, capture_on="Complete", operator_session_token=None):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    action = {"Start": "task_start", "Verify": "task_verify"}.get(capture_on, "task_complete")
    require_operator(operator_session_token, action, operation=task.linked_operation,
                     workstation=task.workstation)
    result = task_form(task_name, capture_on)
    result["media"] = list_reference_media(
        "CFG Kanban Process Task", task.name, permission_checked=True
    )
    return result


@frappe.whitelist()
def start(task_name, operator_session_token, values=None, notes=None):
    return start_task(task_name, operator_session_token, values=values, notes=notes).as_dict()


@frappe.whitelist()
def complete(task_name, operator_session_token, values=None, checklist_results=None, notes=None,
             sample_id=None, qc_result=None, qc_disposition_notes=None):
    return complete_task(task_name, operator_session_token, values=values,
                         checklist_results=checklist_results, notes=notes,
                         sample_id=sample_id, qc_result=qc_result,
                         qc_disposition_notes=qc_disposition_notes).as_dict()


@frappe.whitelist()
def verify(task_name, operator_session_token, values=None, notes=None):
    return verify_task(task_name, operator_session_token, values=values, notes=notes).as_dict()


@frappe.whitelist()
def gate_status(cycle_name, trigger_point, operation=None, operator_session_token=None):
    require_operator(operator_session_token)
    return evaluate_gate(cycle_name, trigger_point, operation)


@frappe.whitelist()
def invalidate_validity(reason, asset=None, workstation=None):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    if not reason:
        frappe.throw("Invalidation reason is required")
    return invalidate_valid_tasks(reason, asset=asset, workstation=workstation)


@frappe.whitelist()
def resolve_scan(scan_value, operator_session_token):
    value = (scan_value or "").strip()
    for marker in ("CFG:PROCESS_TASK:", "CFG:SAMPLE:"):
        if value.upper().startswith(marker):
            value = value[len(marker):]
            break
    task = frappe.get_doc("CFG Kanban Process Task", value)
    require_operator(operator_session_token, operation=task.linked_operation,
                     workstation=task.workstation)
    cycle = frappe.get_doc("CFG Kanban Cycle", task.kanban_cycle)
    card_qr = frappe.db.get_value("CFG Kanban Card", cycle.kanban_card, "qr_code")
    return {"task": task.as_dict(), "cycle": cycle.name, "card": cycle.kanban_card,
            "card_qr": card_qr}


@frappe.whitelist()
def get_sample_label(task_name, label_type="Sample Traveller"):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    sample = label_type == "Sample Traveller"
    payload = ((task.sample_qr_payload or f"CFG:SAMPLE:{task.name}") if sample else
               (task.process_qr_payload or f"CFG:PROCESS_TASK:{task.name}"))
    return {"task": task.as_dict(), "label_type": label_type,
            "payload": payload, "qr_svg": get_qr_svg(payload)}


@frappe.whitelist()
def authorize_retest(task_name, reason, operator_session_token):
    return reset_qc_for_retest(task_name, operator_session_token, reason).as_dict()

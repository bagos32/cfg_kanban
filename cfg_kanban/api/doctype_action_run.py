import frappe

from cfg_kanban.services import doctype_action_runs


@frappe.whitelist()
def cancel(run_name, reason, operator_session_token, retry_token):
    return doctype_action_runs.cancel_run(
        run_name, reason, operator_session_token, retry_token
    )


@frappe.whitelist()
def require_reconciliation(run_name, reason, operator_session_token, retry_token):
    return doctype_action_runs.mark_needs_reconciliation(
        run_name, reason, operator_session_token, retry_token
    )

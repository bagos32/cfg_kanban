import frappe

from cfg_kanban.services import doctype_action_runs, doctype_action_writer


@frappe.whitelist()
def get_operator_form(run_name, operator_session_token):
    return doctype_action_writer.get_operator_form(
        run_name, operator_session_token
    )


@frappe.whitelist(methods=["POST"])
def post(run_name, operator_session_token, retry_token,
         operator_values=None, child_rows=None):
    return doctype_action_writer.post_action(
        run_name,
        operator_session_token,
        retry_token,
        operator_values=operator_values,
        child_rows=child_rows,
    )


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


@frappe.whitelist(methods=["POST"])
def recover(run_name, resolution, reason, operator_session_token, retry_token):
    return doctype_action_runs.recover_run(
        run_name, resolution, reason, operator_session_token, retry_token
    )

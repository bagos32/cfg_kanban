import frappe

from cfg_kanban.services import media
from cfg_kanban.services.operator_auth import require_operator


@frappe.whitelist()
def create_upload_url(reference_doctype, reference_name, original_filename, content_type,
                      size_bytes, media_class, idempotency_key, checksum_value=None):
    return media.create_upload_url(
        reference_doctype, reference_name, original_filename, content_type, size_bytes,
        media_class, idempotency_key, checksum_value=checksum_value,
    )


@frappe.whitelist()
def confirm_upload(media_id, confirmation_token):
    return media.confirm_upload(media_id, confirmation_token)


@frappe.whitelist()
def create_view_url(media_id, disposition="inline"):
    return media.create_view_url(media_id, disposition)


@frappe.whitelist()
def delete_object(media_id, mode="archive"):
    return media.delete_object(media_id, mode)


@frappe.whitelist()
def get_metadata(media_id):
    return media.get_metadata(media_id)


@frappe.whitelist()
def create_task_upload_url(task_name, original_filename, content_type, size_bytes,
                           idempotency_key, operator_session_token):
    _task, profile, session = _authorize_task(
        task_name, operator_session_token, "task_complete"
    )
    return media.create_upload_url(
        "CFG Kanban Task", task_name, original_filename, content_type, size_bytes,
        "maintenance-evidence", idempotency_key, permission_checked=True,
        extensions={"cfg_kanban": {"capture_source": "service-task-panel"}},
        operator_employee=profile.employee, operator_session=session.name,
    )


@frappe.whitelist()
def confirm_task_upload(task_name, media_id, confirmation_token, operator_session_token):
    _authorize_task(task_name, operator_session_token, "task_complete")
    _assert_task_media(task_name, media_id)
    return media.confirm_upload(media_id, confirmation_token, permission_checked=True)


@frappe.whitelist()
def list_task_media(task_name, operator_session_token):
    _authorize_task(task_name, operator_session_token)
    return media.list_reference_media("CFG Kanban Task", task_name, permission_checked=True)


@frappe.whitelist()
def create_task_view_url(task_name, media_id, operator_session_token, disposition="inline"):
    _authorize_task(task_name, operator_session_token)
    _assert_task_media(task_name, media_id)
    return media.create_view_url(media_id, disposition, permission_checked=True)


def _authorize_task(task_name, operator_session_token, action=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(
        operator_session_token, action, workstation=task.workstation
    )
    if (task.assigned_employee and task.assigned_employee != profile.employee and
            profile.kanban_role != "Supervisor"):
        frappe.throw(f"Task is assigned to Employee {task.assigned_employee}")
    return task, profile, session


def _assert_task_media(task_name, media_id):
    reference = frappe.db.get_value(
        "CFG Kanban Media", {"media_id": media_id},
        ["reference_doctype", "reference_name"], as_dict=True,
    )
    if not reference or reference.reference_doctype != "CFG Kanban Task" or \
            reference.reference_name != task_name:
        frappe.throw("Media does not belong to this Service Task", frappe.PermissionError)

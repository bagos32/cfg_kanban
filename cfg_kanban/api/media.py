import frappe

from cfg_kanban.services import media
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.task_access import (
    assert_service_task_access,
    assert_service_task_execution_access,
    can_view_service_task,
)


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
def get_reference_gallery(reference_doctype, reference_name):
    """Return metadata plus ephemeral image previews for an authorised Desk record."""
    rows = media.list_reference_media(reference_doctype, reference_name)
    for row in rows:
        row["preview_url"] = None
        if (row.get("content_type") or "").startswith("image/"):
            row["preview_url"] = media.create_view_url(
                row.media_id, permission_checked=True
            )["url"]
    return rows


@frappe.whitelist()
def create_task_upload_url(task_name, original_filename, content_type, size_bytes,
                           idempotency_key, operator_session_token,
                           capture_source="file-upload", capture_timestamp=None,
                           latitude=None, longitude=None, location_accuracy=None):
    _task, profile, session = _authorize_task(
        task_name, operator_session_token, "task_complete"
    )
    return media.create_upload_url(
        "CFG Kanban Task", task_name, original_filename, content_type, size_bytes,
        "maintenance-evidence", idempotency_key, permission_checked=True,
        extensions=_capture_extensions(capture_source, capture_timestamp, latitude,
                                       longitude, location_accuracy),
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


@frappe.whitelist()
def get_task_camera_stamp(task_name, operator_session_token):
    task, _profile, _session = _authorize_task(
        task_name, operator_session_token, "task_complete"
    )
    if task.status != "In Progress":
        frappe.throw("Start the Service Task before taking timestamped execution photos")
    return {"captured_at": str(frappe.utils.now_datetime()), "task": task.name,
            "started_on": task.started_on}


@frappe.whitelist()
def archive_task_media(task_name, media_id, operator_session_token):
    _authorize_task(task_name, operator_session_token, "task_complete")
    _assert_task_media(task_name, media_id)
    return media.delete_object(media_id, permission_checked=True)


@frappe.whitelist()
def create_process_task_upload_url(task_name, original_filename, content_type, size_bytes,
                                   idempotency_key, operator_session_token,
                                   capture_source="file-upload", capture_timestamp=None,
                                   latitude=None, longitude=None, location_accuracy=None):
    _task, profile, session = _authorize_process_task(
        task_name, operator_session_token, "task_complete"
    )
    return media.create_upload_url(
        "CFG Kanban Process Task", task_name, original_filename, content_type, size_bytes,
        "process-task-evidence", idempotency_key, permission_checked=True,
        extensions=_capture_extensions(capture_source, capture_timestamp, latitude,
                                       longitude, location_accuracy),
        operator_employee=profile.employee, operator_session=session.name,
    )


@frappe.whitelist()
def confirm_process_task_upload(task_name, media_id, confirmation_token,
                                operator_session_token):
    _authorize_process_task(task_name, operator_session_token, "task_complete")
    _assert_reference_media("CFG Kanban Process Task", task_name, media_id)
    return media.confirm_upload(media_id, confirmation_token, permission_checked=True)


@frappe.whitelist()
def list_process_task_media(task_name, operator_session_token):
    _authorize_process_task(task_name, operator_session_token)
    return media.list_reference_media(
        "CFG Kanban Process Task", task_name, permission_checked=True
    )


@frappe.whitelist()
def create_process_task_view_url(task_name, media_id, operator_session_token,
                                 disposition="inline"):
    _authorize_process_task(task_name, operator_session_token)
    _assert_reference_media("CFG Kanban Process Task", task_name, media_id)
    return media.create_view_url(media_id, disposition, permission_checked=True)


@frappe.whitelist()
def get_process_task_camera_stamp(task_name, operator_session_token):
    task, _profile, _session = _authorize_process_task(
        task_name, operator_session_token, "task_complete"
    )
    if task.status != "In Progress":
        frappe.throw("Start the Process Task before taking timestamped execution photos")
    return {"captured_at": str(frappe.utils.now_datetime()), "task": task.name,
            "started_on": task.started_on, "cycle": task.kanban_cycle}


@frappe.whitelist()
def archive_process_task_media(task_name, media_id, operator_session_token):
    _authorize_process_task(task_name, operator_session_token, "task_complete")
    _assert_reference_media("CFG Kanban Process Task", task_name, media_id)
    return media.delete_object(media_id, permission_checked=True)


@frappe.whitelist()
def create_delivery_proof_upload_url(proof_name, original_filename, content_type,
                                     size_bytes, idempotency_key,
                                     operator_session_token, evidence_kind,
                                     capture_source="file-upload", capture_timestamp=None,
                                     latitude=None, longitude=None, location_accuracy=None):
    proof, profile, session = _authorize_delivery_proof(
        proof_name, operator_session_token, "complete"
    )
    if proof.state != "Draft":
        frappe.throw("Submitted delivery proof cannot accept more evidence")
    if evidence_kind not in ("photo", "signature", "attachment"):
        frappe.throw("Delivery evidence kind is not supported")
    declared_type = (content_type or "").lower()
    if evidence_kind == "photo" and not declared_type.startswith("image/"):
        frappe.throw("Delivery photograph must be an image")
    if evidence_kind == "photo" and capture_source != "timestamped-camera":
        frappe.throw("Delivery photograph must use the timestamped camera workflow")
    if evidence_kind == "signature" and declared_type != "image/png":
        frappe.throw("Recipient signature must be a PNG image")
    if evidence_kind == "signature" and capture_source != "signature-pad":
        frappe.throw("Recipient signature must use the controlled signature pad")
    extensions = _capture_extensions(
        capture_source, capture_timestamp, latitude, longitude, location_accuracy
    )
    extensions["cfg_kanban"]["evidence_kind"] = evidence_kind
    return media.create_upload_url(
        proof.doctype, proof.name, original_filename, content_type, size_bytes,
        "delivery-proof-evidence", idempotency_key, permission_checked=True,
        extensions=extensions, operator_employee=profile.employee,
        operator_session=session.name,
    )


@frappe.whitelist()
def confirm_delivery_proof_upload(proof_name, media_id, confirmation_token,
                                  operator_session_token):
    _authorize_delivery_proof(proof_name, operator_session_token, "complete")
    _assert_reference_media("CFG Kanban Delivery Proof", proof_name, media_id)
    return media.confirm_upload(media_id, confirmation_token, permission_checked=True)


@frappe.whitelist()
def list_delivery_proof_media(proof_name, operator_session_token):
    _authorize_delivery_proof(proof_name, operator_session_token)
    return media.list_reference_media(
        "CFG Kanban Delivery Proof", proof_name, permission_checked=True
    )


@frappe.whitelist()
def create_delivery_proof_view_url(proof_name, media_id, operator_session_token,
                                   disposition="inline"):
    _authorize_delivery_proof(proof_name, operator_session_token)
    _assert_reference_media("CFG Kanban Delivery Proof", proof_name, media_id)
    return media.create_view_url(media_id, disposition, permission_checked=True)


@frappe.whitelist()
def archive_delivery_proof_media(proof_name, media_id, operator_session_token):
    proof, _profile, _session = _authorize_delivery_proof(
        proof_name, operator_session_token, "complete"
    )
    if proof.state != "Draft":
        frappe.throw("Submitted delivery proof evidence cannot be removed")
    _assert_reference_media("CFG Kanban Delivery Proof", proof_name, media_id)
    return media.delete_object(media_id, permission_checked=True)


@frappe.whitelist()
def get_delivery_proof_camera_stamp(proof_name, operator_session_token):
    proof, _profile, _session = _authorize_delivery_proof(
        proof_name, operator_session_token, "complete"
    )
    if proof.state != "Draft":
        frappe.throw("Delivery proof is already submitted")
    return {"captured_at": str(frappe.utils.now_datetime()), "proof": proof.name,
            "delivery_session": proof.delivery_session, "site": proof.site_name}


@frappe.whitelist()
def create_return_case_upload_url(return_case, original_filename, content_type,
                                  size_bytes, idempotency_key,
                                  operator_session_token, evidence_kind,
                                  capture_source="file-upload", capture_timestamp=None,
                                  latitude=None, longitude=None, location_accuracy=None):
    case, profile, session = _authorize_return_case(
        return_case, operator_session_token, write=True
    )
    if evidence_kind not in ("photo", "attachment"):
        frappe.throw("Return evidence kind is not supported")
    declared_type = (content_type or "").lower()
    if evidence_kind == "photo":
        if not declared_type.startswith("image/"):
            frappe.throw("Return photograph must be an image")
        if capture_source != "timestamped-camera":
            frappe.throw("Return photograph must use the timestamped camera workflow")
    extensions = _capture_extensions(
        capture_source, capture_timestamp, latitude, longitude, location_accuracy
    )
    extensions["cfg_kanban"]["evidence_kind"] = evidence_kind
    return media.create_upload_url(
        case.doctype, case.name, original_filename, content_type, size_bytes,
        "customer-return-evidence", idempotency_key, permission_checked=True,
        extensions=extensions, operator_employee=profile.employee,
        operator_session=session.name,
    )


@frappe.whitelist()
def confirm_return_case_upload(return_case, media_id, confirmation_token,
                               operator_session_token):
    _authorize_return_case(return_case, operator_session_token, write=True)
    _assert_reference_media("CFG Kanban Return Case", return_case, media_id)
    return media.confirm_upload(media_id, confirmation_token, permission_checked=True)


@frappe.whitelist()
def list_return_case_media(return_case, operator_session_token):
    _authorize_return_case(return_case, operator_session_token)
    return media.list_reference_media(
        "CFG Kanban Return Case", return_case, permission_checked=True
    )


@frappe.whitelist()
def create_return_case_view_url(return_case, media_id, operator_session_token,
                                disposition="inline"):
    _authorize_return_case(return_case, operator_session_token)
    _assert_reference_media("CFG Kanban Return Case", return_case, media_id)
    return media.create_view_url(media_id, disposition, permission_checked=True)


@frappe.whitelist()
def archive_return_case_media(return_case, media_id, operator_session_token):
    _authorize_return_case(return_case, operator_session_token, write=True)
    _assert_reference_media("CFG Kanban Return Case", return_case, media_id)
    return media.delete_object(media_id, permission_checked=True)


@frappe.whitelist()
def get_return_case_camera_stamp(return_case, operator_session_token):
    case, _profile, _session = _authorize_return_case(
        return_case, operator_session_token, write=True
    )
    return {
        "captured_at": str(frappe.utils.now_datetime()), "return_case": case.name,
        "customer": case.customer, "site": case.site_name,
    }


def _authorize_task(task_name, operator_session_token, action=None):
    task = frappe.get_doc("CFG Kanban Task", task_name)
    profile, session = require_operator(
        operator_session_token, action, workstation=task.workstation
    )
    if action == "task_complete":
        assert_service_task_execution_access(task, profile)
    elif not can_view_service_task(task, profile):
        assert_service_task_access(task, profile)
    return task, profile, session


def _assert_task_media(task_name, media_id):
    return _assert_reference_media("CFG Kanban Task", task_name, media_id)


def _authorize_process_task(task_name, operator_session_token, action=None):
    task = frappe.get_doc("CFG Kanban Process Task", task_name)
    profile, session = require_operator(
        operator_session_token, action, operation=task.linked_operation,
        workstation=task.workstation,
    )
    return task, profile, session


def _authorize_delivery_proof(proof_name, operator_session_token, action=None):
    from cfg_kanban.services.customer_delivery import (
        CUSTOMER_DELIVERY_RESPONSIBILITY,
        assert_delivery_access,
    )

    proof = frappe.get_doc("CFG Kanban Delivery Proof", proof_name)
    profile, session = require_operator(operator_session_token, action)
    responsibilities = {row.responsibility for row in profile.responsibilities
                        if row.responsibility}
    can_view_all = (
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and profile.get("view_all_responsibilities")
    )
    if CUSTOMER_DELIVERY_RESPONSIBILITY not in responsibilities and not can_view_all:
        frappe.throw("Operator is not assigned to Customer Delivery", frappe.PermissionError)
    assert_delivery_access(proof.delivery_session, profile)
    return proof, profile, session


def _authorize_return_case(return_case, operator_session_token, write=False):
    from cfg_kanban.services.customer_returns import (
        CUSTOMER_RETURN_QC_RESPONSIBILITY,
        CUSTOMER_RETURN_RESPONSIBILITY,
    )

    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    profile, session = require_operator(operator_session_token)
    responsibilities = {
        row.responsibility for row in profile.responsibilities if row.responsibility
    }
    can_view_all = (
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and profile.get("view_all_responsibilities")
    )
    can_intake = CUSTOMER_RETURN_RESPONSIBILITY in responsibilities
    can_qc = CUSTOMER_RETURN_QC_RESPONSIBILITY in responsibilities
    if not (can_view_all or can_intake or can_qc):
        frappe.throw("Operator is not assigned to Customer Return", frappe.PermissionError)
    if not can_view_all and not can_qc and case.created_by_operator != profile.employee:
        frappe.throw("Operator cannot access this Return Case", frappe.PermissionError)
    if write:
        allowed = (
            case.return_flow == "Customer Return for QC"
            and case.state in ("Awaiting QC Receipt", "QC In Progress")
            and (can_view_all or can_qc or case.created_by_operator == profile.employee)
        )
        if not allowed:
            frappe.throw("Return evidence is locked after QC completion")
    return case, profile, session


def _assert_reference_media(reference_doctype, reference_name, media_id):
    reference = frappe.db.get_value(
        "CFG Kanban Media", {"media_id": media_id},
        ["reference_doctype", "reference_name"], as_dict=True,
    )
    if not reference or reference.reference_doctype != reference_doctype or \
            reference.reference_name != reference_name:
        frappe.throw("Media does not belong to this task", frappe.PermissionError)


def _capture_extensions(source, captured_at, latitude, longitude, accuracy):
    payload = {"capture_source": source, "capture_timestamp": captured_at}
    if source == "timestamped-camera":
        if latitude in (None, "") or longitude in (None, ""):
            frappe.throw("Geolocation is required for a timestamped execution photo")
        lat = frappe.utils.flt(latitude)
        lng = frappe.utils.flt(longitude)
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            frappe.throw("Invalid photo geolocation")
        payload["geotag"] = {
            "latitude": lat, "longitude": lng,
            "accuracy_metres": frappe.utils.flt(accuracy),
        }
    return {"cfg_kanban": payload}

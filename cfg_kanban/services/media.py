"""Private S3 media control plane following the company cross-app media contract."""

import hashlib
import hmac
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import PurePath
from urllib.parse import quote

import frappe
from frappe.utils import cint, now_datetime


APP_ID = "cfg_kanban"
APP_PREFIX = "cfg-kanban"
MEDIA_CLASSES = {
    "maintenance-evidence": {"CFG Kanban Task"},
    "process-task-evidence": {"CFG Kanban Process Task"},
    "incident-evidence": {"CFG Kanban Exception"},
    "production-evidence": {"CFG Kanban Cycle", "CFG Kanban Operation Progress"},
}
STATUSES = {"pending", "available", "quarantined", "archived", "deleting", "deleted", "failed"}
DEFAULT_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "video/mp4", "application/pdf"}


def create_upload_url(reference_doctype, reference_name, original_filename, content_type,
                      size_bytes, media_class, idempotency_key, checksum_value=None,
                      permission_checked=False, extensions=None, operator_employee=None,
                      operator_session=None):
    config = _config()
    _validate_reference(reference_doctype, reference_name, media_class, "write",
                        permission_checked)
    filename = _safe_filename(original_filename)
    content_type = (content_type or "").lower().strip()
    size_bytes = cint(size_bytes)
    _validate_file(filename, content_type, size_bytes, config)
    if not idempotency_key:
        frappe.throw("Upload idempotency key is required")
    existing = frappe.db.get_value(
        "CFG Kanban Media", {"upload_idempotency_key": idempotency_key}, "name"
    )
    if existing:
        media = frappe.get_doc("CFG Kanban Media", existing)
        _assert_same_request(media, reference_doctype, reference_name, filename,
                             content_type, size_bytes, media_class)
        if media.status == "available":
            return {"media": _metadata(media), "already_available": True}
        if media.status != "pending":
            frappe.throw(f"Upload retry is not allowed while media is {media.status}")
        return _upload_authorization(media, config, _new_confirmation_token(media))

    media_id = uuid.uuid4().hex
    created_at = now_datetime()
    object_key = _object_key(config, media_class, reference_doctype, reference_name,
                             media_id, filename, created_at)
    confirmation_token = frappe.generate_hash(length=48)
    media = frappe.get_doc({
        "doctype": "CFG Kanban Media",
        "media_id": media_id,
        "status": "pending",
        "media_class": media_class,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "app_id": APP_ID,
        "environment": config["environment"],
        "bucket": config["bucket"],
        "object_key": object_key,
        "original_filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "checksum_algorithm": "SHA-256",
        "checksum_value": checksum_value,
        "retention_class": config["retention_class"],
        "access_classification": "internal",
        "upload_idempotency_key": idempotency_key,
        "confirmation_token_hash": _token_hash(confirmation_token),
        "created_by": frappe.session.user,
        "operator_employee": operator_employee,
        "operator_session": operator_session,
        "created_at": created_at,
        "extensions_json": frappe.as_json(extensions or {"cfg_kanban": {}}),
    }).insert(ignore_permissions=True)
    return _upload_authorization(media, config, confirmation_token)


def confirm_upload(media_id, confirmation_token, permission_checked=False):
    media = _get(media_id)
    _validate_reference(media.reference_doctype, media.reference_name, media.media_class,
                        "write", permission_checked)
    if not hmac.compare_digest(media.confirmation_token_hash or "",
                               _token_hash(confirmation_token or "")):
        frappe.throw("Invalid or expired media confirmation token", frappe.PermissionError)
    if media.status == "available":
        return _metadata(media)
    if media.status != "pending":
        frappe.throw(f"Media cannot be confirmed while it is {media.status}")
    config = _config(media)
    # A transient AWS/network failure leaves the record pending so confirmation can be retried.
    head = _s3_client(config).head_object(Bucket=media.bucket, Key=media.object_key)
    actual_size = cint(head.get("ContentLength"))
    actual_type = (head.get("ContentType") or "").lower()
    actual_metadata = {str(key).lower(): value for key, value in (head.get("Metadata") or {}).items()}
    failure = None
    if actual_size != cint(media.size_bytes) or actual_type != media.content_type:
        failure = "Uploaded object size or content type does not match its authorization"
    if (actual_metadata.get("media-id") != media.media_id or
            actual_metadata.get("app-id") != APP_ID):
        failure = "Uploaded object metadata does not match its authorization"
    remote_checksum = head.get("ChecksumSHA256")
    if media.checksum_value and remote_checksum and media.checksum_value != remote_checksum:
        failure = "Uploaded object checksum does not match"
    if failure:
        media.db_set({"status": "failed", "quarantine_reason": failure}, update_modified=True)
        frappe.throw(failure)
    media.db_set({
        "status": "available", "size_bytes": actual_size,
        "etag": (head.get("ETag") or "").strip('"'),
        "version_id": head.get("VersionId"),
        "checksum_value": remote_checksum or media.checksum_value,
        "confirmed_at": now_datetime(), "quarantine_reason": None,
    }, update_modified=True)
    media.reload()
    return _metadata(media)


def create_view_url(media_id, disposition="inline", permission_checked=False):
    media = _get(media_id)
    _validate_reference(media.reference_doctype, media.reference_name, media.media_class,
                        "read", permission_checked)
    if media.status != "available":
        frappe.throw(f"Media is not available while it is {media.status}")
    config = _config(media)
    filename = media.original_filename.replace('"', "")
    params = {"Bucket": media.bucket, "Key": media.object_key,
              "ResponseContentDisposition": f'{disposition}; filename="{filename}"'}
    if media.version_id:
        params["VersionId"] = media.version_id
    url = _s3_client(config).generate_presigned_url(
        "get_object", Params=params,
        ExpiresIn=config["view_ttl"],
    )
    return {"media_id": media.media_id, "url": url,
            "expires_in": config["view_ttl"], "disposition": disposition}


def delete_object(media_id, mode="archive", permission_checked=False):
    media = _get(media_id)
    _validate_reference(media.reference_doctype, media.reference_name, media.media_class,
                        "write", permission_checked)
    if mode != "archive":
        frappe.only_for(("Manufacturing Manager", "System Manager"))
        frappe.throw("Physical media deletion requires a future approved retention workflow")
    if media.status in ("archived", "deleted"):
        return _metadata(media)
    if media.status not in ("available", "quarantined", "failed"):
        frappe.throw(f"Media cannot be archived while it is {media.status}")
    media.db_set({"status": "archived", "archived_at": now_datetime()}, update_modified=True)
    media.reload()
    return _metadata(media)


def get_metadata(media_id, permission_checked=False):
    media = _get(media_id)
    _validate_reference(media.reference_doctype, media.reference_name, media.media_class,
                        "read", permission_checked)
    return _metadata(media)


def list_reference_media(reference_doctype, reference_name, permission_checked=False,
                         include_archived=False):
    _validate_reference(reference_doctype, reference_name, None, "read", permission_checked)
    statuses = ["available"] if not include_archived else ["available", "archived"]
    rows = frappe.get_all(
        "CFG Kanban Media",
        filters={"reference_doctype": reference_doctype, "reference_name": reference_name,
                 "status": ["in", statuses]},
        fields=["media_id", "status", "media_class", "original_filename", "content_type",
                "size_bytes", "created_by", "created_at", "confirmed_at"],
        order_by="confirmed_at desc, created_at desc",
    )
    return rows


def get_print_media(reference_doctype, reference_name):
    """Jinja-safe metadata list; print output never embeds a durable or signed URL."""
    return frappe.get_all(
        "CFG Kanban Media",
        filters={"reference_doctype": reference_doctype, "reference_name": reference_name,
                 "status": "available"},
        fields=["media_id", "media_class", "original_filename", "content_type",
                "size_bytes", "checksum_algorithm", "checksum_value", "confirmed_at"],
        order_by="confirmed_at asc, creation asc",
    )


def _upload_authorization(media, config, confirmation_token):
    fields = {"Content-Type": media.content_type,
              "x-amz-meta-media-id": media.media_id,
              "x-amz-meta-app-id": APP_ID}
    conditions = [
        {"Content-Type": media.content_type},
        {"x-amz-meta-media-id": media.media_id},
        {"x-amz-meta-app-id": APP_ID},
        ["content-length-range", 1, cint(media.size_bytes)],
    ]
    if media.checksum_value:
        fields["x-amz-checksum-sha256"] = media.checksum_value
        conditions.append({"x-amz-checksum-sha256": media.checksum_value})
    if config.get("kms_key_arn"):
        fields.update({"x-amz-server-side-encryption": "aws:kms",
                       "x-amz-server-side-encryption-aws-kms-key-id": config["kms_key_arn"]})
        conditions.extend([
            {"x-amz-server-side-encryption": "aws:kms"},
            {"x-amz-server-side-encryption-aws-kms-key-id": config["kms_key_arn"]},
        ])
    authorization = _s3_client(config).generate_presigned_post(
        Bucket=media.bucket, Key=media.object_key, Fields=fields,
        Conditions=conditions, ExpiresIn=config["upload_ttl"],
    )
    return {"media_id": media.media_id, "method": "POST", "url": authorization["url"],
            "required_headers": {}, "fields": authorization["fields"],
            "expires_in": config["upload_ttl"], "confirmation_token": confirmation_token}


def _new_confirmation_token(media):
    token = frappe.generate_hash(length=48)
    media.db_set("confirmation_token_hash", _token_hash(token), update_modified=False)
    return token


def _config(media=None):
    required = {
        "region": _setting("MEDIA_S3_REGION"),
        "bucket": media.bucket if media else _setting("MEDIA_S3_BUCKET"),
        "environment": media.environment if media else _setting("MEDIA_ENVIRONMENT"),
        "app_id": _setting("MEDIA_APP_ID") or APP_ID,
        "app_prefix": _setting("MEDIA_APP_PREFIX") or APP_PREFIX,
        "max_size": cint(_setting("MEDIA_MAX_SIZE_BYTES")),
        "retention_class": _setting("MEDIA_DEFAULT_RETENTION_CLASS"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        frappe.throw("Private media storage is not configured: " + ", ".join(missing))
    if required["app_id"] != APP_ID or required["app_prefix"] != APP_PREFIX:
        frappe.throw("Media app identity or prefix does not match the registered cfg_kanban namespace")
    if required["environment"] not in ("production", "staging", "test", "development"):
        frappe.throw("MEDIA_ENVIRONMENT is not registered")
    required.update({
        "upload_ttl": cint(_setting("MEDIA_UPLOAD_URL_TTL_SECONDS") or 300),
        "view_ttl": cint(_setting("MEDIA_VIEW_URL_TTL_SECONDS") or 300),
        "allowed_mime_types": _allowed_mime_types(),
        "kms_key_arn": _setting("MEDIA_KMS_KEY_ARN"),
    })
    return required


def _setting(name):
    deployment_value = frappe.conf.get(name.lower()) or frappe.conf.get(name) or os.environ.get(name)
    if deployment_value not in (None, ""):
        return deployment_value
    fieldname = {
        "MEDIA_S3_REGION": "media_s3_region",
        "MEDIA_S3_BUCKET": "media_s3_bucket",
        "MEDIA_ENVIRONMENT": "media_environment",
        "MEDIA_APP_ID": "media_app_id",
        "MEDIA_APP_PREFIX": "media_app_prefix",
        "MEDIA_UPLOAD_URL_TTL_SECONDS": "media_upload_url_ttl_seconds",
        "MEDIA_VIEW_URL_TTL_SECONDS": "media_view_url_ttl_seconds",
        "MEDIA_MAX_SIZE_BYTES": "media_max_size_bytes",
        "MEDIA_ALLOWED_MIME_TYPES": "media_allowed_mime_types",
        "MEDIA_DEFAULT_RETENTION_CLASS": "media_default_retention_class",
        "MEDIA_KMS_KEY_ARN": "media_kms_key_arn",
    }.get(name)
    if not fieldname:
        return None
    try:
        if not cint(frappe.db.get_single_value("CFG Kanban Settings", "enable_private_media")):
            return None
        return frappe.db.get_single_value("CFG Kanban Settings", fieldname)
    except Exception:
        # Installation and migration can run before the Single DocType table is available.
        return None


def _allowed_mime_types():
    value = _setting("MEDIA_ALLOWED_MIME_TYPES")
    if not value:
        return DEFAULT_MIME_TYPES
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = re.split(r"[,\r\n]+", value)
    return {item.strip().lower() for item in value if item.strip()}


def _s3_client(config):
    try:
        import boto3
    except ImportError:
        frappe.throw("boto3 is required for private media storage")
    return boto3.client("s3", region_name=config["region"])


def _validate_reference(doctype, name, media_class, permission_type, permission_checked):
    if media_class and (media_class not in MEDIA_CLASSES or
                        doctype not in MEDIA_CLASSES[media_class]):
        frappe.throw("Media class is not registered for this business record")
    if not frappe.db.exists(doctype, name):
        frappe.throw("Owning business record was not found")
    if not permission_checked:
        frappe.get_doc(doctype, name).check_permission(permission_type)


def _validate_file(filename, content_type, size_bytes, config):
    if content_type not in config["allowed_mime_types"]:
        frappe.throw("This media content type is not allowed")
    if size_bytes <= 0 or size_bytes > config["max_size"]:
        frappe.throw(f"Media size must be between 1 and {config['max_size']} bytes")
    extension = PurePath(filename).suffix.lower()
    expected = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"},
                "image/webp": {".webp"}, "video/mp4": {".mp4"},
                "application/pdf": {".pdf"}}
    if content_type in expected and extension not in expected[content_type]:
        frappe.throw("Filename extension does not match the declared content type")


def _safe_filename(value):
    value = unicodedata.normalize("NFKC", PurePath(value or "").name)
    value = re.sub(r"[\x00-\x1f\x7f/\\]+", "-", value).strip(" .")[:180]
    if not value:
        frappe.throw("A valid original filename is required")
    return value


def _object_key(config, media_class, doctype, name, media_id, filename, created_at):
    stamp = created_at if isinstance(created_at, datetime) else datetime.now(timezone.utc)
    record_type = re.sub(r"[^a-z0-9]+", "-", doctype.lower()).strip("-")
    record_id = quote(str(name), safe="")
    return (f"{config['environment']}/{APP_PREFIX}/{media_class}/{stamp:%Y}/{stamp:%m}/"
            f"{record_type}/{record_id}/{media_id}/original/{quote(filename, safe='.-_')}")


def _token_hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _get(media_id):
    name = frappe.db.get_value("CFG Kanban Media", {"media_id": media_id}, "name")
    if not name:
        frappe.throw("Media record was not found")
    return frappe.get_doc("CFG Kanban Media", name)


def _assert_same_request(media, doctype, name, filename, content_type, size_bytes, media_class):
    expected = (doctype, name, filename, content_type, cint(size_bytes), media_class)
    actual = (media.reference_doctype, media.reference_name, media.original_filename,
              media.content_type, cint(media.size_bytes), media.media_class)
    if actual != expected:
        frappe.throw("Upload idempotency key was already used for different media")


def _metadata(media):
    return {field: media.get(field) for field in (
        "media_id", "app_id", "environment", "bucket", "object_key", "media_class",
        "reference_doctype", "reference_name", "original_filename", "content_type",
        "size_bytes", "checksum_algorithm", "checksum_value", "etag", "version_id",
        "status", "created_by", "created_at", "confirmed_at", "retention_class",
        "access_classification", "operator_employee", "operator_session", "archived_at",
        "deleted_at",
    )}

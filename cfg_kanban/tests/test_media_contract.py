import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestSharedMediaContract(TestCase):
    def test_media_schema_contains_cross_app_required_metadata(self):
        path = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_media" /
                "cfg_kanban_media.json")
        schema = json.loads(path.read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        required = {
            "media_id", "app_id", "environment", "bucket", "object_key", "media_class",
            "reference_doctype", "reference_name", "original_filename", "content_type",
            "size_bytes", "checksum_algorithm", "checksum_value", "etag", "version_id",
            "status", "created_by", "created_at", "confirmed_at", "retention_class",
            "access_classification", "upload_idempotency_key",
            "operator_employee", "operator_session",
        }
        self.assertTrue(required.issubset(fields))
        self.assertEqual(fields["upload_idempotency_key"].get("unique"), 1)
        self.assertEqual(fields["object_key"].get("read_only"), 1)
        self.assertEqual(
            fields["status"]["options"].splitlines(),
            ["pending", "available", "quarantined", "archived", "deleting", "deleted", "failed"],
        )

    def test_service_uses_registered_namespace_and_direct_s3_contract(self):
        source = (ROOT / "services" / "media.py").read_text()
        self.assertIn('APP_ID = "cfg_kanban"', source)
        self.assertIn('APP_PREFIX = "cfg-kanban"', source)
        self.assertIn("generate_presigned_post", source)
        self.assertIn("head_object", source)
        self.assertIn('endpoint_url=f"https://s3.{region}.amazonaws.com"', source)
        self.assertIn('signature_version="s3v4"', source)
        self.assertIn('"addressing_style": "virtual"', source)
        self.assertIn('actual_metadata.get("media-id")', source)
        self.assertIn('["content-length-range", 1, cint(media.size_bytes)]', source)
        self.assertNotIn("presigned_url\"", source)

    def test_service_task_ui_uploads_directly_and_confirms(self):
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("Take Timestamped Photo", console)
        self.assertIn("Upload Photo / PDF / File", console)
        self.assertIn("get_execution_geotag", console)
        self.assertIn("archive_task_media", console)
        self.assertIn("new FormData()", console)
        self.assertIn("fetch(upload.url", console)
        self.assertIn("confirm_task_upload", console)
        self.assertIn("create_task_view_url", console)

    def test_process_task_supports_private_qc_evidence(self):
        api = (ROOT / "api" / "media.py").read_text()
        operator = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                    "kanban_operator.js").read_text()
        self.assertIn("create_process_task_upload_url", api)
        self.assertIn("confirm_process_task_upload", api)
        self.assertIn("process-task-evidence", (ROOT / "services" / "media.py").read_text())
        self.assertIn("Take Timestamped Photo", operator)
        self.assertIn("Upload Photo / PDF / File", operator)
        self.assertIn("process_execution_geotag", operator)
        self.assertIn("archive_process_task_media", operator)
        self.assertIn("confirm_process_task_upload", operator)

    def test_execution_camera_evidence_has_server_time_geotag_and_recoverable_remove(self):
        api = (ROOT / "api" / "media.py").read_text()
        service = (ROOT / "services" / "media.py").read_text()
        self.assertIn("get_task_camera_stamp", api)
        self.assertIn("get_process_task_camera_stamp", api)
        self.assertIn("Geolocation is required", api)
        self.assertIn('"geotag"', api)
        self.assertIn("archive_task_media", api)
        self.assertIn("archive_process_task_media", api)
        self.assertIn('"capture_timestamp"', service)
        self.assertIn('"extensions_json"', service)

    def test_task_form_exposes_private_thumbnail_gallery(self):
        form = (ROOT / "public" / "js" / "cfg_kanban_task.js").read_text()
        self.assertIn("get_reference_gallery", form)
        self.assertIn("preview_url", form)
        self.assertIn("Open Original", form)
        self.assertIn("operator_employee", form)
        schema = json.loads((ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_task" /
                             "cfg_kanban_task.json").read_text())
        fields = {row["fieldname"] for row in schema["fields"]}
        self.assertIn("media_evidence_html", fields)

    def test_media_configuration_is_deployment_owned_and_fail_closed(self):
        source = (ROOT / "services" / "media.py").read_text()
        for setting in ("MEDIA_S3_REGION", "MEDIA_S3_BUCKET", "MEDIA_ENVIRONMENT",
                        "MEDIA_MAX_SIZE_BYTES", "MEDIA_DEFAULT_RETENTION_CLASS"):
            self.assertIn(setting, source)
        self.assertIn("Private media storage is not configured", source)

    def test_media_configuration_has_restricted_erpnext_ui(self):
        path = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_settings" /
                "cfg_kanban_settings.json")
        schema = json.loads(path.read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertIn("enable_private_media", fields)
        self.assertIn("media_s3_bucket", fields)
        self.assertIn("media_allowed_mime_types", fields)
        roles = {row["role"] for row in schema["permissions"]}
        self.assertEqual(roles, {"CFG Kanban System Maintenance"})
        self.assertNotIn("aws_access_key_id", fields)
        self.assertNotIn("aws_secret_access_key", fields)

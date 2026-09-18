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
        self.assertIn("Take Photo / Add Evidence", console)
        self.assertIn("new FormData()", console)
        self.assertIn("fetch(upload.url", console)
        self.assertIn("confirm_task_upload", console)
        self.assertIn("create_task_view_url", console)

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

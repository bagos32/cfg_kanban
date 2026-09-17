import json

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class CFGKanbanSettings(Document):
    def validate(self):
        self._validate_media_storage()

    def _validate_media_storage(self):
        self.media_app_id = "cfg_kanban"
        self.media_app_prefix = "cfg-kanban"
        if not self.enable_private_media:
            self.media_configuration_status = "Disabled"
            return
        required = {
            "AWS Region": self.media_s3_region,
            "Private S3 Bucket": self.media_s3_bucket,
            "Environment": self.media_environment,
            "Maximum Upload Size": self.media_max_size_bytes,
            "Retention Class": self.media_default_retention_class,
            "Allowed MIME Types": self.media_allowed_mime_types,
        }
        missing = [label for label, value in required.items() if not value]
        if missing:
            frappe.throw("Complete the Private Media fields: " + ", ".join(missing))
        if self.media_environment not in ("production", "staging", "test", "development"):
            frappe.throw("Private Media Environment must use a registered environment")
        if cint(self.media_max_size_bytes) <= 0:
            frappe.throw("Maximum Upload Size must be greater than zero")
        for fieldname in ("media_upload_url_ttl_seconds", "media_view_url_ttl_seconds"):
            value = cint(self.get(fieldname))
            if value < 60 or value > 900:
                frappe.throw(f"{self.meta.get_label(fieldname)} must be between 60 and 900 seconds")
        self.media_allowed_mime_types = _normalise_mime_types(self.media_allowed_mime_types)
        self.media_configuration_status = "Configured"


def _normalise_mime_types(value):
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            values = decoded if isinstance(decoded, list) else [decoded]
        except ValueError:
            values = value.replace(",", "\n").splitlines()
    else:
        values = value or []
    cleaned = sorted({str(item).strip().lower() for item in values if str(item).strip()})
    invalid = [item for item in cleaned if "/" not in item or " " in item]
    if invalid:
        frappe.throw("Invalid allowed MIME type: " + ", ".join(invalid))
    return "\n".join(cleaned)

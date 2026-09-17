# CFG Kanban Shared Media Storage Conformance

The approved **Shared Media Storage Architecture — Cross-App Source of Truth**, architecture
version 1.0 effective 17 September 2026, governs this implementation. This note records the
Kanban-specific mapping and does not redefine that contract.

## Ownership and boundaries

- App ID: `cfg_kanban`; registered object prefix: `cfg-kanban`.
- AWS S3 is authoritative for binary content. `CFG Kanban Media` stores metadata and lifecycle
  state only; it never stores a durable presigned URL.
- Upload and download bytes move directly between the browser/mobile client and private S3.
- CFG Kanban authorizes access through the current owning business record and operator session.
- TrackQMS and other apps are not runtime dependencies. Cross-app exchange uses `media_id` and
  approved metadata, never another app's key or URL.

## Registered V1 media classes

| Media class | Allowed owning records |
|---|---|
| `maintenance-evidence` | CFG Kanban Task |
| `process-task-evidence` | CFG Kanban Process Task |
| `incident-evidence` | CFG Kanban Exception |
| `production-evidence` | CFG Kanban Cycle, CFG Kanban Operation Progress |

The Service Task mobile panel implements direct upload and confirmation for
`maintenance-evidence`. The service/API contract supports the other registered classes for later
business-screen integration without changing object identity or metadata.

## Restricted ERPNext configuration

Open **CFG Kanban Settings → Private Media Storage** as Administrator or a user assigned the
**CFG Kanban System Maintenance** role. The form manages the non-secret storage
configuration, validates registered values, and records changes in the document timeline. Ordinary
operators, service supervisors, and manufacturing users cannot access this configuration.

The form manages these contract values:

```text
MEDIA_S3_REGION
MEDIA_S3_BUCKET
MEDIA_ENVIRONMENT
MEDIA_APP_ID=cfg_kanban
MEDIA_APP_PREFIX=cfg-kanban
MEDIA_UPLOAD_URL_TTL_SECONDS
MEDIA_VIEW_URL_TTL_SECONDS
MEDIA_MAX_SIZE_BYTES
MEDIA_ALLOWED_MIME_TYPES
MEDIA_DEFAULT_RETENTION_CLASS
MEDIA_KMS_KEY_ARN (when required)
```

The app remains installable while Private Media Storage is disabled, but every upload/view operation
fails closed until it is enabled and configured. AWS credentials come from the server workload role
or a development-only named credential mechanism. They are never entered in the ERPNext screen,
returned to clients, or stored in Frappe records.

Environment variables or `site_config.json` values with the same names remain supported as
deployment-level emergency overrides. A defined override takes precedence over the ERPNext value;
maintenance users therefore do not need server file-system access for normal administration.

An optional deployment-override fragment (with no credential material) is:

```json
{
  "media_s3_region": "ap-southeast-1",
  "media_s3_bucket": "replace-with-approved-private-bucket",
  "media_environment": "development",
  "media_app_id": "cfg_kanban",
  "media_app_prefix": "cfg-kanban",
  "media_upload_url_ttl_seconds": 300,
  "media_view_url_ttl_seconds": 300,
  "media_max_size_bytes": 26214400,
  "media_allowed_mime_types": [
    "image/jpeg", "image/png", "image/webp", "video/mp4", "application/pdf"
  ],
  "media_default_retention_class": "operational-evidence"
}
```

The signer role must be limited to the registered environment prefix, for example
`development/cfg-kanban/*`. Keep S3 Block Public Access enabled, require TLS, enable bucket
versioning and encryption, and restrict CORS to the exact ERPNext origin with only the required
`POST`, `GET`, and `HEAD` methods and request headers. S3 lifecycle policy should remove abandoned
pending uploads and multipart parts without deleting objects still marked available in Frappe.

## V1 lifecycle

```text
pending -> available -> archived
    |            |
    v            v
  failed      quarantined
```

Physical deletion is intentionally blocked until retention classes, holds, version-aware deletion,
and operations approval are implemented. Pending-object cleanup, multipart video, malware scanning,
derivatives, reconciliation, and physical deletion remain controlled follow-on work.

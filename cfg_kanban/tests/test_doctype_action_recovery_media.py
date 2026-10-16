import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestDocTypeActionRecoveryMedia(TestCase):
    def test_action_run_pins_safe_media_registry_references(self):
        schema_path = (
            ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_doctype_action_run" /
            "cfg_kanban_doctype_action_run.json"
        )
        schema = json.loads(schema_path.read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["evidence_reference_count"]["fieldtype"], "Int")
        self.assertEqual(fields["evidence_snapshot_on"]["fieldtype"], "Datetime")
        self.assertEqual(fields["evidence_references"]["options"], "JSON")
        self.assertEqual(fields["evidence_references"]["read_only"], 1)

        source = (ROOT / "services" / "doctype_action_media.py").read_text()
        self.assertIn('"CFG Kanban Task", task.name', source)
        self.assertIn('ACTION_RUN_DOCTYPE, run.name', source)
        self.assertIn('row.get("status") != "available"', source)
        self.assertIn('row.get("media_class") != expected_class', source)
        self.assertIn('ACTION_MEDIA_CLASS = "doctype-action-evidence"', source)
        self.assertIn('"media_id": row.get("media_id")', source)
        self.assertNotIn("create_view_url", source)
        self.assertNotIn("object_key", source)

    def test_writer_snapshots_evidence_before_target_write(self):
        writer = (ROOT / "services" / "doctype_action_writer.py").read_text()
        snapshot_at = writer.index("snapshot_action_evidence(run, source)")
        insert_at = writer.index("target.insert()")
        self.assertLess(snapshot_at, insert_at)
        self.assertIn('"evidence": evidence_for_operator_form(run, source)', writer)
        self.assertIn('"evidence_controls": action_evidence_controls(run)', writer)
        self.assertIn('"recovery": recovery_context(run, profile)', writer)

    def test_direct_action_evidence_is_mutable_only_before_snapshot(self):
        service = (ROOT / "services" / "doctype_action_media.py").read_text()
        api = (ROOT / "api" / "media.py").read_text()
        self.assertIn('MUTABLE_EVIDENCE_STATES = {"Form In Progress", "Ready to Post", "Failed"}', service)
        self.assertIn('statuses=("pending", "available", "quarantined", "failed")', service)
        self.assertIn("_assert_no_pending_action_media(run)", service)
        self.assertIn("def create_action_run_upload_url", api)
        self.assertIn("def confirm_action_run_upload", api)
        self.assertIn("def archive_action_run_media", api)
        self.assertIn("get_locked_run(run_name)", api)
        self.assertIn('run.get("evidence_snapshot_on")', api)
        self.assertIn('"CFG Kanban DocType Action Run", run.name', api)
        self.assertIn('"doctype-action-evidence"', api)

    def test_recovery_reuses_run_and_exact_target(self):
        source = (ROOT / "services" / "doctype_action_runs.py").read_text()
        api = (ROOT / "api" / "doctype_action_run.py").read_text()
        self.assertIn("def recover_run(", source)
        self.assertIn('resolution not in {"Return to Form", "Recheck Linked Target"}', source)
        self.assertIn("_authorized_supervisor(run, operator_session_token)", source)
        self.assertIn("target.check_permission(\"read\")", source)
        self.assertIn('new_state = "Submitted" if cint(target.docstatus) == 1 else "Draft Created"', source)
        self.assertNotIn("target.insert()", source[source.index("def recover_run("):source.index("def recovery_context(")])
        self.assertIn("def recover(run_name, resolution, reason", api)
        self.assertIn('@frappe.whitelist(methods=["POST"])', api)

    def test_service_and_supervisor_pages_expose_controlled_recovery(self):
        tasks = (
            ROOT / "cfg_kanban" / "page" / "kanban_tasks" / "kanban_tasks.js"
        ).read_text()
        supervisor = (
            ROOT / "cfg_kanban" / "page" / "kanban_supervisor" /
            "kanban_supervisor.js"
        ).read_text()
        supervisor_api = (ROOT / "api" / "supervisor.py").read_text()
        self.assertIn("Linked Private Evidence", tasks)
        self.assertIn("Action Run Private Evidence", tasks)
        self.assertIn("Open Evidence", tasks)
        self.assertIn("Take Timestamped Photo", tasks)
        self.assertIn("create_action_run_upload_url", tasks)
        self.assertIn("Action attempt history", tasks)
        self.assertIn("cfg_kanban.api.doctype_action_run.recover", tasks)
        self.assertIn("Document Action Recovery", supervisor)
        self.assertIn('"action_recoveries"', supervisor_api)
        self.assertIn("def _doctype_action_recoveries", supervisor_api)

    def test_draft_created_submit_policy_can_resume_same_draft(self):
        tasks = (
            ROOT / "cfg_kanban" / "page" / "kanban_tasks" / "kanban_tasks.js"
        ).read_text()
        self.assertIn('run.state === "Draft Created" && form.posting_policy === "Save Draft"', tasks)
        writer = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("target = _update_existing_draft(target, payload, configuration)", writer)


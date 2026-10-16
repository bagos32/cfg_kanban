import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestDocTypeActionRunFoundation(TestCase):
    def _schema(self, folder):
        return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())

    def test_runs_and_attempts_are_system_created_read_only_records(self):
        for folder in (
            "cfg_kanban_doctype_action_run",
            "cfg_kanban_doctype_action_attempt",
        ):
            schema = self._schema(folder)
            for permission in schema["permissions"]:
                self.assertEqual(permission.get("read"), 1)
                self.assertNotIn("create", permission)
                self.assertNotIn("write", permission)
                self.assertNotIn("delete", permission)
            controller = (DOCTYPE_ROOT / folder / f"{folder}.py").read_text()
            self.assertIn("doctype_action_engine_insert", controller)

    def test_run_and_attempt_identities_have_database_unique_guards(self):
        run = self._schema("cfg_kanban_doctype_action_run")
        run_fields = {row["fieldname"]: row for row in run["fields"]}
        self.assertEqual(run_fields["action_id"]["unique"], 1)
        self.assertEqual(run_fields["idempotency_key"]["unique"], 1)
        self.assertEqual(run_fields["mapping_snapshot"]["options"], "JSON")

        attempt = self._schema("cfg_kanban_doctype_action_attempt")
        attempt_fields = {row["fieldname"]: row for row in attempt["fields"]}
        self.assertEqual(attempt_fields["attempt_id"]["unique"], 1)
        self.assertEqual(attempt_fields["retry_token_hash"]["unique"], 1)
        self.assertEqual(attempt_fields["idempotency_key"]["unique"], 1)

    def test_runtime_is_locked_idempotent_and_deliberately_non_posting(self):
        service = (ROOT / "services" / "doctype_action_runs.py").read_text()
        self.assertIn('canonical_key(', service)
        self.assertIn('"doctype-action-run-v1"', service)
        self.assertIn("insert_once(run, run_key", service)
        self.assertIn("FOR UPDATE", service)
        self.assertIn("executable_profile_snapshot", service)
        self.assertIn("mapping_snapshot", service)
        self.assertIn("operator_employee", service)
        self.assertIn("terminal_user", service)
        self.assertIn("sanitize_error", service)
        self.assertIn("assert_pinned_snapshot_compatible", service)
        self.assertIn("metadata_fingerprint", service)
        self.assertIn("Gate 1B intentionally stops", service)
        self.assertNotIn(".submit()", service)
        self.assertNotIn('"doctype": run.target_doctype', service)

    def test_recovery_requires_operator_override_and_preserves_linked_targets(self):
        service = (ROOT / "services" / "doctype_action_runs.py").read_text()
        api = (ROOT / "api" / "doctype_action_run.py").read_text()
        ui = (ROOT / "public" / "js" / "cfg_kanban_doctype_action_run.js").read_text()
        self.assertIn('require_operator(operator_session_token, "override")', service)
        self.assertIn("if run.target_name", service)
        self.assertIn("cannot be silently cancelled", service)
        self.assertIn("cancellation reason is required", service.lower())
        self.assertIn("operator_session_token", api)
        self.assertIn("retry_token", api)
        self.assertIn("Cancel Run with Reason", ui)
        self.assertIn("Mark Needs Reconciliation", ui)
        self.assertIn("cfg_kanban_operator_session", ui)

    def test_service_task_and_events_link_to_the_action_run(self):
        task = self._schema("cfg_kanban_task")
        task_fields = {row["fieldname"]: row for row in task["fields"]}
        self.assertEqual(
            task_fields["doctype_action_run"]["options"],
            "CFG Kanban DocType Action Run",
        )
        event = self._schema("cfg_kanban_event")
        event_fields = {row["fieldname"]: row for row in event["fields"]}
        self.assertEqual(
            event_fields["action_run"]["options"],
            "CFG Kanban DocType Action Run",
        )
        events = (ROOT / "services" / "events.py").read_text()
        self.assertIn("action_run=None", events)
        self.assertIn('"action_run": action_run', events)

    def test_every_locked_lifecycle_state_is_declared(self):
        run = self._schema("cfg_kanban_doctype_action_run")
        state = next(row for row in run["fields"] if row["fieldname"] == "state")
        self.assertEqual(
            set(state["options"].splitlines()),
            {
                "Form In Progress", "Ready to Post", "Posting", "Draft Created",
                "Submitted", "Failed", "Skipped by Condition",
                "Needs Reconciliation", "Cancelled",
            },
        )

import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestDocTypeActionWriter(TestCase):
    def _schema(self, folder):
        return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())

    def test_action_run_retains_validated_operator_payload(self):
        run = self._schema("cfg_kanban_doctype_action_run")
        fields = {row["fieldname"]: row for row in run["fields"]}
        self.assertEqual(fields["form_payload"]["options"], "JSON")
        self.assertEqual(fields["form_payload"]["read_only"], 1)
        self.assertEqual(fields["form_payload_hash"]["read_only"], 1)
        self.assertEqual(fields["last_input_by"]["options"], "Employee")
        self.assertEqual(fields["last_input_on"]["fieldtype"], "Datetime")

        attempt = self._schema("cfg_kanban_doctype_action_attempt")
        attempt_type = next(
            row for row in attempt["fields"] if row["fieldname"] == "attempt_type"
        )
        self.assertIn("Post", attempt_type["options"].splitlines())

    def test_writer_uses_pinned_metadata_and_allowlisted_inputs(self):
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("assert_pinned_snapshot_compatible(run)", source)
        self.assertIn("_reject_extra_keys(operator_values, allowed_parent", source)
        self.assertIn("_reject_extra_keys(child_rows, set(table_configs)", source)
        self.assertIn("frappe.get_meta(run.target_doctype)", source)
        self.assertIn("MAX_TEXT_LENGTH", source)
        self.assertIn("max_child_rows", source)
        self.assertIn("_condition_matches", source)
        self.assertIn('target.set(mapping["fieldname"], None)', source)
        self.assertIn('target.set(table["table_fieldname"], [])', source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)

    def test_destination_writes_use_terminal_user_permissions(self):
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("_assert_create_permission(run.target_doctype)", source)
        self.assertIn('target.check_permission("write")', source)
        self.assertIn('target.check_permission("submit")', source)
        self.assertIn("target.insert()", source)
        self.assertIn("target.save()", source)
        self.assertIn("target.submit()", source)
        self.assertNotIn("ignore_permissions=True", source)

    def test_one_target_is_linked_before_submit_and_reused_on_retry(self):
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        insert_at = source.index("target.insert()")
        link_at = source.index("_link_target(run, target)", insert_at)
        submit_at = source.index("target.submit()")
        self.assertLess(insert_at, link_at)
        self.assertLess(link_at, submit_at)
        self.assertIn("if run.target_name and run.target_name != target.name", source)
        self.assertIn('if run.state == "Failed"', source)
        self.assertIn('"draft-restored"', source)

    def test_uncertain_or_external_target_states_require_reconciliation(self):
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("if run.target_name and not existing_target", source)
        self.assertIn("target document linked to this Action Run no longer exists", source)
        self.assertIn("linked target document is cancelled", source)
        self.assertIn("linked target was submitted outside", source)
        self.assertIn('run.state == "Posting"', source)
        self.assertIn("_reconciliation_result", source)

    def test_posting_is_idempotent_and_audited_without_raw_tokens(self):
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("get_attempt_for_retry_token(retry_token)", source)
        self.assertIn('canonical_key("doctype-action-writer-v1"', source)
        self.assertIn('record_run_attempt(\n            run, "Post", "Succeeded"', source)
        self.assertIn('record_run_attempt(\n            current, "Post", "Failed"', source)
        self.assertNotIn('"retry_token": retry_token', source)

    def test_runtime_api_exposes_only_authorized_form_and_post_actions(self):
        api = (ROOT / "api" / "doctype_action_run.py").read_text()
        source = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.assertIn("def get_operator_form(run_name, operator_session_token)", api)
        self.assertIn("def post(run_name, operator_session_token, retry_token", api)
        self.assertIn('@frappe.whitelist(methods=["POST"])', api)
        self.assertIn("authorize_run_actor(run, operator_session_token)", source)
        self.assertIn("terminal_user", (ROOT / "services" / "doctype_action_runs.py").read_text())

    def test_operator_form_supports_safe_dynamic_parent_and_child_inputs(self):
        writer = (ROOT / "services" / "doctype_action_writer.py").read_text()
        page = (
            ROOT / "cfg_kanban" / "page" / "kanban_tasks" / "kanban_tasks.js"
        ).read_text()
        self.assertIn('"condition_context": _condition_context_for_form(', writer)
        self.assertIn('"source_type": mapping.get("source_type")', writer)
        self.assertIn('"visible": bool(visible)', writer)
        self.assertIn("_condition_fieldnames", writer)
        self.assertIn(
            "cfg_kanban.api.doctype_action_run.get_operator_form", page
        )
        self.assertIn("mount_action_child_table", page)
        self.assertIn("action_condition_matches", page)
        self.assertIn("Complete Required Document", page)
        self.assertIn("cfg_kanban.api.doctype_action_run.post", page)
        self.assertIn("dialog.__cfg_action_retry_token", page)

    def test_run_creator_can_finish_exact_run_after_task_status_transition(self):
        runs = (ROOT / "services" / "doctype_action_runs.py").read_text()
        self.assertIn("_assert_task_access(task, profile, run=run)", runs)
        self.assertIn("run.operator_employee == profile.employee", runs)
        self.assertIn("workstation_allowed(task.workstation, profile)", runs)


import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestDocTypeActionTaskBinding(TestCase):
    def _schema(self, folder):
        return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())

    def test_schedule_has_optional_profile_trigger_and_required_gate(self):
        schema = self._schema("cfg_kanban_task_schedule")
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(
            fields["doctype_action_profile"]["options"],
            "CFG Kanban DocType Action Profile",
        )
        self.assertEqual(
            set(fields["doctype_action_trigger"]["options"].splitlines()),
            {
                "", "On Task Start", "On Task Complete",
                "After Supervisor Verification",
            },
        )
        self.assertEqual(fields["doctype_action_required"]["default"], "0")
        self.assertEqual(fields["doctype_action_profile"]["permlevel"], 1)
        level_one_roles = {
            row["role"] for row in schema["permissions"]
            if row.get("permlevel") == 1 and row.get("write")
        }
        self.assertEqual(
            level_one_roles,
            {"System Manager", "CFG Kanban System Maintenance"},
        )
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_task_schedule" /
            "cfg_kanban_task_schedule.py"
        ).read_text()
        binding = (ROOT / "services" / "doctype_action_tasks.py").read_text()
        self.assertIn("assert_schedule_binding_authorized(self)", controller)
        self.assertIn("require_configuration_role()", binding)

    def test_generated_task_snapshots_schedule_binding(self):
        task = self._schema("cfg_kanban_task")
        fields = {row["fieldname"]: row for row in task["fields"]}
        self.assertEqual(
            fields["doctype_action_profile"]["options"],
            "CFG Kanban DocType Action Profile",
        )
        self.assertEqual(fields["doctype_action_profile"]["read_only"], 1)
        self.assertEqual(fields["doctype_action_trigger"]["read_only"], 1)
        self.assertEqual(fields["doctype_action_required"]["read_only"], 1)
        self.assertIn(
            "Pending Document Posting",
            fields["status"]["options"].splitlines(),
        )
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        self.assertIn("task_values.update(occurrence_snapshot(schedule))", service)
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_task" / "cfg_kanban_task.py"
        ).read_text()
        self.assertIn("effective DocType Action binding is immutable", controller)

    def test_exact_service_task_events_resolve_one_action_run(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        binding = (ROOT / "services" / "doctype_action_tasks.py").read_text()
        self.assertIn('resolve_for_task_event(task, "On Task Start"', service)
        self.assertIn('resolve_for_task_event(task, "On Task Complete"', service)
        self.assertIn(
            'resolve_for_task_event(task, "After Supervisor Verification"',
            service,
        )
        self.assertIn('"On Task Start": "Task Start"', binding)
        self.assertIn('"On Task Complete": "Task Complete"', binding)
        self.assertIn(
            '"After Supervisor Verification": "Supervisor Verification"',
            binding,
        )
        self.assertIn("resolve_task_run(", binding)
        self.assertIn("Start this Service Task before completing", service)

    def test_required_action_uses_explicit_pending_state_and_truthful_release(self):
        service = (ROOT / "services" / "doctype_action_tasks.py").read_text()
        writer = (ROOT / "services" / "doctype_action_writer.py").read_text()
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_task" / "cfg_kanban_task.py"
        ).read_text()
        self.assertIn('task.status = "Pending Document Posting"', service)
        self.assertIn("SATISFIED_BY_POSTING_POLICY", service)
        self.assertIn('"Save Draft": {"Draft Created", "Submitted"', service)
        self.assertIn('"Submit When Authorized": {"Submitted"', service)
        self.assertIn("release_task_gate(run, profile, session)", writer)
        self.assertIn("frappe.db.savepoint(savepoint)", writer)
        self.assertIn("frappe.db.rollback(save_point=savepoint)", writer)
        self.assertIn("required DocType Action is not ready", controller)

    def test_schedule_rejects_premature_or_unverified_submission(self):
        service = (ROOT / "services" / "doctype_action_tasks.py").read_text()
        self.assertIn("On Task Start may only Save Draft", service)
        self.assertIn("must run After Supervisor Verification", service)
        self.assertIn("cannot submit its target On Task Complete", service)

    def test_task_disposition_cancels_only_through_controlled_run_recovery(self):
        tasks = (ROOT / "services" / "standalone_tasks.py").read_text()
        binding = (ROOT / "services" / "doctype_action_tasks.py").read_text()
        self.assertIn("cancel_task_action(task, session_token, reason)", tasks)
        self.assertIn("cancel_run(", binding)
        self.assertIn("operator_session_token", binding)

    def test_task_events_retain_action_run_trace(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        self.assertIn("action_run=task.doctype_action_run", service)

    def test_production_process_task_schema_is_not_bound_to_action_profiles(self):
        process = self._schema("cfg_kanban_process_execution")
        fieldnames = {row["fieldname"] for row in process["fields"]}
        self.assertNotIn("doctype_action_profile", fieldnames)
        self.assertNotIn("doctype_action_run", fieldnames)

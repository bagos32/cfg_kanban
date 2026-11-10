import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestOperationMaterialRunContract(unittest.TestCase):
    def test_operation_profile_exposes_optional_high_frequency_control(self):
        profile = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_operation_profile" /
             "cfg_kanban_operation_profile.json").read_text()
        )
        fields = {row["fieldname"]: row for row in profile["fields"]}
        self.assertEqual(fields["material_run_control"]["default"], "Disabled")
        self.assertIn("Required Before Progress", fields["material_run_control"]["options"])
        self.assertIn("Every Material Run", fields["material_run_output_boundary"]["options"])
        self.assertEqual(fields["allow_material_carry_forward"]["default"], "1")
        self.assertIn("At Job Card End", fields["material_run_settlement_timing"]["options"])

    def test_execution_snapshots_material_run_policy(self):
        execution = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_process_execution" /
             "cfg_kanban_process_execution.json").read_text()
        )
        fields = {row["fieldname"]: row for row in execution["fields"]}
        self.assertEqual(fields["material_run_control"]["default"], "Disabled")
        self.assertEqual(
            fields["open_material_run"]["options"],
            "CFG Kanban Operation Material Run",
        )
        feedback = (ROOT / "integrations" / "erp_feedback.py").read_text()
        selector = (ROOT / "services" / "runtime_selector.py").read_text()
        for source in (feedback, selector):
            self.assertIn('"material_run_control": profile.material_run_control', source)
            self.assertIn('"material_run_output_boundary": profile.material_run_output_boundary', source)

    def test_material_run_is_immutable_and_concurrency_guarded(self):
        schema = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_operation_material_run" /
             "cfg_kanban_operation_material_run.json").read_text()
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["active_execution_key"]["unique"], 1)
        self.assertEqual(fields["idempotency_key"]["unique"], 1)
        controller = (DOCTYPE_ROOT / "cfg_kanban_operation_material_run" /
                      "cfg_kanban_operation_material_run.py").read_text()
        self.assertIn("Material Run audit records cannot be deleted", controller)
        self.assertIn("IMMUTABLE_CONTEXT_FIELDS", controller)

    def test_scanner_lifecycle_is_global_printable_and_focus_safe(self):
        api = (ROOT / "api" / "operator.py").read_text()
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                 "kanban_operator.js").read_text()
        service = (ROOT / "services" / "operation_material_runs.py").read_text()
        self.assertIn("CFG:CMD:START_MATERIAL_RUN", api)
        self.assertIn("CFG:CMD:CANCEL_MATERIAL_RUN", api)
        self.assertIn("START_MATERIAL_RUN: open_material_run_dialog", panel)
        self.assertIn("CANCEL_MATERIAL_RUN: cancel_open_material_run", panel)
        self.assertIn("CFG:SELECT:n", panel)
        self.assertIn("bind_confirmation_scanner(dialog, true, values", panel)
        self.assertIn('dialog.get_field("scanner_command").set_focus()', panel)
        self.assertIn("row.material_run_context", panel)
        self.assertNotIn(
            'method: "cfg_kanban.services.operation_material_runs.get_material_run_context"',
            panel,
        )
        self.assertIn("def start_scanner_run", service)
        self.assertIn("def cancel_scanner_run", service)
        self.assertIn("def close_run_with_progress", service)
        self.assertIn('ACTIVE_EXECUTION_STATES = {"In Progress", "Paused"}', service)
        self.assertIn('canonical_key("operation-material-run"', service)

    def test_current_package_does_not_post_erp_stock(self):
        service = (ROOT / "services" / "operation_material_runs.py").read_text()
        self.assertNotIn("Stock Entry", service)
        self.assertNotIn("post_quantity_event", service)
        self.assertIn("ERPNext remains the manufacturing and stock system of record", service)

    def test_progress_links_and_closes_an_open_run(self):
        progress_schema = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_operation_progress" /
             "cfg_kanban_operation_progress.json").read_text()
        )
        fields = {row["fieldname"]: row for row in progress_schema["fields"]}
        self.assertEqual(
            fields["material_run"]["options"],
            "CFG Kanban Operation Material Run",
        )
        operator = (ROOT / "api" / "operator.py").read_text()
        progress = (ROOT / "services" / "progress.py").read_text()
        self.assertIn("material_run = open_run_for_execution(execution.name)", operator)
        self.assertIn("close_run_with_progress(", progress)


if __name__ == "__main__":
    unittest.main()

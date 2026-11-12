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
        self.assertTrue(fields["material_run_rules_json"]["hidden"])
        feedback = (ROOT / "integrations" / "erp_feedback.py").read_text()
        selector = (ROOT / "services" / "runtime_selector.py").read_text()
        for source in (feedback, selector):
            self.assertIn('"material_run_control": profile.material_run_control', source)
            self.assertIn('"material_run_output_boundary": profile.material_run_output_boundary', source)
            self.assertIn('"material_run_rules_json": build_material_run_rule_snapshot', source)

    def test_material_flow_rule_opts_in_without_changing_simple_materials(self):
        schema = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_material_flow_rule" /
             "cfg_kanban_material_flow_rule.json").read_text()
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["material_run_tracking_mode"]["default"], "No Run Tracking")
        self.assertIn("Source Tag Quantity", fields["material_run_tracking_mode"]["options"])
        self.assertEqual(fields["material_run_scan_warehouse"]["options"], "Warehouse")
        self.assertEqual(fields["material_run_qty_per_output"]["read_only"], 1)
        master = (DOCTYPE_ROOT / "cfg_kanban_master" / "cfg_kanban_master.py").read_text()
        self.assertIn("material_run_qty_per_output", master)
        self.assertIn("exact-serial Material Run package", master)
        self.assertIn("Material Run Source Tag Quantity currently requires", master)

    def test_material_draw_is_immutable_and_does_not_mutate_stock(self):
        schema = json.loads(
            (DOCTYPE_ROOT / "cfg_kanban_operation_material_draw" /
             "cfg_kanban_operation_material_draw.json").read_text()
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["source_handling_unit"]["options"], "CFG Kanban Handling Unit")
        self.assertEqual(fields["idempotency_key"]["unique"], 1)
        self.assertIn("Carry Forward", fields["status"]["options"])
        controller = (DOCTYPE_ROOT / "cfg_kanban_operation_material_draw" /
                      "cfg_kanban_operation_material_draw.py").read_text()
        self.assertIn("Operation Material Draw identity is immutable", controller)
        self.assertIn("cannot be deleted", controller)

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
        self.assertIn("def preview_material_draw", service)
        self.assertIn("def validate_progress_materials", service)
        self.assertIn("def apply_progress_material_plan", service)
        self.assertIn('ACTIVE_EXECUTION_STATES = {"In Progress", "Paused"}', service)
        self.assertIn('canonical_key("operation-material-run"', service)

    def test_material_draws_settle_only_through_native_erp_trace(self):
        service = (ROOT / "services" / "operation_material_runs.py").read_text()
        trace = (ROOT / "services" / "production_trace.py").read_text()
        self.assertIn("def adopt_material_run_draws", service)
        self.assertIn("allocate_input_tag", service)
        self.assertIn("def confirm_material_run_settlement", service)
        self.assertIn("def reverse_material_run_settlement", service)
        self.assertIn("confirm_material_run_settlement(trace.name)", trace)
        self.assertIn("reverse_material_run_settlement(trace.name)", trace)
        self.assertNotIn("post_quantity_event", service)

    def test_skip_wip_uses_selected_settlement_route_without_orphan_draft(self):
        service = (ROOT / "services" / "operation_material_runs.py").read_text()
        flow = (ROOT / "services" / "production_material_flow.py").read_text()
        gateway = (ROOT / "integrations" / "erp_gateway.py").read_text()
        feedback = (ROOT / "integrations" / "erp_feedback.py").read_text()
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                 "kanban_operator.js").read_text()
        self.assertIn("material_run_settlement_lines", flow)
        self.assertIn("At Job Card End", flow)
        self.assertIn("At Work Order Manufacture Receipt", flow)
        self.assertIn("adopt_material_run_draws", flow)
        self.assertIn("_prepare_material_draw_rows", service)
        self.assertIn("_cloned_entry_input_row", service)
        self.assertIn("Skip-WIP Work Order material is consumed by the final Manufacture entry", flow)
        self.assertIn("and not receipt_draws", flow)
        self.assertIn("material_run_job_end_settlement_ready", flow)
        self.assertIn('work_order.transfer_material_against == "Job Card"', flow)
        self.assertIn("Work Order material control has no Job Card Item rows", gateway)
        self.assertIn("Production Draft Stock Entry remains open", feedback)
        self.assertIn("unresolved_material_run_settlement", feedback)
        self.assertIn("material_run_job_end_pending_count", panel)
        self.assertIn("Material Run settlement requires an authorized operator", panel)
        self.assertIn("Settle Material Runs button or scan CFG:CMD:PREPARE_MATERIALS", panel)
        self.assertIn("Settle the Job Card-end Material Runs before preparing Manufacture", panel)
        self.assertNotIn('__("Consume Work Order Materials")', panel)

    def test_scanner_run_captures_quantity_then_physical_source(self):
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                 "kanban_operator.js").read_text()
        self.assertIn("dialog.cfg_pending_material_qty", panel)
        self.assertIn("dialog.cfg_material_draws", panel)
        self.assertIn("preview_material_draw", panel)
        self.assertIn("CFG:QTY:MATERIAL:", panel)
        self.assertIn("material_draws: JSON.stringify", panel)
        self.assertIn("physical source Stock Tag", panel)
        self.assertIn("finally {\n\t\t\t\tif (dialog.$wrapper.is(\":visible\"))", panel)

    def test_progress_uses_material_plan_before_run_closure(self):
        progress = (ROOT / "services" / "progress.py").read_text()
        validate_at = progress.index("validate_progress_materials")
        insert_at = progress.index("progress.insert")
        apply_at = progress.index("apply_progress_material_plan")
        close_at = progress.index("close_run_with_progress")
        self.assertLess(validate_at, insert_at)
        self.assertLess(insert_at, apply_at)
        self.assertLess(apply_at, close_at)

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

    def test_progress_command_prefers_the_open_material_run_lane(self):
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                 "kanban_operator.js").read_text()
        self.assertIn(
            'eligible.filter((row) => row.material_run?.status === "Open")',
            panel,
        )
        self.assertIn(
            'eligible.filter((row) => ["In Progress", "Paused"].includes(row.status))',
            panel,
        )
        self.assertIn("select_scanner_execution_action(action, eligible)", panel)
        self.assertIn("Scan CFG:SELECT:n, then scan Confirm", panel)
        self.assertNotIn(
            "More than one execution lane is eligible. Select the correct lane on screen.",
            panel,
        )


    def test_material_rotation_is_checked_at_preview_and_confirmation(self):
        service = (ROOT / "services" / "operation_material_runs.py").read_text()
        self.assertEqual(service.count("rotation = validate_material_rotation(execution, unit)"), 2)
        self.assertIn("_assert_carry_forward_expiry(execution)", service)
        self.assertIn("lock_material_rotation(execution)", service)
        self.assertIn("assert_material_not_expired(frappe.get_doc", service)
        controller = (DOCTYPE_ROOT / "cfg_kanban_operation_material_draw" /
                      "cfg_kanban_operation_material_draw.py").read_text()
        self.assertIn('"material_rotation_override", "material_rotation_evidence"', controller)

    def test_work_order_override_is_scanner_accessible_and_audited(self):
        panel = (ROOT / "cfg_kanban/page/kanban_operator/kanban_operator.js").read_text()
        api = (ROOT / "api/operator.py").read_text()
        manual = (ROOT.parent / "docs/USER_MANUAL.md").read_text()
        for command in ("APPROVE_MATERIAL_FEFO_OVERRIDE", "REVOKE_MATERIAL_FEFO_OVERRIDE"):
            self.assertIn(command, panel)
            self.assertIn("CFG:CMD:" + command, api)
            self.assertIn("CFG:CMD:" + command, manual)
        self.assertIn('bind_confirmation_scanner(dialog, true, names, "execution_name")', panel)
        schema = json.loads((DOCTYPE_ROOT / "cfg_kanban_material_rotation_override" /
                             "cfg_kanban_material_rotation_override.json").read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["active_work_order_key"]["unique"], 1)
        self.assertEqual(fields["work_order"]["options"], "Work Order")
        self.assertTrue(all(not permission.get("write") and not permission.get("create")
                            for permission in schema["permissions"]))


if __name__ == "__main__":
    unittest.main()

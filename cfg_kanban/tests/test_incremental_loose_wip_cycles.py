import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestIncrementalLooseWIPCycles(TestCase):
    def test_material_rule_exposes_opt_in_incremental_policy(self):
        schema = json.loads((
            ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_material_flow_rule" /
            "cfg_kanban_material_flow_rule.json"
        ).read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        policy = fields["loose_wip_release_policy"]
        self.assertIn("Full Job Card Quantity Before Start", policy["options"])
        self.assertIn("Incremental by Operation Cycle", policy["options"])
        self.assertEqual(policy["default"], "Full Job Card Quantity Before Start")

    def test_job_card_start_preserves_non_incremental_material_gates(self):
        source = (ROOT / "services" / "production_material_flow.py").read_text()
        readiness = source[source.index("def job_card_material_readiness("):]
        readiness = readiness[:readiness.index("\ndef _work_order_material_row(")]
        self.assertIn("blocking_pending", readiness)
        self.assertIn("incremental_without_stock", readiness)
        self.assertIn('"quantity is not required for incremental rows."', readiness)
        self.assertIn("_available_incremental_loose_wip", readiness)

    def test_operation_cycle_closure_requires_its_loose_usage(self):
        source = (ROOT / "api" / "operator.py").read_text()
        readiness = source[source.index("def _runtime_close_readiness("):]
        readiness = readiness[:readiness.index("\ndef _execution_completion_rule(")]
        self.assertIn("incremental_loose_wip_items", readiness)
        self.assertIn('"requesting_cycle": execution.kanban_cycle', readiness)
        self.assertIn("Record the actual Loose WIP use", readiness)

    def test_operator_complete_returns_unfulfilled_demand_to_queue(self):
        source = (ROOT / "api" / "operator.py").read_text()
        completion = source[source.index("def complete_runtime_cycle("):]
        completion = completion[:completion.index("\ndef _runtime_close_readiness(")]
        self.assertIn('completion_rule != "Operator Complete"', completion)
        self.assertIn("unfulfilled_qty = max", completion)
        self.assertIn('"partial_close": partial_close', completion)
        selector = (ROOT / "services" / "runtime_selector.py").read_text()
        self.assertIn("accounted_completed = max", selector)
        self.assertIn("row.remaining_qty = max", selector)

    def test_loose_wip_erp_posting_can_be_scoped_to_completed_job_card(self):
        service = (ROOT / "services" / "production_material_flow.py").read_text()
        prepare = service[service.index("def prepare_consolidated_loose_wip_consumption("):]
        prepare = prepare[:prepare.index("\n\n@frappe.whitelist()", 1)]
        self.assertIn("job_card=None", prepare)
        self.assertIn("operation_consumption_submission_readiness", prepare)
        self.assertIn('usage_filters["job_card"] = job_card', prepare)
        self.assertIn('"job_card": job_card', prepare)

        loose = (ROOT / "services" / "loose_wip.py").read_text()
        self.assertIn('untouched_filters["job_card"] = entry.cfg_kanban_job_card', loose)

    def test_operator_panel_supports_partial_close_and_scanner_posting(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn("runtime_cycle_has_closable_progress", panel)
        self.assertIn("Partial close: unfulfilled demand returns", panel)
        self.assertIn("Select Completed Job Card for Loose WIP Posting", panel)
        self.assertIn("PREPARE_LOOSE_WIP_CONSUMPTION", panel)


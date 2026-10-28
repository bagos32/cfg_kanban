from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestRuntimeOperationCycleCloseContract(TestCase):
    def test_operation_cycle_uses_submitted_work_order_not_started_state(self):
        source = (ROOT / "api" / "operator.py").read_text()
        readiness = source[source.index("def _runtime_close_readiness("):]
        readiness = readiness[:readiness.index("\n\n@frappe.whitelist()")]

        self.assertIn("cint(work_order.docstatus) != 1", readiness)
        self.assertIn('work_order.status in ("Stopped", "Cancelled")', readiness)
        self.assertNotIn("work_order_started", readiness)
        self.assertNotIn('work_order.status == "Not Started"', readiness)
        self.assertIn("_runtime_execution_erp_progress_qty", readiness)

    def test_close_uses_current_operation_cycle_erp_evidence(self):
        source = (ROOT / "api" / "operator.py").read_text()
        readiness = source[source.index("def _runtime_close_readiness("):]
        readiness = readiness[:readiness.index("\ndef _execution_completion_rule(")]

        self.assertIn("required_erp_qty = flt(execution.good_qty)", readiness)
        self.assertIn("progress.process_execution=%s", readiness)
        self.assertIn("jctl.cfg_kanban_progress", readiness)
        self.assertNotIn("prior_good", readiness)

    def test_operation_close_releases_only_reusable_operation_card(self):
        source = (ROOT / "api" / "operator.py").read_text()
        completion = source[source.index("def complete_runtime_cycle("):]
        completion = completion[:completion.index("\ndef _runtime_close_readiness(")]

        self.assertIn("Runtime Allocation Completed", completion)
        self.assertIn("Operation allocation closed independently", completion)
        self.assertIn('"main_production_cycle_kept_open": True', completion)
        self.assertIn('transition_card(card, "Available"', completion)

    def test_operator_panel_names_the_operation_scope(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn('__("Close Operation Cycle")', panel)
        self.assertIn('__("Close Operation and Release Card")', panel)
        self.assertIn(
            "The main production Cycle, Work Order, and remaining Job Card demand stay open",
            panel,
        )

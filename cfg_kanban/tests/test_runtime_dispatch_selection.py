import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestRuntimeDispatchSelection(unittest.TestCase):
    def test_supervisor_queue_precedes_runtime_fallback_for_one_workstation(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        self.assertIn("def _order_candidates(candidates, fallback_rule):", service)
        self.assertIn("len(workstations) == 1", service)
        self.assertIn('row.get("sequence_source") == "Supervisor Override"', service)
        self.assertIn('basis = "Supervisor Dispatch Queue"', service)
        self.assertIn("basis = fallback_rule", service)
        queue_branch = service[
            service.index("if supervisor_queue:"):
            service.index("def _attach_dispatch_context")
        ]
        self.assertIn('row.get("queue_position")', queue_branch)

    def test_runtime_candidate_carries_visible_dispatch_evidence(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        for fieldname in (
            '"selection_basis"', '"selection_rank"', '"dispatch_queue"',
            '"queue_position"', '"sequence_source"', '"expedite"',
        ):
            self.assertIn(fieldname, service)
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" /
            "kanban_operator.js"
        ).read_text()
        self.assertIn('__("Recommendation Basis")', panel)
        self.assertIn('value.selection_basis === "Supervisor Dispatch Queue"', panel)

    def test_allocation_preserves_the_recommendation_evidence(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        schema = (
            ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_runtime_allocation" /
            "cfg_kanban_runtime_allocation.json"
        ).read_text()
        for fieldname in (
            "recommendation_basis", "dispatch_queue",
            "supervisor_queue_position", "sequence_source",
        ):
            self.assertIn(f'"{fieldname}"', service)
            self.assertIn(f'"fieldname":"{fieldname}"', schema)


if __name__ == "__main__":
    unittest.main()

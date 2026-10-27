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

    def test_repeated_cycles_do_not_shadow_the_supervisor_queue(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        attach = service[
            service.index("def _attach_dispatch_context"):
            service.index("def _available_input")
        ]
        self.assertIn("A reusable Process Card creates a new execution/queue row", attach)
        self.assertIn(
            '0 if row.sequence_source == "Supervisor Override" else 1',
            attach,
        )
        self.assertIn("queue = matching[0] if matching else None", attach)

    def test_paused_job_card_is_not_offered_as_a_new_runtime_allocation(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        candidate_section = service[
            service.index("def _eligible_candidates"):
            service.index("def _work_order_execution_open")
        ]
        self.assertIn("paused_job_cards = _paused_job_cards(rows)", candidate_section)
        self.assertIn("if row.name in paused_job_cards:", candidate_section)
        self.assertIn('"status": "Paused"', candidate_section)
        self.assertIn('pluck="job_card"', candidate_section)

    def test_paused_queue_row_cannot_supply_stale_supervisor_priority(self):
        service = (ROOT / "services" / "runtime_selector.py").read_text()
        attach = service[
            service.index("def _attach_dispatch_context"):
            service.index("def _available_input")
        ]
        self.assertIn(
            '"dispatch_status": ["not in", ["Completed", "Cancelled", "Paused"]]',
            attach,
        )


if __name__ == "__main__":
    unittest.main()

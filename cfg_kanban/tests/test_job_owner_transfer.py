import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class TestJobOwnerTransfer(unittest.TestCase):
    def test_exact_action_approval_binds_replacement_operator(self):
        approval = schema("CFG Kanban Supervisor Action Approval")
        fields = {row["fieldname"]: row for row in approval["fields"]}
        self.assertEqual(fields["subject_employee"]["options"], "Employee")
        self.assertEqual(
            fields["subject_operator_profile"]["options"],
            "CFG Kanban Operator Profile",
        )
        service = (ROOT / "services" / "action_approval.py").read_text()
        self.assertIn(
            '"TRANSFER_CYCLE_OWNERSHIP": "can_transfer_ownership"', service
        )
        self.assertIn('"subject_employee": subject.employee', service)
        self.assertIn("different transfer reason", service)
        self.assertIn("replacement owner cannot approve", service)

    def test_owner_assignments_form_an_auditable_transfer_chain(self):
        assignment = schema("CFG Kanban Job Owner Assignment")
        fields = {row["fieldname"]: row for row in assignment["fields"]}
        self.assertEqual(
            fields["previous_assignment"]["options"],
            "CFG Kanban Job Owner Assignment",
        )
        self.assertEqual(
            fields["supervisor_action_approval"]["options"],
            "CFG Kanban Supervisor Action Approval",
        )
        service = (ROOT / "services" / "job_ownership.py").read_text()
        self.assertIn('"status": "Ended"', service)
        self.assertIn('"assignment_source": "Supervisor Ownership Transfer"', service)
        self.assertIn('"previous_assignment": previous_assignment.name', service)
        self.assertIn('"Cycle Ownership Transferred"', service)
        self.assertIn("def _assert_owner_role_requirements(", service)
        self.assertIn("has_authority_role", service)
        self.assertIn("employee_has_competency", service)

    def test_api_consumes_exact_pass_before_transfer_mutation(self):
        source = (ROOT / "api" / "operator.py").read_text()
        start = source.index("def transfer_job_ownership(")
        consume = source.index("consume_action_approval(", start)
        mutation = source.index("transfer_cycle_ownership(", consume)
        self.assertLess(consume, mutation)
        self.assertIn("def preview_job_ownership_transfer(", source)

    def test_panel_supports_touch_and_scanner_transfer(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn("Transfer Owner", panel)
        self.assertIn("CFG:CMD:TRANSFER_OWNER", panel)
        self.assertIn("preview_job_ownership_transfer", panel)
        self.assertIn('action_code: "TRANSFER_CYCLE_OWNERSHIP"', panel)
        self.assertIn("replacement operator credential", panel)
        self.assertIn("approving supervisor credential", panel)


if __name__ == "__main__":
    unittest.main()

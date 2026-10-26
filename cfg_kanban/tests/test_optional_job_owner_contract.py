import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


def fields(doctype):
    return {row["fieldname"]: row for row in schema(doctype)["fields"]}


class TestOptionalJobOwnerContract(unittest.TestCase):
    def test_card_policy_is_explicitly_opt_in(self):
        card = fields("CFG Kanban Card")
        self.assertEqual(card["enforce_job_owner"]["default"], "0")
        self.assertEqual(card["owner_job_code"]["options"], "CFG Kanban Job Code")
        self.assertEqual(
            card["owner_job_code"]["mandatory_depends_on"],
            "eval:doc.enforce_job_owner",
        )

    def test_cycle_persists_policy_snapshot_and_actual_owner(self):
        cycle = fields("CFG Kanban Cycle")
        for fieldname in (
            "enforce_job_owner",
            "owner_job_code",
            "job_owner",
            "job_owner_operator_profile",
            "job_owner_assigned_on",
            "active_owner_assignment",
        ):
            self.assertEqual(cycle[fieldname]["read_only"], 1)
        self.assertEqual(cycle["job_owner"]["options"], "Employee")

    def test_operator_job_codes_are_separate_from_authority_and_scope(self):
        profile = fields("CFG Kanban Operator Profile")
        self.assertEqual(profile["job_codes"]["fieldtype"], "Table")
        self.assertEqual(profile["job_codes"]["options"], "CFG Kanban Operator Job Code")
        self.assertIn("kanban_role", profile)
        self.assertIn("allowed_operations", profile)
        self.assertIn("responsibilities", profile)

    def test_owner_assignment_is_auditable_history(self):
        assignment = schema("CFG Kanban Job Owner Assignment")
        assignment_fields = {row["fieldname"]: row for row in assignment["fields"]}
        self.assertEqual(assignment["autoname"], "JOA-.YYYY.-.#####")
        self.assertEqual(assignment_fields["kanban_cycle"]["reqd"], 1)
        self.assertEqual(assignment_fields["employee"]["reqd"], 1)
        self.assertEqual(assignment_fields["status"]["options"], "Active\nEnded")
        self.assertTrue(all(not row.get("write") for row in assignment["permissions"]))

    def test_first_operation_start_claims_owner_after_crew_authorization(self):
        source = (ROOT / "api" / "operator.py").read_text()
        crew = source.index("crew_result = enforce_execution_crew(")
        accept = source.index("accept_cycle_ownership(", crew)
        command = source.index("command_type =", accept)
        self.assertLess(crew, accept)
        self.assertLess(accept, command)

    def test_operator_panel_explains_owner_acceptance(self):
        source = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn("Cycle Operator-in-Charge", source)
        self.assertIn("Accept Ownership and Start", source)
        self.assertIn("Job Code Required", source)
        self.assertIn("CFG:CMD:ACCEPT_OWNER", source)


if __name__ == "__main__":
    unittest.main()

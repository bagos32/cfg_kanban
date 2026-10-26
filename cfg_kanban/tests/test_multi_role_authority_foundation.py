import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


def fields(name):
    return {row["fieldname"]: row for row in schema(name)["fields"]}


class TestMultiRoleAuthorityFoundation(unittest.TestCase):
    def test_authority_role_has_explicit_capabilities(self):
        role = fields("CFG Kanban Authority Role")
        for fieldname in (
            "can_perform_work",
            "can_lead_crew",
            "can_supervise_trainees",
            "can_verify_work",
            "can_approve_progress",
            "can_close_on_behalf",
            "can_correct_records",
            "can_override_material",
            "can_cancel_or_bypass",
            "can_transfer_ownership",
        ):
            self.assertEqual(role[fieldname]["fieldtype"], "Check")
        self.assertEqual(role["company"]["options"], "Company")

    def test_operator_profile_supports_multiple_scoped_authorities(self):
        profile = fields("CFG Kanban Operator Profile")
        self.assertEqual(
            profile["authority_assignments"]["options"],
            "CFG Kanban Operator Authority",
        )
        assignment = fields("CFG Kanban Operator Authority")
        self.assertEqual(assignment["company"]["options"], "Company")
        self.assertEqual(assignment["operation"]["options"], "Operation")
        self.assertEqual(assignment["workstation"]["options"], "Workstation")
        self.assertEqual(
            assignment["responsibility"]["options"], "CFG Kanban Responsibility"
        )
        self.assertIn("kanban_role", profile)

    def test_card_declares_roles_without_granting_them(self):
        card = fields("CFG Kanban Card")
        self.assertEqual(
            card["job_role_requirements"]["options"],
            "CFG Kanban Card Role Requirement",
        )
        requirement = fields("CFG Kanban Card Role Requirement")
        self.assertEqual(requirement["job_code"]["options"], "CFG Kanban Job Code")
        self.assertEqual(
            requirement["authority_role"]["options"], "CFG Kanban Authority Role"
        )
        self.assertEqual(requirement["skill"]["options"], "CFG Kanban Skill")
        self.assertIn("Supervisor / Mentor", requirement["assignment_type"]["options"])
        self.assertIn("Verifier", requirement["assignment_type"]["options"])

    def test_cycle_has_immutable_role_requirement_snapshot(self):
        cycle = fields("CFG Kanban Cycle")
        self.assertEqual(
            cycle["job_role_requirements_snapshot"]["options"],
            "CFG Kanban Cycle Role Requirement",
        )
        self.assertEqual(cycle["job_role_requirements_snapshot"]["read_only"], 1)
        snapshot = fields("CFG Kanban Cycle Role Requirement")
        self.assertTrue(all(row.get("read_only") for row in snapshot.values()))

    def test_foundation_is_additive_and_not_runtime_enforcement(self):
        source = (ROOT / "services" / "authority.py").read_text()
        self.assertIn("legacy_fallback_active", source)
        self.assertIn("Scoped Assignment", source)
        self.assertIn("def has_authority", source)
        operator_auth = (ROOT / "services" / "operator_auth.py").read_text()
        self.assertIn('"authority_capabilities"', operator_auth)
        self.assertIn('"legacy_authority_fallback"', operator_auth)

    def test_workspace_exposes_authority_configuration(self):
        workspace = json.loads(
            (
                ROOT
                / "cfg_kanban"
                / "workspace"
                / "cfg_job_architecture"
                / "cfg_job_architecture.json"
            ).read_text()
        )
        links = {row.get("link_to") for row in workspace["links"]}
        self.assertIn("CFG Kanban Authority Role", links)


if __name__ == "__main__":
    unittest.main()

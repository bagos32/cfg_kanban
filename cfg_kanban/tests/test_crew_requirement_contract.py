import json
from pathlib import Path
from unittest import TestCase

from cfg_kanban.services.crew_policy_rules import merge_normalized_crew_policies


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestCrewRequirementContract(TestCase):
    def _doctype(self, folder, filename):
        return json.loads((DOCTYPE_ROOT / folder / filename).read_text())

    def test_profile_is_submitted_manager_policy_with_four_modes(self):
        schema = self._doctype(
            "cfg_kanban_crew_requirement_profile",
            "cfg_kanban_crew_requirement_profile.json",
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(schema["is_submittable"], 1)
        self.assertEqual(schema["autoname"], "field:requirement_code")
        self.assertEqual(fields["crew_mode"]["options"].splitlines(), [
            "Single Operator",
            "Multiple Operators",
            "Supervised Operation",
            "Qualified Lead + Assistants",
        ])
        self.assertTrue({
            "minimum_direct_workers", "minimum_assistants", "trainee_policy",
            "supervision_presence", "max_trainees_per_supervisor",
            "skill_requirements", "approved_by", "approved_on",
            "external_policy_identifier", "external_policy_revision_snapshot",
        }.issubset(fields))
        self.assertEqual(
            fields["skill_requirements"]["options"],
            "CFG Kanban Crew Skill Requirement",
        )

    def test_skill_rows_are_skill_specific_and_role_specific(self):
        schema = self._doctype(
            "cfg_kanban_crew_skill_requirement",
            "cfg_kanban_crew_skill_requirement.json",
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(fields["participation_role"]["options"].splitlines(), [
            "Direct Worker", "Qualified Lead", "Active Supervisor",
        ])
        self.assertEqual(fields["skill"]["options"], "CFG Kanban Skill")
        self.assertTrue({
            "minimum_level", "minimum_people",
            "require_independent_authorization",
            "require_supervisor_authorization",
        }.issubset(fields))

    def test_three_policy_layers_are_explicit(self):
        operation = self._doctype(
            "cfg_kanban_operation_profile", "cfg_kanban_operation_profile.json"
        )
        card = self._doctype("cfg_kanban_card", "cfg_kanban_card.json")
        workstation = self._doctype(
            "cfg_kanban_workstation_crew_requirement",
            "cfg_kanban_workstation_crew_requirement.json",
        )
        operation_fields = {row["fieldname"]: row for row in operation["fields"]}
        card_fields = {row["fieldname"]: row for row in card["fields"]}
        workstation_fields = {row["fieldname"]: row for row in workstation["fields"]}
        expected = "CFG Kanban Crew Requirement Profile"
        self.assertEqual(operation_fields["crew_requirement_profile"]["options"], expected)
        self.assertEqual(card_fields["crew_requirement_profile"]["options"], expected)
        self.assertEqual(workstation_fields["crew_requirement_profile"]["options"], expected)
        self.assertEqual(workstation["is_submittable"], 1)
        self.assertFalse(workstation_fields["operation"].get("reqd", 0))

    def test_effective_policy_uses_conservative_merging(self):
        source = (ROOT / "services" / "crew_policy.py").read_text()
        rules = (ROOT / "services" / "crew_policy_rules.py").read_text()
        self.assertIn("def get_effective_crew_policy", source)
        self.assertIn("def merge_crew_policies", source)
        self.assertIn("TRAINEE_POLICY_RANK", rules)
        self.assertIn("SUPERVISION_RANK", rules)
        self.assertIn('result["minimum_direct_workers"] = max(', rules)
        self.assertIn('result["minimum_assistants"] = max(', rules)
        self.assertIn("min(ratios)", rules)
        self.assertIn("Workstation Restriction", source)
        self.assertIn("Kanban Card", source)

        direct = {
            "crew_mode": "Single Operator",
            "minimum_direct_workers": 1,
            "minimum_assistants": 0,
            "trainee_policy": "Permitted",
            "supervision_presence": "Not Required",
            "skill_requirements": [{
                "participation_role": "Direct Worker",
                "skill": "MIXING",
                "minimum_level": "L1",
                "minimum_level_rank": 1,
                "minimum_people": 1,
                "require_independent_authorization": False,
                "require_supervisor_authorization": False,
            }],
        }
        workstation = {
            "crew_mode": "Multiple Operators",
            "minimum_direct_workers": 2,
            "minimum_assistants": 0,
            "trainee_policy": "Prohibited",
            "supervision_presence": "Always Required",
            "max_trainees_per_supervisor": 1,
            "skill_requirements": [{
                "participation_role": "Direct Worker",
                "skill": "MIXING",
                "minimum_level": "L2",
                "minimum_level_rank": 2,
                "minimum_people": 2,
                "require_independent_authorization": True,
                "require_supervisor_authorization": False,
            }],
        }
        merged = merge_normalized_crew_policies([direct, workstation])
        self.assertEqual(merged["minimum_direct_workers"], 2)
        self.assertEqual(merged["trainee_policy"], "Prohibited")
        self.assertEqual(merged["supervision_presence"], "Always Required")
        self.assertEqual(merged["max_trainees_per_supervisor"], 1)
        self.assertEqual(merged["skill_requirements"][0]["minimum_level"], "L2")
        self.assertEqual(merged["skill_requirements"][0]["minimum_people"], 2)
        self.assertTrue(
            merged["skill_requirements"][0]["require_independent_authorization"]
        )

    def test_workspace_exposes_crew_configuration(self):
        workspace = json.loads(
            (ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
             "cfg_kanban.json").read_text()
        )
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(
            links["Crew Requirement Profiles"],
            "CFG Kanban Crew Requirement Profile",
        )
        self.assertEqual(
            links["Workstation Crew Requirements"],
            "CFG Kanban Workstation Crew Requirement",
        )

    def test_p02_boundary_assigns_runtime_enforcement_to_p04(self):
        guide = (ROOT.parent / "docs" / "WORKFORCE_COMPETENCY_CREW_CONTROL.md").read_text()
        self.assertIn("P02 alone does not block", guide)
        self.assertIn("P04 engine applies its result", guide)

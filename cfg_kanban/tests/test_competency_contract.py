import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestCompetencyContract(TestCase):
    def _doctype(self, folder, filename):
        return json.loads((DOCTYPE_ROOT / folder / filename).read_text())

    def test_skill_registry_is_stable_and_manager_controlled(self):
        schema = self._doctype("cfg_kanban_skill", "cfg_kanban_skill.json")
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(schema["autoname"], "field:skill_code")
        self.assertEqual(schema["title_field"], "skill_name")
        self.assertTrue({
            "skill_code", "skill_name", "skill_category", "active",
            "requires_certification", "requires_expiry_tracking",
            "default_validity_days", "external_standard_reference",
        }.issubset(fields))
        permissions = {row["role"]: row for row in schema["permissions"]}
        self.assertEqual(permissions["Manufacturing User"].get("read"), 1)
        self.assertEqual(permissions["Manufacturing Manager"].get("write"), 1)
        self.assertEqual(permissions["System Manager"].get("write"), 1)

    def test_employee_competency_preserves_approval_and_external_boundary(self):
        schema = self._doctype(
            "cfg_kanban_employee_competency", "cfg_kanban_employee_competency.json"
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertEqual(schema["is_submittable"], 1)
        self.assertEqual(fields["employee"]["options"], "Employee")
        self.assertEqual(fields["operator_profile"]["options"],
                         "CFG Kanban Operator Profile")
        self.assertEqual(fields["skill"]["options"], "CFG Kanban Skill")
        self.assertEqual(fields["competency_level"]["options"].splitlines(), [
            "L0 - Untrained / Awareness Only",
            "L1 - Trainee",
            "L2 - Qualified Operator",
            "L3 - Senior / Lead",
            "L4 - Trainer / Supervisor",
        ])
        self.assertTrue({
            "can_work_independently", "can_supervise_trainees", "effective_from",
            "valid_until", "assessment_reference", "certification_reference",
            "external_evidence_id", "external_revision_snapshot", "status",
            "approved_by", "approved_on", "status_reason", "revoked_by", "revoked_on",
        }.issubset(fields))
        self.assertEqual(fields["external_evidence_id"]["fieldtype"], "Data")
        self.assertNotEqual(fields["external_evidence_id"].get("options"), "TrackQMS")

    def test_validity_service_is_ready_for_later_authorization_engine(self):
        service = (ROOT / "services" / "competency.py").read_text()
        controller = (DOCTYPE_ROOT / "cfg_kanban_employee_competency" /
                      "cfg_kanban_employee_competency.py").read_text()
        self.assertIn('LEVEL_RANKS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}', service)
        self.assertIn("def effective_competency_status", service)
        self.assertIn("def employee_has_competency", service)
        self.assertIn('return "Expired"', service)
        self.assertIn("_validate_no_overlapping_approval", controller)
        self.assertIn("Independent work authorization requires competency level L2", controller)
        self.assertIn("Trainee supervision authorization requires competency level L3", controller)

    def test_operator_profile_and_workspace_expose_competency_records(self):
        profile = self._doctype(
            "cfg_kanban_operator_profile", "cfg_kanban_operator_profile.json"
        )
        fields = {row["fieldname"]: row for row in profile["fields"]}
        self.assertEqual(fields["competency_summary"]["fieldtype"], "HTML")
        client = (ROOT / "public" / "js" / "cfg_kanban_operator_profile.js").read_text()
        self.assertIn("get_operator_profile_competency_summary", client)
        self.assertIn("Employee Competencies", client)
        workspace = json.loads(
            (ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" / "cfg_kanban.json").read_text()
        )
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(links["Skill Registry"], "CFG Kanban Skill")
        self.assertEqual(links["Employee Competencies"],
                         "CFG Kanban Employee Competency")

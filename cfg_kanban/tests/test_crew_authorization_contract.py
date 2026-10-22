import json
from pathlib import Path
from unittest import TestCase

from cfg_kanban.services.crew_authorization_rules import evaluate_crew_authorization


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestCrewAuthorizationContract(TestCase):
    def _doctype(self, folder, filename):
        return json.loads((DOCTYPE_ROOT / folder / filename).read_text())

    def _policy(self, **updates):
        policy = {
            "configured": True,
            "minimum_direct_workers": 2,
            "minimum_assistants": 1,
            "trainee_policy": "Supervised Only",
            "supervision_presence": "Required When Trainees Present",
            "max_trainees_per_supervisor": 1,
            "skill_requirements": [{
                "participation_role": "Direct Worker",
                "skill": "MIXING",
                "minimum_level": "L2",
                "minimum_people": 1,
            }, {
                "participation_role": "Active Supervisor",
                "skill": "MIXING",
                "minimum_level": "L3",
                "minimum_people": 1,
            }],
        }
        policy.update(updates)
        return policy

    def _members(self):
        return [
            {"employee": "EMP-LEAD", "status": "Active", "crew_role": "Main Operator",
             "work_category": "Direct Participation"},
            {"employee": "EMP-TRAINEE", "status": "Active",
             "crew_role": "Supporting Operator", "work_category": "Direct Participation"},
            {"employee": "EMP-SUP", "status": "Active", "crew_role": "Senior / Overseer",
             "work_category": "Oversight Only"},
        ]

    def test_unconfigured_policy_is_backward_compatible(self):
        result = evaluate_crew_authorization({"configured": False}, [])
        self.assertTrue(result["allowed"])
        self.assertFalse(result["configured"])

    def test_qualified_supervised_crew_passes(self):
        result = evaluate_crew_authorization(
            self._policy(),
            self._members(),
            qualified_by_requirement={
                "Direct Worker|MIXING": ["EMP-LEAD"],
                "Active Supervisor|MIXING": ["EMP-SUP"],
            },
            trainee_employees=["EMP-TRAINEE"],
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["active_direct_workers"], 2)
        self.assertEqual(result["active_assistants"], 1)
        self.assertEqual(result["active_supervisors"], 1)

    def test_break_member_does_not_count_and_creates_findings(self):
        members = self._members()
        members[1]["status"] = "On Break"
        result = evaluate_crew_authorization(
            self._policy(),
            members,
            qualified_by_requirement={
                "Direct Worker|MIXING": ["EMP-LEAD"],
                "Active Supervisor|MIXING": ["EMP-SUP"],
            },
        )
        self.assertFalse(result["allowed"])
        self.assertIn("MINIMUM_DIRECT_WORKERS", {row["code"] for row in result["findings"]})
        self.assertIn("MINIMUM_ASSISTANTS", {row["code"] for row in result["findings"]})

    def test_trainee_supervision_ratio_and_concurrency_are_enforced(self):
        result = evaluate_crew_authorization(
            self._policy(),
            self._members(),
            qualified_by_requirement={
                "Direct Worker|MIXING": ["EMP-LEAD"],
                "Active Supervisor|MIXING": [],
            },
            trainee_employees=["EMP-TRAINEE"],
            concurrent_employees=["EMP-LEAD"],
        )
        codes = {row["code"] for row in result["findings"]}
        self.assertFalse(result["allowed"])
        self.assertIn("SUPERVISOR_REQUIRED", codes)
        self.assertIn("TRAINEE_RATIO", codes)
        self.assertIn("CONCURRENT_DIRECT_WORK", codes)

    def test_schema_preserves_decision_and_execution_hold_links(self):
        check = self._doctype(
            "cfg_kanban_crew_compliance_check",
            "cfg_kanban_crew_compliance_check.json",
        )
        execution = self._doctype(
            "cfg_kanban_process_execution", "cfg_kanban_process_execution.json"
        )
        check_fields = {row["fieldname"]: row for row in check["fields"]}
        execution_fields = {row["fieldname"]: row for row in execution["fields"]}
        self.assertTrue({
            "checkpoint", "result", "policy_snapshot", "crew_snapshot", "findings",
            "crew_session", "actor_employee", "operator_session", "exception",
        }.issubset(check_fields))
        self.assertTrue({
            "crew_compliance_status", "last_crew_compliance_check",
            "crew_compliance_hold", "crew_hold_previous_status",
        }.issubset(execution_fields))

    def test_runtime_checkpoints_and_crew_change_reconciliation_are_wired(self):
        operator = (ROOT / "api" / "operator.py").read_text()
        scan = (ROOT / "api" / "scan.py").read_text()
        progress = (ROOT / "services" / "progress.py").read_text()
        registry = (ROOT / "services" / "crew_registry.py").read_text()
        self.assertIn('"Before Runtime Allocation"', operator)
        self.assertIn('"Before Operation Start"', operator)
        self.assertIn('"Progress"', operator)
        self.assertIn('"Before Completion"', operator)
        self.assertIn('"Before WIP Release"', scan)
        self.assertIn("release_execution_wip_if_authorized", progress)
        self.assertIn("reconcile_workstation_crew_compliance", registry)

    def test_workspace_exposes_compliance_history(self):
        workspace = json.loads(
            (ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
             "cfg_kanban.json").read_text()
        )
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(
            links["Crew Compliance Checks"], "CFG Kanban Crew Compliance Check"
        )

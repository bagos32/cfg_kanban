import json
from pathlib import Path
from unittest import TestCase

from cfg_kanban.services.job_participation_rules import (
    desired_participants,
    participation_kind,
    segment_identity,
)


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestJobParticipationContract(TestCase):
    def test_direct_and_oversight_are_separate_facts(self):
        self.assertEqual(participation_kind("Direct Participation"), "Production Labour")
        self.assertEqual(participation_kind("Oversight Only"), "Oversight")

    def test_only_active_members_are_projected(self):
        members = [
            {"name": "KCM-1", "employee": "EMP-1", "status": "Active",
             "crew_role": "Main Operator", "work_category": "Direct Participation"},
            {"name": "KCM-2", "employee": "EMP-2", "status": "On Break",
             "crew_role": "Supporting Operator", "work_category": "Direct Participation"},
            {"name": "KCM-3", "employee": "EMP-3", "status": "Active",
             "crew_role": "Senior / Overseer", "work_category": "Oversight Only"},
        ]
        result = desired_participants(members)
        self.assertEqual([row["employee"] for row in result], ["EMP-1", "EMP-3"])
        self.assertEqual(result[1]["participation_kind"], "Oversight")

    def test_no_policy_operator_fallback_is_explicit(self):
        result = desired_participants([], {"employee": "EMP-1"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["participation_source"], "Authenticated Operator Fallback")
        self.assertEqual(result[0]["participation_kind"], "Production Labour")

    def test_role_change_creates_a_new_segment_identity(self):
        base = {
            "crew_membership": "KCM-1", "employee": "EMP-1",
            "crew_role": "Supporting Operator", "work_category": "Direct Participation",
            "participation_source": "Crew Membership",
        }
        promoted = dict(base, crew_role="Main Operator")
        self.assertNotEqual(segment_identity(base), segment_identity(promoted))

    def test_schema_has_context_interval_and_audit_evidence(self):
        schema = json.loads((
            DOCTYPE_ROOT / "cfg_kanban_job_participation" /
            "cfg_kanban_job_participation.json"
        ).read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertTrue({
            "process_execution", "job_card", "employee", "crew_membership",
            "crew_role", "work_category", "participation_kind", "status",
            "started_on", "ended_on", "duration_seconds", "duration_hours",
            "crew_compliance_check", "participation_source",
        }.issubset(fields))
        self.assertNotIn("good_qty", fields)
        self.assertNotIn("completed_qty", fields)

    def test_runtime_and_crew_lifecycle_are_wired(self):
        operator = (ROOT / "api" / "operator.py").read_text()
        scan = (ROOT / "api" / "scan.py").read_text()
        authorization = (ROOT / "services" / "crew_authorization.py").read_text()
        feedback = (ROOT / "integrations" / "erp_feedback.py").read_text()
        self.assertIn("sync_execution_participation", operator)
        self.assertIn("close_execution_participation", operator)
        self.assertIn("sync_execution_participation", scan)
        self.assertIn("_sync_participation_projection", authorization)
        self.assertIn("sync_execution_participation", feedback)

    def test_workspace_exposes_participation_ledger(self):
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" / "cfg_kanban.json"
        ).read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(
            links["Employee Job Participation"], "CFG Kanban Job Participation"
        )

import json
from pathlib import Path
from unittest import TestCase

from cfg_kanban.services.crew_registry_rules import (
    active_coverage_members,
    expected_roster_match,
    next_presence_state,
    validate_membership_choice,
)


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestCrewRegistryContract(TestCase):
    def _doctype(self, folder, filename):
        return json.loads((DOCTYPE_ROOT / folder / filename).read_text())

    def test_template_is_approved_but_does_not_record_attendance(self):
        template = self._doctype("cfg_kanban_crew_template", "cfg_kanban_crew_template.json")
        fields = {row["fieldname"]: row for row in template["fields"]}
        session = self._doctype("cfg_kanban_crew_session", "cfg_kanban_crew_session.json")
        session_fields = {row["fieldname"]: row for row in session["fields"]}
        self.assertEqual(template["is_submittable"], 1)
        self.assertEqual(fields["members"]["options"], "CFG Kanban Crew Template Member")
        self.assertIn("never marks any employee present", fields["identity_section"]["description"])
        self.assertIn(
            "not present until they join",
            session_fields["expected_roster_snapshot"]["description"],
        )

    def test_session_membership_and_event_schema_preserve_actual_presence(self):
        session = self._doctype("cfg_kanban_crew_session", "cfg_kanban_crew_session.json")
        membership = self._doctype(
            "cfg_kanban_crew_membership", "cfg_kanban_crew_membership.json"
        )
        event = self._doctype("cfg_kanban_crew_event", "cfg_kanban_crew_event.json")
        session_fields = {row["fieldname"]: row for row in session["fields"]}
        membership_fields = {row["fieldname"]: row for row in membership["fields"]}
        event_fields = {row["fieldname"]: row for row in event["fields"]}
        self.assertTrue({
            "company", "workstation", "operation_context", "status", "main_employee",
            "main_membership", "crew_template", "expected_roster_snapshot", "started_on",
            "ended_on",
        }.issubset(session_fields))
        self.assertEqual(
            membership_fields["crew_role"]["options"].splitlines(),
            ["Main Operator", "Supporting Operator", "Senior / Overseer", "Temporary Support"],
        )
        self.assertEqual(
            membership_fields["work_category"]["options"].splitlines(),
            ["Direct Participation", "Oversight Only"],
        )
        self.assertEqual(
            membership_fields["status"]["options"].splitlines(),
            ["Active", "On Break", "Left"],
        )
        self.assertTrue({
            "event_type", "occurred_on", "subject_employee", "actor_employee",
            "operator_session", "terminal_user", "previous_state", "new_state",
        }.issubset(event_fields))

    def test_presence_transition_rules_are_explicit(self):
        self.assertEqual(next_presence_state("Active", "Break"), "On Break")
        self.assertEqual(next_presence_state("On Break", "Resume"), "Active")
        self.assertEqual(next_presence_state("Active", "Leave"), "Left")
        with self.assertRaises(ValueError):
            next_presence_state("Left", "Resume")
        with self.assertRaises(ValueError):
            validate_membership_choice("Main Operator", "Oversight Only")

    def test_break_members_do_not_count_as_active_coverage(self):
        members = [
            {"employee": "EMP-A", "status": "Active"},
            {"employee": "EMP-B", "status": "On Break"},
            {"employee": "EMP-C", "status": "Left"},
        ]
        self.assertEqual(
            [row["employee"] for row in active_coverage_members(members)],
            ["EMP-A"],
        )

    def test_template_matching_is_identity_only(self):
        expected = [{"employee": "EMP-A", "crew_role": "Supporting Operator"}]
        self.assertEqual(expected_roster_match(expected, "EMP-A"), expected[0])
        self.assertIsNone(expected_roster_match(expected, "EMP-B"))

    def test_service_keeps_helper_scan_separate_from_authentication(self):
        source = (ROOT / "services" / "crew_registry.py").read_text()
        self.assertIn("def _scanned_identity", source)
        self.assertIn("credential_hash(qr_token)", source)
        self.assertIn("def _actor", source)
        self.assertIn("require_operator(", source)
        helper_body = source.split("def _scanned_identity", 1)[1].split("def _active_session", 1)[0]
        self.assertNotIn("open_session(", helper_body)
        self.assertIn("Use the existing persistent crew", source)

    def test_workspace_exposes_configuration_and_audit_records(self):
        workspace = json.loads(
            (ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" / "cfg_kanban.json").read_text()
        )
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(links["Crew Templates"], "CFG Kanban Crew Template")
        self.assertEqual(links["Workstation Crew Sessions"], "CFG Kanban Crew Session")
        self.assertEqual(links["Crew Membership Intervals"], "CFG Kanban Crew Membership")
        self.assertEqual(links["Crew Presence Events"], "CFG Kanban Crew Event")

    def test_p03_boundary_hands_actual_crew_to_p04(self):
        guide = (ROOT.parent / "docs" / "WORKFORCE_COMPETENCY_CREW_CONTROL.md").read_text()
        self.assertIn("P04 consumes this registry", guide)
        self.assertIn("server-side authorization boundary", guide)

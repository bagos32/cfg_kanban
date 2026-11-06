from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestCrewOperatorInterfaceContract(TestCase):
    def test_operator_api_derives_crew_scope_from_execution(self):
        source = (ROOT / "api" / "operator.py").read_text()
        panel = source.split("def get_execution_crew_panel", 1)[1].split(
            "def open_execution_crew_session", 1
        )[0]
        opener = source.split("def open_execution_crew_session", 1)[1].split(
            "def get_card_context", 1
        )[0]
        self.assertIn("require_operator(operator_session_token, execution=execution)", panel)
        self.assertIn("evaluate_execution_crew", panel)
        self.assertIn("master.company", opener)
        self.assertIn("execution.workstation", opener)
        self.assertIn("execution.operation", opener)

    def test_runtime_card_can_prepare_crew_before_allocation(self):
        source = (ROOT / "api" / "operator.py").read_text()
        panel = source.split("def get_runtime_crew_panel", 1)[1].split(
            "def _crew_panel_payload", 1
        )[0]
        opener = source.split("def open_runtime_crew_session", 1)[1].split(
            "def get_card_context", 1
        )[0]
        self.assertIn("preview_runtime_card(card_name, job_card)", panel)
        self.assertIn("evaluate_operation_crew", panel)
        self.assertIn("card_name=card.name", panel)
        self.assertIn("proposal[\"workstation\"]", opener)
        self.assertIn("proposal[\"operation\"]", opener)

    def test_scanner_sheet_contains_every_crew_transition(self):
        source = (ROOT / "api" / "operator.py").read_text()
        for command in (
            "CREW_OPEN", "CREW_JOIN", "CREW_JOIN_SENIOR", "CREW_JOIN_OVERSIGHT", "CREW_JOIN_TEMP",
            "CREW_BREAK", "CREW_RESUME", "CREW_LEAVE", "CREW_MAIN",
            "CREW_CONTEXT", "CREW_CLOSE",
        ):
            self.assertIn(f'CFG:CMD:{command}', source)

    def test_floor_ui_keeps_helper_identity_separate_from_login(self):
        source = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        action_body = source.split("async function run_scanned_crew_member_action", 1)[1].split(
            "async function refresh_crew_dialog", 1
        )[0]
        self.assertIn("operator_token_from_scan(value)", source)
        self.assertIn("crew_registry.join_crew_member", action_body)
        self.assertIn("operator_session_token: state.session_token", action_body)
        self.assertNotIn("login_operator", action_body)

    def test_floor_ui_supports_touch_and_scanner_controls(self):
        source = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn("Workstation Crew", source)
        self.assertIn("Crew Controls", source)
        self.assertIn("handle_crew_dialog_scan", source)
        self.assertIn("Join Direct", source)
        self.assertIn("Join / Set Direct Senior", source)
        self.assertIn("Role Qualification", source)
        self.assertIn("qualification.actual_level", source)
        self.assertIn('style="font-size:11px', source)
        self.assertIn('style="font-size:9px', source)
        self.assertIn("Join Oversight", source)
        self.assertIn("Start Break", source)
        self.assertIn("Change Main Operator", source)
        self.assertIn("Close Crew", source)
        self.assertIn("Set Workstation Crew", source)
        self.assertIn("get_runtime_crew_panel", source)
        self.assertIn("open_runtime_crew_session", source)
        self.assertIn("open_workstation_queue_crew", source)
        self.assertIn("open-queued-crew", source)

    def test_direct_senior_action_is_scanner_operable_and_audited(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        registry = (ROOT / "services" / "crew_registry.py").read_text()
        self.assertIn('CFG:CMD:CREW_JOIN_SENIOR', panel)
        self.assertIn('crew_registry.assign_direct_senior', panel)
        self.assertIn('def assign_direct_senior', registry)
        self.assertIn('"Senior / Overseer"', registry)
        self.assertIn('"Direct Participation"', registry)
        self.assertIn('"Change Crew Role"', registry)

    def test_crew_panel_returns_policy_scoped_l_levels(self):
        source = (ROOT / "api" / "operator.py").read_text()
        panel = source.split("def get_execution_crew_panel", 1)[1].split(
            "def open_execution_crew_session", 1
        )[0]
        self.assertIn("crew_qualification_summary", panel)
        self.assertIn('member["qualifications"]', panel)

    def test_live_revision_includes_immutable_crew_events(self):
        source = (ROOT / "api" / "operator.py").read_text()
        revision = source.split("def get_card_live_revision", 1)[1]
        self.assertIn("CFG Kanban Crew Event", revision)
        self.assertIn("crew_event_modified", revision)


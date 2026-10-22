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

    def test_scanner_sheet_contains_every_crew_transition(self):
        source = (ROOT / "api" / "operator.py").read_text()
        for command in (
            "CREW_OPEN", "CREW_JOIN", "CREW_JOIN_OVERSIGHT", "CREW_JOIN_TEMP",
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
        self.assertIn("Join Oversight", source)
        self.assertIn("Start Break", source)
        self.assertIn("Change Main Operator", source)
        self.assertIn("Close Crew", source)

    def test_live_revision_includes_immutable_crew_events(self):
        source = (ROOT / "api" / "operator.py").read_text()
        revision = source.split("def get_card_live_revision", 1)[1]
        self.assertIn("CFG Kanban Crew Event", revision)
        self.assertIn("crew_event_modified", revision)


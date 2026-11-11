from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_PANEL = (
    APP_ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
)
SUPERVISOR_PANEL = (
    APP_ROOT / "cfg_kanban" / "page" / "kanban_supervisor" / "kanban_supervisor.js"
)
SUPERVISOR_API = APP_ROOT / "api" / "supervisor.py"


class TestCertificateProcessReleaseInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operator_panel = OPERATOR_PANEL.read_text()
        cls.supervisor_panel = SUPERVISOR_PANEL.read_text()
        cls.supervisor_api = SUPERVISOR_API.read_text()

    def test_available_no_bom_card_exposes_activation(self):
        self.assertIn(
            'if (!cycle && card.current_state === "Available" && '
            "state.operator.permissions.consume)",
            self.operator_panel,
        )
        self.assertIn(
            'add_action($actions, __("Consume / Trigger"), "btn-primary"',
            self.operator_panel,
        )
        self.assertIn("Select Consume / Trigger or scan Activate", self.operator_panel)

    def test_no_bom_card_does_not_imply_a_missing_work_order(self):
        self.assertIn("Not used — no-BOM Certificate Process", self.operator_panel)

    def test_released_cycle_shows_its_signal_approval_context(self):
        self.assertIn('document_link("cfg-kanban-signal", cycle.signal)', self.operator_panel)
        self.assertIn("Approve the Signal in the Kanban Supervisor Action Centre", self.operator_panel)

    def test_supervisor_queue_supports_certificate_process_signals(self):
        self.assertIn('"Certificate Process", "Purchase Replenishment"', self.supervisor_panel)
        self.assertIn('row.signal_type === "Certificate Process"', self.supervisor_panel)
        self.assertIn('"certificate_process_operation"', self.supervisor_api)
        self.assertIn('else "Release Certificate Process"', self.supervisor_api)


if __name__ == "__main__":
    unittest.main()

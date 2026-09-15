from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestOperatorAuthenticationContract(TestCase):
    def test_all_operator_mutations_require_operator_session(self):
        operator_api = (ROOT / "api" / "operator.py").read_text()
        scan_api = (ROOT / "api" / "scan.py").read_text()
        self.assertIn("require_operator(operator_session_token, action", operator_api)
        self.assertIn("require_operator(operator_session_token, \"report_progress\"", operator_api)
        self.assertIn("require_operator(operator_session_token, action)", scan_api)
        self.assertIn("require_operator(operator_session_token, permission_action)", scan_api)

    def test_credentials_are_hashed_before_lookup(self):
        source = (ROOT / "services" / "operator_auth.py").read_text()
        self.assertIn('"qr_token_hash": credential_hash(qr_token)', source)
        self.assertIn('"session_token_hash": credential_hash(raw_token)', source)
        self.assertNotIn('{"qr_token": qr_token}', source)

    def test_terminal_role_is_required_without_replacing_erp_session(self):
        source = (ROOT / "services" / "operator_auth.py").read_text()
        self.assertIn('"Kanban Terminal"', source)
        self.assertNotIn("frappe.local.login_manager", source)
        self.assertNotIn("frappe.set_user", source)

    def test_job_card_gateway_supports_employee_time_logs(self):
        source = (ROOT / "integrations" / "erp_gateway.py").read_text()
        self.assertIn('"employee": payload.get("employee")', source)
        self.assertIn("An Employee is required for a Kanban operator Job Card action", source)

    def test_console_supports_logout_printable_qr_and_fragment_deep_link(self):
        api = (ROOT / "api" / "operator.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                   "kanban_operator.js").read_text()
        profile = (ROOT / "public" / "js" / "cfg_kanban_operator_profile.js").read_text()
        self.assertIn('"qr_svg": get_qr_svg(login_url, 220)', api)
        self.assertIn("def get_console_access", api)
        self.assertIn("End Operator Session", console)
        self.assertIn('params.get("operator")', console)
        self.assertIn("window.history.replaceState", console)
        self.assertIn("Print Card", profile)
        self.assertIn("Download QR", profile)

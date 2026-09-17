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
        self.assertIn('"employee_image": employee.image', api)
        self.assertIn("def get_console_access", api)
        self.assertIn("End Operator Session", console)
        self.assertIn('params.get("operator")', console)
        self.assertIn("window.history.replaceState", console)
        self.assertIn("Print CR80 Horizontal Card", profile)
        self.assertIn("Print CR80 Vertical Card", profile)
        self.assertIn("@page{size:85.60mm 53.98mm;margin:0}", profile)
        self.assertIn("@page{size:53.98mm 85.60mm;margin:0}", profile)
        self.assertIn("Print Large QR Sheet", profile)
        self.assertIn("Download QR", profile)

    def test_operator_console_supports_scanner_first_commands(self):
        api = (ROOT / "api" / "operator.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                   "kanban_operator.js").read_text()
        self.assertIn("def get_scanner_command_sheet", api)
        self.assertIn("CFG:CMD:SWITCH_OPERATOR", api)
        self.assertIn("CFG:CMD:START", api)
        self.assertIn("CFG:CMD:REPORT_PROGRESS", api)
        self.assertIn("quantity_steps", api)
        self.assertIn("CFG:CMD:DISMISS", api)
        self.assertIn("CFG:QTY:GOOD:+1", api)
        self.assertIn("install_scanner_shortcuts", console)
        self.assertIn("inputmode: \"none\"", console)
        self.assertIn("Print Command Labels", console)
        self.assertIn('primary_action_label: __("Close")', console)
        self.assertIn('run_context_execution_action("start")', console)
        self.assertIn('run_context_execution_action("report_progress")', console)
        self.assertIn("capture_scan_behind_message", console)
        self.assertIn("configure_scanner_command_sheet", console)
        self.assertLess(console.index("cfg-scanner-status"),
                        console.index("cfg-kanban-card-camera"))

    def test_development_proxy_is_explicitly_enabled_and_administrator_only(self):
        auth = (ROOT / "services" / "operator_auth.py").read_text()
        api = (ROOT / "api" / "operator.py").read_text()
        settings = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_settings" /
                    "cfg_kanban_settings.json").read_text()
        session = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_operator_session" /
                   "cfg_kanban_operator_session.json").read_text()
        self.assertIn('frappe.session.user != "Administrator"', auth)
        self.assertIn('"enable_administrator_operator_bypass"', auth)
        self.assertIn("def login_development_proxy", api)
        self.assertIn('"default": "0"', settings)
        self.assertIn('"development_proxy"', session)

    def test_process_task_actions_reuse_operator_authorization(self):
        auth = (ROOT / "services" / "operator_auth.py").read_text()
        api = (ROOT / "api" / "process_task.py").read_text()
        self.assertIn('"task_start": "can_start"', auth)
        self.assertIn('"task_complete": "can_complete"', auth)
        self.assertIn('"task_verify": "can_verify_tasks"', auth)
        self.assertIn("require_operator", api)

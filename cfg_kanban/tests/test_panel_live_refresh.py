from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestPanelLiveRefreshContract(TestCase):
    def test_service_panel_uses_lightweight_revision_before_full_refresh(self):
        api = (ROOT / "api" / "task.py").read_text()
        auth = (ROOT / "services" / "operator_auth.py").read_text()
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                 "kanban_tasks.js").read_text()
        self.assertIn("def get_service_tasks_live_revision", api)
        self.assertIn("hashlib.sha256", api)
        self.assertIn("live_poll_ms = 15000", panel)
        self.assertIn("check_live_updates", panel)
        self.assertIn("get_service_tasks_live_revision", panel)
        self.assertIn("live_refresh_safe", panel)
        self.assertIn("interaction_epoch", panel)
        self.assertIn("frappe.dom?.freeze_count", panel)
        self.assertGreaterEqual(panel.count("if (!live_refresh_safe(requested_token, requested_epoch)) return;"), 3)
        self.assertIn("state.task_filter", panel)
        self.assertIn("Live update received", panel)
        self.assertIn("touch_activity=True", auth)
        self.assertIn("touch_activity=False", api)
        self.assertIn("operator_session_expired", panel)

    def test_logistics_panel_refreshes_selected_work_only_after_revision_change(self):
        api = (ROOT / "api" / "logistics.py").read_text()
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                 "kanban_logistics.js").read_text()
        self.assertIn("def get_logistics_live_revision", api)
        self.assertIn("selected_manifest", api)
        self.assertIn("hashlib.sha256", api)
        self.assertIn("live_poll_ms = 15000", panel)
        self.assertIn("refresh_live_work_context", panel)
        self.assertIn("get_logistics_live_revision", panel)
        self.assertIn("refresh_list(false, apply_guard)", panel)
        self.assertIn("refresh_live_work_context(apply_guard)", panel)
        self.assertIn("live_refresh_safe", panel)
        self.assertIn("interaction_epoch", panel)
        self.assertIn("frappe.dom?.freeze_count", panel)
        self.assertIn("if (!apply_guard()) return false;", panel)
        self.assertIn("Live update received", panel)
        self.assertIn("touch_activity=False", api)
        self.assertIn("operator_session_expired", panel)

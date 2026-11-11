import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestMasterAutomationPolicy(TestCase):
    def test_master_exposes_global_or_individual_policy_selection(self):
        path = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_master" /
                "cfg_kanban_master.json")
        schema = json.loads(path.read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        source = fields["automation_policy_source"]
        override = fields["automation_level"]
        self.assertEqual(source["default"], "Master Override")
        self.assertIn("Use Global Default", source["options"])
        self.assertEqual(override["label"], "Master Automation Override")
        self.assertIn("automation_policy_source", override["depends_on"])

    def test_policy_service_preserves_existing_masters_and_snapshots_effective_value(self):
        policy = (ROOT / "services" / "automation_policy.py").read_text()
        trigger = (ROOT / "services" / "triggers.py").read_text()
        threshold = (ROOT / "services" / "inventory_threshold.py").read_text()
        self.assertIn('or MASTER_OVERRIDE', policy)
        self.assertIn('get_single_value(', policy)
        self.assertIn('"CFG Kanban Settings", "default_automation_level"', policy)
        self.assertIn("get_effective_automation_level(master)", trigger)
        self.assertIn('"automation_level": effective_automation_level', trigger)
        self.assertIn("get_effective_automation_level(master)", threshold)
        self.assertIn('"automation_level": effective_automation_level', threshold)

    def test_operator_context_reports_effective_and_configured_policy(self):
        operator = (ROOT / "api" / "operator.py").read_text()
        self.assertIn("get_automation_policy_snapshot(master)", operator)
        self.assertIn('"automation_level": automation_policy["effective_level"]', operator)
        self.assertIn('"automation_policy_source": automation_policy["source"]', operator)

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "cfg_kanban" / "report" / "cfg_shared_job_register"
WORKSPACE_PATH = (
    ROOT
    / "cfg_kanban"
    / "workspace"
    / "cfg_job_architecture"
    / "cfg_job_architecture.json"
)


class TestSharedJobRegisterContract(unittest.TestCase):
    def test_report_reuses_cycle_as_shared_job(self):
        report = json.loads((REPORT_ROOT / "cfg_shared_job_register.json").read_text())
        self.assertEqual(report["name"], "CFG Shared Job Register")
        self.assertEqual(report["ref_doctype"], "CFG Kanban Job Participation")
        self.assertEqual(report["report_type"], "Script Report")

        source = (REPORT_ROOT / "cfg_shared_job_register.py").read_text()
        self.assertIn('"CFG Kanban Cycle"', source)
        self.assertIn("tabCFG Kanban Process Execution", source)
        self.assertIn("tabCFG Kanban Job Participation", source)
        self.assertIn("operational evidence", source)
        self.assertNotIn("CFG Work Instance", source)
        self.assertNotIn("CFG Work Participation", source)

    def test_report_uses_permission_aware_cycle_selection(self):
        source = (REPORT_ROOT / "cfg_shared_job_register.py").read_text()
        self.assertIn("frappe.get_list(", source)
        self.assertNotIn("frappe.get_all(\n        \"CFG Kanban Cycle\"", source)

    def test_workspace_exposes_shared_job_register(self):
        workspace = json.loads(WORKSPACE_PATH.read_text())
        links = {
            row.get("link_to")
            for row in workspace["links"]
            if row.get("type") == "Link"
        }
        self.assertIn("CFG Shared Job Register", links)

    def test_report_filter_definitions_remain_read_only(self):
        script = (REPORT_ROOT / "cfg_shared_job_register.js").read_text()
        for fieldname in (
            "company",
            "status",
            "item_code",
            "work_order",
            "from_date",
            "to_date",
            "active_only",
        ):
            self.assertIn(f'fieldname: "{fieldname}"', script)
        self.assertNotIn("frappe.call", script)


if __name__ == "__main__":
    unittest.main()

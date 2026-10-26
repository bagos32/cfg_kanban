import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = ROOT / "cfg_kanban" / "page" / "kanban_workforce_supervisor"


class TestWorkforceSupervisorCentre(unittest.TestCase):
    def test_page_is_manager_only_and_separate_from_production_action_centre(self):
        page = json.loads((PAGE_ROOT / "kanban_workforce_supervisor.json").read_text())
        self.assertEqual(page["name"], "kanban-workforce-supervisor")
        self.assertEqual(page["module"], "CFG Kanban")
        roles = {row["role"] for row in page["roles"]}
        self.assertEqual(roles, {"Manufacturing Manager", "HR Manager", "System Manager"})

    def test_api_is_read_only_permission_aware_and_reuses_existing_records(self):
        source = (ROOT / "api" / "workforce_supervisor.py").read_text()
        self.assertIn("def get_workforce_action_centre(", source)
        self.assertIn("frappe.get_list(", source)
        self.assertIn("frappe.has_permission", source)
        self.assertIn("doc.check_permission(\"read\")", source)
        self.assertNotIn("frappe.db.sql(", source)
        self.assertNotIn(".insert(", source)
        self.assertNotIn(".db_set(", source)
        self.assertIn('{"control_type": "Production"}', source)
        for doctype in (
            "CFG Kanban Cycle",
            "CFG Kanban Process Execution",
            "CFG Kanban Crew Session",
            "CFG Kanban Crew Membership",
            "CFG Kanban Employee Competency",
            "CFG Kanban Job Participation",
            "CFG Kanban Supervisor Action Approval",
        ):
            self.assertIn(doctype, source)

    def test_participation_is_explicitly_not_payroll(self):
        source = (ROOT / "api" / "workforce_supervisor.py").read_text()
        panel = (PAGE_ROOT / "kanban_workforce_supervisor.js").read_text()
        self.assertIn('"payroll_authoritative": False', source)
        self.assertIn("not attendance, payroll eligibility, or payable hours", panel)

    def test_hidden_tabs_do_not_keep_refreshing_server(self):
        panel = (PAGE_ROOT / "kanban_workforce_supervisor.js").read_text()
        self.assertIn("if (!freeze && document.hidden) return schedule()", panel)
        self.assertIn("visibilitychange.cfg-workforce", panel)
        self.assertIn("state.loading", panel)

    def test_transfer_target_is_visible_in_exact_action_audit(self):
        source = (ROOT / "api" / "workforce_supervisor.py").read_text()
        panel = (PAGE_ROOT / "kanban_workforce_supervisor.js").read_text()
        self.assertIn('"subject_employee", "subject_name"', source)
        self.assertIn('row.subject_name || row.subject_employee', panel)

    def test_workspace_exposes_centre(self):
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_job_architecture"
            / "cfg_job_architecture.json"
        ).read_text())
        self.assertTrue(any(
            row.get("link_to") == "kanban-workforce-supervisor"
            for row in workspace["links"]
        ))


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_PATH = (
    ROOT
    / "cfg_kanban"
    / "workspace"
    / "cfg_job_architecture"
    / "cfg_job_architecture.json"
)


class TestJobArchitectureWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = json.loads(WORKSPACE_PATH.read_text())
        cls.content = json.loads(cls.workspace["content"])

    def test_is_separate_workspace_inside_cfg_kanban(self):
        self.assertEqual(self.workspace["name"], "CFG Job Architecture")
        self.assertEqual(self.workspace["module"], "CFG Kanban")
        self.assertEqual(self.workspace["parent_page"], "CFG Kanban")
        self.assertEqual(self.workspace["public"], 1)

    def test_exposes_existing_workforce_and_execution_records(self):
        links = {
            row.get("link_to")
            for row in self.workspace["links"]
            if row.get("type") == "Link"
        }
        expected = {
            "CFG Kanban Operator Profile",
            "CFG Kanban Skill",
            "CFG Kanban Employee Competency",
            "CFG Kanban Crew Requirement Profile",
            "CFG Kanban Workstation Crew Requirement",
            "CFG Kanban Crew Template",
            "CFG Kanban Crew Session",
            "CFG Kanban Crew Membership",
            "CFG Kanban Crew Event",
            "CFG Kanban Crew Compliance Check",
            "CFG Kanban Job Participation",
            "CFG Kanban Cycle",
            "CFG Kanban Process Execution",
            "CFG Kanban Operation Progress",
            "CFG Kanban Operation Summary",
            "CFG Kanban Event",
            "CFG Kanban Exception",
        }
        self.assertTrue(expected.issubset(links))

    def test_does_not_claim_unimplemented_architecture_records(self):
        serialized = json.dumps(self.workspace)
        for proposed_record in (
            "CFG Shared Job",
            "CFG EODR",
            "CFG Payroll Export",
            "CFG Capacity Ledger",
        ):
            self.assertNotIn(proposed_record, serialized)
        self.assertEqual(self.workspace["charts"], [])
        self.assertEqual(self.workspace["number_cards"], [])

    def test_content_references_defined_shortcuts_and_cards(self):
        shortcut_names = {row["label"] for row in self.workspace["shortcuts"]}
        card_names = {
            row["label"]
            for row in self.workspace["links"]
            if row.get("type") == "Card Break"
        }
        for block in self.content:
            if block["type"] == "shortcut":
                self.assertIn(block["data"]["shortcut_name"], shortcut_names)
            elif block["type"] == "card":
                self.assertIn(block["data"]["card_name"], card_names)


if __name__ == "__main__":
    unittest.main()

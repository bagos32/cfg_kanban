import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


def fields(doctype):
    return {row["fieldname"]: row for row in schema(doctype)["fields"]}


class TestRuntimeRoleAssignmentFoundation(unittest.TestCase):
    def test_assignment_is_read_only_audit_history(self):
        assignment = schema("CFG Kanban Cycle Role Assignment")
        assignment_fields = {row["fieldname"]: row for row in assignment["fields"]}
        self.assertEqual(assignment["autoname"], "CRA-.YYYY.-.#####")
        self.assertEqual(assignment_fields["status"]["options"], "Active\nEnded")
        self.assertEqual(assignment_fields["assignment_source"]["options"],
                         "Cycle Ownership\nActive Crew")
        self.assertTrue(all(not row.get("write") for row in assignment["permissions"]))

    def test_cycle_has_advisory_summary_fields(self):
        cycle = fields("CFG Kanban Cycle")
        for fieldname in (
            "job_role_compliance_status",
            "job_role_compliance_summary",
            "job_role_last_evaluated_on",
        ):
            self.assertEqual(cycle[fieldname]["read_only"], 1)
        self.assertEqual(cycle["job_role_compliance_status"]["default"], "Not Configured")

    def test_runtime_service_is_advisory_and_auditable(self):
        source = (ROOT / "services" / "runtime_roles.py").read_text()
        self.assertIn("for update", source)
        self.assertIn('"enforcement_active": False', source)
        self.assertIn('"advisory_only": True', source)
        self.assertIn("separate_approver_required", source)
        self.assertIn("has_authority_role", source)
        self.assertIn("employee_has_competency", source)
        self.assertIn("Cycle Ownership", source)
        self.assertIn("Active Crew", source)

    def test_operator_context_and_live_revision_include_role_coverage(self):
        source = (ROOT / "api" / "operator.py").read_text()
        self.assertIn('"job_role_compliance": job_role_compliance', source)
        self.assertIn("evaluate_cycle_roles(cycle.name, persist=True)", source)
        self.assertIn('"CFG Kanban Cycle Role Assignment"', source)

    def test_terminal_cycle_paths_close_role_intervals(self):
        state_machine = (ROOT / "services" / "state_machine.py").read_text()
        cancellation = (ROOT / "services" / "signal_cancellation.py").read_text()
        self.assertIn("close_cycle_role_assignments", state_machine)
        self.assertIn("close_cycle_role_assignments", cancellation)

    def test_operator_panel_and_workspace_expose_coverage(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_job_architecture"
            / "cfg_job_architecture.json"
        ).read_text())
        self.assertIn("Job Role Coverage", panel)
        self.assertIn("Advisory visibility only in P07-0B1", panel)
        self.assertTrue(any(
            row.get("link_to") == "CFG Kanban Cycle Role Assignment"
            for row in workspace["links"]
        ))


if __name__ == "__main__":
    unittest.main()

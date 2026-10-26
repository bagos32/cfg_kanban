import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class TestSupervisorActionApproval(unittest.TestCase):
    def test_approval_is_read_only_hash_backed_audit_history(self):
        approval = schema("CFG Kanban Supervisor Action Approval")
        approval_fields = {row["fieldname"]: row for row in approval["fields"]}
        self.assertEqual(approval["autoname"], "SAA-.YYYY.-.#####")
        self.assertEqual(
            approval_fields["status"]["options"],
            "Approved\nConsumed\nExpired\nCancelled",
        )
        self.assertEqual(approval_fields["approval_token_hash"]["hidden"], 1)
        self.assertEqual(approval_fields["approval_token_hash"]["unique"], 1)
        self.assertTrue(all(not row.get("write") for row in approval["permissions"]))

    def test_service_is_exact_action_scoped_and_single_use(self):
        source = (ROOT / "services" / "action_approval.py").read_text()
        self.assertIn('"CLOSE_CYCLE_ON_BEHALF": "can_close_on_behalf"', source)
        self.assertIn("add_to_date(current, minutes=2)", source)
        self.assertIn("approval_token_hash", source)
        self.assertIn("credential_hash(raw_token)", source)
        self.assertIn("hmac.compare_digest", source)
        self.assertIn("for update", source)
        self.assertIn('"status": "Consumed"', source)
        self.assertIn("different action context", source)
        self.assertIn("def _retire_prior_approvals(", source)

    def test_requirement_uses_snapshot_scope_competency_presence_and_separation(self):
        source = (ROOT / "services" / "action_approval.py").read_text()
        self.assertIn('("Supervisor / Mentor", "Verifier")', source)
        self.assertIn("has_authority_role", source)
        self.assertIn("employee_has_competency", source)
        self.assertIn("separate_approver_required", source)
        self.assertIn('"CFG Kanban Cycle Role Assignment"', source)
        self.assertIn('"status": "Active"', source)
        self.assertIn('"CFG Kanban Job Code"', source)

    def test_requirement_resolves_projected_execution_rows_by_name(self):
        source = (ROOT / "services" / "action_approval.py").read_text()
        helper = source[source.index("def _execution_doc(execution):"):]
        self.assertIn("if isinstance(execution, dict):", helper)
        self.assertIn('execution_name = execution.get("name")', helper)
        self.assertIn(
            'frappe.get_doc("CFG Kanban Process Execution", execution_name)',
            helper,
        )

    def test_close_api_consumes_pass_before_state_mutation(self):
        source = (ROOT / "api" / "operator.py").read_text()
        function_start = source.index("def complete_runtime_cycle(")
        consume = source.index("consume_action_approval(", function_start)
        mutation = source.index('execution.db_set({"status": "Completed"', function_start)
        self.assertLess(consume, mutation)
        self.assertIn("def approve_supervisor_action(", source)
        self.assertIn("supervisor_approval_token=None", source)
        self.assertIn('execution["close_requires_supervisor_approval"]', source)

    def test_scanner_dialog_does_not_switch_operator(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertIn("Supervisor Pass & Close", panel)
        self.assertIn("approve_supervisor_action", panel)
        self.assertIn("supervisor_qr_token: operator_token_from_scan(credential)", panel)
        self.assertIn("does not switch the active operator", panel)
        self.assertIn("supervisor_approval_token", panel)
        approval_dialog = panel[panel.index("function close_runtime_cycle(row)"):]
        self.assertNotIn("login_operator", approval_dialog[:8000])

    def test_workspace_exposes_approval_audit(self):
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_job_architecture"
            / "cfg_job_architecture.json"
        ).read_text())
        self.assertTrue(any(
            row.get("link_to") == "CFG Kanban Supervisor Action Approval"
            for row in workspace["links"]
        ))
        self.assertTrue(any(
            row.get("link_to") == "CFG Kanban Supervisor Action Approval"
            for row in workspace["shortcuts"]
        ))


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class TestCorrectionRequests(unittest.TestCase):
    def test_request_is_a_read_only_audit_record(self):
        request = schema("CFG Kanban Correction Request")
        fields = {row["fieldname"]: row for row in request["fields"]}
        self.assertEqual(
            fields["status"]["options"].splitlines(),
            [
                "Open", "Under Review", "Approved", "Rejected",
                "ERP Correction Required", "Resolved",
            ],
        )
        self.assertEqual(fields["affected_document"]["options"], "affected_doctype")
        self.assertEqual(
            fields["erp_correction_document"]["options"], "erp_correction_doctype"
        )
        self.assertTrue(fields["current_value_snapshot"]["read_only"])
        self.assertTrue(fields["idempotency_key"]["unique"])
        for permission in request["permissions"]:
            self.assertFalse(permission.get("create"))
            self.assertFalse(permission.get("write"))
            self.assertFalse(permission.get("delete"))
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_correction_request"
            / "cfg_kanban_correction_request.py"
        ).read_text()
        self.assertIn("immutable audit records and cannot be deleted", controller)
        self.assertIn("use the Workforce Supervisor Centre", controller)

    def test_creation_snapshots_but_does_not_rewrite_affected_record(self):
        service = (ROOT / "services" / "correction_requests.py").read_text()
        self.assertIn("def create_correction_request(", service)
        self.assertIn("_resolve_affected_record(", service)
        self.assertIn("_record_snapshot(", service)
        self.assertIn('"current_value_snapshot": json.dumps(snapshot', service)
        self.assertIn('canonical_key(\n        "correction-request"', service)
        self.assertIn("insert_once(", service)
        self.assertIn("Use a real Employee operator credential", service)
        self.assertNotIn("frappe.delete_doc", service)
        self.assertNotIn("frappe.db.delete", service)
        for protected in ("Work Order", "Job Card", "Stock Entry"):
            self.assertNotIn(f'frappe.get_doc("{protected}"', service)

    def test_review_uses_exact_action_correct_records_authority(self):
        service = (ROOT / "services" / "correction_requests.py").read_text()
        approval = (ROOT / "services" / "action_approval.py").read_text()
        self.assertIn("approve_and_consume_correction_review(", service)
        self.assertIn('"APPROVE_CORRECTION_REQUEST": "can_correct_records"', approval)
        self.assertIn('"REJECT_CORRECTION_REQUEST": "can_correct_records"', approval)
        self.assertIn('"REQUIRE_ERP_CORRECTION": "can_correct_records"', approval)
        self.assertIn('"RESOLVE_CORRECTION_REQUEST": "can_correct_records"', approval)
        self.assertIn("cannot approve their own correction decision", approval)
        self.assertIn('"correction_request": request.name', approval)
        self.assertIn("consume_action_approval(", approval)

        approval_schema = schema("CFG Kanban Supervisor Action Approval")
        fields = {row["fieldname"]: row for row in approval_schema["fields"]}
        self.assertEqual(
            fields["correction_request"]["options"], "CFG Kanban Correction Request"
        )
        self.assertEqual(fields["action_terminal_user"]["options"], "User")

    def test_review_state_machine_never_applies_the_future_adjustment(self):
        service = (ROOT / "services" / "correction_requests.py").read_text()
        self.assertIn('"Start Review": {', service)
        self.assertIn('"Approve Kanban Adjustment": {', service)
        self.assertIn('"Require ERP Correction": {', service)
        self.assertIn('"Resolve": {', service)
        self.assertIn('"from": {"ERP Correction Required"}', service)
        self.assertIn("request.db_set(values", service)
        self.assertNotIn("apply_correction", service)
        self.assertNotIn("amend_work_order", service)
        self.assertNotIn("cancel_stock_entry", service)
        self.assertIn("Link the authoritative ERPNext correction document", service)

    def test_floor_and_supervisor_surfaces_are_connected(self):
        operator_api = (ROOT / "api" / "operator.py").read_text()
        operator_panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        supervisor_api = (ROOT / "api" / "workforce_supervisor.py").read_text()
        supervisor_panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_workforce_supervisor"
            / "kanban_workforce_supervisor.js"
        ).read_text()
        self.assertIn('("Report Correction", "CFG:CMD:REQUEST_CORRECTION"', operator_api)
        self.assertIn("def submit_correction_request(", operator_api)
        self.assertIn("REQUEST_CORRECTION: open_context_correction_request", operator_panel)
        self.assertIn("Audit-safe request only", operator_panel)
        self.assertIn("def _correction_requests(", supervisor_api)
        self.assertIn('"open_corrections": len(corrections)', supervisor_api)
        self.assertIn("Controlled Correction Queue", supervisor_panel)
        self.assertIn("review_correction_request", supervisor_panel)
        self.assertIn("Correct Records authority", supervisor_panel)

    def test_workspace_exposes_correction_audit(self):
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_job_architecture"
            / "cfg_job_architecture.json"
        ).read_text())
        self.assertTrue(any(
            row.get("link_to") == "CFG Kanban Correction Request"
            for row in workspace["links"]
        ))


if __name__ == "__main__":
    unittest.main()

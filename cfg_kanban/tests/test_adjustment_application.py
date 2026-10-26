import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class TestAdjustmentApplication(unittest.TestCase):
    def test_application_has_distinct_exact_action_authority(self):
        approval = (ROOT / "services" / "action_approval.py").read_text()
        self.assertIn(
            '"APPLY_KANBAN_ADJUSTMENT": "can_correct_records"', approval
        )
        self.assertIn("def approve_and_consume_adjustment_application(", approval)
        self.assertIn("cannot apply their own adjustment", approval)
        self.assertIn("cannot also authorize its application", approval)
        self.assertIn('"adjustment_proposal": proposal.name', approval)
        self.assertIn("adjustment_proposal=proposal.name", approval)

        fields = {
            row["fieldname"]: row
            for row in schema("CFG Kanban Supervisor Action Approval")["fields"]
        }
        self.assertEqual(
            fields["adjustment_proposal"]["options"],
            "CFG Kanban Adjustment Proposal",
        )

    def test_application_is_append_only_and_kanban_scoped(self):
        service = (ROOT / "services" / "adjustment_proposals.py").read_text()
        self.assertIn("def apply_operation_quantity_adjustment(", service)
        self.assertIn("def _assert_prepared_application_current(", service)
        self.assertIn('"doctype": "CFG Kanban Operation Progress"', service)
        self.assertIn('"source": "Correction"', service)
        self.assertIn('"adjustment_proposal": proposal.name', service)
        self.assertIn("execution.db_set({", service)
        self.assertIn("recalculate(cycle.name, execution.operation)", service)
        self.assertIn('"status": "Applied"', service)
        self.assertIn('"status": "Resolved"', service)
        self.assertIn('"resolution_type": "Kanban Adjustment Applied"', service)
        self.assertIn('"erpnext_changed": False', service)
        self.assertIn('"payroll_changed": False', service)
        self.assertNotIn("frappe.delete_doc", service)
        self.assertNotIn("frappe.db.delete", service)
        self.assertNotIn('frappe.get_doc("Work Order"', service)
        self.assertNotIn('frappe.get_doc("Job Card"', service)
        self.assertNotIn('frappe.get_doc("Stock Entry"', service)

    def test_application_blocks_stale_or_unsafe_proposals(self):
        service = (ROOT / "services" / "adjustment_proposals.py").read_text()
        self.assertIn("execution.modified", service)
        self.assertIn("proposal.target_modified_on", service)
        self.assertIn("changed after this proposal was prepared", service)
        self.assertIn("prepare a new revision from current values", service)
        self.assertIn("proposal.current_good_qty", service)
        self.assertIn("proposal.current_reject_qty", service)
        self.assertIn("proposal.current_processed_qty", service)
        self.assertIn("proposal.released_qty", service)
        self.assertIn("_operation_quantity_preview(", service)

    def test_application_audit_links_are_explicit(self):
        proposal_fields = {
            row["fieldname"]: row
            for row in schema("CFG Kanban Adjustment Proposal")["fields"]
        }
        self.assertEqual(
            proposal_fields["application_progress"]["options"],
            "CFG Kanban Operation Progress",
        )
        self.assertTrue(proposal_fields["application_idempotency_key"]["unique"])
        progress_fields = {
            row["fieldname"]: row
            for row in schema("CFG Kanban Operation Progress")["fields"]
        }
        self.assertEqual(
            progress_fields["correction_request"]["options"],
            "CFG Kanban Correction Request",
        )
        self.assertEqual(
            progress_fields["adjustment_proposal"]["options"],
            "CFG Kanban Adjustment Proposal",
        )
        request_fields = {
            row["fieldname"]: row
            for row in schema("CFG Kanban Correction Request")["fields"]
        }
        self.assertIn(
            "Kanban Adjustment Applied",
            request_fields["resolution_type"]["options"].splitlines(),
        )

    def test_supervisor_centre_exposes_controlled_application(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_workforce_supervisor"
            / "kanban_workforce_supervisor.js"
        ).read_text()
        api = (ROOT / "api" / "workforce_supervisor.py").read_text()
        self.assertIn("Apply Adjustment", panel)
        self.assertIn("Kanban operational correction only", panel)
        self.assertIn("Separate Exact-action Authority", panel)
        self.assertIn("apply_operation_quantity_adjustment", panel)
        self.assertIn("ERPNext and payroll unchanged", panel)
        self.assertIn('"adjustment_current_good"', api)
        self.assertIn('"adjustment_prepared_by_employee"', api)


if __name__ == "__main__":
    unittest.main()

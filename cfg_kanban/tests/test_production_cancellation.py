import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(slug):
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class TestControlledProductionCancellation(unittest.TestCase):
    def test_control_record_is_one_per_cycle_and_audit_only(self):
        cancellation = schema("cfg_kanban_production_cancellation")
        fields = {row["fieldname"]: row for row in cancellation["fields"]}
        self.assertEqual(cancellation["autoname"], "KPC-.YYYY.-.#####")
        self.assertEqual(fields["kanban_cycle"]["options"], "CFG Kanban Cycle")
        self.assertEqual(fields["kanban_cycle"]["unique"], 1)
        self.assertEqual(fields["dependencies"]["options"],
                         "CFG Kanban Production Cancellation Dependency")
        self.assertEqual(
            fields["status"]["options"].splitlines(),
            ["Frozen", "Awaiting ERP Reversal", "Awaiting Physical Reconciliation",
             "Ready to Finalize", "Completed"],
        )
        self.assertTrue(all(not row.get("write") and not row.get("create")
                            for row in cancellation["permissions"]))
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_production_cancellation" /
            "cfg_kanban_production_cancellation.py"
        ).read_text()
        self.assertIn("cannot be deleted", controller)
        self.assertIn("system-controlled", controller)

    def test_cycle_links_exact_control_record(self):
        fields = {
            row["fieldname"]: row for row in schema("cfg_kanban_cycle")["fields"]
        }
        self.assertEqual(fields["production_cancellation"]["options"],
                         "CFG Kanban Production Cancellation")
        self.assertEqual(fields["production_cancellation"]["read_only"], 1)

    def test_service_freezes_before_reconciliation_and_releases_only_at_end(self):
        service = (ROOT / "services" / "production_cancellation.py").read_text()
        self.assertIn("def request_production_cancellation(", service)
        self.assertIn('"status": "Hold"', service)
        self.assertIn('"current_state": "Blocked"', service)
        self.assertIn('"Awaiting ERP Reversal"', service)
        self.assertIn('"Awaiting Physical Reconciliation"', service)
        self.assertIn('"Ready to Finalize"', service)
        self.assertIn("def finalize_production_cancellation(", service)
        self.assertIn('if cancellation.status != "Ready to Finalize"', service)
        self.assertIn('"current_state": "Available"', service)
        self.assertIn('"active_cycle": None', service)
        self.assertIn('"dispatch_status": "Cancelled"', service)
        self.assertIn("def _freeze_related_runtime_cycles", service)
        self.assertIn("def _finalize_related_runtime_cycle", service)
        self.assertIn("Related Operation Card Released after Production Cancellation", service)
        self.assertIn('"Kanban Scope"', service)
        self.assertNotIn("delete_doc(", service)
        self.assertIn("def cancel_production_job_card(", service)
        self.assertIn("def cancel_production_work_order(", service)
        self.assertIn("job_card.flags.ignore_links = True", service)
        self.assertIn("job_card.db_set(_cancelled_job_card_values()", service)
        self.assertIn('frappe.get_meta("Job Card").has_field("is_paused")', service)
        self.assertIn("work_order.flags.ignore_links = True", service)
        self.assertIn("_assert_stock_entries_reversed(cycle)", service)

    def test_assessment_covers_erp_and_physical_dependencies(self):
        service = (ROOT / "services" / "production_cancellation.py").read_text()
        for evidence in (
            '"Work Order"', '"Job Card"', '"Stock Entry"',
            '"CFG Kanban WIP Bin Load"',
            '"CFG Kanban WIP Bin Reconciliation"',
            '"CFG Kanban Handling Unit"',
            '"CFG Kanban Operation Progress"',
            '"CFG Kanban WIP Ledger"',
        ):
            self.assertIn(evidence, service)
        self.assertIn("Material Consumption for Manufacture", service)
        self.assertIn("Material Transfer for Manufacture", service)
        self.assertIn("Pause Job Card", service)

    def test_floor_writes_are_frozen_but_records_remain_readable(self):
        guard = "assert_cycle_not_under_cancellation"
        operator_auth = (ROOT / "services" / "operator_auth.py").read_text()
        production_trace = (ROOT / "services" / "production_trace.py").read_text()
        process_tasks = (ROOT / "services" / "process_tasks.py").read_text()
        self.assertIn("if action:", operator_auth)
        self.assertIn(guard, operator_auth)
        self.assertIn('permission_type == "write"', production_trace)
        self.assertIn(guard, production_trace)
        self.assertIn("_assert_cycle_execution_open(task.kanban_cycle)", process_tasks)
        self.assertIn(guard, process_tasks)

        runtime = (ROOT / "services" / "runtime_selector.py").read_text()
        self.assertIn("_work_order_execution_open(row.owner_cycle)", runtime)
        self.assertIn("_assert_work_order_execution_open(proposal", runtime)
        self.assertIn("for update", runtime)

    def test_manager_ui_and_supervisor_queue_expose_controlled_path(self):
        cycle_js = (ROOT / "public" / "js" / "cfg_kanban_cycle.js").read_text()
        signal_js = (ROOT / "public" / "js" / "cfg_kanban_signal.js").read_text()
        control_js = (
            ROOT / "public" / "js" / "cfg_kanban_production_cancellation.js"
        ).read_text()
        supervisor_api = (ROOT / "api" / "supervisor.py").read_text()
        supervisor_js = (
            ROOT / "cfg_kanban" / "page" / "kanban_supervisor" /
            "kanban_supervisor.js"
        ).read_text()
        self.assertIn("Request Controlled Cancellation", cycle_js)
        self.assertIn("Controlled Production Cancellation", signal_js)
        self.assertIn("Refresh Assessment", control_js)
        self.assertIn("Cancel Linked Job Card", control_js)
        self.assertIn("Cancel Work Order", control_js)
        self.assertIn("Finalize and Release Card", control_js)
        self.assertIn("def _production_cancellations", supervisor_api)
        self.assertIn("Controlled Production Cancellation", supervisor_js)

    def test_workspace_exposes_cancellation_audit(self):
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" / "cfg_kanban.json"
        ).read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(
            links["Controlled Production Cancellations"],
            "CFG Kanban Production Cancellation",
        )


if __name__ == "__main__":
    unittest.main()

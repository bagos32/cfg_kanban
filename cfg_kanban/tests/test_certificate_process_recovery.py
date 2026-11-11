import json
from pathlib import Path
from unittest import TestCase


APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = APP_ROOT / "cfg_kanban" / "doctype"


class TestCertificateProcessRecovery(TestCase):
    def test_recovery_is_an_immutable_audit_record(self):
        folder = DOCTYPE_ROOT / "cfg_process_certificate_recovery"
        schema = json.loads((folder / "cfg_process_certificate_recovery.json").read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        for fieldname in (
            "status", "certificate_process_run", "kanban_cycle", "kanban_card",
            "reason", "previous_run_status", "repack_stock_entry_name",
            "repack_snapshot", "source_handling_unit", "output_handling_unit",
            "blocking_reason", "final_reconciliation_evidence",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["certificate_process_run"]["unique"])
        controller = (folder / "cfg_process_certificate_recovery.py").read_text()
        self.assertIn("system-controlled", controller)
        self.assertIn("audit evidence and cannot be deleted", controller)

    def test_recovery_requires_erp_and_physical_reconciliation_before_card_release(self):
        service = (APP_ROOT / "services" / "certificate_process_recovery.py").read_text()
        self.assertIn("def request_certificate_process_recovery", service)
        self.assertIn("def cancel_certificate_process_repack", service)
        self.assertIn("def finalize_certificate_process_recovery", service)
        self.assertIn("_physical_reversal_blocker(run)", service)
        self.assertIn('entry.docstatus == 1', service)
        self.assertIn("entry.flags.ignore_links = True", service)
        self.assertIn('event_type="Merge"', service)
        self.assertIn('run.output_tag_mode != "Merge Existing"', service)
        self.assertIn("run.output_tag_qty_before", service)
        self.assertIn('"process_certificate_set": run.source_certificate_set', service)
        self.assertIn('"identity_state": "Void"', service)
        self.assertIn('"status": "Cancelled"', service)
        self.assertIn('"active_cycle": None, "blocked": 0', service)

    def test_stock_entry_cancel_and_manager_forms_are_connected(self):
        feedback = (APP_ROOT / "integrations" / "erp_feedback.py").read_text()
        hooks = (APP_ROOT / "hooks.py").read_text()
        run_js = (APP_ROOT / "public" / "js" / "cfg_process_certificate_run.js").read_text()
        recovery_js = (
            APP_ROOT / "public" / "js" / "cfg_process_certificate_recovery.js"
        ).read_text()
        self.assertIn("sync_recovery_from_stock_entry(doc)", feedback)
        self.assertIn('"CFG Process Certificate Run"', hooks)
        self.assertIn('"CFG Process Certificate Recovery"', hooks)
        self.assertIn("Request Controlled Recovery", run_js)
        self.assertIn("Cancel ERPNext Repack", recovery_js)
        self.assertIn("Finalize and Release Card", recovery_js)

    def test_operator_and_workspace_expose_recovery_attention(self):
        operator = (
            APP_ROOT / "cfg_kanban" / "page" / "kanban_operator" /
            "kanban_operator.js"
        ).read_text()
        workspace = json.loads((
            APP_ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
            "cfg_kanban.json"
        ).read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertIn("Controlled recovery in progress", operator)
        self.assertEqual(
            links["Certificate Process Recoveries"],
            "CFG Process Certificate Recovery",
        )

    def test_normal_signal_cancellation_redirects_to_controlled_recovery(self):
        cancellation = (APP_ROOT / "services" / "signal_cancellation.py").read_text()
        self.assertIn("use controlled Certificate Process recovery", cancellation)

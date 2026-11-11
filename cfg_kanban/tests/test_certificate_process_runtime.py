import json
from pathlib import Path
from unittest import TestCase


APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = APP_ROOT / "cfg_kanban" / "doctype"


def schema(folder):
    return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())


class TestCertificateProcessRuntime(TestCase):
    def test_master_has_dedicated_no_bom_runtime_configuration(self):
        master = schema("cfg_kanban_master")
        fields = {row["fieldname"]: row for row in master["fields"]}
        self.assertIn("Certificate Process", fields["control_type"]["options"])
        for fieldname in (
            "certificate_process_operation", "certificate_process_posting_mode",
            "certificate_process_progress_mode",
            "certificate_process_allow_partial_qty", "certificate_process_reuse_source_tag",
            "certificate_process_capture_expiry",
            "certificate_process_capture_serial_boundary",
        ):
            self.assertIn(fieldname, fields)
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_master" / "cfg_kanban_master.py"
        ).read_text()
        self.assertIn("Certificate Process does not use a BOM", controller)
        self.assertIn("Certificate Process requires an ERPNext Stock Item", controller)

    def test_run_snapshots_batch_control_and_erp_authority(self):
        run = schema("cfg_process_certificate_run")
        fields = {row["fieldname"]: row for row in run["fields"]}
        for fieldname in (
            "progress_mode",
            "item_batch_controlled", "source_batch", "output_batch",
            "source_handling_unit", "pending_output_tag_code", "output_handling_unit",
            "output_claim_key", "output_tag_mode", "output_tag_qty_before",
            "source_certificate_set", "result_certificate_set", "repack_stock_entry",
            "first_output_serial", "last_output_serial", "printed_expiry",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["idempotency_key"]["unique"])
        self.assertTrue(fields["output_claim_key"]["unique"])

    def test_runtime_uses_submitted_repack_before_physical_mutation(self):
        service = (APP_ROOT / "services" / "certificate_process.py").read_text()
        feedback = (APP_ROOT / "integrations" / "erp_feedback.py").read_text()
        self.assertIn('"purpose": "Repack"', service)
        self.assertIn('entry.docstatus != 1', service)
        self.assertIn("def reconcile_certificate_process", service)
        reconcile = service.split("def reconcile_certificate_process", 1)[1]
        self.assertLess(
            reconcile.index("entry.docstatus != 1"),
            reconcile.index('"process_certificate_set": run.result_certificate_set'),
        )
        self.assertIn('event_type="Split"', reconcile)
        self.assertIn('event_type="Merge"', reconcile)
        self.assertIn('run.output_tag_mode == "Merge Existing"', reconcile)
        self.assertIn("_issue_output_certificates(run, output)", reconcile)
        self.assertIn('{"repack_stock_entry": doc.name}', feedback)
        self.assertIn("reconcile_certificate_process(certificate_run)", feedback)
        self.assertIn("def reconcile_submitted_certificate_process", service)
        self.assertIn("for update", reconcile)

        run_form = (APP_ROOT / "public" / "js" / "cfg_process_certificate_run.js").read_text()
        self.assertIn("Reconcile Submitted Repack", run_form)
        self.assertIn("reconcile_submitted_certificate_process", run_form)

    def test_trigger_and_approval_never_create_work_order_for_certificate_process(self):
        triggers = (APP_ROOT / "services" / "triggers.py").read_text()
        operator = (APP_ROOT / "api" / "operator.py").read_text()
        self.assertIn('"Certificate Process": "Certificate Process"', triggers)
        self.assertIn("release_certificate_process(signal.name)", triggers)
        self.assertIn('if master.control_type == "Certificate Process"', operator)
        self.assertIn("certificate_process_run", operator)

    def test_scanner_contract_is_printable_and_dialog_complete(self):
        operator = (APP_ROOT / "api" / "operator.py").read_text()
        panel = (
            APP_ROOT / "cfg_kanban" / "page" / "kanban_operator" /
            "kanban_operator.js"
        ).read_text()
        commands = (
            "START_CERTIFICATE_PROCESS", "COMPLETE_CERTIFICATE_PROCESS",
            "REPORT_CERTIFICATE_PROGRESS", "CLOSE_CERTIFICATE_PROCESS",
            "SUBMIT_CERTIFICATE_PROCESS", "CANCEL_CERTIFICATE_PROCESS",
            "CERTIFICATE_OUTPUT_TAG", "CERTIFICATE_BATCH", "CERTIFICATE_EXPIRY",
            "CERTIFICATE_SERIAL_START", "CERTIFICATE_SERIAL_END",
        )
        for command in commands:
            self.assertIn(f"CFG:CMD:{command}", operator)
            self.assertIn(command, panel)
        self.assertIn("handle_certificate_dialog_scan", panel)
        self.assertIn("CFG:QTY:(MATERIAL|GOOD|REJECT)", panel)
        self.assertIn('upper === "CFG:CMD:CONFIRM"', panel)
        self.assertIn('upper === "CFG:CMD:CANCEL"', panel)
        self.assertIn("change.cfg-certificate-scan", panel)
        self.assertIn("rearm_certificate_scanner", panel)
        self.assertIn("Scanner Ready", panel)
        self.assertIn("Camera Scan Source Tag", panel)
        self.assertIn("Camera Scan Output Tag", panel)
        self.assertIn("Good Qty {number:g}", operator)

    def test_consolidated_progress_is_provisional_until_one_repack_is_created(self):
        progress = schema("cfg_certificate_process_progress")
        fields = {row["fieldname"]: row for row in progress["fields"]}
        for fieldname in (
            "certificate_process_run", "sequence", "good_qty", "reject_qty",
            "output_tag_code", "result_certificate_set", "repack_stock_entry",
            "recorded_on", "recorded_by_operator", "operator_session",
            "idempotency_key",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["idempotency_key"]["unique"])

        controller = (
            DOCTYPE_ROOT / "cfg_certificate_process_progress" /
            "cfg_certificate_process_progress.py"
        ).read_text()
        service = (APP_ROOT / "services" / "certificate_process.py").read_text()
        panel = (
            APP_ROOT / "cfg_kanban" / "page" / "kanban_operator" /
            "kanban_operator.js"
        ).read_text()
        self.assertIn("evidence is immutable", controller)
        self.assertIn("def report_certificate_process_progress", service)
        self.assertIn("def close_consolidated_certificate_process", service)
        self.assertIn("def _claim_output_identity", service)
        self.assertIn("already claimed by open Certificate Process Run", service)
        self.assertIn("_create_repack_entry(", service)
        self.assertIn("Pending ERP Consolidation", panel)
        self.assertIn("Record Partial Progress", panel)
        self.assertIn("Close and Create Repack", panel)

    def test_operational_inventory_separates_pending_certificate_state_from_stock(self):
        report = (
            APP_ROOT / "cfg_kanban" / "report" /
            "kanban_operational_inventory_balance" /
            "kanban_operational_inventory_balance.py"
        ).read_text()
        report_js = (
            APP_ROOT / "cfg_kanban" / "report" /
            "kanban_operational_inventory_balance" /
            "kanban_operational_inventory_balance.js"
        ).read_text()
        self.assertIn("Pending ERP Consolidation", report)
        self.assertIn("pending_certificate_qty", report)
        self.assertIn("0 as total_qty", report)
        self.assertIn("0 as available_qty", report)
        self.assertIn("process_certificate_set", report_js)
        self.assertIn("certificate_posting_status", report_js)

    def test_work_order_production_has_operation_gate_and_output_binding(self):
        execution = schema("cfg_kanban_process_execution")
        execution_fields = {row["fieldname"]: row for row in execution["fields"]}
        progress = schema("cfg_kanban_operation_progress")
        progress_fields = {row["fieldname"]: row for row in progress["fields"]}
        for fieldname in (
            "certificate_gate_status", "input_certificate_sets_json",
            "result_certificate_set", "certificate_checked_on",
        ):
            self.assertIn(fieldname, execution_fields)
        self.assertIn("result_certificate_set", progress_fields)

        service = (APP_ROOT / "services" / "production_certificates.py").read_text()
        for contract in (
            "def assert_execution_certificate_gate",
            "def finalize_execution_certificate_result",
            "def validate_production_certificate_stock_entry",
            "def reconcile_production_output_certificates",
            "def _stock_qty",
            'rule.issue_scope != "Finished Output"',
            '"to_process_certificate_set"',
            "Parallel final Job Card lanes produced different Process Certificate Sets",
        ):
            self.assertIn(contract, service)

    def test_certified_stock_entry_uses_erpnext_target_inventory_dimension(self):
        service = (APP_ROOT / "services" / "certificate_process.py").read_text()
        production = (APP_ROOT / "services" / "production_certificates.py").read_text()
        self.assertIn('output_row["to_process_certificate_set"] = result_set', service)
        self.assertIn('row.to_process_certificate_set = result_set', production)
        self.assertIn('row.get("to_process_certificate_set")', production)

    def test_compatible_existing_output_tag_is_audited_and_recoverable(self):
        service = (APP_ROOT / "services" / "certificate_process.py").read_text()
        recovery = (APP_ROOT / "services" / "certificate_process_recovery.py").read_text()
        self.assertIn("def _resolve_output_tag", service)
        self.assertIn('"mode": "Merge Existing"', service)
        self.assertIn('canonical_key("certificate-process-merge-existing"', service)
        self.assertIn('run.output_tag_mode != "Merge Existing"', recovery)
        self.assertIn("run.output_tag_qty_before", recovery)

    def test_work_order_hooks_share_process_card_evidence_by_job_card(self):
        service = (APP_ROOT / "services" / "production_certificates.py").read_text()
        operator = (APP_ROOT / "api" / "operator.py").read_text()
        feedback = (APP_ROOT / "integrations" / "erp_feedback.py").read_text()
        self.assertIn('"job_card": execution.job_card', service)
        self.assertIn("assert_execution_certificate_gate(execution, \"Before Progress\")", operator)
        self.assertIn("assert_execution_certificate_gate(execution, \"Before Operation Start\")", operator)
        self.assertIn("validate_production_certificate_stock_entry(doc)", feedback)
        self.assertIn("reconcile_production_output_certificates(doc)", feedback)
        self.assertIn("revoke_cancelled_stock_entry_certificates(doc)", feedback)
        self.assertIn("def revoke_cancelled_stock_entry_certificates", service)

    def test_production_output_rules_require_finished_output_scope(self):
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_master" / "cfg_kanban_master.py"
        ).read_text()
        client = (APP_ROOT / "public" / "js" / "cfg_kanban_master.js").read_text()
        self.assertIn('row.issue_scope != "Finished Output"', controller)
        self.assertIn('"issue_scope", "Finished Output"', client)

    def test_workspace_and_acceptance_guide_expose_runtime(self):
        workspace = json.loads((
            APP_ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
            "cfg_kanban.json"
        ).read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(links["Certificate Process Runs"], "CFG Process Certificate Run")
        guide = (
            APP_ROOT.parent / "docs" /
            "TEST_CERTIFICATE_PROCESS_PRINT_PLASTIC_BAG.md"
        ).read_text()
        self.assertIn("no Work Order or Job Card", guide)
        self.assertIn("Scanner-only kiosk run", guide)
        self.assertIn("Native Stock Ledger evidence", guide)
        production_guide = (
            APP_ROOT.parent / "docs" / "TEST_PRODUCTION_PROCESS_CERTIFICATES.md"
        ).read_text()
        self.assertIn("reusable Process/Station Card", production_guide)
        self.assertIn("Before Progress", production_guide)
        self.assertIn("Native Stock Ledger dimension evidence", production_guide)

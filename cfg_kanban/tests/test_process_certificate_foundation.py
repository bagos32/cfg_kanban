import json
from pathlib import Path
from unittest import TestCase


APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = APP_ROOT / "cfg_kanban" / "doctype"


def schema(folder):
    return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())


class TestProcessCertificateFoundation(TestCase):
    def test_certificate_type_is_revisioned_approved_configuration(self):
        document = schema("cfg_process_certificate_type")
        fields = {row["fieldname"]: row for row in document["fields"]}
        self.assertTrue(document["is_submittable"])
        self.assertNotIn("autoname", document)
        controller = (
            DOCTYPE_ROOT / "cfg_process_certificate_type" /
            "cfg_process_certificate_type.py"
        ).read_text()
        self.assertIn('self.name = f"{self.certificate_code}-R{self.revision:03d}"', controller)
        for fieldname in (
            "certificate_code", "certificate_name", "active", "revision", "item",
            "item_group", "validity_days", "evidence_required",
            "supervisor_verification_required", "split_inheritance", "merge_policy",
            "external_standard_identifier", "external_revision_snapshot",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["active"]["allow_on_submit"])

    def test_certificate_set_is_exact_immutable_combination(self):
        document = schema("cfg_process_certificate_set")
        fields = {row["fieldname"]: row for row in document["fields"]}
        self.assertNotIn("autoname", document)
        self.assertEqual(fields["members"]["options"], "CFG Process Certificate Set Member")
        self.assertTrue(fields["signature_hash"]["unique"])
        controller = (
            DOCTYPE_ROOT / "cfg_process_certificate_set" /
            "cfg_process_certificate_set.py"
        ).read_text()
        self.assertIn("Certificate Set membership and code are immutable", controller)
        self.assertIn("Certificate Set {duplicate} already represents", controller)

    def test_issued_certificate_binds_exact_physical_and_process_context(self):
        document = schema("cfg_process_certificate")
        fields = {row["fieldname"]: row for row in document["fields"]}
        for fieldname in (
            "certificate_type", "certificate_set", "handling_unit", "item_code",
            "certified_qty", "stock_uom", "inventory_company", "warehouse", "batch_no",
            "kanban_cycle", "process_execution", "work_order", "job_card", "operation",
            "issued_on", "issued_by_operator", "valid_until", "evidence_references",
            "revocation_reason", "idempotency_key",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["idempotency_key"]["unique"])
        controller = (
            DOCTYPE_ROOT / "cfg_process_certificate" / "cfg_process_certificate.py"
        ).read_text()
        self.assertIn("Issued Process Certificate identity is immutable", controller)

    def test_master_exposes_certificate_gates_and_output_rules(self):
        master = schema("cfg_kanban_master")
        fields = {row["fieldname"]: row for row in master["fields"]}
        self.assertEqual(
            fields["certificate_requirements"]["options"],
            "CFG Kanban Certificate Requirement",
        )
        self.assertEqual(
            fields["certificate_output_rules"]["options"],
            "CFG Kanban Certificate Output Rule",
        )
        controller = (
            DOCTYPE_ROOT / "cfg_kanban_master" / "cfg_kanban_master.py"
        ).read_text()
        self.assertIn("def _validate_process_certificate_rules", controller)
        self.assertIn("must be approved and Active", controller)
        client = (APP_ROOT / "public" / "js" / "cfg_kanban_master.js").read_text()
        self.assertIn('"certificate_requirements", "certificate_output_rules"', client)

    def test_handling_unit_displays_exact_active_certificate_set(self):
        handling_unit = schema("cfg_kanban_handling_unit")
        fields = {row["fieldname"]: row for row in handling_unit["fields"]}
        field = fields["process_certificate_set"]
        self.assertEqual(field["options"], "CFG Process Certificate Set")
        self.assertTrue(field["read_only"])
        self.assertTrue(field["in_standard_filter"])

    def test_migration_creates_native_inventory_dimension_idempotently(self):
        installer = (APP_ROOT / "install.py").read_text()
        self.assertIn("def _ensure_process_certificate_inventory_dimension", installer)
        self.assertIn('dimension_name = "Process Certificate Set"', installer)
        self.assertIn('"reference_document": "CFG Process Certificate Set"', installer)
        self.assertIn('"apply_to_all_doctypes": 1', installer)
        self.assertIn('"validate_negative_stock": 1', installer)
        self.assertIn('expected_source = "process_certificate_set"', installer)
        self.assertIn('expected_target = "process_certificate_set"', installer)
        self.assertIn("_ensure_process_certificate_inventory_dimension()", installer)

    def test_workspace_exposes_configuration_audit_and_native_stock_ledger(self):
        workspace = json.loads((
            APP_ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
            "cfg_kanban.json"
        ).read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        self.assertEqual(links["Process Certificate Types"], "CFG Process Certificate Type")
        self.assertEqual(links["Process Certificate Sets"], "CFG Process Certificate Set")
        self.assertEqual(links["Issued Process Certificates"], "CFG Process Certificate")
        self.assertEqual(links["Native Stock Ledger"], "Stock Ledger")

    def test_runtime_boundary_is_explicit_in_docs(self):
        architecture = (APP_ROOT.parent / "docs" / "PROCESS_CERTIFICATE_ARCHITECTURE.md").read_text()
        acceptance = (APP_ROOT.parent / "docs" / "TEST_PROCESS_CERTIFICATE_FOUNDATION.md").read_text()
        for content in (architecture, acceptance):
            self.assertIn("scanner", content.lower())
            self.assertIn("Inventory Dimension", content)
        self.assertIn("must not be reported as completed floor-operation acceptance", architecture)

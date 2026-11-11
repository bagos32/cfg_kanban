from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = APP_ROOT / "install.py"


class TestInventoryDimensionMigrationCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = INSTALLER.read_text()

    def test_transaction_field_uses_dimension_name(self):
        self.assertIn("expected_source = frappe.scrub(dimension_name)", self.installer)
        self.assertIn("existing.source_fieldname != expected_source", self.installer)

    def test_erpnext_v15_65_reference_document_ledger_name_is_accepted(self):
        self.assertIn("frappe.scrub(existing.reference_document)", self.installer)
        self.assertIn("existing.target_fieldname not in accepted_targets", self.installer)

    def test_dimension_reference_document_still_must_match(self):
        self.assertIn(
            'existing.reference_document != "CFG Process Certificate Set"',
            self.installer,
        )


if __name__ == "__main__":
    unittest.main()

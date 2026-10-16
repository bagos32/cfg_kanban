import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


class TestDocTypeActionFoundation(TestCase):
    def _schema(self, folder):
        return json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())

    def test_profile_uses_flat_parent_and_child_mappings(self):
        profile = self._schema("cfg_kanban_doctype_action_profile")
        fields = {row["fieldname"]: row for row in profile["fields"]}
        self.assertEqual(
            fields["parent_field_mappings"]["options"],
            "CFG Kanban DocType Field Map",
        )
        self.assertEqual(
            fields["child_table_configs"]["options"],
            "CFG Kanban DocType Child Table Config",
        )
        self.assertEqual(
            fields["child_column_mappings"]["options"],
            "CFG Kanban DocType Child Column Map",
        )
        child_config = self._schema("cfg_kanban_doctype_child_table_config")
        self.assertFalse(any(row["fieldtype"] == "Table" for row in child_config["fields"]))

    def test_configuration_is_restricted_to_maintenance_roles(self):
        for folder in (
            "cfg_kanban_doctype_action_policy",
            "cfg_kanban_doctype_action_profile",
        ):
            schema = self._schema(folder)
            roles = {row["role"] for row in schema["permissions"]}
            self.assertEqual(
                roles,
                {"CFG Kanban System Maintenance", "System Manager"},
            )
            self.assertNotIn("Manufacturing User", roles)
            self.assertNotIn("Kanban Terminal", roles)

    def test_engine_is_default_deny_and_does_not_write_targets_yet(self):
        source = (ROOT / "services" / "doctype_actions.py").read_text()
        for denied in (
            '"Work Order"', '"Job Card"', '"Stock Entry"', '"Batch"',
            '"Sales Invoice"', '"Purchase Invoice"', '"User"', '"DocType"',
        ):
            self.assertIn(denied, source)
        self.assertIn("CFG Kanban DocType Action Policy", source)
        self.assertIn("metadata_fingerprint", source)
        self.assertNotIn(".insert(ignore_permissions=True)", source)
        self.assertNotIn(".submit()", source)

    def test_profile_ui_exposes_validation_and_non_posting_preview(self):
        javascript = (
            ROOT / "public" / "js" / "cfg_kanban_doctype_action_profile.js"
        ).read_text()
        self.assertIn("Validate Configuration", javascript)
        self.assertIn("Preview Operator Form", javascript)
        self.assertIn("Preview only — no destination document is created", javascript)
        hooks = (ROOT / "hooks.py").read_text()
        self.assertIn("CFG Kanban DocType Action Profile", hooks)

    def test_locked_extension_specification_is_kept_with_the_code(self):
        specification = (ROOT.parent / "docs" / "SPECIAL_DOCTYPE_CARD_EXTENSION.md")
        self.assertTrue(specification.exists())
        content = specification.read_text()
        self.assertIn("CFG-KANBAN-EXT-SDC-001", content)
        self.assertIn("Gate 1 — reusable core + Phase 1 Service Task integration", content)


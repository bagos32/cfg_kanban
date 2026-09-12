import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1] / "cfg_kanban" / "doctype"


class TestDocTypeSchema(TestCase):
    def _schemas(self):
        for path in ROOT.glob("*/*.json"):
            yield path, json.loads(path.read_text())

    def test_every_field_is_present_once_in_field_order(self):
        for path, schema in self._schemas():
            fields = [row["fieldname"] for row in schema.get("fields", [])]
            order = schema.get("field_order", [])
            self.assertEqual(len(fields), len(set(fields)), path)
            self.assertEqual(set(fields), set(order), path)
            self.assertEqual(len(order), len(set(order)), path)

    def test_child_table_targets_exist_and_are_child_doctypes(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for path, schema in self._schemas():
            for field in schema.get("fields", []):
                if field.get("fieldtype") != "Table":
                    continue
                target = schemas.get(field.get("options"))
                self.assertIsNotNone(target, f"{path}: {field['fieldname']}")
                self.assertEqual(target.get("istable"), 1, f"{path}: {field['fieldname']}")

    def test_card_exposes_operation_and_print_audit_context(self):
        path = ROOT / "cfg_kanban_card" / "cfg_kanban_card.json"
        fields = {row["fieldname"] for row in json.loads(path.read_text())["fields"]}
        required = {"operation", "workstation", "handoff_mode", "stock_uom",
                    "source_warehouse", "destination_warehouse",
                    "last_printed_on", "last_printed_by"}
        self.assertTrue(required.issubset(fields))

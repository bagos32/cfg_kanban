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
        schema = json.loads(path.read_text())
        fields = {row["fieldname"] for row in schema["fields"]}
        required = {"operation", "workstation", "handoff_mode", "stock_uom",
                    "source_warehouse", "destination_warehouse",
                    "last_printed_on", "last_printed_by"}
        self.assertTrue(required.issubset(fields))

        by_name = {row["fieldname"]: row for row in schema["fields"]}
        for fieldname in ("card_type", "item_code", "current_state"):
            self.assertEqual(by_name[fieldname].get("in_list_view"), 1)
            self.assertEqual(by_name[fieldname].get("in_standard_filter"), 1)

    def test_parallel_execution_fields_are_present(self):
        execution_path = ROOT / "cfg_kanban_process_execution" / "cfg_kanban_process_execution.json"
        execution_fields = {row["fieldname"] for row in json.loads(execution_path.read_text())["fields"]}
        self.assertTrue({"operation_summary", "lane_sequence", "execution_mode",
                         "allocated_qty", "destination_operation", "job_card"}
                        .issubset(execution_fields))

        summary_path = ROOT / "cfg_kanban_operation_summary" / "cfg_kanban_operation_summary.json"
        summary = json.loads(summary_path.read_text())
        summary_fields = {row["fieldname"] for row in summary["fields"]}
        self.assertEqual(summary["name"], "CFG Kanban Operation Summary")
        self.assertTrue({"summary_key", "kanban_cycle", "operation", "execution_mode",
                         "target_qty", "allocated_qty", "good_qty", "released_qty",
                         "execution_count", "completed_execution_count"}
                        .issubset(summary_fields))

    def test_runtime_allocation_traceability_fields_are_present(self):
        cycle_path = ROOT / "cfg_kanban_cycle" / "cfg_kanban_cycle.json"
        cycle_fields = {row["fieldname"] for row in json.loads(cycle_path.read_text())["fields"]}
        self.assertTrue({"nominal_card_qty", "effective_cycle_qty", "available_input_qty",
                         "short_cycle_reason", "selected_job_card", "runtime_allocation"}
                        .issubset(cycle_fields))
        allocation_path = ROOT / "cfg_kanban_runtime_allocation" / "cfg_kanban_runtime_allocation.json"
        allocation_fields = {row["fieldname"] for row in json.loads(allocation_path.read_text())["fields"]}
        self.assertTrue({"kanban_cycle", "kanban_card", "work_order", "job_card",
                         "nominal_card_qty", "remaining_job_card_qty", "available_input_qty",
                         "effective_qty", "short_cycle_reason", "operator_confirmation"}
                        .issubset(allocation_fields))

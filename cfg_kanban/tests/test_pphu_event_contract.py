import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent


class TestPPHUEventContract(TestCase):
    def test_event_schema_carries_industrial_trace_context(self):
        schema = json.loads(
            (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_event" /
             "cfg_kanban_event.json").read_text()
        )
        fields = {row["fieldname"]: row for row in schema["fields"]}
        for fieldname in (
            "received_on", "input_source", "source_event_id", "idempotency_key",
            "work_order", "job_card", "operation", "workstation", "material_item",
            "material_batch", "output_serial_boundary", "payload_json",
        ):
            self.assertIn(fieldname, fields)
        self.assertTrue(fields["idempotency_key"]["unique"])
        self.assertIn("Scanner", fields["input_source"]["options"])
        self.assertIn("PLC", fields["input_source"]["options"])
        self.assertIn("SCADA", fields["input_source"]["options"])

    def test_scanner_event_is_bound_to_operator_card_and_execution(self):
        source = (ROOT / "services" / "pphu_events.py").read_text()
        self.assertIn('require_operator(operator_session_token, "report_progress", execution=execution_name)', source)
        self.assertIn("_validated_context(card_name, execution_name)", source)
        self.assertIn("execution.kanban_cycle != cycle.name", source)
        self.assertIn("unit.inventory_company != company", source)
        self.assertIn('unit.handling_unit_type != "Hopper"', source)
        self.assertIn('unit.tag_kind != "Reusable Container"', source)
        self.assertIn('unit.tag_kind == "Reusable Container"', source)
        self.assertIn('unit.quality_state != "Released"', source)
        self.assertIn("not unit.item_code or not unit.batch_no", source)
        self.assertIn("flt(unit.current_qty) <= 0", source)

    def test_idempotent_retry_rejects_changed_payload(self):
        source = (ROOT / "services" / "pphu_events.py").read_text()
        self.assertIn('canonical_key("pphu-production-event", input_source, event_token)', source)
        self.assertIn('get_existing("CFG Kanban Event", key)', source)
        self.assertIn("_assert_idempotent_match(existing, expected)", source)
        self.assertIn("already used for different event data", source)

    def test_pphu_event_layer_does_not_post_erp_or_release_quality(self):
        source = (ROOT / "services" / "pphu_events.py").read_text()
        forbidden = (
            "Stock Entry", "make_stock_entry", "submit()", "db_set(\"quality_state\"",
            "execute_command(", "frappe.enqueue(",
        )
        for value in forbidden:
            self.assertNotIn(value, source)
        self.assertIn("records operational evidence only", source)

    def test_operator_panel_and_catalog_are_scanner_complete(self):
        api = (ROOT / "api" / "operator.py").read_text()
        panel = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                 "kanban_operator.js").read_text()
        for command in (
            "CFG:CMD:PPHU_HOPPER_CHANGE",
            "CFG:CMD:PPHU_BATCH_CHANGE",
            "CFG:CMD:PPHU_OUTPUT_SERIAL",
        ):
            self.assertIn(command, api)
            self.assertIn(command, panel)
        self.assertIn("open_pphu_event_dialog", panel)
        self.assertIn("bind_confirmation_scanner(dialog, true, values, \"execution_name\")", panel)
        self.assertIn("CFG:SELECT:n", panel)
        self.assertIn("CFG:CMD:CONFIRM", panel)
        self.assertIn("CFG:CMD:CANCEL", panel)
        self.assertIn("restore_scanner_focus", panel)
        self.assertIn("dialog.cfg_selection_locked = true", panel)

    def test_handover_spec_records_missing_revisions_and_safety_gates(self):
        spec = (REPOSITORY_ROOT / "docs" / "PPHU_HANDOVER_SPEC.md").read_text()
        self.assertIn("V1.1–V1.4", spec)
        self.assertIn("not available as separate retrievable source documents", spec)
        self.assertIn("warehouse-local FIFO/FEFO", spec)
        self.assertIn("cumulative proportional settlement", spec)
        self.assertIn("PLC safety control remains local", spec)
        self.assertIn("does not yet infer the previous ending", spec)

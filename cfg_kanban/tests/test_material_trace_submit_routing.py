from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestMaterialTraceSubmitRoutingContract(TestCase):
    def test_open_trace_submits_its_exact_stock_entry(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()

        submit = panel[panel.index("async function submit_scanner_material_entry("):]
        submit = submit[:submit.index("\n\tfunction scanner_command_message(")]
        self.assertIn("active_dialog?.cfg_trace_plan?.stock_entry", submit)
        self.assertIn("submit_exact_production_stock_entry(explicit_entry, active_dialog)", submit)
        self.assertIn(
            'method: "cfg_kanban.services.production_material_flow.submit_production_stock_entry"',
            submit,
        )
        self.assertLess(
            submit.index("await frappe.call"),
            submit.index("close_operator_material_trace_dialog(trace_dialog)"),
        )

    def test_popup_commands_pass_the_live_trace_entry(self):
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_operator" / "kanban_operator.js"
        ).read_text()
        self.assertGreaterEqual(
            panel.count(
                "submit_scanner_material_entry(dialog.cfg_trace_plan?.stock_entry)"
            ),
            2,
        )

    def test_trace_plan_exposes_physical_staging_readiness(self):
        service = (ROOT / "services" / "production_trace.py").read_text()
        trace_plan = service[service.index("def _trace_plan("):]
        trace_plan = trace_plan[:trace_plan.index("\n\ndef _plan_row(")]
        self.assertIn("can_submit = doc.docstatus == 0 and all(", trace_plan)
        self.assertIn('row.get("wip_bin_remaining_qty")', trace_plan)
        self.assertIn('row.get("remaining_qty")', trace_plan)
        self.assertIn('"can_submit": can_submit', trace_plan)

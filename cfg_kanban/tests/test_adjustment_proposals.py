import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "cfg_kanban" / "doctype"


def schema(name):
    slug = name.lower().replace(" ", "_")
    return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text())


class FakeDoc(dict):
    def __getattr__(self, key):
        return self.get(key)

    def check_permission(self, permission_type):
        return permission_type == "read"


def load_service(cycle, execution):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda value: value
    frappe.PermissionError = PermissionError
    frappe.whitelist = lambda function=None, **kwargs: (
        function if function else (lambda decorated: decorated)
    )
    frappe.get_roles = lambda: ["Manufacturing Manager"]
    frappe.get_doc = lambda doctype, name: (
        cycle if doctype == "CFG Kanban Cycle" else execution
    )
    utils = types.ModuleType("frappe.utils")
    utils.flt = lambda value: float(value or 0)
    utils.now_datetime = lambda: "2026-10-26 12:00:00"
    events = types.ModuleType("cfg_kanban.services.events")
    events.record = lambda *args, **kwargs: None
    idempotency = types.ModuleType("cfg_kanban.services.idempotency")
    idempotency.canonical_key = lambda *args: "::".join(args)
    idempotency.insert_once = lambda *args, **kwargs: (None, False)
    spec = importlib.util.spec_from_file_location(
        "cfg_kanban_test_adjustment_proposals",
        ROOT / "services" / "adjustment_proposals.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "frappe": frappe,
        "frappe.utils": utils,
        "cfg_kanban.services.events": events,
        "cfg_kanban.services.idempotency": idempotency,
    }):
        spec.loader.exec_module(module)
    return module


def approved_request():
    return FakeDoc({
        "name": "KCR-2026-00001",
        "status": "Approved",
        "review_decision": "Approve Kanban Adjustment",
        "correction_category": "Operation Progress",
        "affected_doctype": "CFG Kanban Process Execution",
        "affected_document": "KPE-00001",
        "process_execution": "KPE-00001",
        "kanban_cycle": "KCY-2026-00001",
        "current_value_snapshot": json.dumps({"modified": "2026-10-26 10:00:00"}),
    })


def live_context(job_card="PO-JOB-0001", released_qty=0, cycle_status="In Production"):
    cycle = FakeDoc({
        "name": "KCY-2026-00001", "status": cycle_status, "stock_uom": "Nos",
    })
    execution = FakeDoc({
        "name": "KPE-00001", "kanban_cycle": cycle.name, "status": "In Progress",
        "job_card": job_card, "operation": "Cooking", "workstation": "Kettle",
        "target_qty": 100, "processed_qty": 40, "good_qty": 38, "reject_qty": 2,
        "released_qty": released_qty, "modified": "2026-10-26 11:00:00",
    })
    return cycle, execution


class TestAdjustmentProposals(unittest.TestCase):
    def test_proposal_is_read_only_and_reserves_future_application_audit(self):
        proposal = schema("CFG Kanban Adjustment Proposal")
        fields = {row["fieldname"]: row for row in proposal["fields"]}
        self.assertEqual(
            fields["status"]["options"].splitlines(),
            ["Prepared", "Cancelled", "Applied", "Superseded"],
        )
        self.assertEqual(fields["target_document"]["options"], "target_doctype")
        self.assertTrue(fields["idempotency_key"]["unique"])
        self.assertEqual(
            fields["supervisor_action_approval"]["options"],
            "CFG Kanban Supervisor Action Approval",
        )
        for permission in proposal["permissions"]:
            self.assertFalse(permission.get("create"))
            self.assertFalse(permission.get("write"))
            self.assertFalse(permission.get("delete"))

    def test_preview_is_non_mutating_and_application_is_not_implemented(self):
        service = (ROOT / "services" / "adjustment_proposals.py").read_text()
        self.assertIn("def preview_operation_quantity_adjustment(", service)
        self.assertIn("def prepare_operation_quantity_adjustment(", service)
        self.assertIn("Preview only; not applied.", service)
        self.assertIn("def _assert_consumed_request_approval", service)
        self.assertIn('approval.status != "Consumed"', service)
        self.assertIn('check_permission("read")', service)
        self.assertNotIn("execution.db_set", service)
        self.assertNotIn("cycle.db_set", service)
        self.assertNotIn('"CFG Kanban Operation Progress"', service)
        self.assertNotIn('frappe.get_doc("Work Order"', service)
        self.assertNotIn('frappe.get_doc("Job Card"', service)

    def test_reject_delta_is_eligible_without_changing_linked_job_card(self):
        cycle, execution = live_context()
        service = load_service(cycle, execution)
        result = service._operation_quantity_preview(approved_request(), 0, 3)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["proposed_reject_qty"], 5)
        self.assertEqual(result["proposed_processed_qty"], 43)
        self.assertTrue(any("does not change ERPNext" in row for row in result["warnings"]))

    def test_linked_job_card_good_delta_requires_erp_correction(self):
        cycle, execution = live_context()
        service = load_service(cycle, execution)
        result = service._operation_quantity_preview(approved_request(), -2, 2)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("owned by ERPNext Job Card" in row for row in result["blocks"]))

    def test_unreleased_kanban_only_good_delta_can_be_proposed(self):
        cycle, execution = live_context(job_card=None)
        service = load_service(cycle, execution)
        result = service._operation_quantity_preview(approved_request(), -2, 2)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["proposed_good_qty"], 36)
        self.assertEqual(result["proposed_processed_qty"], 40)

    def test_released_or_terminal_state_blocks_unsafe_preview(self):
        cycle, execution = live_context(job_card=None, released_qty=39)
        service = load_service(cycle, execution)
        result = service._operation_quantity_preview(approved_request(), -2, 0)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("already released" in row for row in result["blocks"]))

        cycle.status = "Completed"
        result = service._operation_quantity_preview(approved_request(), 0, 1)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("already Completed" in row for row in result["blocks"]))

    def test_supervisor_centre_and_workspace_expose_proposals(self):
        api = (ROOT / "api" / "workforce_supervisor.py").read_text()
        panel = (
            ROOT / "cfg_kanban" / "page" / "kanban_workforce_supervisor"
            / "kanban_workforce_supervisor.js"
        ).read_text()
        workspace = json.loads((
            ROOT / "cfg_kanban" / "workspace" / "cfg_job_architecture"
            / "cfg_job_architecture.json"
        ).read_text())
        self.assertIn('"prepared_adjustments"', api)
        self.assertIn("Prepare Adjustment", panel)
        self.assertIn("Preview only", panel)
        self.assertIn("cancel_adjustment_proposal", panel)
        correction_service = (ROOT / "services" / "correction_requests.py").read_text()
        self.assertIn("Cancel Prepared adjustment proposal", correction_service)
        self.assertTrue(any(
            row.get("link_to") == "CFG Kanban Adjustment Proposal"
            for row in workspace["links"]
        ))


if __name__ == "__main__":
    unittest.main()

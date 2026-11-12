"""Offline regression gates for AT-01/AT-02. No Frappe site, DB or network.
Run: python3 -B -m unittest cfg_kanban.tests.test_certificate_retry_behavior -v
These tests assert desired behavior and reproduced failures on the original baseline.
They are neither expectedFailure nor skipped. They do not establish ERP transaction acceptance.
"""
import hashlib
import json
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_service():
    frappe = types.ModuleType("frappe")
    frappe.ValidationError = ValueError
    frappe.whitelist = lambda *a, **k: lambda f: f
    def reject(message):
        raise ValueError(message)
    frappe.throw = Mock(side_effect=reject)
    frappe.db = types.SimpleNamespace(get_value=Mock(return_value="PROGRESS-1"),
                                      savepoint=Mock(), rollback=Mock())
    utils = types.ModuleType("frappe.utils")
    for name in ("add_days", "now_datetime"):
        setattr(utils, name, Mock())
    utils.cint = lambda x: int(x or 0)
    utils.flt = lambda x: float(x or 0)
    modules = {"frappe": frappe, "frappe.utils": utils}
    dependencies = {
        "events": ["record"],
        "idempotency": ["canonical_key"],
        "logistics_foundation": ["assert_erp_stock", "post_quantity_event", "resolve_logistics_scan"],
        "operator_auth": ["require_operator"],
        "physical_identity": ["normalize_physical_code"],
        "state_machine": ["set_cycle_state", "transition_card"],
    }
    for suffix, names in dependencies.items():
        name = "cfg_kanban.services." + suffix
        module = types.ModuleType(name)
        for function in names:
            setattr(module, function, Mock())
        modules[name] = module
    spec = importlib.util.spec_from_file_location(
        "certificate_retry_behavior_subject", ROOT / "services" / "certificate_process.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    module.canonical_key = lambda *parts: hashlib.sha256(
        json.dumps(parts, sort_keys=True).encode()
    ).hexdigest()
    return module, frappe


class CertificateRetryBehavior(unittest.TestCase):
    def fixture(self, status="In Progress"):
        service, frappe = load_service()
        run = types.SimpleNamespace(
            name="RUN-1", status=status, progress_mode="Consolidated Partial Progress",
            kanban_master="MASTER-1", kanban_cycle="CYCLE-1", selected_qty=100,
            good_qty=60, reject_qty=0, stock_uom="Nos", operation="Operation B",
            workstation="Station B",
        )
        service.require_operator.return_value = (
            types.SimpleNamespace(employee="EMP-1"), types.SimpleNamespace(name="SESSION-1")
        )
        service._locked_run = Mock(return_value=run)
        fingerprint = service.canonical_key(
            "certificate-progress-request-v1", 60.0, 0.0, "", "", "", "", ""
        )
        frappe.db.get_value.return_value = types.SimpleNamespace(
            name="PROGRESS-1", request_fingerprint=fingerprint
        )
        service.get_certificate_process_context = Mock(return_value={"replayed": True})
        frappe.get_doc = Mock(return_value=types.SimpleNamespace())
        return service, frappe

    def test_committed_progress_retry_is_not_recounted_against_capacity(self):
        service, frappe = self.fixture()
        result = service.report_certificate_process_progress(
            "CYCLE-1", 60, event_token="already-committed-token",
            operator_session_token="operator-token"
        )
        self.assertEqual(result, {"replayed": True})
        frappe.throw.assert_not_called()

    def test_committed_progress_retry_after_close_is_replayable(self):
        service, frappe = self.fixture("Awaiting ERP Submission")
        result = service.report_certificate_process_progress(
            "CYCLE-1", 60, event_token="already-committed-token",
            operator_session_token="operator-token"
        )
        self.assertEqual(result, {"replayed": True})
        frappe.throw.assert_not_called()

    def test_scope_is_forwarded_before_replay_returns_data(self):
        service, _ = self.fixture("Awaiting ERP Submission")
        try:
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="already-committed-token",
                operator_session_token="operator-token"
            )
        except ValueError:
            pass  # Baseline status rejection must not hide missing scope authorization.
        calls = service.require_operator.call_args_list
        self.assertTrue(any(
            call.kwargs.get("operation") == "Operation B"
            and call.kwargs.get("workstation") == "Station B"
            for call in calls
        ), "Certificate run operation/workstation must reach server authorization")


    def test_changed_quantity_reusing_token_is_rejected(self):
        service, frappe = self.fixture()
        with self.assertRaisesRegex(ValueError, "different request data"):
            service.report_certificate_process_progress(
                "CYCLE-1", 50, event_token="already-committed-token",
                operator_session_token="operator-token"
            )
        service.get_certificate_process_context.assert_not_called()
        frappe.get_doc.assert_not_called()

    def test_changed_evidence_reusing_token_is_rejected(self):
        for field in ("output_tag_scan", "output_batch", "printed_expiry",
                      "first_output_serial", "last_output_serial"):
            with self.subTest(field=field):
                service, _ = self.fixture()
                with self.assertRaisesRegex(ValueError, "different request data"):
                    service.report_certificate_process_progress(
                        "CYCLE-1", 60, event_token="already-committed-token",
                        operator_session_token="operator-token", **{field: "changed"}
                    )
                service.get_certificate_process_context.assert_not_called()

    def test_legacy_replay_fails_closed_without_guessing(self):
        service, frappe = self.fixture()
        frappe.db.get_value.return_value.request_fingerprint = None
        with self.assertRaisesRegex(ValueError, "no request fingerprint"):
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="old-token",
                operator_session_token="operator-token"
            )
        service.get_certificate_process_context.assert_not_called()

    def test_missing_token_rejected_before_evidence_lookup(self):
        for token in (None, "", "   "):
            with self.subTest(token=token):
                service, frappe = self.fixture()
                with self.assertRaisesRegex(ValueError, "non-empty event token"):
                    service.report_certificate_process_progress(
                        "CYCLE-1", 60, event_token=token,
                        operator_session_token="operator-token"
                    )
                frappe.db.get_value.assert_not_called()

    def test_wrong_operation_denied_before_replay_lookup(self):
        service, frappe = self.fixture()
        def authorize(token, action, **scope):
            if scope.get("operation") == "Operation B":
                raise PermissionError("Operation B is forbidden")
            return types.SimpleNamespace(), types.SimpleNamespace()
        service.require_operator.side_effect = authorize
        with self.assertRaises(PermissionError):
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="already-committed-token",
                operator_session_token="operator-token"
            )
        frappe.db.get_value.assert_not_called()
        service.get_certificate_process_context.assert_not_called()

    def test_new_event_still_obeys_capacity_guard(self):
        service, frappe = self.fixture()
        frappe.db.get_value.return_value = None
        with self.assertRaisesRegex(ValueError, "exceeds the selected quantity"):
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="new-token",
                operator_session_token="operator-token"
            )

    def test_revoked_session_cannot_replay(self):
        service, frappe = self.fixture()
        service.require_operator.side_effect = PermissionError("revoked")
        with self.assertRaises(PermissionError):
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="already-committed-token",
                operator_session_token="operator-token"
            )
        service._locked_run.assert_not_called()
        frappe.db.get_value.assert_not_called()


    def test_all_operator_mutations_enforce_run_scope(self):
        cases = [
            ("start_certificate_process", ("CYCLE-1", "TAG-1", 10, "token")),
            ("complete_certificate_process", ("CYCLE-1", 10)),
            ("close_consolidated_certificate_process", ("CYCLE-1",)),
            ("submit_certificate_process", ("RUN-1",)),
            ("cancel_certificate_process", ("RUN-1", "test reason")),
        ]
        for name, args in cases:
            with self.subTest(endpoint=name):
                service, frappe = self.fixture()
                run = service._locked_run.return_value
                frappe.get_doc.return_value = run
                def authorize(token, action, **scope):
                    if scope.get("operation") == "Operation B":
                        raise PermissionError("wrong operation")
                    return types.SimpleNamespace(), types.SimpleNamespace()
                service.require_operator.side_effect = authorize
                with self.assertRaises(PermissionError):
                    getattr(service, name)(*args, operator_session_token="token")
                service.get_certificate_process_context.assert_not_called()

    def test_workstation_scope_denied_when_run_has_workstation(self):
        service, frappe = self.fixture()
        def authorize(token, action, **scope):
            if scope.get("workstation") == "Station B":
                raise PermissionError("wrong workstation")
            return types.SimpleNamespace(), types.SimpleNamespace()
        service.require_operator.side_effect = authorize
        with self.assertRaises(PermissionError):
            service.report_certificate_process_progress(
                "CYCLE-1", 60, event_token="token", operator_session_token="token"
            )
        frappe.db.get_value.assert_not_called()

    def test_operation_scope_works_without_optional_workstation(self):
        service, _ = self.fixture()
        del service._locked_run.return_value.workstation
        service.report_certificate_process_progress(
            "CYCLE-1", 60, event_token="token", operator_session_token="token"
        )
        self.assertEqual(service.require_operator.call_args.kwargs,
                         {"operation": "Operation B", "workstation": None})


    def test_create_persist_then_replay_does_not_insert_or_accumulate_twice(self):
        service, frappe = self.fixture()
        run = service._locked_run.return_value
        run.good_qty = 0
        for key, value in {
            "kanban_card": "CARD-1", "company": "TEST", "item_code": "ITEM-1",
            "source_handling_unit": "SOURCE-1", "item_batch_controlled": 0,
            "source_batch": None, "source_certificate_set": "SET-1",
            "result_certificate_set": None, "printed_expiry": None,
            "first_output_serial": None, "last_output_serial": None,
        }.items():
            setattr(run, key, value)
        run.db_set = Mock(side_effect=lambda values, **kwargs: [
            setattr(run, key, value) for key, value in values.items()
        ])
        master = types.SimpleNamespace(certificate_process_capture_expiry=0,
                                       certificate_process_capture_serial_boundary=0)
        source = types.SimpleNamespace(name="SOURCE-1")
        persisted = {}
        def get_value(doctype, filters, field=None, **kwargs):
            if field == "max(sequence)":
                return len(persisted)
            return persisted.get(filters["idempotency_key"])
        frappe.db.get_value.side_effect = get_value
        def get_doc(doctype, name=None):
            if isinstance(doctype, dict):
                doc = types.SimpleNamespace(**doctype, name="PROGRESS-NEW")
                def insert(**kwargs):
                    persisted[doc.idempotency_key] = doc
                    return doc
                doc.insert = Mock(side_effect=insert)
                return doc
            return master if doctype == "CFG Kanban Master" else source
        frappe.get_doc.side_effect = get_doc
        frappe.session = types.SimpleNamespace(user="test-user")
        service._validate_retain_evidence = Mock()
        service._result_certificate_set = Mock(return_value=types.SimpleNamespace(name="SET-2"))
        service._progress_output_identity = Mock(return_value={
            "visible_code": "TAG-1", "handling_unit": None, "mode": "New Tag",
            "pending_code": "TAG-1", "qty_before": 0,
        })
        service._validate_progress_output_details = Mock()
        service._claim_output_identity = Mock()
        first = service.record_certificate_process_progress(
            "CYCLE-1", 60, output_tag_scan="TAG-1", event_token="one-micro-lot",
            operator_session_token="operator-token",
        )
        self.assertEqual(first["outcome"], "recorded")
        self.assertEqual(len(persisted), 1)
        self.assertEqual(run.good_qty, 60)
        self.assertTrue(next(iter(persisted.values())).request_fingerprint)
        run.status = "Completed"
        second = service.record_certificate_process_progress(
            "CYCLE-1", 60, output_tag_scan="TAG-1", event_token="one-micro-lot",
            operator_session_token="operator-token",
        )
        self.assertEqual(second, first)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(run.good_qty, 60)
        run.db_set.assert_called_once()
        service.record.assert_called_once()
        service._claim_output_identity.assert_called_once()

    def test_validation_rejection_rolls_back_before_confirming_absence(self):
        service, frappe = self.fixture()
        frappe.db.get_value.return_value = None
        ordering = []
        frappe.db.rollback.side_effect = lambda **kwargs: ordering.append("rollback")
        frappe.db.get_value.side_effect = lambda *args, **kwargs: ordering.append("lookup")
        service.report_certificate_process_progress = Mock(side_effect=ValueError("invalid evidence"))
        result = service.record_certificate_process_progress(
            "CYCLE-1", 60, event_token="rejected-token", operator_session_token="token"
        )
        self.assertEqual(result, {"outcome": "rejected", "event_token": "rejected-token"})
        self.assertEqual(ordering, ["rollback", "lookup"])
        frappe.db.rollback.assert_called_once_with(save_point="certificate_progress_attempt")
        self.assertEqual(service.require_operator.call_args.kwargs,
                         {"operation": "Operation B", "workstation": "Station B"})

    def test_existing_conflict_or_legacy_record_never_confirms_rejection(self):
        for fingerprint in (None, "different-fingerprint"):
            with self.subTest(fingerprint=fingerprint):
                service, frappe = self.fixture()
                frappe.db.get_value.return_value.request_fingerprint = fingerprint
                with self.assertRaises(ValueError):
                    service.record_certificate_process_progress(
                        "CYCLE-1", 60, event_token="existing-token", operator_session_token="token"
                    )
                frappe.db.rollback.assert_called_once()

    def test_unexpected_errors_do_not_confirm_rejection(self):
        service, frappe = self.fixture()
        service.report_certificate_process_progress = Mock(side_effect=RuntimeError("database failure"))
        with self.assertRaises(RuntimeError):
            service.record_certificate_process_progress(
                "CYCLE-1", 60, event_token="uncertain", operator_session_token="token"
            )
        frappe.db.get_value.assert_not_called()

    def test_outcome_endpoint_denies_scope_before_savepoint_or_mutation(self):
        service, frappe = self.fixture()
        def authorize(token, action, **scope):
            if scope.get("operation") == "Operation B":
                raise PermissionError("wrong operation")
            return types.SimpleNamespace(), types.SimpleNamespace()
        service.require_operator.side_effect = authorize
        service.report_certificate_process_progress = Mock()
        with self.assertRaises(PermissionError):
            service.record_certificate_process_progress(
                "CYCLE-1", 60, event_token="token", operator_session_token="token"
            )
        frappe.db.savepoint.assert_not_called()
        service.report_certificate_process_progress.assert_not_called()


if __name__ == "__main__":
    unittest.main()

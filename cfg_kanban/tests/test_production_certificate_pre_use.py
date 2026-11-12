"""Offline pre-use certificate behavior; no live ERP transaction acceptance."""
import json
import sys
import types
import unittest
import ast
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_material_actuals_yield import ROOT, Row, functions, frappe_double


class TestPreUseCertificateEvidence(unittest.TestCase):
    def setUp(self):
        self.frappe = frappe_double()
        self.execution = Row(doctype="CFG Kanban Process Execution", name="EXEC", job_card="JC",
            kanban_master="MASTER", operation="Packing", sequence=2, allow_material_carry_forward=0,
            db_set=Mock())
        self.run = Row(name="RUN", process_execution="EXEC", status="Open")
        self.open_run = self.run
        self.requirement = Row(operation="Packing", gate_stage="Before Progress",
            certificate_type="PRINTED", requirement_group="DEFAULT", group_logic="All Required",
            minimum_revision=1, require_unexpired=1)
        self.master = Row(certificate_requirements=[self.requirement])
        self.draws = []
        self.units = {"GOOD": Row(name="GOOD", process_certificate_set="PRINTED-SET"),
                      "BAD": Row(name="BAD", process_certificate_set=None)}
        self.proofs = {"GOOD": True}
        self.prior = []
        self.coverage = types.ModuleType("cfg_kanban.services.logistics_stock_identity")
        self.coverage.certificate_requirement_covered = lambda unit, *args, **kwargs: self.proofs.get(unit.name, False)
        self.frappe.get_all.side_effect = self.get_all
        self.frappe.get_doc.side_effect = self.get_doc
        self.frappe.db.get_value.side_effect = self.get_value
        self.frappe.as_json = json.dumps
        self.ns = functions("services/production_certificates.py", [
            "_execution", "_certificate_evidence", "_requirement_passes",
            "evaluate_execution_certificate_gate", "assert_execution_certificate_gate",
            "assert_pre_use_certificate_gates", "operation_start_certificate_readiness"], {
                "frappe": self.frappe, "cint": lambda x: int(x or 0), "TOLERANCE": 0.000001,
                "now_datetime": lambda: "2026-11-12 12:00:00",
                "_prior_execution_sets": lambda execution: self.prior,
                "_member_union": lambda names: {"PRINTED": 1} if "PRINTED-SET" in names else {},
            })

    def draw(self, source="GOOD", **values):
        row = Row(name="DRAW-"+str(len(self.draws)), process_execution="EXEC", job_card="JC",
            operation="Packing", material_run="RUN", status="Open", remaining_qty=5,
            source_handling_unit=source)
        row.update(values)
        self.draws.append(row)
        return row

    @staticmethod
    def matches(row, filters):
        for key, expected in filters.items():
            value = row.get(key)
            if isinstance(expected, (list, tuple)):
                op, operand = expected
                if op == "in" and value not in operand: return False
                if op == "!=" and value == operand: return False
                if op == ">" and not value > operand: return False
                if op == "is" and operand == "set" and not value: return False
            elif value != expected:
                return False
        return True

    def get_all(self, doctype, *, filters, pluck, **kwargs):
        if doctype == "CFG Kanban Operation Material Draw": rows = self.draws
        elif doctype == "CFG Kanban Handling Unit": rows = list(self.units.values())
        else: raise AssertionError(doctype)
        return [row.get(pluck) for row in rows if self.matches(row, filters)]

    def get_value(self, doctype, name, fields):
        if doctype == "CFG Kanban Operation Material Run":
            self.assertEqual(name, {"process_execution": "EXEC", "status": "Open"})
            return self.open_run.name if self.open_run else None
        self.assertEqual(doctype, "CFG Kanban Handling Unit")
        return self.units[name].get(fields)

    def get_doc(self, doctype, name):
        if doctype == "CFG Kanban Master": return self.master
        if doctype == "CFG Kanban Operation Material Run": return self.run
        if doctype == "CFG Kanban Handling Unit": return self.units[name]
        raise AssertionError((doctype, name))

    def check(self, run=None):
        with patch.dict(sys.modules, {self.coverage.__name__: self.coverage}):
            return self.ns["assert_pre_use_certificate_gates"](self.execution, material_run=run)

    def test_both_gate_stages_validate_the_scanned_source_before_run_start(self):
        self.draw()
        for stage in ("Before Operation Start", "Before Progress"):
            with self.subTest(stage=stage):
                self.requirement.gate_stage = stage
                results = self.check(self.run)
                self.assertTrue(all(row["passed"] for row in results))
                self.assertIn("PRINTED-SET", [name for row in results for name in row["sets"]])

    def test_uncertified_next_run_cannot_borrow_previous_used_source(self):
        self.draw(status="Used", remaining_qty=0, material_run="OLD")
        self.draw("BAD")
        with self.assertRaisesRegex(ValueError, "Before Progress Certificate gate"):
            self.check(self.run)

    def test_source_from_another_lane_cannot_authorize_the_run(self):
        self.draw(process_execution="OTHER-EXEC")
        self.draw("BAD")
        with self.assertRaises(ValueError): self.check(self.run)

    def test_cancelled_empty_or_other_run_source_cannot_authorize(self):
        for values in ({"status":"Cancelled"}, {"remaining_qty":0}, {"material_run":"OLD"}):
            with self.subTest(values=values):
                self.draws.clear(); self.draw(**values)
                with self.assertRaises(ValueError): self.check(self.run)

    def test_allowed_carry_forward_is_rechecked_before_each_use(self):
        self.execution.allow_material_carry_forward = 1
        self.draw(material_run="OLD", status="Carry Forward")
        self.check(self.run)
        self.proofs["GOOD"] = False
        with self.assertRaises(ValueError): self.check(self.run)

    def test_progress_rechecks_revoked_or_expired_proof(self):
        self.draw(); self.check(self.run)
        self.proofs["GOOD"] = False
        with self.assertRaises(ValueError): self.check()

    def test_higher_required_revision_rejects_old_certificate(self):
        self.draw(); self.requirement.minimum_revision = 2
        with self.assertRaises(ValueError): self.check(self.run)

    def test_start_without_open_run_cannot_reuse_historical_scans(self):
        self.draw(status="Used", material_run="OLD"); self.open_run = None
        with self.assertRaises(ValueError): self.check()

    def test_prior_operation_result_still_satisfies_start_gate(self):
        self.requirement.gate_stage = "Before Operation Start"
        self.open_run = None; self.prior = ["PRINTED-SET"]
        self.assertTrue(all(row["passed"] for row in self.check()))

    def test_all_any_logic_remains_scoped_to_the_configured_gate_group(self):
        self.draw()
        self.master.certificate_requirements.append(Row(self.requirement, certificate_type="SANITISED"))
        with self.assertRaises(ValueError): self.check(self.run)
        for row in self.master.certificate_requirements: row.group_logic = "Any in Group"
        self.check(self.run)

    def test_wrong_execution_or_closed_run_is_rejected(self):
        self.draw()
        for values in ({"process_execution":"OTHER"}, {"status":"Progress Posted"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.check(Row(self.run, **values))

    def test_posted_native_gate_retains_job_card_shared_history(self):
        self.draw(status="Used", remaining_qty=0, process_execution="RUNTIME", material_run="OLD")
        with patch.dict(sys.modules, {self.coverage.__name__: self.coverage}):
            result = self.ns["assert_execution_certificate_gate"](self.execution, "Before Progress")
        self.assertTrue(result["passed"])

    def test_readiness_defers_without_throwing_or_mutating_execution(self):
        with patch.dict(sys.modules, {self.coverage.__name__: self.coverage}):
            result = self.ns["operation_start_certificate_readiness"](self.execution)
        self.assertFalse(result["ready"])
        self.assertIn("Start Material Run", result["reason"])
        self.execution.db_set.assert_not_called()

    def test_operations_without_certificate_rules_remain_unrestricted(self):
        self.master.certificate_requirements.clear()
        self.assertTrue(all(row["passed"] for row in self.check()))
        self.frappe.get_all.assert_not_called()


class TestMaterialRunPreparation(unittest.TestCase):
    def setUp(self):
        self.frappe = frappe_double()
        self.execution = Row(name="EXEC", status="Ready", operation="Packing", job_card="JC",
            kanban_master="MASTER", kanban_cycle="CYCLE", runtime_allocation=None,
            allow_material_carry_forward=0, db_set=Mock())
        self.run = Row(name="RUN", doctype="CFG Kanban Operation Material Run", status="Open",
            process_execution="EXEC", run_number=1, db_set=Mock(), reload=Mock())
        self.run.insert = Mock(return_value=self.run)
        self.frappe.get_doc.side_effect = lambda doctype, name=None: self.run if isinstance(doctype, dict) else self.execution
        self.frappe.UniqueValidationError = type("UniqueValidationError", (Exception,), {})
        self.frappe.db.get_value.return_value = "WO"
        self.events = []
        self.certificates = types.ModuleType("cfg_kanban.services.production_certificates")
        self.certificates.assert_pre_use_certificate_gates = Mock(side_effect=lambda *args, **kwargs: self.events.append("certificates"))
        self.ns = functions("services/operation_material_runs.py", ["start_scanner_run"], {
            "frappe": self.frappe, "_":lambda x:x, "flt":lambda x:float(x or 0),
            "PREPARATION_EXECUTION_STATES":{"Ready","In Progress","Paused"},
            "require_operator":Mock(return_value=(Row(employee="EMP"), Row(name="SESSION",terminal_user="terminal"))),
            "_assert_enabled":Mock(), "_normalise_boundary":lambda x:x, "_assert_boundary":Mock(),
            "_normalise_draw_requests":lambda x:x or [], "canonical_key":lambda *args:str(args),
            "get_existing":Mock(return_value=None), "_assert_idempotent_match":Mock(),
            "_open_run":Mock(return_value=None), "_next_run_number":lambda x:1,
            "_assert_carry_forward_expiry":Mock(), "lock_material_rotation":Mock(),
            "_create_material_draws":Mock(side_effect=lambda *args, **kwargs:self.events.append("draws") or []),
            "_assert_tracked_materials_ready":Mock(), "now_datetime":lambda:"2026-11-12 12:00:00",
            "record":Mock(), "_run_payload":lambda run, **kwargs:{"name":run.name,**kwargs},
        })

    def start(self):
        with patch.dict(sys.modules, {self.certificates.__name__:self.certificates}):
            return self.ns["start_scanner_run"]("EXEC", "TOKEN", material_draws=[{"scan_value":"TAG","qty":5}])

    def test_ready_operation_prepares_sources_then_checks_before_linking_run(self):
        self.assertEqual(self.start()["name"], "RUN")
        self.assertEqual(self.events, ["draws","certificates"])
        self.assertEqual(self.execution.status,"Ready")
        self.certificates.assert_pre_use_certificate_gates.assert_called_once_with(self.execution,material_run=self.run)
        self.execution.db_set.assert_called_once_with("open_material_run","RUN",update_modified=True)

    def test_failed_gate_does_not_link_run_or_publish_start_event(self):
        self.certificates.assert_pre_use_certificate_gates.side_effect = ValueError("missing PRINTED")
        with self.assertRaisesRegex(ValueError,"missing PRINTED"):self.start()
        self.execution.db_set.assert_not_called();self.ns["record"].assert_not_called()

    def test_blocked_not_ready_and_terminal_operations_cannot_prepare(self):
        for status in ("Not Ready","Blocked","Completed","Cancelled","Waiting Input"):
            with self.subTest(status=status):
                self.execution.status=status
                with self.assertRaisesRegex(ValueError,"Ready or started"):self.start()
        self.run.insert.assert_not_called()

    def test_existing_open_run_is_rechecked_when_reopened_or_retried(self):
        for getter in ("get_existing","_open_run"):
            with self.subTest(getter=getter):
                self.ns["get_existing"].return_value=None;self.ns["_open_run"].return_value=None
                self.ns[getter].return_value=self.run
                self.certificates.assert_pre_use_certificate_gates.side_effect=ValueError("revoked")
                with self.assertRaisesRegex(ValueError,"revoked"):self.start()
        self.run.insert.assert_not_called()

    def test_prepared_run_cannot_post_progress_before_operation_start(self):
        self.execution.material_run_control="Required Before Progress"
        ns=functions("services/operation_material_runs.py",["validate_progress_materials"],{
            "frappe":self.frappe,"ACTIVE_EXECUTION_STATES":{"In Progress","Paused"}})
        with self.assertRaisesRegex(ValueError,"Start Operation"):
            ns["validate_progress_materials"](self.execution,self.run,5)


class TestRuntimeCertificateAutoStart(unittest.TestCase):
    def test_missing_certificate_defers_start_but_preserves_allocation(self):
        frappe=frappe_double();frappe.session=Row(user="terminal");frappe.as_json=json.dumps
        cert=types.ModuleType("cfg_kanban.services.production_certificates")
        cert.operation_start_certificate_readiness=Mock(return_value={"ready":False,"reason":"Scan PRINTED source"})
        cert.assert_pre_use_certificate_gates=Mock()
        material=types.ModuleType("cfg_kanban.services.production_material_flow")
        material.job_card_material_readiness=Mock(return_value={"ready":True,"reason":"Ready"})
        gateway=types.ModuleType("cfg_kanban.integrations.erp_gateway");gateway.execute_command=Mock()
        tree=ast.parse((ROOT/'services/runtime_selector.py').read_text())
        fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='allocate')
        block=next(node for node in fn.body if isinstance(node,ast.If) and 'auto_start_job_card' in ast.dump(node.test))
        record=Mock();execution=Row(name="EXEC",reload=Mock())
        namespace={"frappe":frappe,"settings":Row(auto_start_job_card=1),
            "proposal":{"job_card_status":"Open","job_card":"JC"},"execution":execution,
            "card":Row(name="CARD"),"cycle":Row(name="CYCLE"),"allocation":Row(name="ALLOC"),
            "record":record,"canonical_key":lambda *args:str(args),"now_datetime":lambda:"NOW",
            "insert_once":Mock(return_value=(Row(name="COMMAND"),True))}
        modules={cert.__name__:cert,material.__name__:material,gateway.__name__:gateway}
        with patch.dict(sys.modules,modules):
            exec(compile(ast.Module(body=[block],type_ignores=[]),'automatic start','exec'),namespace)
            self.assertEqual(record.call_args.kwargs['notes'],'Scan PRINTED source')
            frappe.get_doc.assert_not_called();gateway.execute_command.assert_not_called()
            cert.operation_start_certificate_readiness.return_value={"ready":True,"reason":"Ready"}
            exec(compile(ast.Module(body=[block],type_ignores=[]),'automatic start','exec'),namespace)
        cert.assert_pre_use_certificate_gates.assert_called_once_with(execution)
        gateway.execute_command.assert_called_once_with("COMMAND")


class TestPreUseApiEnforcement(unittest.TestCase):
    def test_direct_start_and_progress_requests_cannot_skip_the_pre_use_gate(self):
        for function, arguments in (
            ("run_job_card_action", ("EXEC", "start")),
            ("submit_progress", ("EXEC", 5)),
        ):
            with self.subTest(function=function):
                frappe=frappe_double()
                execution=Row(name="EXEC",job_card="JC")
                frappe.get_doc.return_value=execution
                cert=types.ModuleType("cfg_kanban.services.production_certificates")
                cert.assert_pre_use_certificate_gates=Mock(side_effect=ValueError("missing PRINTED"))
                cert.finalize_execution_certificate_result=Mock()
                namespace={"frappe":frappe,"require_operator":Mock(return_value=(Row(),Row())),
                    "enforce_execution_crew":Mock(),"_crew_actor":Mock(),
                    "insert_once":Mock(),"execute_command":Mock(),"report":Mock()}
                functions("api/operator.py",[function],namespace)
                with patch.dict(sys.modules,{cert.__name__:cert}):
                    with self.assertRaisesRegex(ValueError,"missing PRINTED"):
                        namespace[function](*arguments)
                cert.assert_pre_use_certificate_gates.assert_called_once_with(execution)
                namespace["insert_once"].assert_not_called()
                namespace["execute_command"].assert_not_called()
                namespace["report"].assert_not_called()


if __name__ == '__main__':unittest.main()

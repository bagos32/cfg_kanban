from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestProcessTaskContract(TestCase):
    def test_cycle_creation_instantiates_tasks_before_automatic_release(self):
        source = (ROOT / "services" / "triggers.py").read_text()
        hooks = (ROOT / "hooks.py").read_text()
        self.assertLess(source.index("ensure_tasks(cycle.name)"),
                        source.index('if created and automatic_release'))
        self.assertIn('evaluate_gate(cycle.name, "Before Cycle Start")', source)
        self.assertIn("process_tasks.on_cycle_created", hooks)

    def test_production_gates_cover_core_release_points(self):
        operator = (ROOT / "api" / "operator.py").read_text()
        progress = (ROOT / "services" / "progress.py").read_text()
        feedback = (ROOT / "integrations" / "erp_feedback.py").read_text()
        self.assertIn('"Before Cycle Start"', operator)
        self.assertIn('"Before Operation Start"', operator)
        self.assertIn('"After Operation Complete"', operator)
        self.assertIn('"Before Cycle Close"', operator)
        self.assertIn('"Before WIP Release"', progress)
        self.assertIn('"Before FG Release"', feedback)
        self.assertIn('"After Operation Complete"', feedback)

    def test_task_service_supports_validity_reuse_and_independent_verification(self):
        source = (ROOT / "services" / "process_tasks.py").read_text()
        self.assertIn("reuse_while_valid", source)
        self.assertIn("valid_until", source)
        self.assertIn("Awaiting Verification", source)
        self.assertIn("must be performed by a different operator", source)

    def test_standalone_tasks_never_create_manufacturing_documents(self):
        source = (ROOT / "services" / "standalone_tasks.py").read_text()
        model = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_task" /
                 "cfg_kanban_task.py").read_text()
        self.assertNotIn('"doctype": "Work Order"', source)
        self.assertNotIn('"doctype": "Job Card"', source)
        self.assertNotIn('"doctype": "Stock Entry"', source)
        self.assertIn("cannot own production or ERP manufacturing records", model)

    def test_standalone_tasks_reuse_auth_forms_and_scheduler(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        forms = (ROOT / "services" / "dynamic_forms.py").read_text()
        hooks = (ROOT / "hooks.py").read_text()
        self.assertIn("require_operator", service)
        self.assertIn("standalone_definitions", forms)
        self.assertIn("generate_due_tasks", hooks)
        self.assertIn("update_overdue_tasks", hooks)

    def test_service_task_console_can_identify_operator_and_create_from_schedule(self):
        api = (ROOT / "api" / "task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("def get_request_schedules", api)
        self.assertIn("def supervisor_request_task", api)
        self.assertIn("Identify Operator", console)
        self.assertIn("Scan Operator QR", console)
        self.assertIn("Create Task", console)
        self.assertIn("No open service tasks", console)

    def test_standalone_compliance_record_supports_rejection_reports_and_printing(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        api = (ROOT / "api" / "task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("def reject_task", service)
        self.assertIn("Correction Required", service)
        self.assertIn("def reject(", api)
        self.assertIn("Submitted Completion Evidence", console)
        self.assertIn("Reject for Correction", console)
        self.assertIn("safe_rich_text", console)
        self.assertTrue((ROOT / "cfg_kanban" / "report" /
                         "kanban_maintenance_register" /
                         "kanban_maintenance_register.py").exists())
        self.assertTrue((ROOT / "cfg_kanban" / "report" /
                         "kanban_maintenance_evidence" /
                         "kanban_maintenance_evidence.py").exists())
        self.assertTrue((ROOT / "cfg_kanban" / "print_format" /
                         "cfg_verified_maintenance_record" /
                         "cfg_verified_maintenance_record.json").exists())

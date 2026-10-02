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

    def test_service_progress_fields_have_a_real_capture_action_and_completion_gate(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        api = (ROOT / "api" / "task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("def progress_task", service)
        self.assertIn("_assert_required_progress(task)", service)
        self.assertIn("def progress(", api)
        self.assertIn("Report Progress", console)
        self.assertIn('Progress: "progress"', console)
        self.assertIn("get_task_progress", api)
        self.assertIn("View Progress", console)
        self.assertIn("last_progress_summary", service)
        self.assertIn("Supervisor correction requested", console)
        self.assertIn("previous ? previous.value", console)

    def test_dynamic_answers_are_serialized_for_frappe_version_history(self):
        forms = (ROOT / "services" / "dynamic_forms.py").read_text()
        model = (ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_task" /
                 "cfg_kanban_task.py").read_text()
        self.assertIn('return "1" if value else "0"', forms)
        self.assertIn('return str(value)', forms)
        self.assertIn("def before_validate", model)
        self.assertIn("not isinstance(row.value, str)", model)

    def test_dynamic_visible_conditions_are_enforced_in_ui_and_server(self):
        forms = (ROOT / "services" / "dynamic_forms.py").read_text()
        service_console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                           "kanban_tasks.js").read_text()
        production_console = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                              "kanban_operator.js").read_text()
        self.assertIn('"visible_condition"', forms)
        self.assertIn("_visible_rows(rows, supplied)", forms)
        self.assertIn("validate_condition_definitions", forms)
        self.assertIn("configure_dynamic_visibility(dialog, definitions)", service_console)
        self.assertIn("visible_dynamic_definitions(definitions, values)", service_console)
        self.assertIn("configure_dynamic_visibility(dialog, definitions)", production_console)
        self.assertIn("visible_dynamic_definitions(definitions, values)", production_console)

    def test_service_task_console_can_identify_operator_and_create_from_schedule(self):
        api = (ROOT / "api" / "task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("def get_request_schedules", api)
        self.assertIn("def supervisor_request_task", api)
        self.assertIn("Identify Operator", console)
        self.assertIn("Scan Operator QR", console)
        self.assertIn("Service Task Scanner", console)
        self.assertIn("Scan Task QR with Camera", console)
        self.assertIn("Find Task / Card", console)
        self.assertIn("Task scanner ready", console)
        self.assertIn("Create Task", console)
        self.assertIn("No open service tasks", console)
        self.assertIn("cfg-service-mobile-actions", console)
        self.assertIn("Scan / Switch Operator", console)
        self.assertIn("End Session", console)
        self.assertIn("cfg-service-task-actions", console)
        self.assertIn("Open Production Operator Panel", console)
        self.assertIn("cfg-service-sticky-shell", console)
        self.assertIn("cfg-service-active-work", console)
        self.assertIn("Ready / Open Tasks", console)
        self.assertIn("Supervisor Attention", console)
        self.assertIn("scroll_to_active_work", console)
        self.assertIn('task.assigned_employee === employee', console)
        operator_console = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                            "kanban_operator.js").read_text()
        self.assertIn("Open Service Task Panel", operator_console)
        self.assertIn("cfg-operator-sticky-shell", operator_console)
        self.assertIn("cfg-production-identity", operator_console)
        self.assertIn("Active Work", operator_console)
        self.assertIn("responsibility_names(profile)", api)
        self.assertIn("can_access_service_task", api)
        access = (ROOT / "services" / "task_access.py").read_text()
        self.assertIn("def can_access_service_task", access)
        self.assertIn('task.status == "Awaiting Verification"', access)
        self.assertIn("View All Service Tasks", access)
        self.assertIn('"responsible_role", "progress_count"', api)
        self.assertIn('"last_progress_on", "last_progress_summary"', api)
        self.assertIn('"verified_by", "verified_on", "modified"', api)

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

    def test_permanent_service_points_resolve_occurrences_and_control_overlap(self):
        service = (ROOT / "services" / "standalone_tasks.py").read_text()
        api = (ROOT / "api" / "task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
                   "kanban_tasks.js").read_text()
        self.assertIn("def resolve_service_point", service)
        self.assertIn("Prevent While Open", service)
        self.assertIn("_is_skipped_holiday", service)
        self.assertIn("def disposition_task", service)
        self.assertIn("def resolve_service_scan", api)
        self.assertIn("def supervisor_disposition", api)
        self.assertIn("CFG:SERVICE:SCHEDULE:", console)
        self.assertIn("Cancel / Bypass", console)

    def test_controlled_qc_tasks_hold_cycle_and_support_retest(self):
        service = (ROOT / "services" / "process_tasks.py").read_text()
        api = (ROOT / "api" / "process_task.py").read_text()
        console = (ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                   "kanban_operator.js").read_text()
        self.assertIn("def _apply_qc_outcome", service)
        self.assertIn('"status": "Hold"', service)
        self.assertIn("QC Process Task Failed", service)
        self.assertIn("def reset_qc_for_retest", service)
        self.assertIn("def resolve_scan", api)
        self.assertIn("get_sample_label", api)
        self.assertIn("Product", console.replace("Item", "Product"))
        self.assertIn("Authorise Retest", console)

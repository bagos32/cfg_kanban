from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class TestDocTypeActionCardRuntime(TestCase):
    def setUp(self):
        self.runs = (ROOT / "services" / "doctype_action_runs.py").read_text()
        self.writer = (ROOT / "services" / "doctype_action_writer.py").read_text()
        self.api = (ROOT / "api" / "doctype_action_run.py").read_text()
        self.page = (
            ROOT / "cfg_kanban" / "page" / "kanban_tasks" / "kanban_tasks.js"
        ).read_text()

    def test_scan_resolution_is_non_production_and_does_not_create_a_run(self):
        resolver = self.runs[
            self.runs.index("def resolve_card_scan"):
            self.runs.index("def start_card_run")
        ]
        self.assertIn('DIRECT_CARD_TYPE = "DocType Action Card"', self.runs)
        self.assertIn('"matched": False', resolver)
        self.assertIn('"open_runs": open_runs', resolver)
        self.assertIn('"can_start_new": True', resolver)
        self.assertNotIn('"doctype": "CFG Kanban DocType Action Run"', resolver)
        self.assertNotIn("insert_once(", resolver)

    def test_explicit_start_and_resume_have_separate_idempotent_paths(self):
        creator = self.runs[
            self.runs.index("def start_card_run"):
            self.runs.index("def resume_card_run")
        ]
        resume = self.runs[
            self.runs.index("def resume_card_run"):
            self.runs.index("def cancel_run")
        ]
        self.assertIn('"doctype-action-card-run-v1"', creator)
        self.assertIn('"action_slot": "direct"', creator)
        self.assertIn("insert_once(run, run_key", creator)
        self.assertIn("_attempt_for_retry_token(request_token)", creator)
        self.assertIn("_is_direct_run_open(run)", resume)
        self.assertNotIn("insert_once(run", resume)
        self.assertNotIn('"doctype": "CFG Kanban DocType Action Run"', resume)

    def test_operator_and_supervisor_scope_are_rechecked_server_side(self):
        self.assertIn('require_operator(operator_session_token, "task_start")', self.runs)
        self.assertIn("run.operator_employee != profile.employee", self.runs)
        self.assertIn("_is_action_supervisor(profile)", self.runs)
        self.assertIn('filters["operator_employee"] = profile.employee', self.runs)
        self.assertIn('require_operator(operator_session_token, "override")', self.runs)

    def test_direct_profiles_cannot_depend_on_service_task_fields(self):
        actions = (ROOT / "services" / "doctype_actions.py").read_text()
        card = (
            ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_card" /
            "cfg_kanban_card.py"
        ).read_text()
        self.assertIn("assert_direct_card_profile_compatible(snapshot)", self.runs)
        self.assertIn('row.get("source_type") == "Service Task Field"', actions)
        self.assertIn("Service Task verification", actions)
        self.assertIn("assert_direct_card_profile_compatible(_snapshot)", card)
        self.assertIn("Service Task Field mappings cannot be used", self.writer)

    def test_runtime_api_and_service_panel_require_explicit_new_intent(self):
        self.assertIn("def resolve_card_scan(scan_value, operator_session_token)", self.api)
        self.assertIn("def start_card_action(card_name, operator_session_token, request_token)", self.api)
        self.assertIn("def resume_card_action(run_name, operator_session_token, retry_token)", self.api)
        self.assertIn("open_action_card_selector", self.page)
        self.assertIn("Start New Action", self.page)
        self.assertIn("Resume", self.page)
        self.assertIn("dialog.__cfg_start_action_token", self.page)
        self.assertIn("dialog.__cfg_resume_tokens", self.page)
        self.assertIn("Scanning identifies the reusable Card only", self.page)

    def test_writer_reuses_the_same_form_for_task_and_card_sources(self):
        self.assertIn('"source": _source_summary(source)', self.writer)
        self.assertIn('source.doctype == "CFG Kanban Task"', self.writer)
        self.assertIn('"card_number": source.card_number', self.writer)
        self.assertIn("Reusable Action Card", self.page)
        self.assertIn("form.source", self.page)

    def test_reusable_card_never_leaks_evidence_across_occurrences(self):
        media = (ROOT / "services" / "doctype_action_media.py").read_text()
        self.assertIn('if run.source_doctype == "CFG Kanban Card"', media)
        self.assertIn("return _action_run_evidence(run)", media)
        self.assertIn("belongs to this immutable Run", media)
        self.assertIn("ACTION_RUN_DOCTYPE, run.name", media)
        self.assertNotIn('"CFG Kanban Card", run.source_name', media)


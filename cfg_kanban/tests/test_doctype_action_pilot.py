import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PILOT_DOCTYPES = ROOT / "cfg_kanban_pilot" / "doctype"


class TestDocTypeActionGate1Pilot(TestCase):
    def _schema(self, folder):
        path = PILOT_DOCTYPES / folder / f"{folder}.json"
        return json.loads(path.read_text())

    def test_pilot_targets_are_isolated_in_the_pilot_module(self):
        modules = (ROOT / "modules.txt").read_text().splitlines()
        self.assertIn("CFG Kanban Pilot", modules)
        for folder in ("cfg_action_pilot_draft", "cfg_action_pilot_submission"):
            schema = self._schema(folder)
            self.assertEqual(schema["module"], "CFG Kanban Pilot")
            self.assertIn("pilot_notice", {row["fieldname"] for row in schema["fields"]})

    def test_draft_and_submit_targets_have_truthful_document_semantics(self):
        draft = self._schema("cfg_action_pilot_draft")
        submission = self._schema("cfg_action_pilot_submission")
        self.assertFalse(bool(draft.get("is_submittable")))
        self.assertEqual(submission.get("is_submittable"), 1)
        draft_terminal = next(row for row in draft["permissions"]
                              if row["role"] == "Kanban Terminal")
        submit_terminal = next(row for row in submission["permissions"]
                               if row["role"] == "Kanban Terminal")
        self.assertFalse(bool(draft_terminal.get("submit")))
        self.assertEqual(submit_terminal.get("submit"), 1)

    def test_both_targets_exercise_parent_and_child_mapping(self):
        for folder in ("cfg_action_pilot_draft", "cfg_action_pilot_submission"):
            schema = self._schema(folder)
            fields = {row["fieldname"]: row for row in schema["fields"]}
            self.assertEqual(fields["performed_by"]["options"], "Employee")
            self.assertEqual(fields["outcome"]["fieldtype"], "Select")
            self.assertEqual(fields["observations"]["fieldtype"], "Table")
            self.assertEqual(
                fields["observations"]["options"], "CFG Action Pilot Observation"
            )
        observation = self._schema("cfg_action_pilot_observation")
        self.assertEqual(observation.get("istable"), 1)
        self.assertIn("measured_value", {
            row["fieldname"] for row in observation["fields"]
        })

    def test_pilot_parent_operator_inputs_remain_editable_in_dialog(self):
        pilot = (ROOT / "services" / "doctype_action_pilot.py").read_text()
        page = (
            ROOT / "cfg_kanban" / "page" / "kanban_tasks" /
            "kanban_tasks.js"
        ).read_text()
        for fieldname in ("summary", "outcome", "notes"):
            self.assertIn(
                f'("{fieldname}", "Operator Input", None', pilot
            )
        self.assertIn("function action_field_read_only(field)", page)
        self.assertIn('field.source_type !== "Operator Input"', page)
        self.assertIn("condition_truthy(field.read_only)", page)
        self.assertIn("enforce_action_parent_editability", page)
        self.assertIn('.prop("readonly", false).prop("disabled", false)', page)

    def test_engine_exception_is_exact_and_policy_is_still_required(self):
        engine = (ROOT / "services" / "doctype_actions.py").read_text()
        self.assertIn('PILOT_TARGETS = {', engine)
        self.assertIn(
            'meta.name in PILOT_TARGETS and meta.module == "CFG Kanban Pilot"', engine
        )
        self.assertIn('"CFG Kanban",', engine)
        self.assertIn('"CFG Kanban Pilot",', engine)
        self.assertIn('"CFG Kanban DocType Action Policy"', engine)

    def test_pilot_setup_is_explicit_not_an_install_or_migrate_side_effect(self):
        hooks = (ROOT / "hooks.py").read_text()
        install = (ROOT / "install.py").read_text()
        api = (ROOT / "api" / "doctype_action.py").read_text()
        list_js = (
            ROOT / "public" / "js" / "cfg_kanban_doctype_action_profile_list.js"
        ).read_text()
        self.assertNotIn("install_pilot_configuration", install)
        self.assertIn("cfg_kanban_doctype_action_profile_list.js", hooks)
        self.assertIn('@frappe.whitelist(methods=["POST"])', api)
        self.assertIn("install_gate1_pilot", api)
        self.assertIn("Install Gate 1 Pilot", list_js)

    def test_canonical_pilot_test_guide_is_linked(self):
        guide = REPO / "docs" / "TEST_GATE1_DOCTYPE_ACTION_PILOT.md"
        self.assertTrue(guide.exists())
        content = guide.read_text()
        self.assertIn("CFG Gate 1 Pilot - Draft", content)
        self.assertIn("CFG Gate 1 Pilot - Submit", content)
        self.assertIn("Pending Document Posting", content)
        self.assertIn("exactly one", content)

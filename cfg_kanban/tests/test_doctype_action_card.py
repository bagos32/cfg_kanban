import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
CARD_ROOT = ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_card"


class TestDocTypeActionCardFoundation(TestCase):
    def setUp(self):
        self.schema = json.loads((CARD_ROOT / "cfg_kanban_card.json").read_text())
        self.fields = {row["fieldname"]: row for row in self.schema["fields"]}

    def test_exact_non_production_card_type_and_profile_link_are_declared(self):
        self.assertIn(
            "DocType Action Card",
            self.fields["card_type"]["options"].splitlines(),
        )
        profile = self.fields["doctype_action_profile"]
        self.assertEqual(profile["options"], "CFG Kanban DocType Action Profile")
        self.assertIn("DocType Action Card", profile["mandatory_depends_on"])
        self.assertIn(
            "DOCTYPE_ACTION_CARD",
            self.fields["card_behavior"]["options"].splitlines(),
        )

    def test_action_card_does_not_require_a_master_or_quantity(self):
        self.assertNotIn("DocType Action Card", self.fields["kanban_master"][
            "mandatory_depends_on"
        ])
        self.assertFalse(self.fields["kanban_qty"].get("reqd", 0))
        self.assertNotIn("DocType Action Card", self.fields["kanban_qty"][
            "mandatory_depends_on"
        ])

    def test_controller_validates_profile_and_preserves_identity_boundary(self):
        controller = (CARD_ROOT / "cfg_kanban_card.py").read_text()
        self.assertIn("def _validate_doctype_action_card", controller)
        self.assertIn("executable_profile_snapshot", controller)
        self.assertIn("require_configuration_role", controller)
        self.assertIn("cannot have a Kanban Cycle", controller)
        self.assertIn("DocType Action Profile is immutable", controller)
        self.assertIn("self.kanban_qty = 0", controller)

    def test_every_production_entry_point_fails_closed(self):
        scan = (ROOT / "api" / "scan.py").read_text()
        operator = (ROOT / "api" / "operator.py").read_text()
        logistics = (ROOT / "api" / "logistics.py").read_text()
        triggers = (ROOT / "services" / "triggers.py").read_text()
        self.assertIn('card_type == "DocType Action Card"', scan)
        self.assertIn('card.card_type == "DocType Action Card"', operator)
        self.assertIn('card.card_type == "DocType Action Card"', logistics)
        self.assertIn(
            'card.card_type not in ("Physical Unit Card", "Physical Batch Card")',
            triggers,
        )

    def test_card_has_a_dedicated_reusable_qr_print_format(self):
        form = (ROOT / "public" / "js" / "cfg_kanban_card.js").read_text()
        self.assertIn("Print DocType Action Card", form)
        self.assertIn("CFG DocType Action Card", form)
        path = (ROOT / "cfg_kanban" / "print_format" /
                "cfg_doctype_action_card" / "cfg_doctype_action_card.json")
        print_format = json.loads(path.read_text())
        self.assertEqual(print_format["doc_type"], "CFG Kanban Card")
        self.assertIn("85.60mm 53.98mm", print_format["css"])
        self.assertIn("doc.qr_code", print_format["html"])


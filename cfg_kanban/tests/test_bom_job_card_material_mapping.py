import importlib.util
import sys
import types
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]


class BOMValidationError(Exception):
    pass


def load_bom_validation():
    frappe = types.ModuleType("frappe")
    frappe._ = lambda value: value

    def throw(message, title=None):
        raise BOMValidationError(f"{title or ''}: {message}")

    frappe.throw = throw
    utils = types.ModuleType("frappe.utils")
    utils.cint = lambda value: int(value or 0)
    utils.cstr = lambda value: "" if value is None else str(value)
    module_name = "cfg_kanban_test_bom_validation"
    spec = importlib.util.spec_from_file_location(
        module_name, APP_ROOT / "integrations" / "bom_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
        spec.loader.exec_module(module)
    return module


class TestBOMJobCardMaterialMapping(TestCase):
    def test_bom_validation_is_registered_on_server_and_desk(self):
        hooks = (APP_ROOT / "hooks.py").read_text()
        self.assertIn('"BOM": "public/js/bom.js"', hooks)
        self.assertIn(
            '"validate": "cfg_kanban.integrations.bom_validation.'
            'validate_job_card_item_operations"',
            hooks,
        )

    def test_server_requires_item_operation_for_job_card_transfer(self):
        validation = (APP_ROOT / "integrations" / "bom_validation.py").read_text()
        self.assertIn('!= "Job Card"', validation)
        self.assertIn('doc.get("items")', validation)
        self.assertIn('row.get("operation")', validation)
        self.assertIn("Set Item Operation on every", validation)
        self.assertIn("this BOM's Operations table", validation)

    def test_desk_marks_and_checks_item_operation(self):
        form = (APP_ROOT / "public" / "js" / "bom.js").read_text()
        self.assertIn('update_docfield_property("operation", "reqd"', form)
        self.assertIn('transfer_material_against !== "Job Card"', form)
        self.assertIn("frm.doc.items", form)
        self.assertIn("Set Item Operation on every", form)

    def test_work_order_transfer_does_not_require_item_operation(self):
        validation = load_bom_validation()
        validation.validate_job_card_item_operations({
            "transfer_material_against": "Work Order",
            "with_operations": 0,
            "operations": [],
            "items": [{"idx": 1, "item_code": "RM-001", "operation": None}],
        })

    def test_job_card_transfer_accepts_complete_mapping(self):
        validation = load_bom_validation()
        validation.validate_job_card_item_operations({
            "transfer_material_against": "Job Card",
            "with_operations": 1,
            "operations": [{"operation": "Cooking"}],
            "items": [{"idx": 1, "item_code": "RM-001", "operation": "Cooking"}],
        })

    def test_job_card_transfer_rejects_missing_item_operation(self):
        validation = load_bom_validation()
        with self.assertRaisesRegex(BOMValidationError, "Row #1: RM-001"):
            validation.validate_job_card_item_operations({
                "transfer_material_against": "Job Card",
                "with_operations": 1,
                "operations": [{"operation": "Cooking"}],
                "items": [{"idx": 1, "item_code": "RM-001", "operation": None}],
            })

    def test_job_card_transfer_rejects_operation_outside_bom_route(self):
        validation = load_bom_validation()
        with self.assertRaisesRegex(BOMValidationError, "Packing"):
            validation.validate_job_card_item_operations({
                "transfer_material_against": "Job Card",
                "with_operations": 1,
                "operations": [{"operation": "Cooking"}],
                "items": [{"idx": 1, "item_code": "RM-001", "operation": "Packing"}],
            })

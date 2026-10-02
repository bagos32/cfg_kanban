from unittest import TestCase

from cfg_kanban.services.field_conditions import (
    ConditionSyntaxError,
    evaluate_visible_condition,
    parse_visible_condition,
)


class TestDynamicFieldVisibleConditions(TestCase):
    def test_check_field_supports_simple_and_frappe_style_conditions(self):
        self.assertTrue(evaluate_visible_condition("damage_found", {"damage_found": 1}))
        self.assertFalse(evaluate_visible_condition("damage_found", {"damage_found": 0}))
        self.assertTrue(evaluate_visible_condition(
            "eval:doc.damage_found == 1", {"damage_found": "1"}
        ))
        self.assertTrue(evaluate_visible_condition(
            "eval:damage_found == Yes", {"damage_found": 1}
        ))

    def test_select_and_negative_conditions_are_supported(self):
        self.assertTrue(evaluate_visible_condition("result == Fail", {"result": "Fail"}))
        self.assertFalse(evaluate_visible_condition("result != Fail", {"result": "Fail"}))
        self.assertTrue(evaluate_visible_condition("result != Fail", {"result": "Pass"}))

    def test_dynamic_prefix_and_single_equals_are_normalized(self):
        self.assertEqual(
            parse_visible_condition("eval:doc.dynamic_damage_found = true"),
            ("damage_found", "==", True),
        )

    def test_arbitrary_javascript_is_rejected(self):
        with self.assertRaises(ConditionSyntaxError):
            parse_visible_condition("eval:window.alert('unsafe')")

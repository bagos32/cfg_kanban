from unittest import TestCase

from cfg_kanban.services.handling_unit_math import (
    apply_balance_delta,
    event_deltas,
    validate_balance,
)
from cfg_kanban.services.physical_identity import (
    format_tag_family_code,
    normalize_physical_code,
    parse_tag_range_code,
    validate_tag_range_definition,
)


class TestHandlingUnitQuantityMath(TestCase):
    def test_preprinted_range_parses_main_and_detachable_children(self):
        registry = {
            "prefix": "FZD-STK",
            "start_number": 1000,
            "end_number": 1999,
            "number_width": 4,
            "child_separator": "-",
            "child_count": 5,
        }
        main = parse_tag_range_code("FZD-STK1000", registry)
        child = parse_tag_range_code("FZD-STK1000-5", registry)
        self.assertEqual(main["tag_role"], "Main")
        self.assertEqual(main["main_code"], "FZD-STK1000")
        self.assertEqual(child["tag_role"], "Child")
        self.assertEqual(child["child_index"], 5)
        self.assertEqual(child["main_code"], "FZD-STK1000")

    def test_preprinted_range_rejects_noncanonical_and_out_of_range_codes(self):
        registry = {
            "prefix": "STK",
            "start_number": 1,
            "end_number": 999,
            "number_width": 4,
            "child_separator": "-",
            "child_count": 5,
        }
        for code in ("STK1", "STK0000", "STK1000", "STK0001-0",
                     "STK0001-6", "STK0001-01", "stk0001"):
            self.assertIsNone(parse_tag_range_code(code, registry), code)

    def test_preprinted_range_validation_limits_registry_size_and_format(self):
        controls = validate_tag_range_definition("STK", 1000, 1999, 4, "-", 5)
        self.assertEqual(controls["child_count"], 5)
        self.assertEqual(format_tag_family_code("STK", 25, 4), "STK0025")
        with self.assertRaises(ValueError):
            validate_tag_range_definition("STK", 0, 100000, 6, "-", 5)
        with self.assertRaises(ValueError):
            validate_tag_range_definition("STK", 1, 10, 2, "1", 5)
        with self.assertRaises(ValueError):
            validate_tag_range_definition("STK", 1, 10, 2, "-", 21)

    def test_preprinted_code_normalization_only_removes_scanner_whitespace(self):
        self.assertEqual(normalize_physical_code("  MFG-STK1000\r\n"), "MFG-STK1000")
        self.assertEqual(normalize_physical_code("mfg-stk1000"), "mfg-stk1000")

    def test_blank_or_embedded_control_code_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_physical_code(" \r\n ")
        with self.assertRaises(ValueError):
            normalize_physical_code("MFG-\tSTK1000")

    def test_split_preserves_total_quantity(self):
        deltas = event_deltas("Split", 5)
        source = apply_balance_delta(10, 0, qty_delta=deltas["source_qty_delta"])
        child = apply_balance_delta(0, 0, qty_delta=deltas["destination_qty_delta"])
        self.assertEqual(float(source[0]), 5)
        self.assertEqual(float(child[0]), 5)
        self.assertEqual(float(source[0] + child[0]), 10)

    def test_merge_returns_child_quantity_without_duplication(self):
        deltas = event_deltas("Merge", 3)
        child = apply_balance_delta(3, 0, qty_delta=deltas["source_qty_delta"])
        parent = apply_balance_delta(7, 0, qty_delta=deltas["destination_qty_delta"])
        self.assertEqual((float(child[0]), float(parent[0])), (0, 10))

    def test_container_load_moves_quantity_without_duplication(self):
        deltas = event_deltas("Load into Container", 2.5)
        source = apply_balance_delta(6, 0, qty_delta=deltas["source_qty_delta"])
        container = apply_balance_delta(1, 0, qty_delta=deltas["destination_qty_delta"])
        self.assertEqual(float(source[0]), 3.5)
        self.assertEqual(float(container[0]), 3.5)

    def test_replacement_moves_balance_without_cloning_it(self):
        deltas = event_deltas("Replace", 10)
        old_tag = apply_balance_delta(10, 0, qty_delta=deltas["source_qty_delta"])
        new_tag = apply_balance_delta(0, 0, qty_delta=deltas["destination_qty_delta"])
        self.assertEqual((float(old_tag[0]), float(new_tag[0])), (0, 10))

    def test_reservation_reduces_available_not_current(self):
        deltas = event_deltas("Reserve", 4)
        current, reserved, available = apply_balance_delta(
            10, 0, reserved_delta=deltas["source_reserved_delta"]
        )
        self.assertEqual(float(current), 10)
        self.assertEqual(float(reserved), 4)
        self.assertEqual(float(available), 6)

    def test_delivery_can_release_reserved_quantity(self):
        deltas = event_deltas("Deliver", 4, release_reserved=True)
        current, reserved, available = apply_balance_delta(
            10,
            4,
            qty_delta=deltas["source_qty_delta"],
            reserved_delta=deltas["source_reserved_delta"],
        )
        self.assertEqual((float(current), float(reserved), float(available)), (6, 0, 6))

    def test_production_consumption_releases_reserved_input(self):
        deltas = event_deltas("Production Consume", 4, release_reserved=True)
        current, reserved, available = apply_balance_delta(
            10,
            4,
            qty_delta=deltas["source_qty_delta"],
            reserved_delta=deltas["source_reserved_delta"],
        )
        self.assertEqual((float(current), float(reserved), float(available)), (6, 0, 6))

    def test_stock_withdrawal_releases_reserved_tag_quantity(self):
        deltas = event_deltas("Stock Withdrawal", 4, release_reserved=True)
        current, reserved, available = apply_balance_delta(
            10,
            4,
            qty_delta=deltas["source_qty_delta"],
            reserved_delta=deltas["source_reserved_delta"],
        )
        self.assertEqual((float(current), float(reserved), float(available)), (6, 0, 6))

    def test_production_reversals_restore_input_and_remove_output(self):
        restored = event_deltas("Production Consume Reversal", 4)
        input_balance = apply_balance_delta(
            6, 0, qty_delta=restored["destination_qty_delta"]
        )
        removed = event_deltas("Production Output Reversal", 4)
        output_balance = apply_balance_delta(
            4, 0, qty_delta=removed["source_qty_delta"]
        )
        self.assertEqual(float(input_balance[0]), 10)
        self.assertEqual(float(output_balance[0]), 0)

    def test_negative_or_over_reserved_balance_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_balance(-1, 0)
        with self.assertRaises(ValueError):
            validate_balance(5, 6)

    def test_unknown_event_is_rejected(self):
        with self.assertRaises(ValueError):
            event_deltas("Invented Event", 1)

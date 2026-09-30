from unittest import TestCase

from cfg_kanban.services.handling_unit_math import (
    apply_balance_delta,
    event_deltas,
    validate_balance,
)


class TestHandlingUnitQuantityMath(TestCase):
    def test_split_preserves_total_quantity(self):
        deltas = event_deltas("Split", 5)
        source = apply_balance_delta(10, 0, qty_delta=deltas["source_qty_delta"])
        child = apply_balance_delta(0, 0, qty_delta=deltas["destination_qty_delta"])
        self.assertEqual(float(source[0]), 5)
        self.assertEqual(float(child[0]), 5)
        self.assertEqual(float(source[0] + child[0]), 10)

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

    def test_negative_or_over_reserved_balance_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_balance(-1, 0)
        with self.assertRaises(ValueError):
            validate_balance(5, 6)

    def test_unknown_event_is_rejected(self):
        with self.assertRaises(ValueError):
            event_deltas("Invented Event", 1)

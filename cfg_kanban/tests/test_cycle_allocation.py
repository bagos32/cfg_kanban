from unittest import TestCase

from cfg_kanban.services.cycle_allocation import calculate_cycle_allocation


class TestCycleAllocation(TestCase):
    def test_two_ten_card_cycles_fulfil_twenty(self):
        first = calculate_cycle_allocation(10, 20, 20)
        second = calculate_cycle_allocation(10, 10, 10)
        self.assertEqual(first.effective_qty + second.effective_qty, 20)
        self.assertIsNone(first.short_reason)
        self.assertIsNone(second.short_reason)

    def test_mixed_twenty_and_ten_cards(self):
        first = calculate_cycle_allocation(20, 30, 30)
        second = calculate_cycle_allocation(10, 10, 10)
        self.assertEqual((first.effective_qty, second.effective_qty), (20, 10))

    def test_final_seven_unit_short_cycle(self):
        plan = calculate_cycle_allocation(10, 7, 30)
        self.assertEqual(plan.effective_qty, 7)
        self.assertEqual(plan.short_reason, "Remaining Demand")

    def test_input_limited_short_cycle(self):
        plan = calculate_cycle_allocation(10, 25, 6)
        self.assertEqual(plan.effective_qty, 6)
        self.assertEqual(plan.short_reason, "Insufficient Input")

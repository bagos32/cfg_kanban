from unittest import TestCase

try:
    from cfg_kanban.services.purchase_replenishment import purchase_request_qty
except ImportError:
    purchase_request_qty = None

from cfg_kanban.services.purchase_uom import calculate_purchase_quantities


class TestPurchaseReplenishmentMath(TestCase):
    def test_minimum_and_multiple_are_applied(self):
        if purchase_request_qty is None:
            self.skipTest("Frappe runtime is unavailable")
        self.assertEqual(purchase_request_qty(7, minimum_order_qty=10, order_multiple=6), 12)
        self.assertEqual(purchase_request_qty(12, pack_size=5), 15)
        self.assertEqual(purchase_request_qty(8), 8)

    def test_purchase_uom_is_derived_from_stock_quantity(self):
        plan = calculate_purchase_quantities(
            500, conversion_factor=25, minimum_purchase_qty=10, purchase_multiple=1
        )
        self.assertEqual(plan["purchase_qty"], 20)
        self.assertEqual(plan["stock_qty"], 500)

    def test_purchase_multiple_rounds_and_recalculates_stock_quantity(self):
        plan = calculate_purchase_quantities(
            510, conversion_factor=25, purchase_multiple=5
        )
        self.assertEqual(plan["purchase_qty"], 25)
        self.assertEqual(plan["stock_qty"], 625)

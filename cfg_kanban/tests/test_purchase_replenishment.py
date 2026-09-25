from unittest import TestCase

try:
    from cfg_kanban.services.purchase_replenishment import purchase_request_qty
except ImportError:
    purchase_request_qty = None


class TestPurchaseReplenishmentMath(TestCase):
    def test_minimum_and_multiple_are_applied(self):
        if purchase_request_qty is None:
            self.skipTest("Frappe runtime is unavailable")
        self.assertEqual(purchase_request_qty(7, minimum_order_qty=10, order_multiple=6), 12)
        self.assertEqual(purchase_request_qty(12, pack_size=5), 15)
        self.assertEqual(purchase_request_qty(8), 8)

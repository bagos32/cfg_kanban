from unittest import TestCase

from cfg_kanban.services.demand_math import calculate_recommendation


class TestDemandRecommendation(TestCase):
    def test_deducts_projected_and_open_kanban_then_rounds_up(self):
        shortage, cards, qty, capped = calculate_recommendation(900, 250, 400, 400)
        self.assertEqual((shortage, cards, qty, capped), (250, 1, 400, False))

    def test_respects_minimum_shortage(self):
        self.assertEqual(calculate_recommendation(100, 75, 0, 400, 50)[1], 0)

    def test_caps_excessive_card_proposal(self):
        shortage, cards, qty, capped = calculate_recommendation(5000, 0, 0, 400, 0, 5)
        self.assertEqual((shortage, cards, qty, capped), (5000, 5, 2000, True))

    def test_sales_outstanding_is_not_double_counted(self):
        self.assertEqual(calculate_recommendation(100, 40, 20, 25)[:3], (40, 2, 50))

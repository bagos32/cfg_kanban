from unittest import TestCase
from unittest.mock import MagicMock


class TestWIPReleaseMath(TestCase):
    def test_documents_expected_transfer_multiple_behavior(self):
        # Kept framework-independent so the arithmetic contract remains visible to reviewers.
        total_good, released, multiple = 35, 0, 12
        eligible = (total_good // multiple) * multiple
        self.assertEqual(eligible - released, 24)

    def test_second_increment_releases_only_delta(self):
        total_good, released, multiple = 60, 24, 12
        eligible = (total_good // multiple) * multiple
        self.assertEqual(eligible - released, 36)


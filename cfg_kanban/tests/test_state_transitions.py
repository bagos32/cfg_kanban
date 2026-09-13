import ast
from pathlib import Path
from unittest import TestCase


class TestCardTransitionContract(TestCase):
    def test_signal_to_release_uses_required_intermediate_state(self):
        app_package = Path(__file__).resolve().parents[1]
        source = (app_package / "services" / "triggers.py").read_text()
        tree = ast.parse(source)
        requested = any(
            isinstance(node, ast.Constant) and node.value == "Replenishment Requested"
            for node in ast.walk(tree)
        )
        self.assertTrue(requested)

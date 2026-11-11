from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
HOOKS = APP_ROOT / "hooks.py"
NAVIGATION_JS = APP_ROOT / "public" / "js" / "cfg_kanban_navigation.js"


class TestNavigationBreadcrumbContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hooks = HOOKS.read_text()
        cls.navigation = NAVIGATION_JS.read_text()

    def test_navigation_controller_is_loaded_for_desk(self):
        self.assertIn(
            'app_include_js = "/assets/cfg_kanban/js/cfg_kanban_navigation.js"',
            self.hooks,
        )

    def test_cfg_routes_use_the_canonical_workspace(self):
        self.assertIn('label: "CFG Kanban"', self.navigation)
        self.assertIn('route: "cfg-kanban"', self.navigation)
        self.assertIn('target.startsWith("cfg kanban ")', self.navigation)
        self.assertIn('target.startsWith("cfg process certificate")', self.navigation)
        self.assertIn('"kanban-logistics"', self.navigation)
        self.assertIn('"kanban-operator"', self.navigation)

    def test_child_workspace_names_are_replaced_not_preserved(self):
        self.assertIn('"CFG Dispatch Control"', self.navigation)
        self.assertIn('"CFG Job Architecture"', self.navigation)
        self.assertIn('"/app/cfg-dispatch-control"', self.navigation)
        self.assertIn('first_link.setAttribute("href", href)', self.navigation)
        self.assertIn("first_link.textContent = label", self.navigation)

    def test_late_frappe_breadcrumb_updates_are_reconciled(self):
        self.assertIn("new MutationObserver(schedule_breadcrumb_update)", self.navigation)
        self.assertIn('frappe.router.on("change"', self.navigation)
        self.assertIn('document.querySelector(".navbar-breadcrumbs")', self.navigation)

    def test_native_erpnext_documents_are_not_claimed(self):
        self.assertNotIn('target.startsWith("work order")', self.navigation)
        self.assertNotIn('target.startsWith("job card")', self.navigation)
        self.assertNotIn('target.startsWith("stock entry")', self.navigation)


if __name__ == "__main__":
    unittest.main()

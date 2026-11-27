"""Open Route cancellation response/reload with offline documents, never a live site."""
import copy
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_trip_dispatch as fixture
from cfg_kanban.tests.test_vehicle_overview import load

PLAN = 'CFG Kanban Dispatch Plan'
ALLOCATION = 'CFG Kanban Dispatch Allocation'
STOP = 'CFG Kanban Route Stop'


class TestOpenRoutePlanCancellation(unittest.TestCase):
    def setUp(self):
        self.b = fixture.TestTripDispatch()
        self.b.setUp()
        self.addCleanup(self.b.doCleanups)
        self.data = self.b.data
        self.service = self.b.planning
        self.trip = self.b.trip
        self.trip.orders = []
        self.trip.stops = [self.trip.stops[1]]
        self.data['CFG Kanban Customer Scan Point']['SITE2'].site_name = 'Sin Yong'
        self.b.open.tag_policy = 'Untagged'
        self.b.b.add('Item', 'WR1,5KG', item_name='WR1,5KG', disabled=0,
                     is_stock_item=1, stock_uom='Nos')
        self.trip.route_stock = [fixture.base.Doc(item_code='WR1,5KG', stock_uom='Nos', qty=10)]
        self.b.generate()
        self.plan = self.data[PLAN][self.trip.open_route_plan]
        # Frappe treats a zero page length as unlimited, including plucked names.
        self.b.b.frappe.get_all = lambda dt, **kw: self.b.b.get_list(
            dt, **{key: value for key, value in kw.items() if key != 'limit_page_length' or value})
        self.data['CFG Kanban Dispatch Plan Line'] = {row.name: row for row in self.plan.lines}
        self.plan.update(actual_stop_count=0, completed_stop_count=0, total_reserved_qty=0)
        self.service = types.ModuleType('cfg_kanban.services.dispatch_planning')
        self.service.__dict__.update(self.b.planning.__dict__)
        load('services/dispatch_planning.py', self.service.__dict__)
        self.stop = next(iter(self.data[STOP].values()))
        self.stop.update(state='Skipped', skip_reason='Test customer visit skipped',
                         skipped_by='TEST-SUPERVISOR', skipped_on='2026-11-27 10:00:00')
        self.released = self.b.b.add(ALLOCATION, 'TEST-RELEASED', dispatch_plan=self.plan.name,
            dispatch_plan_line=self.plan.lines[0].name, state='Released',
            allocation_kind='Untagged ERP Stock', visible_code='ERP STOCK',
            item_code='WR1,5KG', stock_uom='Nos', allocated_qty=10,
            source_company=self.plan.company, source_warehouse=self.plan.source_warehouse,
            released_by_operator='TEST-OPERATOR', released_on='2026-11-27 09:00:00',
            release_reason='Test stock was not needed', release_key='TEST-ORIGINAL-RELEASE')
        self.operator = fixture.base.Doc(employee='TEST-SUPERVISOR', kanban_role='Supervisor',
            responsibilities=[fixture.base.Doc(responsibility='Dispatch')],
            view_all_responsibilities=0, can_override=1, can_start=1)
        self.session = fixture.base.Doc(name='TEST-SESSION', terminal_user='test@example.invalid')
        self.service.require_operator = Mock(return_value=(self.operator, self.session))
        self.b.b.frappe.PermissionError = PermissionError
        def throw(message, kind=ValueError):
            raise kind(message)
        self.b.b.frappe.throw = throw
        engine = types.ModuleType('cfg_kanban.services.customer_delivery')
        load('services/customer_delivery.py', engine.__dict__)
        p = patch.dict(sys.modules, {engine.__name__: engine, self.service.__name__: self.service})
        p.start()
        self.addCleanup(p.stop)
        self.b.routes._engine = lambda: engine
        self.context = Mock(wraps=self.b.routes.plan_context)
        self.b.routes.plan_context = self.context
        self.release = Mock(wraps=self.service._release_allocation)
        self.service._release_allocation = self.release
        self.b.events.reset_mock()
        self.original_release = copy.deepcopy(self.released.as_dict())
        self.original_stop = copy.deepcopy(self.stop.as_dict())
        self.created_before = len(self.b.created)

    def cancel(self, token='TEST-CANCEL', reason='Test unused shared pool cancelled'):
        return self.service.cancel_dispatch_plan(self.plan.name, reason, token, 'TEST-SESSION')

    def assert_no_stock_work(self):
        for doctype in ('CFG Kanban Movement Manifest', 'Stock Entry', 'Delivery Note',
                        'Stock Ledger Entry', 'CFG Kanban Handling Unit Quantity Ledger',
                        'CFG Kanban Delivery Session', 'CFG Kanban ERP Command'):
            self.assertFalse(self.data.get(doctype), doctype)
        self.b.ledger.assert_not_called()
        self.assertEqual(len(self.b.created), self.created_before)

    def assert_history_preserved(self):
        self.assertEqual(self.released.as_dict(), self.original_release)
        self.assertEqual(self.stop.as_dict(), self.original_stop)
        self.assertEqual(self.plan.lines[0].requested_qty, 10)

    def test_reported_approved_shared_pool_cancels_and_reloads_without_active_panel(self):
        self.assertEqual(self.plan.state, 'Approved')
        self.assertEqual(self.plan.plan_type, 'Open Route Stock')
        self.assertEqual(self.plan.fulfilment_mode, 'Vehicle Delivery')
        self.assertEqual(self.plan.office_delivery_trip, self.trip.name)
        self.assertEqual(self.trip.open_route_plan, self.plan.name)
        self.assertEqual(self.plan.actual_stop_count, 0)
        self.assertEqual(self.plan.completed_stop_count, 0)
        self.assertEqual(self.plan.lines[0].reserved_qty, 0)
        before = self.service.get_dispatch_plan(self.plan.name, 'TEST-SESSION')
        self.assertEqual(before['route_delivery']['stops'][0].state, 'Skipped')
        self.context.reset_mock()

        response = self.cancel()
        self.assertEqual(response['state'], 'Cancelled')
        self.assertNotIn('route_delivery', response)
        self.assertEqual(response['allocations'][0].state, 'Released')
        for action in ('can_cancel', 'can_submit', 'can_approve', 'can_reserve',
                       'can_claim_vehicle', 'can_start_route_delivery', 'can_review_dispatch'):
            self.assertFalse(response[action], action)
        self.assertEqual(self.data[PLAN][self.plan.name].state, 'Cancelled')
        reloaded = self.service.get_dispatch_plan(self.plan.name, 'TEST-SESSION')
        self.assertEqual(reloaded['state'], 'Cancelled')
        self.assertNotIn('route_delivery', reloaded)
        self.context.assert_not_called()
        self.release.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()
        self.assertEqual([call.args[0] for call in self.b.events.call_args_list], ['Dispatch Plan Cancelled'])
        self.assertEqual(self.plan.cancelled_by_operator, self.operator.employee)
        self.assertEqual(self.plan.cancellation_reason, 'Test unused shared pool cancelled')

    def test_same_action_retry_and_reopen_do_not_repeat_audit_or_release(self):
        first = self.cancel()
        stamp = self.plan.cancelled_on
        self.cancel()
        self.cancel('TEST-REOPEN')
        self.assertEqual(first['state'], 'Cancelled')
        self.assertEqual(self.plan.cancelled_on, stamp)
        self.assertEqual(self.b.events.call_count, 1)
        self.release.assert_not_called()
        self.context.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()

    def test_override_is_still_required_for_approved_pool(self):
        self.operator.can_override = 0
        with self.assertRaisesRegex(ValueError, 'Supervisor Override'):
            self.cancel()
        self.assertEqual(self.plan.state, 'Approved')
        self.b.events.assert_not_called()
        self.release.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()

    def test_unassigned_responsibility_cannot_cancel_or_reload(self):
        self.operator.responsibilities = []
        with self.assertRaisesRegex(PermissionError, 'responsibility'):
            self.cancel()
        with self.assertRaisesRegex(PermissionError, 'responsibility'):
            self.service.get_dispatch_plan(self.plan.name, 'TEST-SESSION')
        self.assertEqual(self.plan.state, 'Approved')
        self.b.events.assert_not_called()
        self.assert_no_stock_work()

    def test_reason_and_event_token_are_still_required(self):
        for reason in ('', '   '):
            with self.assertRaisesRegex(ValueError, 'reason'):
                self.cancel(reason=reason)
        with self.assertRaisesRegex(ValueError, '(?i)event token'):
            self.cancel(token='')
        self.assertEqual(self.plan.state, 'Approved')
        self.b.events.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()

    def test_released_history_does_not_prevent_releasing_a_different_active_reservation(self):
        active = self.b.b.add(ALLOCATION, 'TEST-ACTIVE', dispatch_plan=self.plan.name,
            dispatch_plan_line=self.plan.lines[0].name, state='Reserved',
            allocation_kind='Untagged ERP Stock', item_code='WR1,5KG', stock_uom='Nos',
            allocated_qty=2, source_company=self.plan.company, source_warehouse=self.plan.source_warehouse)
        self.plan.total_reserved_qty = self.plan.lines[0].reserved_qty = 2
        self.cancel()
        self.assertEqual(active.state, 'Cancelled')
        self.assertEqual(self.plan.total_reserved_qty, 0)
        self.release.assert_called_once()
        self.assertEqual([call.args[0] for call in self.b.events.call_args_list],
                         ['Dispatch Stock Reservation Released', 'Dispatch Plan Cancelled'])
        self.cancel()
        self.assertEqual(self.release.call_count, 1)
        self.assertEqual(self.b.events.call_count, 2)
        self.assert_history_preserved()
        self.assert_no_stock_work()

    def test_direct_delivery_readiness_guard_still_rejects_unloaded_and_cancelled(self):
        for state in ('Approved', 'Cancelled'):
            self.plan.state = state
            with self.assertRaisesRegex(ValueError, 'requires a Loaded Plan'):
                self.b.routes._assert_route_plan(self.plan)
        with self.assertRaisesRegex(ValueError, 'requires a Loaded Plan'):
            self.context(self.plan, self.operator)
        self.assert_no_stock_work()

    def test_loaded_plan_still_requires_existing_recovery_instead_of_e2_cancellation(self):
        self.plan.state = 'Loaded'
        with self.assertRaisesRegex(ValueError, 'cannot be cancelled from Loaded'):
            self.cancel()
        self.assertEqual(self.plan.state, 'Loaded')
        self.b.events.assert_not_called()
        self.release.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()

    def test_draft_cancellation_still_requires_start_permission(self):
        self.plan.state = 'Draft'
        self.operator.can_start = 0
        with self.assertRaisesRegex(ValueError, 'Start permission'):
            self.cancel()
        self.assertEqual(self.plan.state, 'Draft')
        self.b.events.assert_not_called()
        self.assert_history_preserved()
        self.assert_no_stock_work()


if __name__ == '__main__':
    unittest.main()

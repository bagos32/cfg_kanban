"""Actual dispatch order-preview/validation functions with offline document doubles."""
import ast
import json
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__

class TestDispatchOrderQuantities(unittest.TestCase):
    def setUp(self):
        self.policy = Row(name='PROFILE', active=1, plan_type='Customer Order', company='B',
                          dispatch_point='CARD-B', source_warehouse='WH-B', dispatch_responsibility='Dispatch',
                          customer_site=None, logistics_route=None, territory=None)
        self.operator = Row(kanban_role='Operator', responsibilities=[Row(responsibility='Dispatch')])
        self.order = types.SimpleNamespace(items=[Row(name='SO-ROW', item_code='ITEM', qty=5,
                                        delivered_qty=2, conversion_factor=12)])
        self.order_header = Row(docstatus=1, company='B', customer='CUSTOMER', status='To Deliver and Bill')
        self.site = Row(active=1, selling_company='B', customer='CUSTOMER', customer_address='ADDR', territory=None)
        self.item = Row(item_name='Item', stock_uom='Nos', disabled=0)
        self.card = Row(active=1, blocked=0, card_type='Location Card', location_purpose='Dispatch Operations',
                        company='B', current_warehouse='WH-B')
        self.frappe = Row(parse_json=json.loads, get_doc=Mock(side_effect=self.get_doc),
                          db=Row(get_value=Mock(side_effect=self.get_value)),
                          throw=lambda msg,*args: (_ for _ in ()).throw(ValueError(msg)))
        self.ns = dict(frappe=self.frappe, flt=lambda n:float(n or 0), today=lambda:'2026-11-19',
                       require_operator=Mock(return_value=(self.operator, Row(name='SESSION'))),
                       _validate_batch=Mock())
        names={'get_dispatch_sales_order_lines', '_normalize_lines', '_sales_order_item_map',
               '_business_context', '_authorized_profile', '_validate_profile_card', '_responsibilities', '_view_all'}
        nodes=[]
        for node in ast.parse((ROOT/'services/dispatch_planning.py').read_text()).body:
            if isinstance(node,ast.FunctionDef) and node.name in names:
                node.decorator_list=[]; nodes.append(node)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'dispatch_planning.py','exec'),self.ns)

    def get_doc(self, doctype, name):
        if doctype=='Sales Order': return self.order
        if doctype=='CFG Kanban Dispatch Profile': return self.policy
        raise AssertionError(doctype)

    def get_value(self, doctype, name, fields, **kwargs):
        if doctype=='Item':
            if fields=='is_stock_item': return name!='SERVICE'
            return self.item
        if doctype=='Sales Order': return self.order_header
        if doctype=='CFG Kanban Customer Scan Point': return self.site
        if doctype=='CFG Kanban Card': return self.card
        raise AssertionError(doctype)

    def preview(self):
        return self.ns['get_dispatch_sales_order_lines']('PROFILE','SO','SITE','TOKEN')

    def normalize(self, rows):
        return self.ns['_normalize_lines'](rows,'SO')

    def test_preview_loads_remaining_in_stock_uom_without_writes(self):
        result=self.preview()
        self.assertEqual(result['lines'][0]['requested_qty'],36)
        self.assertEqual(result['lines'][0]['stock_uom'],'Nos')
        self.assertEqual(result['lines'][0]['sales_order_item'],'SO-ROW')
        self.ns['require_operator'].assert_called_once_with('TOKEN','start')
        self.assertEqual(set(self.frappe.db),{'get_value'})

    def test_repeated_order_item_rows_aggregate_only_undelivered(self):
        self.order.items += [Row(name='DONE',item_code='ITEM',qty=3,delivered_qty=3,conversion_factor=12),
                            Row(name='SECOND',item_code='ITEM',qty=2,delivered_qty=1,conversion_factor=6)]
        self.assertEqual(self.preview()['lines'][0]['requested_qty'],42)

    def test_fully_delivered_and_non_stock_lines_are_omitted(self):
        self.order.items += [Row(name='DONE',item_code='OTHER',qty=2,delivered_qty=2,conversion_factor=1),
                            Row(name='SERVICE',item_code='SERVICE',qty=2,delivered_qty=0,conversion_factor=1)]
        self.assertEqual([r['item_code'] for r in self.preview()['lines']],['ITEM'])

    def test_no_remaining_stock_is_explicitly_rejected(self):
        self.order.items[0].delivered_qty=5
        with self.assertRaisesRegex(ValueError,'no remaining stock'): self.preview()

    def test_nonpositive_conversion_is_rejected(self):
        for factor in (0,-1,None):
            self.order.items[0].conversion_factor=factor
            with self.assertRaisesRegex(ValueError,'conversion factor'): self.preview()

    def test_partial_dispatch_can_use_stock_quantity(self):
        self.assertEqual(self.normalize([{'item_code':'ITEM','requested_qty':24}])[0]['requested_qty'],24)

    def test_excess_stock_qty_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'exceeds Sales Order'):
            self.normalize([{'item_code':'ITEM','requested_qty':37}])

    def test_batch_rows_share_the_order_limit(self):
        rows=[{'item_code':'ITEM','batch_no':'A','requested_qty':20},
              {'item_code':'ITEM','batch_no':'B','requested_qty':20}]
        with self.assertRaisesRegex(ValueError,'total requested 40'): self.normalize(rows)
        rows[1]['requested_qty']=16
        self.assertEqual(len(self.normalize(rows)),2)

    def test_blank_qty_and_item_not_in_order_remain_rejected(self):
        with self.assertRaisesRegex(ValueError,'positive Requested Qty'):
            self.normalize([{'item_code':'ITEM','requested_qty':0}])
        with self.assertRaisesRegex(ValueError,'not in Sales Order'):
            self.normalize([{'item_code':'OTHER','requested_qty':1}])

    def test_preview_rechecks_responsibility(self):
        self.operator.responsibilities=[]
        with self.assertRaisesRegex(ValueError,'responsibility'): self.preview()
        self.assertFalse(any(c.args[0]=='Sales Order' for c in self.frappe.get_doc.call_args_list))

    def test_preview_rejects_other_company_and_customer(self):
        for field,value in [('company','A'),('customer','OTHER'),('docstatus',0)]:
            before=self.order_header[field];self.order_header[field]=value
            with self.assertRaisesRegex(ValueError,'same Company and Customer Site'): self.preview()
            self.order_header[field]=before

    def test_closed_or_held_orders_are_rejected(self):
        for status in ('Closed','On Hold','Cancelled'):
            self.order_header.status=status
            with self.assertRaisesRegex(ValueError,'open and submitted'): self.preview()

    def test_open_route_cannot_fetch_order_lines(self):
        self.policy.plan_type='Open Route Stock'
        with self.assertRaisesRegex(ValueError,'Customer Order Dispatch Profile'): self.preview()

    def test_exact_dispatch_point_alignment_is_required(self):
        self.card.current_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'no longer matches'): self.preview()

    def test_manual_plan_still_uses_entered_quantity(self):
        rows=self.ns['_normalize_lines']([{'item_code':'ITEM','requested_qty':9}],None)
        self.assertEqual(rows[0]['requested_qty'],9)
        self.assertIsNone(rows[0]['sales_order_item'])

if __name__=='__main__': unittest.main()

"""Exercise actual batched API context assembly, also used by the scanner regression."""
import ast
import unittest
from pathlib import Path
from cfg_kanban.tests.test_material_actuals_yield import Row

ROOT=Path(__file__).resolve().parents[1]


def card_run_context(mode):
    source=ROOT/'api/operator.py'
    tree=ast.parse(source.read_text())
    assignment=next(node for node in ast.walk(tree) if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name)
                and target.value.id=='execution' and isinstance(target.slice,ast.Constant)
                and target.slice.value=='material_run_context' for target in node.targets))
    execution=Row(name='EXEC-0',operation='Packing',workstation='PACK',job_card='JC',status='Ready',
        material_run_control='Required Before Progress',allow_material_carry_forward=1,
        material_run_settlement_timing='At Work Order Manufacture Receipt',material_run=None,
        material_run_hopper_mode=mode,material_run_hopper_warehouse='Production')
    namespace={'master':Row(item_code='PRODUCT'),'execution':execution,'boundary_mode':'None','prior_run_count':0,
        '_material_rule_context':lambda row:[{'rule_row':'BAG','item_code':'BAG','stock_uom':'Nos','qty_per_output':1}],
        '_work_order_yield_context':lambda row:None,
        'frappe':Row(db=Row(get_value=lambda *args:'WO'))}
    return eval(compile(ast.Expression(assignment.value),str(source),'eval'),namespace)


class TestCardMaterialRunContext(unittest.TestCase):
    def test_batched_api_includes_each_released_hopper_mode_and_location(self):
        for mode in ('Fill Hopper','Consume Hopper','None'):
            with self.subTest(mode=mode):
                context=card_run_context(mode)
                self.assertEqual(context['hopper_mode'],mode)
                self.assertEqual(context['hopper_warehouse'],'Production')
                self.assertEqual(context['output_item_code'],'PRODUCT')
    def test_legacy_empty_mode_defaults_to_no_hopper(self):
        self.assertEqual(card_run_context(None)['hopper_mode'],'None')

"""Offline genealogy sort regressions; no live database/site acceptance."""
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import Mock

from cfg_kanban.tests.test_material_actuals_yield import functions


def get_datetime(value):
    """Frappe datetime conversion double for valid stored Date/Datetime values."""
    if isinstance(value, datetime):return value
    if isinstance(value, date):return datetime.combine(value, datetime.min.time())
    return datetime.fromisoformat(value)


class TestGenealogyDateSorting(TestCase):
    def setUp(self):
        self.summaries={name:{'name':name,'visible_code':name,'packed_on':None}
                        for name in ('ROOT','PARENT','CHILD','A','B','C','D')}
        self.edges=[]
        self.levels={'ROOT':0,'PARENT':-1,'CHILD':1,'A':-1,'B':-1,'C':1,'D':1}
        self.ns=functions('services/genealogy.py',[
            'get_handling_unit_genealogy','get_genealogy_print_context','_serialise_edges','_date_sort_key'],{
                'get_datetime':get_datetime,'cint':lambda value:int(value or 0),
                '_require_read_access':Mock(),'_resolve_root':lambda *args:({'visible_code':'RM00005'},'ROOT'),
                '_walk_graph':lambda *args:(set(self.summaries),self.edges,self.levels,False),
                '_unit_summaries':lambda names:{key:dict(value) for key,value in self.summaries.items()},
                '_timeline':lambda *args:[], '_manifest_history':lambda *args:[],
                '_delivery_allocation_history':lambda *args:[], '_container_history':lambda *args:[],
                '_serial_history':lambda *args:[],
            })

    def edge(self,reference,**values):
        return {'source':'ROOT','target':'CHILD','reference_name':reference,**values}

    def test_ledger_datetime_and_undated_child_edges_sort_without_error(self):
        timestamp=datetime(2026,11,12,10,30)
        self.edges=[self.edge('LEDGER',posting_datetime=timestamp),self.edge('CHILD',relation_type='Detachable Child Tag')]
        result=self.ns['_serialise_edges'](self.edges,self.summaries)
        self.assertEqual([row['reference_name'] for row in result],['CHILD','LEDGER'])
        self.assertIs(result[1]['posting_datetime'],timestamp)
        self.assertNotIn('posting_datetime',result[0])
        self.assertNotIn('source_code',self.edges[0])

    def test_mixed_iso_text_native_datetime_and_date_are_chronological(self):
        self.edges=[self.edge('LATE',posting_datetime=datetime(2026,11,12,10)),
                    self.edge('EARLY',posting_datetime='2026-11-12T09:00:00'),
                    self.edge('DAY',posting_datetime=date(2026,11,12)),
                    self.edge('MISSING',posting_datetime=None)]
        result=self.ns['_serialise_edges'](self.edges,self.summaries)
        self.assertEqual([row['reference_name'] for row in result],['MISSING','DAY','EARLY','LATE'])
        self.assertEqual(result[2]['posting_datetime'],'2026-11-12T09:00:00')

    def test_same_timestamp_preserves_reference_and_visible_code_tie_breaks(self):
        self.edges=[self.edge('B',posting_datetime=datetime(2026,11,12,9)),
                    self.edge('A',posting_datetime='2026-11-12 09:00:00')]
        result=self.ns['_serialise_edges'](self.edges,self.summaries)
        self.assertEqual([row['reference_name'] for row in result],['A','B'])

    def test_relationships_with_invisible_nodes_are_still_excluded(self):
        self.edges=[self.edge('PRIVATE',target='HIDDEN',posting_datetime=datetime(2026,11,12))]
        self.assertEqual(self.ns['_serialise_edges'](self.edges,self.summaries),[])

    def test_endpoint_sorts_both_lineage_lists_with_missing_and_native_packed_dates(self):
        self.summaries['A']['packed_on']=datetime(2026,11,12,10)
        self.summaries['B']['packed_on']='2026-11-12T09:00:00'
        self.summaries['C']['packed_on']=datetime(2026,11,12,10)
        self.summaries['D']['packed_on']='2026-11-12T09:00:00'
        result=self.ns['get_handling_unit_genealogy'](scan_value='RM00005')
        self.assertEqual([row['name'] for row in result['upstream']],['PARENT','B','A'])
        self.assertEqual([row['name'] for row in result['downstream']],['CHILD','D','C'])
        self.ns['_require_read_access'].assert_called_once()

    def test_depth_remains_primary_over_packed_date(self):
        self.levels['A']=-2;self.summaries['A']['packed_on']=None
        self.levels['C']=2;self.summaries['C']['packed_on']=None
        self.summaries['PARENT']['packed_on']=datetime(2026,11,12)
        self.summaries['CHILD']['packed_on']=datetime(2026,11,12)
        result=self.ns['get_handling_unit_genealogy'](scan_value='RM00005')
        self.assertEqual(result['upstream'][-1]['name'],'A')
        self.assertEqual(result['downstream'][-1]['name'],'C')

    def test_print_context_uses_same_mixed_relationship_sort(self):
        self.edges=[self.edge('LEDGER',posting_datetime=datetime(2026,11,12)),self.edge('FAMILY')]
        result=self.ns['get_genealogy_print_context']('ROOT')
        self.assertTrue(result['activated'])
        self.assertEqual([row['reference_name'] for row in result['relationships']],['FAMILY','LEDGER'])

"""Real monitor functions over a permission-aware SQLite/dictionary Frappe double.

This does not establish native Frappe permissions, MariaDB isolation or site acceptance.
"""
import ast, copy, datetime, json, math, sqlite3, types, unittest
from pathlib import Path
from unittest.mock import Mock
from cfg_kanban.tests.test_direct_customer_returns import Doc

ROOT=Path(__file__).resolve().parents[1]
CASE='CFG Kanban Return Case'
NOW=datetime.datetime(2026,11,23,12)


def load(path, ns):
    tree=ast.parse((ROOT/path).read_text());body=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef,ast.Assign)):
            if isinstance(node,ast.FunctionDef):node.decorator_list=[]
            body.append(node)
    exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),ns)
    return ns


class TestReturnQCMonitor(unittest.TestCase):
    def setUp(self):
        self.data={};self.queries=[];self.reads=[];self.authorized={'A'};self.denied=set();self.can_read=True
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_return_case/cfg_kanban_return_case.json').read_text())
        self.states=next(r['options'] for r in schema['fields'] if r['fieldname']=='state')
        names=['name','creation','modified']+[r['fieldname'] for r in schema['fields'] if r['fieldtype'] not in ('Section Break','Column Break','Tab Break','Table')]
        self.db.execute('CREATE TABLE cases ('+','.join('"'+name+'" TEXT' for name in names)+')')
        self.names=names;self.profile=Doc(employee='QC1',can_start=1,can_complete=1,kanban_role='Operator',responsibilities=[Doc(responsibility='Customer Return QC')])
        self.session=Doc(name='SESSION',station='QC',employee='QC1');self.auth=Mock(return_value=(self.profile,self.session))
        self.f=Doc(get_list=self.get_list,get_doc=self.get_doc,parse_json=json.loads,throw=self.throw,
            PermissionError=PermissionError,DoesNotExistError=KeyError,has_permission=lambda *a,**kw:self.can_read,
            get_meta=lambda dt:Doc(get_field=lambda field:Doc(options=self.states)))
        self.returns=types.SimpleNamespace(**load('services/customer_returns.py',dict(frappe=self.f,_=lambda v:v,cint=lambda v:int(v or 0))))
        self.ns=load('services/return_qc_monitor.py',dict(frappe=self.f,flt=lambda v:float(v or 0),cint=lambda v:int(v or 0),
            get_datetime=lambda v:v if isinstance(v,datetime.datetime) else datetime.datetime.fromisoformat(str(v)),
            getdate=lambda v:datetime.date.fromisoformat(str(v)[:10]),now_datetime=lambda:NOW,timedelta=datetime.timedelta,isfinite=math.isfinite,
            require_operator=self.auth,public_operator=lambda p,s:dict(employee=p.employee,kanban_role=p.kanban_role)))
        self.ns['_returns']=lambda:self.returns
        self.add('Company','A');self.add('Company','B')
        self.case('OLD',claimed_on='2026-11-01 08:00:00',modified='2026-11-01 08:00:00',created_by_operator='OTHER')
        self.case('FOREIGN',selling_company='B');self.case('HIDDEN');self.denied.add('HIDDEN')
    def add(self,dt,name,**values):
        doc=Doc(doctype=dt,name=name,**values);self.data.setdefault(dt,{})[name]=doc;return doc
    def case(self,name,**values):
        row=dict(state='Awaiting QC Receipt',return_flow='Customer Return for QC',intake_method='Direct Customer',selling_company='A',customer='CUSTOMER',
            inspection_location='QC BAY',claimed_on='2026-11-23 08:00:00',creation='2026-11-23 08:00:00',modified='2026-11-23 08:00:00',
            accepted_total_qty=0,accounting_status='Pending Source Selection',disposition_status='Not Started',stock_already_owned=0,
            lines=[Doc(name=name+'-L1',idx=1,item_code='ITEM',stock_uom='Nos',claimed_qty=3,received_qty=0,accepted_qty=0,rejected_qty=0,qc_disposition='Pending')]);row.update(values)
        doc=self.add(CASE,name,**row);self.save_sql(doc);return doc
    def save_sql(self,doc):
        self.db.execute('DELETE FROM cases WHERE name=?',(doc.name,))
        columns=[key for key in self.names if doc.get(key) is not None]
        self.db.execute('INSERT INTO cases ('+','.join('"'+k+'"' for k in columns)+') VALUES ('+','.join('?' for _ in columns)+')',[str(doc[k]) for k in columns])
    def get_doc(self,dt,name,**kw):
        self.reads.append((dt,name));doc=self.data[dt][name]
        if dt==CASE and name in self.denied:raise PermissionError('Case denied')
        return doc
    def throw(self,message,kind=ValueError):raise kind(message)
    def term(self,term,params):
        key,op,value=term;assert key in self.names
        if op in ('in','not in'):
            if not value:return '1' if op=='not in' else '0'
            params.extend(value);return '"'+key+'" '+op+' ('+','.join('?' for _ in value)+')'
        assert op in ('=','>=','<','like');params.append(value)
        return '"'+key+'" '+op+' ?'+(" ESCAPE '\\'" if op=='like' else '')
    def get_list(self,dt,filters=None,or_filters=None,fields=None,pluck=None,limit_start=0,limit_page_length=20,order_by=None,group_by=None,**kw):
        assert 'ignore_permissions' not in kw
        self.queries.append(dict(dt=dt,filters=copy.deepcopy(filters),or_filters=or_filters,fields=fields,group_by=group_by,start=limit_start,length=limit_page_length))
        if dt=='Company':return sorted(self.authorized)
        assert dt==CASE
        params=[];terms=[self.term(['selling_company','in',sorted(self.authorized)],params)]
        if self.denied:terms.append(self.term(['name','not in',sorted(self.denied)],params))
        for term in ([[k,*v] if isinstance(v,list) else [k,'=',v] for k,v in filters.items()] if isinstance(filters,dict) else filters or []):terms.append(self.term(term,params))
        if or_filters:terms.append('('+' OR '.join(self.term(t,params) for t in or_filters)+')')
        columns=', '.join(fields or [pluck or 'name']);query='SELECT '+columns+' FROM cases WHERE '+(' AND '.join(terms) if terms else '1')
        if group_by:query+=' GROUP BY '+group_by
        if order_by:query+=' ORDER BY '+order_by
        if limit_page_length:query+=' LIMIT '+str(limit_page_length)+' OFFSET '+str(limit_start)
        result=[Doc(dict(r)) for r in self.db.execute(query,params)]
        return [r[pluck] for r in result] if pluck else result
    def list(self,**kw):return self.ns['get_qc_worklist']('TOKEN',**kw)
    def detail(self,name='OLD',**kw):return self.ns['get_qc_case'](name,'TOKEN',**kw)
    def complete(self,case,accepted=2):
        case.update(state='QC Completed - Accounting Pending',qc_completed_on='2026-11-23 10:00:00',accepted_total_qty=accepted)
        case.lines[0].update(received_qty=3,accepted_qty=accepted,rejected_qty=3-accepted,qc_disposition='Accept for Credit')
        self.save_sql(case)
    def test_oldest_pending_is_first_and_every_page_is_reachable_beyond_thirty(self):
        for n in range(45):self.case('NEW-%02d'%n)
        names=[]
        for start in range(0,50,10):
            data=self.list(start=start);names.extend(r['name'] for r in data['rows']);self.assertEqual(data['total'],46)
        self.assertEqual(names[0],'OLD');self.assertEqual(len(set(names)),46);self.assertNotIn('FOREIGN',names);self.assertNotIn('HIDDEN',names)
        self.assertFalse(self.list(start=40)['has_more']);self.assertEqual(self.list()['counts'],{'Awaiting QC Receipt':46})
    def test_native_company_and_row_permissions_scope_counts_lookup_and_history(self):
        self.case('DONE',state='Closed');data=self.list(filters={'view':'All Returns'})
        self.assertEqual(data['total'],2);self.assertEqual(data['companies'],['A'])
        for name in ('FOREIGN','HIDDEN','MISSING'):
            with self.assertRaisesRegex(PermissionError,'not accessible'):self.detail(name)
        with self.assertRaises(PermissionError):self.list(filters={'company':'B'})
        self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.detail()
    def test_no_accessible_company_returns_no_case_information(self):
        self.authorized.clear();data=self.list();self.assertEqual(data['rows'],[]);self.assertEqual(data['total'],0)
        self.assertFalse(any(q['dt']==CASE for q in self.queries))
    def test_qc_or_unrestricted_supervisor_required_and_creator_is_not_a_qc_filter(self):
        self.profile.responsibilities=[]
        with self.assertRaises(PermissionError):self.list()
        self.profile.update(kanban_role='Supervisor',view_all_responsibilities=1);self.assertEqual(self.list()['rows'][0]['name'],'OLD')
        self.can_read=False
        with self.assertRaises(PermissionError):self.list()
    def test_passive_reads_do_not_touch_operator_activity_and_page_is_read_only(self):
        original=copy.deepcopy(self.data);self.list();self.detail();self.assertTrue(all(c.kwargs['touch_activity'] is False for c in self.auth.call_args_list))
        self.list(interactive=1);self.assertTrue(self.auth.call_args.kwargs['touch_activity']);self.assertEqual(self.data,original)
    def test_all_history_and_active_tracks_include_accounting_completed_not_only_recent_open_states(self):
        self.case('CLOSED',state='Closed');self.case('CANCELLED',state='Cancelled');self.case('POSTED',return_flow='Delivery Note Correction',state='Delivery Correction Posted')
        self.case('ACCOUNTED',state='Accounting Completed',qc_completed_on='2026-11-22',accepted_total_qty=2,accounting_status='Completed')
        self.assertEqual(self.list()['total'],2);self.assertEqual(self.list(filters={'view':'All Returns'})['total'],5)
        self.assertEqual(self.list(filters={'view':'Closed / Cancelled'})['total'],3)
        actions=self.detail('ACCOUNTED')['follow_up'];self.assertEqual([a['code'] for a in actions],['stock'])
    def test_search_literals_dates_customer_location_and_trip_are_parameterized(self):
        self.case('SPECIAL',customer='50%_Buyer',driver_trip='TRIP',inspection_location='CAGE',claimed_on='2026-11-10 23:59:59')
        data=self.list(filters={'search':'%_','trip':'TRIP','location':'CAGE','customer':'50%_Buyer','from_date':'2026-11-10','to_date':'2026-11-10'})
        self.assertEqual([r['name'] for r in data['rows']],['SPECIAL']);self.assertEqual(data['total'],1)
        self.assertEqual(self.list(filters={'search':"' OR 1=1 --"})['total'],0)
    def test_bad_filters_pagination_and_dates_reject_without_silent_truncation(self):
        for filters in ({'ignore_permissions':True},{'view':'All secrets'},{'sort':'name; DROP TABLE cases'},{'flow':'Other'},{'state':'Made up'},{'from_date':'tomorrow'},{'from_date':'2026-11-20','to_date':'2026-11-01'},['bad']):
            with self.subTest(filters=filters),self.assertRaises(ValueError):self.list(filters=filters)
        for kwargs in ({'start':-1},{'start':'1.5'},{'page_length':0},{'page_length':51},{'page_length':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.list(**kwargs)
    def test_profile_employee_change_is_rejected_before_return_data_is_read(self):
        self.profile.employee='OTHER'
        with self.assertRaisesRegex(PermissionError,'identity changed'):self.list()
        self.assertFalse(self.queries)
    def test_existing_start_and_complete_recheck_native_case_and_company_before_mutation(self):
        case=self.data[CASE]['OLD'];events=Mock()
        common=self.returns.start_qc_inspection.__globals__
        common.update(require_operator=self.auth,now_datetime=lambda:NOW,record=events,flt=lambda v:float(v or 0))
        case._denied=True
        with self.assertRaises(PermissionError):self.returns.start_qc_inspection('OLD','EVENT','TOKEN')
        case._denied=False;self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.returns.start_qc_inspection('OLD','EVENT','TOKEN')
        self.assertEqual(case.state,'Awaiting QC Receipt');events.assert_not_called()
        self.data['Company']['A']._denied=False;self.returns.start_qc_inspection('OLD','EVENT','TOKEN')
        self.assertEqual(case.state,'QC In Progress');events.reset_mock()
        before=copy.deepcopy(case);case._denied=True
        values=[dict(name=case.lines[0].name,received_qty=3,accepted_qty=2,rejected_qty=1,qc_disposition='Accept for Credit')]
        with self.assertRaises(PermissionError):self.returns.complete_qc_inspection('OLD',values,'Inspected','COMPLETE','TOKEN')
        case._denied=False;self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.returns.complete_qc_inspection('OLD',values,'Inspected','COMPLETE','TOKEN')
        self.assertEqual(case.lines,before.lines);self.assertFalse(case.qc_completed_on);events.assert_not_called()
        self.data['Company']['A']._denied=False;self.returns.complete_qc_inspection('OLD',values,'Inspected','COMPLETE','TOKEN')
        self.assertEqual(case.state,'QC Completed - Accounting Pending');self.assertEqual(case.accepted_total_qty,2)

    def test_scanner_commands_are_selectable_in_the_existing_print_catalogue(self):
        ns=load('api/operator.py',dict(frappe=self.f,flt=lambda v:float(v or 0)))
        commands={r['payload'] for r in ns['_scanner_command_catalog']()}
        self.assertTrue({'CFG:CMD:VIEW_RETURN_QC_MONITOR','CFG:CMD:QC_INSPECT_RETURN','CFG:CMD:RETURN_CASE_RECORD'}<=commands)
    def test_existing_logistics_recent_returns_use_native_case_permissions(self):
        rows=self.returns.return_case_summaries(self.profile)
        self.assertEqual([r.name for r in rows],['OLD']);self.assertEqual(self.queries[-1]['length'],30)
        self.can_read=False;self.assertEqual(self.returns.return_case_summaries(self.profile),[])
    def test_case_name_and_uuid_lookup_use_the_same_native_scope(self):
        self.data[CASE]['OLD'].scan_token='uuid-token';self.save_sql(self.data[CASE]['OLD'])
        self.assertEqual(self.detail('uuid-token')['name'],'OLD')
        self.case('uuid-token')
        with self.assertRaisesRegex(PermissionError,'ambiguous'):self.detail('uuid-token')
    def test_parallel_accounting_and_stock_followup_are_both_visible(self):
        case=self.data[CASE]['OLD'];self.complete(case)
        self.assertEqual([a['code'] for a in self.detail()['follow_up']],['accounting','stock'])
        case.disposition_status='Completed';self.save_sql(case)
        self.assertEqual([a['code'] for a in self.detail()['follow_up']],['accounting'])
    def test_draft_credit_receipt_and_cancellation_remain_pending(self):
        case=self.data[CASE]['OLD'];self.complete(case);case.update(accounting_status='Credit Pending',stock_disposition_entry_status='Draft');self.save_sql(case)
        actions=self.detail()['follow_up'];self.assertIn('submit',actions[0]['label']);self.assertIn('Draft',actions[1]['label'])
        case.update(accounting_status='Source Selected',stock_disposition_entry_status='Cancelled',disposition_status='Decision Recorded');self.save_sql(case)
        self.assertEqual(len(self.detail()['follow_up']),2)
    def test_owned_refusal_never_suggests_customer_credit_or_a_second_receipt(self):
        case=self.data[CASE]['OLD'];self.complete(case);case.update(stock_already_owned=1,state='QC Completed - Stock Pending',accounting_status='Not Required');self.save_sql(case)
        detail=self.detail();self.assertEqual([a['code'] for a in detail['follow_up']],['owned_stock']);self.assertEqual(detail['kind'],'Company-owned refusal')
    def test_receipt_inspection_capabilities_and_correction_are_distinct(self):
        self.assertTrue(self.detail()['can_inspect']);self.profile.can_start=0;self.assertFalse(self.detail()['can_inspect'])
        case=self.data[CASE]['OLD'];case.update(state='QC In Progress',qc_started_on='2026-11-23 09:00');self.save_sql(case)
        self.assertEqual(self.detail()['inspection'],'In Progress');self.assertTrue(self.detail()['can_inspect']);self.profile.can_complete=0;self.assertFalse(self.detail()['can_inspect'])
        case.update(state='Delivery Correction Draft',return_flow='Delivery Note Correction');self.save_sql(case)
        detail=self.detail();self.assertFalse(detail['can_inspect']);self.assertEqual(detail['inspection'],'Not applicable');self.assertEqual(detail['follow_up'][0]['code'],'correction')
    def test_rejected_and_investigation_remain_visible_until_native_closure(self):
        case=self.data[CASE]['OLD'];self.complete(case,0);case.state='QC Rejected';case.lines[0].qc_disposition='Hold for Investigation';self.save_sql(case)
        self.assertEqual([a['code'] for a in self.detail()['follow_up']],['investigation','rejected']);self.assertEqual(self.list()['total'],1)
        case.state='Closed';self.save_sql(case);self.assertEqual(self.detail()['follow_up'],[])
    def test_quantity_totals_keep_stock_uoms_separate_and_preserve_tag_expiry(self):
        case=self.data[CASE]['OLD'];case.lines[0].update(original_visible_code='TAG1',batch_no='BATCH',expiry_date='2027-01-01')
        case.lines.append(Doc(name='OTHER',idx=2,item_code='BULK',stock_uom='Kg',claimed_qty=1.5,received_qty=1.5,accepted_qty=1,rejected_qty=.5))
        data=self.detail();self.assertEqual(data['totals_by_uom']['Nos']['claimed_qty'],3);self.assertEqual(data['totals_by_uom']['Kg']['claimed_qty'],1.5)
        self.assertEqual(data['lines'][0]['expiry_date'],'2027-01-01');self.assertNotIn('claimed_total_qty',data)
        case.lines[0].received_qty=float('nan');self.assertIsNone(self.detail()['lines'][0]['received_qty']);self.assertTrue(self.detail()['warnings'])
    def test_native_link_permissions_company_customer_and_optional_doctype_are_checked(self):
        case=self.data[CASE]['OLD'];case.update(credit_document_doctype='User',credit_document='secret',driver_trip='TRIP',stock_disposition_entry='RECEIPT')
        self.add('CFG Kanban Delivery Trip','TRIP',company='B');self.add('Stock Entry','RECEIPT',company='A',_denied=True)
        self.assertEqual(self.detail()['links'],[]);self.assertNotIn(('User','secret'),self.reads)
        case.update(credit_document_doctype='Credit Note',credit_document='CN1');self.add('Credit Note','CN1',company='A',customer='WRONG')
        self.assertEqual(self.detail()['links'],[])
        self.data['Credit Note']['CN1'].customer='CUSTOMER';self.assertEqual(self.detail()['links'][0]['name'],'CN1')
    def test_live_owned_custody_retains_exact_case_lines_only(self):
        case=self.data[CASE]['OLD'];case.update(stock_already_owned=1,driver_trip='TRIP',driver_delivery_outcome='OUT');case.lines[0].driver_outcome_line='OWN'
        self.add('CFG Kanban Delivery Outcome','OUT',company='A',delivery_trip='TRIP',lines=[Doc(name='OWN',qc_return_case='OLD',item_code='ITEM',stock_uom='Nos',refused_qty=2,stock_state='Transferred Hold',current_warehouse='QC WH',visible_code='TAG'),Doc(name='OTHER',qc_return_case='OTHER',refused_qty=8)])
        result=self.detail()['owned_custody'];self.assertEqual(len(result),1);self.assertEqual(result[0]['warehouse'],'QC WH')
        self.data['CFG Kanban Delivery Outcome']['OUT']._denied=True;self.assertEqual(self.detail()['owned_custody'],[])
    def test_ages_are_server_based_and_corrupt_dates_do_not_invent_freshness(self):
        self.assertEqual(self.detail()['age_seconds'],22*86400+4*3600)
        self.data[CASE]['OLD'].claimed_on='future?';self.assertIsNone(self.detail()['age_seconds'])
        self.data[CASE]['OLD'].claimed_on='2026-11-24 08:00';self.assertEqual(self.detail()['age_seconds'],0)


if __name__=='__main__':unittest.main()

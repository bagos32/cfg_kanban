"""Current version markers for a follow-on physical stock review.

The usual identity service owns certificate/printed-expiry interpretation. These
markers detect metadata changed while a request waited for stock locks, including
changes in inherited certificate provenance. They never issue new certificates.
"""
import frappe


def _rows(doctype,filters,fields,current):
    if current:
        return frappe.db.get_values(doctype,filters,fields,as_dict=True,for_update=True,order_by='name')
    return frappe.get_all(doctype,filters=filters,fields=fields,order_by='name',limit_page_length=0)


def revision(unit,current=False):
    result={'batch':None,'serials':[],'certificates':[],'postings':[],'runs':[],'progress':[]}
    if unit.batch_no:
        result['batch']=frappe.db.get_value('Batch',unit.batch_no,['name','modified','expiry_date','item'],
            as_dict=True,**({'for_update':True} if current else {}))
    result['serials']=_rows('CFG Kanban Handling Unit Serial',{'handling_unit':unit.name,'state':'Active'},
        ['name','serial_no','state','modified'],current)
    if not unit.get('process_certificate_set'):return result
    fields=['name','modified','status','valid_from','valid_until','certificate_type','revision_snapshot',
        'source_reference_doctype','source_reference_name']
    pending=_rows('CFG Process Certificate',{'handling_unit':unit.name,'certificate_set':unit.process_certificate_set},fields,current)
    known={};postings=set()
    while pending:
        proof=pending.pop(0)
        if proof.name in known:continue
        if len(known)>=256:frappe.throw('Certificate provenance exceeds the safe review limit; reconcile the source tag')
        known[proof.name]=proof
        if proof.source_reference_doctype=='CFG Process Certificate' and proof.source_reference_name:
            parent=frappe.db.get_value('CFG Process Certificate',proof.source_reference_name,fields,as_dict=True,
                **({'for_update':True} if current else {}))
            if parent:pending.append(parent)
            else:known[proof.source_reference_name]={'name':proof.source_reference_name,'missing':True}
        elif proof.source_reference_doctype=='Stock Entry' and proof.source_reference_name:
            postings.add(proof.source_reference_name)
    result['certificates']=[known[name] for name in sorted(known)]
    for name in sorted(postings):
        result['postings'].append(frappe.db.get_value('Stock Entry',name,['name','modified','docstatus','purpose'],
            as_dict=True,**({'for_update':True} if current else {})))
        if not frappe.db.table_exists('CFG Process Certificate Run'):continue
        runs=_rows('CFG Process Certificate Run',{'repack_stock_entry':name},
            ['name','modified','status','printed_expiry','first_output_serial','last_output_serial','output_handling_unit','result_certificate_set'],current)
        result['runs']+=runs
        if runs and frappe.db.table_exists('CFG Certificate Process Progress'):
            result['progress']+=_rows('CFG Certificate Process Progress',{'certificate_process_run':['in',[r.name for r in runs]]},
                ['name','modified','status','printed_expiry','first_output_serial','last_output_serial'],current)
    return result

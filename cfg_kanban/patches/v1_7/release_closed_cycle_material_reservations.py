"""Audited, repeatable cleanup after the released-quantity field is installed."""
import frappe


def execute():
    if not frappe.db.table_exists("CFG Kanban Operation Material Draw"):
        return
    from cfg_kanban.services.material_run_release import release_closed_execution
    names = frappe.db.sql("""
        select distinct execution.name
        from `tabCFG Kanban Process Execution` execution
        inner join `tabCFG Kanban Cycle` cycle on cycle.name=execution.kanban_cycle
        inner join `tabCFG Kanban Operation Material Draw` draw
            on draw.process_execution=execution.name
        where cycle.status='Completed' and draw.remaining_qty > 0.000001
          and draw.status in ('Open','Partially Used','Carry Forward','Used','Bound to ERP')
        order by execution.name
    """)
    for row in names:
        release_closed_execution(row[0], "Migration: unused reservation on an already completed Cycle")

    # Old carry-only use could leave a stale cached run total even when its Draw is exhausted.
    from cfg_kanban.services.operation_material_runs import _refresh_run_totals
    runs = frappe.db.sql("""
        select run.name from `tabCFG Kanban Operation Material Run` run
        inner join `tabCFG Kanban Cycle` cycle on cycle.name=run.kanban_cycle
        where cycle.status='Completed' and run.carry_forward_qty > 0.000001
        order by run.name
    """)
    for row in runs:
        _refresh_run_totals(frappe.get_doc("CFG Kanban Operation Material Run", row[0]))

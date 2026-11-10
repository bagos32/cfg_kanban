# Acceptance Test — Operation Material Run Source Draws

## Purpose

Verify the opt-in scanner flow that binds a physical source Stock Tag quantity to one
high-frequency Operation Material Run, consumes the declared quantity when progress is posted,
and carries an unused balance into the next run without changing ERPNext stock prematurely.

This is a development acceptance test. It does **not** accept exact serial membership or final
ERP settlement; those remain the next packages.

## Minimal sample

- one submitted BOM producing `10 Unit` of output;
- one non-serial input Item `TEST-BAG` with BOM Qty `20 Nos` and an Item Operation;
- one active released Stock Tag for `TEST-BAG`, quantity at least `20 Nos`;
- one Production Master with one Operation Profile and one reusable Process Card.

In **CFG Kanban Master → Operation Profiles**, set:

- **Output Reporting Mode** = `Incremental`;
- **Material Run Control** = `Required Before Progress`;
- **Output Boundary Requirement** = `Every Material Run`;
- **Allow Unused Material Carry-forward** = enabled.

In **BOM Component Material Flow**, set only the `TEST-BAG` row:

- **Material Run Tracking** = `Source Tag Quantity`;
- **Material Run Scan Warehouse** = the physical Warehouse on the source Stock Tag;
- **WIP Presentation** = `Standard ERP / Tag Flow`.

Save the Master. Verify **Material Qty per Output Unit** becomes `2 Nos`. Leave every other BOM
row as **No Run Tracking**; those rows must not appear in the Material Run scanner guide. Release a
new Cycle/Process Execution after saving; an execution that already existed retains its immutable
older rule snapshot.

## Scanner-only positive test

1. Release production, identify the operator, scan the Process Card and start the operation.
2. Scan `CFG:CMD:START_MATERIAL_RUN`.
3. Scan the first output boundary requested by the dialog.
4. Scan `CFG:QTY:MATERIAL:12`.
5. Scan the physical `TEST-BAG` source Stock Tag.
6. Verify the dialog shows `12 Nos`, Item, visible source code, Warehouse and carry status. Scan
   `CFG:CMD:CONFIRM`.
7. Verify one **CFG Kanban Operation Material Draw** exists with **Draw Status = Open**,
   **Drawn Qty = 12**, **Used Qty = 0** and **Operationally Reserved Balance = 12**. Verify neither
   ERPNext stock nor the Handling Unit quantity ledger changed.
8. Report `Good +5`. The ratio requires `10 Nos`. Verify progress posts, the run becomes
   **Progress Posted**, the Draw becomes **Carry Forward**, **Used Qty = 10**, and balance is `2`.
9. Start the next Material Run and scan its output boundary. Do not scan another material tag.
   Confirm the run; the existing `2 Nos` carry-forward must satisfy run start.
10. Report `Good +1`. Verify the remaining `2 Nos` is used and the original Draw becomes **Used**.

## Rejection and recovery tests

1. On a new required run with no balance, Confirm without quantity/source. Expect an instruction
   to scan the missing Item; no open run may remain after the failed transaction.
2. Scan a wrong Item, wrong Warehouse, wrong UOM, inactive/Hold tag, or quantity above physical
   availability. Expect an exact rejection and restored scanner focus.
3. Try to reserve the same physical balance from a parallel execution. Expect availability to be
   reduced by the first unbound Material Draw reservation.
4. With carry-forward disabled, scan more than the progress ratio requires. Progress must reject
   and require the exact current-run quantity.
5. Start a run with a valid draw, then scan `CFG:CMD:CANCEL_MATERIAL_RUN` before progress. Confirm
   cancellation. The Draw remains as **Cancelled** audit evidence and no longer blocks source
   availability.
6. Leave Material Run Control disabled and all material rows at **No Run Tracking** on a simple
   Production Master. Verify its existing start/progress/material flow is unchanged.

## Evidence to record

- deployed Git revision;
- Master, Cycle, Process Execution, Material Run and Material Draw names;
- source Handling Unit code and before/after quantities;
- two Progress records and final carry balance;
- screenshots of scanner guide, rejection, and focus recovery;
- explicit note that ERP settlement and exact serial acceptance remain open.

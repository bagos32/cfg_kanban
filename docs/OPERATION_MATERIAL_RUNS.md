# Operation Material Runs — High-frequency Production Traceability

## Purpose

An Operation Material Run is a short, auditable production boundary inside one Job Card or
Process Card execution. It is intended for fast repeated floor work where the operator must later
bind raw-material Batch/serial evidence to a small output interval without slowing every unit.

This feature is optional per Operation Profile. Existing production remains unchanged while
**Material Run Control** is **Disabled**.

## Package status

Package 1 provides the safe run foundation:

- operation-level configuration and immutable runtime snapshots;
- one concurrently open Material Run per execution lane;
- scanner-only start using `CFG:CMD:START_MATERIAL_RUN`;
- numbered `CFG:SELECT:1` to `CFG:SELECT:10` disambiguation;
- configurable output-boundary capture;
- idempotent creation, operator/session audit, live refresh and printable command label;
- automatic linkage and closure when the next operator progress record is posted;
- scanner-safe cancellation before progress.

Package 2 adds opt-in source quantity evidence:

- per-BOM-component **Material Run Tracking = Source Tag Quantity**;
- immutable rule snapshots on newly released Process Executions;
- scanner sequence of Material Quantity then physical source Stock Tag;
- Item, Company, Warehouse, UOM, active/released and available-quantity validation;
- immutable **CFG Kanban Operation Material Draw** audit rows;
- cross-execution operational reservation so a shared bulk tag cannot be over-declared;
- BOM-ratio progress gating and FIFO carry-forward into later Material Runs;
- cancelled-draw audit with reservation release;
- no change to operations and components that retain Disabled/No Run Tracking defaults.

Package 3 adds controlled ERP settlement without a second physical scan:

- **At Job Card End** creates a dedicated Draft `Material Consumption for Manufacture` only for
  the used Material Draw quantities of that Job Card;
- **At Work Order Manufacture Receipt** adopts those quantities into the final native
  `Manufacture` entry instead;
- ordinary Skip-WIP inputs are consumed only by final Manufacture and no longer create a duplicate
  intermediate consumption entry;
- the original source Handling Unit, Warehouse, UOM, Batch and quantity are adopted into Production
  Material Trace through the same validation used by a live scan;
- different scanned input Batches are split into exact native Stock Entry Detail rows;
- ERP submission changes stock/Handling Unit quantity and marks the Draw **Bound to ERP**;
- Draft line cancellation, Draft abandonment and submitted-entry reversal restore controlled Draw
  state; and
- Cycle closure is blocked by any linked Draft production Stock Entry or used, unsettled Draw.

The following packages must still be completed before this is accepted as the full
serial-controlled material-trace flow:

1. exact serial reservation and serial-range evidence with parallel-machine collision protection;
2. controlled post-progress quantity correction beyond ERP cancellation/reversal;
3. complete floor acceptance of both settlement timings and recovery cases.

## Minimal configuration

In **CFG Kanban Master → Operation Profiles**, use these values only on an operation that needs
the high-frequency flow:

| Field | Recommended pilot value |
|---|---|
| Output Reporting Mode | Incremental |
| Material Run Control | Optional first; Required Before Progress after Package 2 acceptance |
| Output Boundary Requirement | Every Material Run |
| Allow Unused Material Carry-forward | Enabled |
| ERP Settlement Timing | At Job Card End |

For each tracked BOM row, select **Source Tag Quantity**, its physical scan Warehouse, and
**Standard ERP / Tag Flow**. The calculated ratio is BOM component quantity divided by BOM output
quantity. Leave simple components at **No Run Tracking**. Do not enable it for an ERPNext
serial-controlled Item until the exact-serial package is delivered.

Source Tag Quantity currently requires **Production Material Mode = Skip WIP Transfer**. At Job
Card end, BOMs controlled against Job Card use the Job Card material rows. BOMs controlled against
Work Order use the immutable used Material Draws as the exact settlement scope while preserving
the originating Job Card in CFG Kanban's audit field.

## Scanner-only pilot

1. Release the production and start the relevant operation normally.
2. Scan `CFG:CMD:START_MATERIAL_RUN`.
3. If several enabled operations are active, scan the displayed `CFG:SELECT:n` label.
4. If requested, scan the first output serial or other printed output boundary.
5. Scan `CFG:QTY:MATERIAL:n`, then the physical source Stock Tag for each tracked component.
6. Scan `CFG:CMD:CONFIRM`.
7. Verify that the execution lane displays the open Material Run number and boundary and that each
   Draw is recorded without reducing ERPNext or Handling Unit stock.
8. Scan `CFG:CMD:START_MATERIAL_RUN` again. Verify that it reports the existing open run rather
   than creating a second run.
9. Report a positive progress quantity. Verify that the BOM-ratio quantity is used, the progress
   record links to the Material Run, the run becomes **Progress Posted**, and any remainder becomes
   **Carry Forward**.
10. Start another run by mistake, scan `CFG:CMD:CANCEL_MATERIAL_RUN`, then Confirm. Verify that the
   run and staged Draws are Cancelled before progress and no reservation remains active.
11. For an operation where Material Run Control is Disabled, verify that the start command says no
   eligible operation is available and that normal production remains unchanged.
12. If **ERP Settlement Timing = At Job Card End**, complete/submit the Job Card, select/scan
    **Prepare Materials**, choose the Job Card when prompted, and use **Settle Material Runs**.
    Verify the Draft already contains the earlier source scans. Submit it with the normal scanner
    command; do not scan those tags again.
13. If **ERP Settlement Timing = At Work Order Manufacture Receipt**, finish all Job Cards and
    prepare Manufacture. Verify the final Draft already contains the earlier source scans. Scan
    only other required physical inputs and the finished-output tag, then submit.
14. Verify no unused `Material Transfer for Manufacture` or duplicate consumption Draft remains.
    Attempting to close with any linked Draft or unsettled Draw must be rejected with its identifier.

Follow `docs/TEST_OPERATION_MATERIAL_RUN_DRAWS.md` for scanner evidence and
`docs/TEST_OPERATION_MATERIAL_RUN_SETTLEMENT.md` for ERP settlement. A Draw remains only an
operational reservation until its linked native Stock Entry is submitted. Exact serial membership
is not included; do not enable Source Tag Quantity for an ERPNext serial-controlled Item.

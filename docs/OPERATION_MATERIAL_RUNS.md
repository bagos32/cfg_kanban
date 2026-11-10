# Operation Material Runs — High-frequency Production Traceability

## Purpose

An Operation Material Run is a short, auditable production boundary inside one Job Card or
Process Card execution. It is intended for fast repeated floor work where the operator must later
bind raw-material Batch/serial evidence to a small output interval without slowing every unit.

This feature is optional per Operation Profile. Existing production remains unchanged while
**Material Run Control** is **Disabled**.

## Package 1 status

This package provides the safe foundation:

- operation-level configuration and immutable runtime snapshots;
- one concurrently open Material Run per execution lane;
- scanner-only start using `CFG:CMD:START_MATERIAL_RUN`;
- numbered `CFG:SELECT:1` to `CFG:SELECT:10` disambiguation;
- configurable output-boundary capture;
- idempotent creation, operator/session audit, live refresh and printable command label;
- automatic linkage and closure when the next operator progress record is posted;
- scanner-safe cancellation of an empty run started by mistake;
- no ERPNext stock posting and no change to ordinary progress reporting yet.

The following packages must be completed before this is accepted as the full material-trace flow:

1. material-source draws, progress gate, source-change boundaries and carry-forward;
2. exact serial reservation with parallel-machine collision protection;
3. final Material Trace adoption and ERP settlement without rescanning or double reservation;
4. controlled correction/recovery plus complete floor acceptance.

## Minimal configuration

In **CFG Kanban Master → Operation Profiles**, use these values only on an operation that needs
the high-frequency flow:

| Field | Recommended pilot value |
|---|---|
| Output Reporting Mode | Incremental |
| Material Run Control | Optional |
| Output Boundary Requirement | Every Material Run |
| Allow Unused Material Carry-forward | Enabled |
| ERP Settlement Timing | At Job Card End |

Use **Optional** during floor trials. Change to **Required Before Progress** only after the later
progress-gate package is deployed and accepted.

## Scanner-only pilot

1. Release the production and start the relevant operation normally.
2. Scan `CFG:CMD:START_MATERIAL_RUN`.
3. If several enabled operations are active, scan the displayed `CFG:SELECT:n` label.
4. If requested, scan the first output serial or other printed output boundary.
5. Scan `CFG:CMD:CONFIRM`.
6. Verify that the execution lane displays the open Material Run number and boundary.
7. Scan `CFG:CMD:START_MATERIAL_RUN` again. Verify that it reports the existing open run rather
   than creating a second run.
8. Report a positive progress quantity. Verify that the progress record links to the Material Run,
   the run becomes **Progress Posted**, and a new run may be opened.
9. Start another run by mistake, scan `CFG:CMD:CANCEL_MATERIAL_RUN`, then Confirm. Verify that the
   empty run is Cancelled. A run with material/progress evidence must reject this simple recovery.
10. For an operation where Material Run Control is Disabled, verify that the start command says no
   eligible operation is available and that normal production remains unchanged.

The current package records a boundary only. Do not treat it as final raw-material reservation,
serial allocation, progress enforcement, or ERP consumption acceptance.

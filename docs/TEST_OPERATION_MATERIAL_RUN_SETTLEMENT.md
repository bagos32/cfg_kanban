# Acceptance Test — Operation Material Run ERP Settlement

## Purpose

Verify that Skip-WIP production consumes each raw-material quantity exactly once, reuses the
physical source evidence captured during Material Runs, and leaves no non-functional production
Draft when a Cycle closes.

Run this only after `docs/TEST_OPERATION_MATERIAL_RUN_DRAWS.md` passes. Use non-serial test Items
and disposable development quantities. This test does not accept exact serial-number reservation.

## Minimal test data

Use one submitted Work Order with one Job Card and these inputs:

| Input | Material Run tracking | Physical policy | Purpose |
|---|---|---|---|
| `TEST-BAG` | Source Tag Quantity | Required Physical Tag | Proves scan adoption |
| `TEST-WATER` | No Run Tracking | No Physical Tag | Proves ordinary final consumption |

Prepare one active `TEST-BAG` Stock Tag in the configured source Warehouse. For the multi-Batch
test, prepare two active tags of the same Item/UOM/Warehouse carrying different ERPNext Batches.

Use **Production Material Mode = Skip WIP Transfer**. No `Material Transfer for Manufacture`
should be created in either settlement route.

## Route A — settle at Work Order Manufacture receipt

1. On the Operation Profile select **ERP Settlement Timing = At Work Order Manufacture Receipt**.
2. Release a new Cycle so the Process Execution snapshots the setting.
3. Start the Job Card operation and start one Material Run.
4. Scan a Material Quantity and the physical `TEST-BAG` source tag, then Confirm.
5. Report the matching positive progress and complete the Job Card.
6. Verify the Material Draw has positive **Used Qty**, remains operationally reserved, and has no
   Material Trace yet. ERPNext and Handling Unit quantities must still be unchanged.
7. On the main production Card choose **Prepare Manufacture Receipt**.

Expected:

- no separate `Material Consumption for Manufacture` was created;
- one Draft `Manufacture` entry is created, even if the Master normally auto-submits;
- Production Material Trace already contains the `TEST-BAG` input line with the original source
  Handling Unit and used quantity;
- `TEST-WATER` remains on the native Manufacture input row and needs no physical scan;
- the operator is not asked to scan the adopted `TEST-BAG` quantity again.

8. Stage the finished-output tag/container and scan `CFG:CMD:SUBMIT_MATERIALS`.

Expected after submission:

- ERPNext consumes `TEST-BAG` and `TEST-WATER` once and receives the finished output;
- the source Handling Unit reduces by the adopted quantity once;
- the Material Draw status becomes **Bound to ERP** and links to the confirmed Material Trace;
- there is no Draft production Stock Entry left for the Work Order.

## Route B — settle at Job Card end

1. On a new Master revision select **ERP Settlement Timing = At Job Card End** and release a new
   Cycle/Process Execution.
2. Capture and use one Material Run source Draw, then complete and submit the native Job Card.
3. In Production Material Control choose **Settle Material Runs**, or scan the standard Prepare
   Materials command and select the eligible Job Card with `CFG:SELECT:n` when prompted.

Expected:

- one Draft `Material Consumption for Manufacture` is created only for the used Draw quantity;
- its Production Material Trace already contains the earlier physical source scan;
- no second scan of that source tag is requested.

4. Scan `CFG:CMD:SUBMIT_MATERIALS`.
5. Prepare the final Manufacture receipt.

Expected:

- the submitted Job Card-end entry consumes the tracked quantity once;
- the final Manufacture entry contains only ERPNext's remaining input quantity plus output;
- the tracked quantity is not requested or consumed again;
- the Draw is **Bound to ERP**.

## Multi-Batch adoption

1. In two Material Runs, use two `TEST-BAG` tags carrying different Batches.
2. Post progress so both Draws have Used Qty.
3. Prepare the selected settlement route.

Expected: CFG Kanban splits the native input into separate Stock Entry Detail rows for the exact
Batch quantities and binds each original source tag to its matching row. Submission must update
both Batches once. A Warehouse, UOM, Item, Batch, or quantity conflict must reject with a visible
message and restore scanner focus.

## Recovery and orphan-Draft gates

1. Prepare settlement but do not submit it. Attempt to close/release the production Cycle.
   Expected: closure is rejected and names the open Draft Stock Entry.
2. Cancel one adopted Draft trace line. Expected: its Draw loses the Draft trace link and returns
   to its operational reservation state.
3. Abandon the entire Draft trace through the controlled action, then have an authorized supervisor
   delete the unposted Draft Stock Entry. Expected: every adopted Draw is released and can be
   settled again; the Material Trace and event audit remain.
4. Submit the entry, then cancel it through the controlled ERP recovery path. Expected: Handling
   Unit quantity is reversed and the linked Draw becomes unsettled again rather than disappearing.
5. Attempt closure while a used Draw is unsettled. Expected: closure is rejected and names the
   Material Draw.

## Evidence to record

- deployed Git revision;
- Master, Cycle, Work Order, Job Card and Process Execution;
- both Material Run and Material Draw identifiers;
- source Handling Unit before/after quantity;
- settlement Stock Entry and Material Trace;
- Stock Ledger evidence showing one consumption only;
- screenshots of automatic trace adoption and both closure rejections;
- any accepted exception or deferred risk.


## Unused BOM residual regression — live tests NOT RUN

1. Require 5 Kg in the BOM; record approved actual use 3 Kg and finish/submit the Job Cards.
   Settle 3 Kg at Job Card end and submit its native consumption. Prepare Manufacture: no 2 Kg
   residual input/tag allocation is requested, 3 Kg is consumed once, and 2 Kg remains in stock.
2. Repeat with settlement at Manufacture receipt: native input/adopted trace are exactly 3 Kg,
   not the mapped 5 Kg. Check over-BOM actuals, multiple Batches and differing UOM conversion.
3. Check the receipt confirmation shows used/posted/pending actuals and omits tracked inputs from
   manual entry. Untracked inputs remain editable and retain their physical-tag requirements.
4. Save an old unsubmitted residual Draft, reopen Scan Material Tags and submit with the scanner.
   Verify valid allocations remain bound to the same rows. Reject quantity below existing trace
   reservations until controlled cancellation; retain posted stock and audit unchanged.
5. Negative: missing draws, partial snapshot coverage, another Warehouse, incomplete Job Card,
   open run, cancelled/mismatched ERP consumption, another Company and unrelated input rows.
   No missing-consumption check may be bypassed merely because a tag was not scanned.
6. Repeated save/preparation and a second/partial receipt must not consume actuals twice.
   Verify native rollback/concurrency and the Manufacturing actual-cost/valuation behavior.

Record deployed SHA, exact Work Order/Job Card/Draw/Trace/Stock Entry/Event names and before/after
ERP stock plus tag balances. Offline source/behavior checks do not establish live ERP acceptance.


Local validation, 2026-11-12: 305 Python checks passed, including 21 new receipt-actuals
checks; all 44 JavaScript checks passed, including 6 new receipt scanner checks. Operator
JavaScript syntax, changed Python syntax and whitespace checks passed. These results use
dependency doubles and source contracts; no live ERP stock, valuation, rollback, concurrent
posting or physical scanner behavior was verified. No commit or deployment was performed.

# Package D3 — End-of-Route Reconciliation System Test

## Purpose

This test proves that a driver or logistics supervisor can physically count a Company-specific
vehicle Warehouse, compare it with ERPNext, and close the route only when the physical count is
balanced. ERPNext Stock Ledger Entries remain the stock authority. CFG Kanban records exact tag
scans, loose/untagged quantities, variance Exceptions, recounts, and correction references.

The test deliberately includes tagged and untagged stock. A physical tag is optional unless the
Item/Company trace policy requires it.

## Preconditions and sample data

1. Deploy and migrate Package D3, build assets, clear cache, and restart.
2. In ERPNext create or reuse an active, non-group Warehouse belonging to the selling Company.
   Enable **Vehicle Warehouse** (`cfg_is_vehicle_warehouse`) and set **Physical Vehicle Reference**
   (`cfg_vehicle_reference`) to `LORRY-TEST-01`.
3. Add **Logistics Reconciliation** to the tester's **CFG Kanban Operator Profile**. The profile
   also needs Start and Complete permission. Add Supervisor Override only to the supervisor profile.
4. Put this sample ERP stock in the vehicle Warehouse through submitted ERPNext documents:

   | Item | Batch | ERP quantity | Physical representation |
   |---|---|---:|---|
   | TEST-FG-TAG | TEST-BATCH-01 | 10 | one active Stock Tag containing 10 |
   | TEST-FG-LOOSE | no batch | 6 | untagged/loose quantity |

5. The Stock Tag must have the same Inventory Company and Current Warehouse and a Current Qty of
   10. For a reusable container test, load that tag into an active container before beginning.

## Test 1 — Open one controlled route count

1. Open **CFG Kanban → Logistics Operator Panel** and identify the reconciliation operator.
2. Select **Route Stock Count**.
3. Select the Company-specific `LORRY-TEST-01` Warehouse and select **Start / Continue Count**.
4. Record the generated `KREC-...` number.

Expected result:

- state is `Counting`;
- Opening ERP Qty and Expected Closing Qty reflect submitted ERP stock at count opening;
- starting the same Warehouse again returns the existing open count instead of making a duplicate;
- a separate Company Warehouse for the same physical lorry is counted separately.

## Test 2 — Count exact tags and loose stock

1. Select **Start Tag Count Scanning** and scan the Stock Tag.
2. If using a reusable container, scan the container once instead. Confirm that its current content
   tag is expanded into the Exact Scanned Tags list.
3. Scan the same tag/container again.
4. Stop count scanning.
5. Select **Enter Loose / Untagged Count** and enter `TEST-FG-LOOSE`, no Batch, quantity `6`.

Expected result:

- the exact tag contributes 10 to Scanned Tag Qty;
- the loose row contributes 6 to Loose / Untagged Qty;
- a duplicate scan is rejected;
- a tag in another Company/Warehouse, an empty tag, or an unactivated preprinted code is rejected;
- a contained tag must be counted by scanning its reusable container;
- removing a container-origin scan removes all content rows counted by that container scan;
- no Stock Entry or Stock Ledger Entry is created by counting.

## Test 3 — Balanced closure

1. Select **Evaluate against ERPNext**.
2. Confirm state becomes `Ready to Close`, all Variance Qty values are zero, and no Exception is
   created.
3. Select **Close Balanced Route**, optionally enter a closing note, and confirm.
4. Open the record from **CFG Kanban → Route Reconciliations** and print
   **CFG Route Reconciliation Report**.

Expected result:

- state is `Closed` and the closing operator/time are immutable;
- every scanned Handling Unit receives Last Reconciled On;
- the report shows opening, submitted ERP movement, expected closing, tags, loose quantity, count,
  and variance by Item/Batch;
- the report clearly states ERPNext is the stock system of record.

## Test 4 — Submitted movement during an open count

1. Start a new count and record its opening balance.
2. Post a valid ERPNext load, delivery, transfer, return, or damage Stock Entry affecting the same
   vehicle Warehouse.
3. Count the resulting physical stock and select **Evaluate against ERPNext**.

Expected result: Net ERP Movement equals current ERP balance minus the opening snapshot. Expected
Closing Qty changes accordingly. Draft ERP documents do not affect the expected quantity.

## Test 5 — Variance, recount, and authorized correction

1. Start another count, scan the 10-unit tag, but enter loose quantity `5` instead of `6`.
2. Select **Evaluate against ERPNext**.

Expected result:

- state becomes `Variance`;
- a Critical open **CFG Kanban Exception** of type `Route Stock Variance` is linked;
- closing is unavailable and no automatic ERP stock adjustment is made.

Correct the physical count to `6`, or post an authorized ERPNext stock-correction document when the
physical result is correct and ERP is wrong. Evaluate again. State must become `Ready to Close`.
Close the route, enter mandatory recount/resolution notes, and optionally link the submitted ERP
correction document. The linked Exception must become `Resolved`.

## Test 6 — Negative controls

- A profile without Logistics Reconciliation sees no actionable count list and cannot call the
  write API.
- A non-supervisor cannot cancel a count.
- Supervisor cancellation requires a reason and preserves the count/event history.
- A closed or cancelled reconciliation cannot be changed or deleted.
- A count cannot close if ERP stock changes after evaluation; closure refreshes ERP balances and
  returns the record to `Variance` instead.
- Evaluation rejects a scanned tag whose quantity, Warehouse, identity state, or container
  membership changed after its scan; remove and rescan the current physical state.
- A balanced count cannot close while the same Vehicle Warehouse has an unfinished Customer
  Delivery Session or physically open Movement Manifest.

## Pass criteria

Package D3 passes when the route closes only on a zero Item/Batch variance, both tagged and untagged
stock are represented, submitted ERP movements are reflected, all mismatches create auditable
Exceptions, correction never deletes history, and no counting action changes ERPNext stock.

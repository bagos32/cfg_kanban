# System Test — Existing Finished Stock Adoption

## Purpose

Prove that finished goods already posted in ERPNext can receive a preprinted CFG Stock Tag without
creating or duplicating ERP stock, and that a supervisor can optionally reserve the complete tag for
an eligible stock-replenishment Cycle without reporting production.

## Sample data

| Record | Sample value |
|---|---|
| Company | Manufacturing Company |
| Warehouse | Finished Goods - MC |
| Stock Item | FG-TEST-500ML |
| Stock UOM | Nos |
| ERP actual stock | 100 Nos |
| Optional Batch | FG-TEST-BATCH-01 |
| Active tagged stock before test | 40 Nos |
| Unused preprinted main tag | TST-STK1500 |
| Adoption quantity | 20 Nos |
| Expected remaining untagged | 40 Nos |

Use actual records from the test site when these names do not exist. Do not alter production stock
only to satisfy this test; first confirm the Warehouse has a submitted ERP stock balance.

## Setup

1. Confirm the Item is a stock Item and note whether it uses Batch or Serial Numbers.
2. Confirm the Warehouse belongs to the selected Company.
3. Register `TST-STK1500` in an active Tag Family or Tag Range Registry.
4. Create an active Location Card with **Location Purpose = Warehouse Operations** and **Current
   Warehouse = Finished Goods - MC**. Print or display its QR.
5. Add **Stock Adoption** to the test operator's CFG Kanban Operator Profile responsibilities.
6. For Cycle allocation, use a Supervisor profile with **Supervisor Override** enabled.

## Test A — Balance preview and adoption

1. Open the Logistics Operator Panel and scan the operator credential.
2. Scan the Warehouse Operations Card.
3. Select **Tag Existing ERP Stock** and select `FG-TEST-500ML` plus its Batch when applicable.
4. Confirm the panel shows ERP actual `100`, active tagged `40`, and available for tagging `60`.
5. Scan `TST-STK1500`, enter `20`, complete the packing timestamp and adoption reason, then confirm.

Expected:

- one **CFG Kanban Stock Adoption** is created with status **Adopted**;
- one Handling Unit is created for `TST-STK1500`, quantity `20`, in the selected Company/Warehouse;
- its origin is the Stock Adoption record;
- ERPNext stock remains exactly `100`;
- the Operational Inventory Balance report shows All Active Tagged `60` and Untagged ERP Qty `40`;
- Event History and Handling Unit Quantity Ledger contain one activation event.

## Test B — Duplicate and over-adoption protection

1. Retry the same browser request/event token. Expected: the original adoption is returned; no
   second record, Handling Unit or ledger event is created.
2. Try adopting `TST-STK1500` again. Expected: rejected because the tag is active.
3. Use another unused tag and request `41`. Expected: rejected because only `40` remains untagged.
4. For a Batch Item, omit Batch. Expected: no adoption and a Batch-required message.
5. For a serial Item, omit or duplicate Serial Numbers. Expected: no adoption.

## Test C — Optional Cycle allocation

1. Prepare an open Production Cycle for the same Company, Item, Stock UOM and destination Warehouse.
   Its Master must use **Stock Replenishment**, it must have no Work Order, and its remaining target
   must be at least `20`.
2. Adopt another `20`-unit tag and select this Cycle with an allocation reason.

Expected:

- Stock Adoption status becomes **Allocated to Cycle**;
- Handling Unit Reserved Qty increases by `20` and Available Qty becomes zero;
- Cycle Existing Stock Allocated Qty increases by `20` and shows Partially/Fully Allocated;
- Cycle Actual Good Qty, Job Cards and ERP stock remain unchanged;
- the Cycle is not automatically closed.

Negative tests:

- a Make-to-Order Cycle is rejected;
- a Cycle with an existing Work Order is rejected;
- Company, Item, UOM, Warehouse or Batch mismatch is rejected;
- allocation above the remaining Cycle target is rejected with an instruction to split the tag.

## Test D — Controlled allocation release

Call the release action as an authorized supervisor and enter a reason.

Expected:

- Stock Adoption status becomes **Allocation Released**;
- the reservation is removed and Handling Unit Available Qty returns to `20`;
- Cycle allocation totals are recalculated;
- an immutable release ledger entry and Event History row identify the supervisor and reason.

## Pass criteria

The test passes only if no action changes ERP actual stock, duplicate retries are idempotent, active
tags never exceed verified ERP quantity, and Cycle allocation never masquerades as production.

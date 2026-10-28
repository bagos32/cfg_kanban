# Acceptance Test — Loose Multi-Item WIP Bin

## Objective

Prove that one permanent bin can receive variable quantities of several authorized Items, accept
usage from repeated operation-card cycles for one Job Card, post one consolidated ERP consumption,
return unused WIP, and become reusable without weakening ERPNext stock control.

Run this on a test Company and Warehouse. Record all generated document names.

## Sample data

| Record | Sample |
|---|---|
| Finished Item | `TEST-LOOSE-WIP-FG` |
| Component A | `TEST-FLOUR` — 10 Kg required |
| Component B | `TEST-OIL` — 4 Kg required |
| Operation / Workstation | `Cooking` / `Kettle 1` |
| Source Warehouse | `Raw Material - TEST` |
| WIP Warehouse | `Work In Progress - TEST` |
| Permanent bin code | `LWIP-COOK-01` |
| First load | Flour 10 Kg and Oil 4 Kg |
| Recorded use | Flour 8 Kg and Oil 3 Kg |
| Expected unused return | Flour 2 Kg and Oil 1 Kg |

## A. Configure the physical bin

1. Create **CFG Kanban Handling Unit**.
2. Set **Tag Kind** to `Reusable Container`.
3. Set **Reusable Container Role** to `Loose Multi-Item WIP Bin`.
4. Enter the test Company and WIP Warehouse.
5. Under **Allowed Loose WIP Items**, add `TEST-FLOUR` and `TEST-OIL` as active.
6. Save and print one bin/slot QR.

Expected: the state is `Empty`; the record has no direct Item quantity; Standard full-bin capacity
is not requested.

Negative test: add a serial-controlled Item. Saving must be rejected.

## B. Configure the pool and Master

1. Create **CFG Kanban WIP Bin Pool**.
2. Set **WIP Bin Mode** to `Loose Multi-Item`.
3. Confirm posting shows `Accumulate until Work Order close`.
4. Select the Company, `Cooking`, and WIP Warehouse.
5. Add `LWIP-COOK-01`, map it to `Kettle 1`, and save.
6. Open the production Kanban Master using the sample BOM.
7. Set **Production Material Mode** to `Transfer to WIP by Job Card`.
8. On both sample BOM component rows, set **WIP Presentation** to
   `Loose Multi-Item WIP Bin` and select the pool.
9. Save.

Expected: Pool and Master validation succeeds only when Company, Operation, WIP Warehouse,
Workstation, role, and Item allow-list agree.

## C. Transfer variable material to WIP

1. Trigger and approve the production Card; create/submit the Work Order and Job Card normally.
2. In the production or exact operation Card, choose **Prepare Operation Materials**.
3. Open **Production Material Trace**.
4. Do not select the Flour ERP row with the mouse. Scan `CFG:QTY:MATERIAL:10`, scan its source Stock
   Tag if required, then scan `LWIP-COOK-01`.
5. Scan `CFG:QTY:MATERIAL:4`, scan the Oil source when required, then scan the same permanent bin.
6. Submit the native `Material Transfer for Manufacture`.

Odd-quantity scanner test: for a requirement of 21, scan `CFG:QTY:MATERIAL:+10`, scan it again,
then scan `CFG:QTY:MATERIAL:+1` before the source tag and Loose WIP Bin. Expected: the armed and
allocated quantity is 21. Scan `CFG:QTY:MATERIAL:4` first when deliberately replacing/resetting the
armed quantity rather than adding to it.

Expected:

- two separate WIP Bin Load episodes exist under one permanent bin;
- the bin state is `Accumulating`;
- submitted ERPNext stock shows 10 Kg Flour and 4 Kg Oil in WIP;
- any source Stock Tag is reduced only after ERP submission; and
- no child tag was printed or created merely to load the Loose bin.

Rapid-scan test: without waiting between devices, scan one Material Quantity, its required source
tag, and the Loose WIP Bin. Expected: the popup visibly queues scans received while classification
is running, processes all three in order, creates exactly one correct load, and never closes or
silently loses the source/bin identity. Scan an unrelated tag next. Expected: a red rejection names
the rejected scan, the popup remains open, and Scanner Ready is restored.

Visibility-refresh regression test: after Material Quantity is armed, scan the source Stock Tag.
Expected: the source field fills, the Loose WIP quantity controls remain visible, and the scanner
asks for the Loose WIP Bin without any `wrapper.toggle is not a function` error. Scan the Loose bin.
Expected: the load is allocated and the popup refreshes with the remaining ERP quantity.

Authorization regression test: the Loose-bin allow-list validation must use the Item from the
selected ERP material row. If the Item is not enabled in **Allowed Loose WIP Items**, the rejection
must name that Item (for example, `Item TPJ is not authorized...`). `Item None` is never a valid
authorization result.

Mixed-mode routing test: add one Standard Quantity WIP component and one ordinary tagged component
to the same test production. Scan each physical identity without first changing the ERP-row
dropdown. Expected: the Standard bin selects only its Standard row, the Loose bin selects an
allow-listed Loose row, and the ordinary Stock Tag becomes a source for its matching Item,
Warehouse, UOM, and Batch. No reusable bin code appears in the source-tag field.

Ambiguity test: authorize the same Loose bin for two pending rows that cannot be distinguished by
physical identity. Expected: the system holds the scan, displays the valid row numbers, accepts
`CFG:SELECT:n`, and continues the held scan without requiring the bin to be scanned again.

Negative test: try another Item not in **Allowed Loose WIP Items**. It must be rejected before load
creation.

## D. Accumulate use across operation-card cycles

1. Activate the operation Card for this Job Card.
2. Select **Record Loose WIP Use**.
3. Scan `LWIP-COOK-01`; select Flour and record 5 Kg.
4. Close that operation-card cycle after reporting its progress.
5. Activate the same reusable operation Card again for the same Job Card.
6. Record Flour 3 Kg and Oil 3 Kg from the same bin.
7. Inspect **CFG Kanban Loose WIP Usage**.

Expected: three immutable usage rows total Flour 8 Kg and Oil 3 Kg. Each row shows its requesting
operation-card Cycle while retaining the same material-owner Cycle, Work Order, and Job Card. No
ERP stock changed from usage recording alone.

Correction test: create one extra unposted use, choose **Undo**, enter a reason, and confirm its
status becomes `Reversed` without deleting the row or changing ERP stock.

## E. Final consolidated consumption and unused return

1. Complete every Job Card in the Work Order.
2. On the main Production Card choose **Prepare Consolidated Loose WIP Consumption**.
3. Enter the operator confirmation.
4. Inspect the Draft `Material Consumption for Manufacture`.

Expected: it contains Flour 8 Kg and Oil 3 Kg from the WIP Warehouse, is linked to the Kanban Cycle
and Work Order, and has the **Consolidated Loose WIP Consumption** control flag. It does not pretend
to be submitted stock.

5. Submit it using **Submit ERP Entry**.
6. Inspect the automatically prepared unused-material return Drafts.

Expected: Flour 2 Kg and Oil 1 Kg are returned from WIP to their original source Warehouses. The
bin remains unavailable until every return submits.

7. Submit every return Draft.
8. Refresh **WIP Bin Control** and the Handling Unit.

Expected:

- usage rows are `Posted`;
- load episodes are resolved/consumed;
- the bin state is `Empty` and reusable;
- ERPNext stock equals transfer minus actual consumption minus confirmed return movement; and
- the final Manufacture receipt can now proceed.

## F. Mandatory negative tests

1. Scan the bin for a different Work Order, Job Card, Operation, or Workstation while active.
   Expected: rejected.
2. Record more than the live available quantity. Expected: rejected with available quantity.
3. Try final consumption before all Job Cards complete. Expected: blocked with operation readiness.
4. Delete a consolidated Draft before submission. Expected: usage returns to `Recorded`, load/bin
   remain auditable, and no ERP stock changes.
5. Try Manufacture receipt while consumption or return is unresolved. Expected: blocked.
6. Open **WIP Bin Control**. Expected: Loose role/mode, active load count, loaded Items, accumulated
   reported use, state, and attention are visible without changing stock.

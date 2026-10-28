# Dispatch E3 Vehicle Claim and Loading Acceptance Test

## Purpose

Verify that one fully reserved Dispatch Plan can be claimed by exactly one Company-specific lorry,
physically loaded through the Logistics Operator Panel, and posted as a controlled ERPNext Material
Transfer. This test begins after the E2 Plan is **Ready for Vehicle**.

ERPNext remains the stock system of record. A claim or loading scan alone must not move stock.

## Prerequisites

1. Complete `TEST_DISPATCH_E1_PROFILE_LAUNCHER.md` and
   `TEST_DISPATCH_E2_PLAN_RESERVATION.md`.
2. Use an active **Vehicle Delivery** Dispatch Profile with:
   - a Company and source Warehouse;
   - an active **Internal Warehouse Transfer** Logistics Route;
   - Route transfer mode **Direct Transfer**;
   - source and destination Companies equal to the Profile Company;
   - Route source Warehouse equal to the Profile source Warehouse;
   - a Dispatch Responsibility assigned to the test operator;
   - optional **Auto Submit Stock Transfer** according to the test policy.
3. Create a non-group Warehouse in the same Company for the lorry. Set:
   - **Is Vehicle Warehouse** = enabled;
   - **Vehicle Reference** = `LORRY-E3-01`.
4. Create an active **Location Card** for that lorry Warehouse:
   - Location Purpose = **Warehouse Operations**;
   - Company = the Profile Company;
   - Current Warehouse = the lorry Warehouse;
   - Location Reference = `LORRY-E3-01`.
   Print its Warehouse Operations card.
5. Prepare one E2 Plan in **Ready for Vehicle**. Test either:
   - one or more fully reserved physical Stock Tags; or
   - verified untagged ERP stock; or
   - a mixture of both.
6. For a tagged line, reserve the complete physical tag quantity. If only part of a tag is needed,
   split/repack the exact load before this test. E3 deliberately rejects one tag being left in two
   Warehouses.

## A. Claim from the Dispatch Plan

1. Open **CFG Kanban → Logistics Operator Panel** and identify the operator.
2. Scan the Dispatch Operations card, open the Ready Plan, and confirm the state is
   **Ready for Vehicle**.
3. Select **Scan Lorry Card to Claim**.
4. Confirm the scanner state reads **Scan Lorry Card → DPL-...**.
5. Scan the printed `LORRY-E3-01` Warehouse Operations card.

Expected result:

- the Plan becomes **Vehicle Claimed**;
- Vehicle Warehouse and Vehicle Reference are snapshotted;
- exactly one linked Movement Manifest is created;
- the Manifest destination is the scanned lorry Warehouse;
- the Manifest contains one line for every active Plan Allocation;
- no Stock Entry exists yet;
- selecting **Open Loading Manifest** opens the same Manifest.

## B. Alternative claim from the lorry card

Use a separate Ready Plan for this path.

1. Return to safe lookup mode and scan the `LORRY-E3-01` Warehouse Operations card.
2. Under **Ready Loads for this Lorry**, verify only authorized, same-Company, Ready Plans appear.
3. Select **Claim This Load** for the correct Plan.

Expected result: the same atomic claim and Manifest result described in section A. A Plan fixed to a
different lorry Warehouse must not be claimable.

## C. Negative claim controls

Verify each rejection without changing the Plan:

1. scan a normal Warehouse card that is not marked as a vehicle Warehouse;
2. scan a lorry Warehouse card belonging to another Company;
3. attempt to claim an incompletely reserved Plan;
4. attempt to claim a Plan that another lorry already claimed;
5. attempt to use a Route that is inactive, not Direct Transfer, or has the wrong source.

The Plan must retain its previous state and must not gain a second Manifest.

## D. Confirm physical loading

1. Open the linked Manifest.
2. For tagged allocations, select **Start Tag Loading Scan** and scan each exact reserved Stock Tag
   only when it is physically placed into the lorry.
3. Stop scanning when the tagged loading is complete.
4. For every untagged line, physically verify/pick the quantity, then select
   **Confirm Physical Pick**.

Expected result:

- a wrong, unreserved, wrong-Company, wrong-Warehouse or duplicate tag is rejected;
- accepted lines show **Physical loading confirmed**;
- the Plan becomes **Loading**;
- Allocation and Manifest Line retain operator and timestamp evidence;
- ERP stock and tag Warehouse remain unchanged at this stage.

## E. Prepare and dispatch

1. Before all lines are confirmed, try **Confirm Loading / Prepare Dispatch**.
   It must reject and identify the unconfirmed line.
2. Confirm every line, return to safe lookup mode, then select
   **Confirm Loading / Prepare Dispatch**.
3. Confirm the Plan becomes **Ready to Dispatch** and the Manifest becomes **Prepared**.
4. Select **Confirm Dispatch**. Supply only genuinely missing mandatory ERP fields if the panel asks.

Expected result with auto-submit enabled:

- one submitted ERPNext **Material Transfer** Stock Entry moves the exact quantities from the source
  Warehouse to `LORRY-E3-01`;
- the Manifest becomes **Received** because this is a Direct Transfer;
- tagged Handling Units move to the lorry Warehouse and their reservations clear;
- untagged stock follows the submitted ERP Stock Entry;
- Dispatch Allocations become **Loaded**;
- Plan lines and Plan become **Loaded** with the loaded totals;
- Event and ERP Command audit records identify the Plan, Manifest, operator and Stock Entry.

Expected result with auto-submit disabled: the controlled Stock Entry remains Draft/pending according
to policy, and the Plan must not become **Loaded** until ERPNext submission feedback is received.

## F. Release a claim before ERP posting

Use a separate Ready Plan.

1. Claim the lorry and optionally confirm some loading lines.
2. As an authorized Supervisor, open the linked Draft/Prepared Manifest and select
   **Cancel Manifest** with a reason.

Expected result:

- the Manifest is retained as **Cancelled**;
- the Plan returns to **Ready for Vehicle**;
- Vehicle and Manifest claim fields clear;
- E2 tagged/untagged reservations remain intact;
- the cancelled Manifest retains its loading evidence for audit, while the preserved Allocations
  are reset so the next claim starts with no loading confirmations;
- another valid lorry may claim the Plan;
- once an ERP document exists, this shortcut is rejected and controlled recovery is required.

## Acceptance result

Pass E3 only when claim concurrency, physical loading evidence, cancellation/reclaim, ERP posting,
Handling Unit movement, Plan closure, and all negative controls behave as stated. Do not treat E4
customer fulfilment as accepted merely because the lorry Material Transfer succeeds.

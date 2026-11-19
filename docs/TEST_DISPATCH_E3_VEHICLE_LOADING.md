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


## Checkpoint recorded 19 November 2026

Runtime revision inspected: `d01b40d` (`Fix dispatch Sales Order quantities`). No runtime changes
are included in this checkpoint. The checkpoint adds actual-function behavioral regression tests;
it does not replace site acceptance or establish E3 as passed.

Offline command:

```bash
python3 -B -m unittest cfg_kanban.tests.test_dispatch_e3_behavior
```

Result: **18 tests passed** using an in-memory document/DB double. Covered: one Manifest per
sequential vehicle claim/replay, rejection of a later different vehicle, row-lock request issuance,
Company/route/responsibility restrictions, full physical-tag quantity, physical loading evidence,
untagged physical pick, prepare guards, loaded-feedback state updates, and pre-ERP claim
release/reclaim while preserving reservations.

Limits: issuing a row-lock SQL statement is not proof of real locking. These tests do not run
simultaneous MariaDB transactions, invoke native Stock Entry submission, validate ERP balances,
exercise failure rollback, or operate a browser/camera/kiosk. The loading-feedback test calls the
Plan notification function directly; the ERP submission hook and tag location movement remain
separate live checks.

### Compact live checkpoint record

Run the detailed A–F procedures above on the development site. Use separate Plans where stated.
Record evidence here; leave a failed or unrun step visible. Do not infer acceptance from an empty
record or the offline test count.

- Test site: **Not recorded**
- Deployed commit (`git log -1 --oneline`): **Not recorded**
- Tester / date: **Not recorded**
- Company / source Warehouse / lorry Warehouse: **Not recorded**
- Dispatch Profile / route: **Not recorded**
- Tagged / untagged test Items, UOMs and quantities: **Not recorded**

| Check | Evidence required | Site result |
|---|---|---|
| Claim and lookup | Plan ID, lorry Card ID, one linked Manifest, no ERP document yet | Not run |
| Concurrent drivers and replay | Two simultaneous claims; exactly one winner/Manifest; same-vehicle retry reuses it | Not run |
| Rejection controls | Wrong Company, non-vehicle card, missing responsibility, incomplete reservation and invalid route leave no claim | Not run |
| Tagged and untagged loading | Exact-tag scan and explicit untagged pick, operator/time; wrong scan and premature prepare rejected | Not run |
| Draft ERP policy | Draft Stock Entry ID; Plan remains pending; no tag movement or stock posting | Not run |
| Submitted ERP policy | Submitted Stock Entry ID and rows; exact stock movement, tag locations and reservations; Plan Loaded | Not run |
| Cancellation and reclaim | Cancelled pre-ERP Manifest, preserved reservations, new claim to another lorry; ERP-linked shortcut rejected | Not run |
| Floor operation | Actual tablet/fixed scanner, camera where used, focus after success/error/cancel | Not run |

Overall E3 live acceptance: **Not recorded / pending**. The locked Dispatch baseline requires E3
acceptance before E4 development. If the owner explicitly defers that gate, record the decision and
its scope separately; deferral does not change these site results to Passed.


### Owner-reported site result — 19 November 2026

The owner confirmed: “yes, i have tested E3 and it works. manage to load the goods into lorry with
last minuite lorry selection.” This records a successful owner-reported late vehicle selection and
lorry-loading path and the instruction to continue E4A development. No independent site session was
run by Codex. The deployed SHA, ERP/Plan/Manifest IDs, concurrent-driver, rollback and full negative
acceptance evidence above have not been supplied and remain pending; do not relabel those rows as
Passed. The owner also confirmed that E4A must handle both tagged and untagged ERP quantities.

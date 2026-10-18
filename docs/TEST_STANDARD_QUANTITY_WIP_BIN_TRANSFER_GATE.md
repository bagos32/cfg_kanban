# Standard Quantity WIP Bin — Full Transfer and Consumption Test Guide

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Test gate:** Full Job Card transfer/consume lifecycle and supervisor partial-bin exception
**Status:** Ready for controlled server acceptance testing
**Date:** 18 October 2026

## 1. What this test covers

This package adds the scanner and audit path that will load a visually controlled, fixed-capacity
reusable WIP bin from either:

- a tagged source quantity;
- an optional physical tag; or
- normal ERPNext quantity without a physical source tag.

The package also proves that:

- the permanent WIP-bin identity is separate from Item, Batch, and quantity;
- one load reserves exactly **Qty per Full Bin**;
- a source Stock Tag is not deducted while the ERPNext transfer remains Draft;
- submitted ERPNext transfer feedback is the only event that makes a load `Ready`;
- cancelling a Draft allocation releases the source reservation;
- cancelling a submitted transfer restores the source-tag balance through an audit event; and
- mixed BOM material policies remain independent row by row.

The package also binds each Ready bin to the exact Job Card's Draft Material Consumption, returns
the bin to Empty only after ERPNext submits that consumption, and prevents Job Card/Manufacture
completion while a physical load remains unconsumed.

## 2. Acceptance rule for this gate

Record this gate as passed only after both the transfer tests and the Ready-bin consumption tests
below pass on the development server.

Do not bypass the Work Order safety stop by editing database values, changing a Master after its
Cycle is released, or attaching a manually created Stock Entry to a Cycle. Those actions would not
represent the supported workflow.

## 3. Suggested sample data

Use dedicated test records. Replace the abbreviations only if your ERPNext naming series requires
different values.

| Record | Suggested value |
|---|---|
| Company | Existing manufacturing company |
| Finished Item | `WIP-BIN-PILOT-FG` |
| Component Item | `WIP-BIN-PILOT-RM` |
| Component Stock UOM | `Kg` |
| Operation | `Cooking` |
| Workstation | `Kettle` |
| Source Warehouse | Existing raw-material Warehouse |
| WIP Warehouse | Existing WIP Warehouse |
| Full-bin quantity | `10 Kg` |
| Source Stock Tag | `WIP-RM-0025` containing `25 Kg` |
| Reusable WIP Bin 1 | `WIP-BIN-KETTLE-01` |
| Reusable WIP Bin 2 | `WIP-BIN-KETTLE-02` |
| WIP Bin Pool | `Cooking 10 Kg WIP Bins` |

The Component Item must not be serial controlled. A Batch may be used, but the source Stock Tag,
ERP transfer row, and later WIP-bin load must all use the same Batch.

## 4. Deployment smoke check

After the server migration/build/cache-clear/restart has completed:

1. Open **CFG Kanban Workspace**.
2. Open **CFG Kanban WIP Bin Pool**.
3. Open **CFG Kanban WIP Bin Load**.
4. Open **CFG Kanban Handling Unit Quantity Ledger**.
5. Open the Production Operator panel and select **Hands-free Scanner Controls**.
6. Select **Print Command Labels**.

Expected result:

- all three DocTypes open without a missing-field error;
- the command sheet contains **WIP Bin: Use ERP-only Source**;
- its exact payload is `CFG:CMD:NO_SOURCE`; and
- no migration, JavaScript, or permission error appears.

## 5. Create the two permanent WIP-bin identities

Create two **CFG Kanban Handling Unit** records.

For each record set:

| Screen label (`fieldname`) | Value |
|---|---|
| Preprinted Tag / Handling Unit ID (`handling_unit_id`) | `WIP-BIN-KETTLE-01`, then `WIP-BIN-KETTLE-02` |
| Handling Unit Type (`handling_unit_type`) | Reusable Box, Tote, or the actual physical type |
| Tag Kind (`tag_kind`) | Reusable Container |
| Reusable Container Role (`reusable_container_role`) | Standard Quantity WIP Bin |
| Inventory Company (`inventory_company`) | Manufacturing company |
| Current Warehouse (`current_warehouse`) | WIP Warehouse |
| Allow Mixed Item / Batch Content (`allow_mixed_content`) | Disabled |

Save both records.

Expected result:

- Item and Stock UOM are not required for the permanent empty bin;
- WIP Bin State is `Empty`;
- the bin remains a permanent reusable identity; and
- the bin does not display an independent stock quantity.

Negative check:

1. Try to enable **Allow Mixed Item / Batch Content** for a Standard Quantity WIP Bin.
2. Try to assign the bin to a Warehouse belonging to another Company.

Expected result: validation rejects both unsafe configurations.

## 6. Create the WIP Bin Pool

Create **CFG Kanban WIP Bin Pool**:

| Screen label (`fieldname`) | Value |
|---|---|
| Pool Name (`pool_name`) | `Cooking 10 Kg WIP Bins` |
| Active (`active`) | Enabled |
| Company (`company`) | Manufacturing company |
| Operation (`operation`) | Cooking |
| WIP Warehouse (`wip_warehouse`) | Test WIP Warehouse |
| Require Bin Scan (`require_bin_scan`) | Enabled |
| Require Full-bin Consumption (`require_full_bin_consumption`) | Enabled |
| Allow Supervisor Partial Exception (`allow_supervisor_partial_exception`) | Disabled for full-bin tests; enable only for Section 10.13 |

In **Approved Physical WIP Bins**, add both bins and set Workstation to `Kettle`.

Expected result:

- the Pool saves;
- both bins are visible with their Workstation;
- a bin already assigned to another Pool cannot be reused; and
- a normal logistics container cannot be added as a Standard Quantity WIP Bin.

## 7. Prepare the Item, BOM, and production Master

### 7.1 Item and BOM

1. Ensure `WIP-BIN-PILOT-RM` is a stock Item with Stock UOM `Kg`.
2. Ensure **Has Serial No** is disabled.
3. Create a BOM for `WIP-BIN-PILOT-FG`.
4. Add Operation `Cooking` at Workstation `Kettle`.
5. Assign the component's **Item Operation** to `Cooking`.
6. Use a planned component quantity that is a multiple of `10 Kg`, for example `20 Kg`.

Expected result: the BOM saves with a deterministic Item Operation.

### 7.2 Kanban Master

Create or duplicate a test-only Production **CFG Kanban Master**.

Set:

| Screen label (`fieldname`) | Value |
|---|---|
| Control Type (`control_type`) | Production |
| Item (`item_code`) | `WIP-BIN-PILOT-FG` |
| BOM (`bom`) | Test BOM |
| Production Material Mode (`production_material_mode`) | Transfer to WIP by Job Card |
| WIP Warehouse (`wip_warehouse`) | Test WIP Warehouse |

Synchronize **BOM Component Material Flow** from the BOM. On the
`WIP-BIN-PILOT-RM / Cooking` row set:

| Screen label (`fieldname`) | Value |
|---|---|
| Source Warehouse (`source_warehouse`) | Test raw-material Warehouse |
| WIP Presentation (`wip_presentation_method`) | Standard Quantity Reusable WIP Bin |
| WIP Bin Pool (`wip_bin_pool`) | `Cooking 10 Kg WIP Bins` |
| Qty per Full Bin (`standard_bin_qty`) | `10` |

If the BOM has other materials, leave at least one other material on
`Standard ERP / Tag Flow` to prove mixed row policies can coexist.

Expected result:

- the Master saves;
- the component Item, Item Operation, quantity, and Stock UOM remain synchronized from the BOM;
- only the selected component row has the WIP-bin method; and
- ordinary material rows retain their existing ERP/tag policy.

## 8. Configuration negative tests

Perform these one at a time, then restore the correct value.

### 8.1 Wrong production mode

Change Production Material Mode to `Transfer to WIP by Work Order`.

Expected result: the Master refuses the configuration because Standard Quantity WIP Bins require
`Transfer to WIP by Job Card`.

### 8.2 Missing Item Operation

Use a BOM component without Item Operation and resynchronize the Master.

Expected result: validation identifies the material row and requires an Item Operation.

### 8.3 Wrong Pool operation or Company

Select a Pool belonging to another Operation or Company.

Expected result: validation refuses the mismatch.

### 8.4 Zero standard quantity

Set Qty per Full Bin to `0`.

Expected result: the Master requires a positive quantity.

### 8.5 Serial-controlled component

Use a serial-controlled test component with the WIP-bin method.

Expected result: validation says the serial-controlled Item must use `Standard ERP / Tag Flow` so
exact serial membership is preserved.

## 9. Work Order release test

1. Create and print a test Production Kanban Card from the configured Master.
2. Scan the Card in the Production Operator panel.
3. Trigger the production signal and complete the normal Supervisor approval step.

Expected result: the approved production flow creates/submits the Work Order according to its normal
automation policy and ERPNext creates the operation Job Cards. No Stock Entry or WIP Bin Load is
created until an operator prepares the operation materials.

## 10. Full transfer-and-consumption acceptance test

### 10.1 Required source Stock Tag path

Precondition:

- Item production-input tag policy is `Required Physical Tag`;
- `WIP-RM-0025` is active, Released, in the source Warehouse, and contains `25 Kg`;
- the Draft Job Card Material Transfer requires `20 Kg`; and
- both reusable bins are Empty.

Steps:

1. Scan the Production or correct Operation Card.
2. Select **Prepare Operation Materials**.
3. Confirm creation of the Draft `Material Transfer for Manufacture`.
4. Open **Scan Material Tags / Production Material Trace**.
5. If several fixed-bin rows exist, scan `CFG:SELECT:1` for the required row.
6. Scan source Stock Tag `WIP-RM-0025`.
7. Scan empty WIP bin `WIP-BIN-KETTLE-01`.

Expected result before ERP submission:

- one `CFG Kanban WIP Bin Load` exists with status `Transfer Draft`;
- its actual and standard quantities are `10 Kg`;
- it records the exact Cycle, Work Order, Job Card, Operation, Workstation, source tag, source
  Warehouse, WIP Warehouse, and Draft Stock Entry row;
- source tag current quantity remains `25 Kg`;
- source tag reserved quantity becomes `10 Kg`;
- source tag available quantity becomes `15 Kg`;
- bin state becomes `Reserved`; and
- ERPNext stock has not moved.

8. Scan `WIP-RM-0025` again.
9. Scan `WIP-BIN-KETTLE-02`.

Expected result before ERP submission:

- a second `Transfer Draft` load exists for `10 Kg`;
- the source tag remains current `25 Kg`, reserved `20 Kg`, available `5 Kg`;
- both bins are Reserved; and
- total WIP-bin allocation equals the ERP row quantity of `20 Kg`.

10. Scan `CFG:CMD:SUBMIT_MATERIALS` or use the controlled Submit ERP Entry action.

Expected result after successful native ERPNext submission:

- ERPNext moves `20 Kg` from source Warehouse to WIP Warehouse;
- both WIP Bin Loads become `Ready`;
- both reusable bins become `Ready`;
- the source Stock Tag becomes current `5 Kg`, reserved `0`, available `5 Kg`;
- each Load contains a source reservation and source confirmation ledger link; and
- no detachable child Stock Tag is created for either WIP bin.

### 10.2 ERP-only source path

Precondition: use a second component row whose production-input tag policy is `No Physical Tag`.

Steps:

1. Select its numbered WIP material row.
2. Scan the empty reusable WIP bin directly.

Expected result:

- the Load records no Source Handling Unit;
- the Draft ERP transfer remains the stock authority; and
- submission is refused until every fixed-bin ERP row is fully covered.

### 10.3 Optional source path

Precondition: use a component whose production-input tag policy is `Optional Physical Tag`.

Steps:

1. Select the optional material row.
2. Scan `CFG:CMD:NO_SOURCE`.
3. Scan the empty WIP bin.

Expected result: the load is staged without a source Handling Unit, while the native Stock Entry
still controls the material movement.

Repeat with a valid source Stock Tag instead of `CFG:CMD:NO_SOURCE`.

Expected result: the fixed quantity is reserved and later deducted from that source tag.

### 10.4 Cancel before ERP submission

1. Allocate one source tag and one WIP bin.
2. In Current Trace Lines, select **Cancel** for that WIP Bin Load.

Expected result:

- Load status becomes `Cancelled` and remains available for audit;
- source reserved quantity is released;
- source current quantity is unchanged;
- bin state returns to `Empty`; and
- no ERPNext stock movement occurs.

### 10.5 Submission coverage guard

Create a Draft ERP row for `20 Kg`, but allocate only one `10 Kg` bin. Try to submit.

Expected result: submission is rejected because WIP Bin Loads cover only `10 of 20 Kg`.

### 10.6 Invalid scans

Test each case separately:

- source tag contains the wrong Item;
- source tag belongs to another Company;
- source tag is in another Warehouse;
- source tag has the wrong UOM or Batch;
- source tag has less than `10 Kg` available;
- source tag is loaded inside a logistics container;
- scanned reusable bin is not a Standard Quantity WIP Bin;
- WIP bin belongs to another Pool or Warehouse;
- WIP bin is already Reserved/Ready; and
- source scan is omitted when the Item requires a physical tag.

Expected result: every case is rejected before a load or stock mutation is created, with a message
identifying the mismatch.

### 10.7 ERP cancellation after submission

Cancel the submitted Material Transfer using an authorized ERPNext user.

Expected result:

- each related Load becomes `Reversed`;
- each reusable bin becomes `Empty` for a transfer reversal;
- the source Stock Tag quantity is restored through `WIP Bin Load Reversal` ledger evidence;
- the Load records its source reversal ledger; and
- the historical Load record is not deleted.

### 10.8 Create the Job Card consumption Draft

1. Return to the Production or matching Operation Card after both bins are `Ready`.
2. Confirm that its Job Card shows **2 Ready bin(s), 20 total quantity**.
3. Select **Consume Ready WIP Bins** and enter the operator confirmation.

Expected result:

- one Draft native `Material Consumption for Manufacture` is created for the exact Job Card;
- its source Warehouse is the configured WIP Warehouse;
- its quantity is `20 Kg` and its Item/UOM/Batch agree with the Ready loads;
- both loads remain `Ready` until they are physically scanned; and
- ERPNext stock is unchanged.

### 10.9 Scan and correct Ready-bin consumption

1. In the opened Production Material Trace dialog, scan `WIP-BIN-KETTLE-01`.

Expected result: the matching load becomes `Consumption Draft`, the bin becomes `In Use`, and the
dialog shows `10 / 20 Kg` covered. ERPNext stock is still unchanged.

2. Select **Cancel** on that Draft WIP Bin line.

Expected result: the load and physical bin return to `Ready`; the Draft Stock Entry remains open;
no stock is consumed and no audit history is deleted.

3. Scan `WIP-BIN-KETTLE-01` again, followed by `WIP-BIN-KETTLE-02`.

Expected result: both loads become `Consumption Draft`, both bins become `In Use`, and the exact
ERP row is fully covered.

### 10.10 Consumption submission and Empty-bin feedback

1. Scan `CFG:CMD:SUBMIT_MATERIALS` or select **Submit ERP Entry**.

Expected result after successful native ERPNext submission:

- ERPNext consumes `20 Kg` from the WIP Warehouse for the exact Work Order/Job Card;
- both WIP Bin Loads become `Consumed`;
- both permanent reusable bins become `Empty` and may be loaded again;
- each Load keeps both its transfer and consumption Stock Entry links; and
- the submitted document, load history and Kanban event timeline agree.

### 10.11 Completion guards

Repeat the flow with one Ready bin and try each action before submitting consumption:

1. complete/submit the Job Card; and
2. prepare or submit Manufacture receipt.

Expected result: Job Card completion identifies the active bin load, and Manufacture submission
requires the WIP-bin consumption first. After consumption is submitted, both actions may proceed
subject to their normal ERPNext requirements.

### 10.12 Submitted consumption cancellation

Using an authorized ERPNext user, cancel a submitted WIP-bin consumption Stock Entry.

Expected result: related loads become `Reversed`, physical bins become `Exception`, the Cycle is
blocked for supervisor reconciliation, a Critical **CFG Kanban Exception** and Open
**CFG Kanban WIP Bin Reconciliation** are created, and the system does not falsely return those
bins to Empty.

### 10.13 Controlled supervisor partial-bin exception

Use a dedicated test Pool and do not enable this policy in live production until the exception
method has been approved.

Preconditions:

1. Enable **Allow Supervisor Partial-bin Exception** on the test Pool.
2. Use a Draft transfer row whose remaining quantity is below one full bin, for example `5 Kg`
   remaining against a `10 Kg` standard bin.
3. First sign in with a normal Operator QR.

Negative test:

1. Scan `CFG:QTY:MATERIAL:5`, then attempt to allocate the bin.

Expected result: the panel refuses the action and requires a Kanban Supervisor with Override
permission.

Controlled approval test:

1. Switch operator and scan a Supervisor QR whose profile has **Override** enabled.
2. Reopen Production Material Trace.
3. Select the correct material row.
4. Scan `CFG:QTY:MATERIAL:5`. For an exact final ERP remainder, the standard reason is populated;
   otherwise enter a specific reason.
5. Scan the source Stock Tag when required, then scan the Empty reusable WIP bin.

Expected result before ERP submission:

- the Load is `Transfer Draft` with Standard Qty `10 Kg` and Actual Qty `5 Kg`;
- **Partial-bin Exception** is enabled;
- Exception Reason, approving Employee, terminal ERP User, approval time, and operator session are
  recorded;
- a `WIP Bin Partial Exception Approved` timeline event exists; and
- source reservation is exactly `5 Kg`, not `10 Kg`.

6. Submit the native Material Transfer.
7. Prepare WIP-bin consumption for the same Job Card and scan the partial bin.
8. Submit the native Material Consumption.

Expected result:

- ERPNext transfers and consumes exactly `5 Kg`;
- the partial Load progresses `Ready` → `Consumption Draft` → `Consumed`;
- the reusable bin returns to `Empty`; and
- the immutable partial exception evidence remains on the completed Load.

Additional negative tests:

- disable the Pool policy and retry;
- omit the exception reason;
- request zero, a negative quantity, a quantity equal to/above `10 Kg`, or more than the ERP row
  remainder; and
- use a Supervisor profile without Override permission.

Expected result: every unsafe attempt is rejected without reserving a source tag or physical bin.

Scan `CFG:CMD:FULL_BIN` to clear partial mode and return the trace dialog to normal full-bin
allocation.

### 10.14 Reconcile a cancelled submitted consumption

Run both outcomes on separate test loads. Never use database edits to release the bin.

#### Outcome A — exact material physically restored

1. After Section 10.12, rescan the Production Card or the exact Operation Card.
2. Confirm the red **WIP Bin supervisor reconciliation required** block identifies the bin, Item,
   quantity, Job Card, and cancelled Stock Entry.
3. With a normal Operator QR, try to reconcile it.

Expected result: the panel requires a Supervisor QR with **Override** permission.

4. Switch to that Supervisor QR and select **Reconcile**.
5. Physically verify that the exact Item, Batch, and complete reversed quantity are back in the
   affected bin.
6. Select **Material Restored to Bin**, scan that exact physical bin, enter the verification
   reason, and confirm. Scanner-only selection may use `CFG:SELECT:1` and
   `CFG:CMD:CONFIRM`.

Expected result:

- the original consumed Load stays `Reversed` and remains linked to the cancelled Stock Entry;
- the reconciliation becomes `Resolved` with Supervisor Employee, operator session, terminal User,
  timestamp, reason, and exact physical evidence;
- a new Load linked by **Recovered From Reversed Load** becomes `Ready` for the same exact
  Item/Batch/quantity/Job Card;
- the permanent bin changes from `Exception` to `Ready`;
- the Critical Exception becomes `Resolved`; and
- after all bins from that cancelled entry are reconciled, the generic `Stock Entry Cancelled`
  Cycle/Card hold returns to its audited pre-cancellation state; and
- the recovered Ready load can follow the normal Job Card consumption scanner again.

#### Outcome B — bin empty after ERP correction

1. Use a second cancelled-consumption test whose physical bin is actually empty.
2. In ERPNext, create and submit an authorized correction Stock Entry after the hold was raised.
   It must remove the exact reversed Item, Batch, Stock UOM, and quantity from the WIP Warehouse.
3. In the Kanban reconciliation select **Bin Empty after ERP Correction**, scan the affected bin,
   link that submitted Stock Entry, enter the physical verification reason, and confirm. Scanner
   selection may use `CFG:SELECT:2`.

Expected result:

- Draft, cancelled, wrong-Company, older, wrong-Item, wrong-Batch, wrong-UOM, wrong-Warehouse, and
  wrong-quantity correction documents are rejected;
- the original Load remains `Reversed`;
- no replacement Ready load is created;
- the bin changes from `Exception` to `Empty` only after exact ERP evidence passes;
- the reconciliation and Critical Exception become `Resolved`; and
- the generic cancellation hold is released only after every affected bin is resolved; and
- the Event timeline identifies the decision, Supervisor, correction, and reason.

### 10.15 Reconcile a cancelled submitted transfer

Use separate submitted transfer/load records for both outcomes below. Cancelling a Draft transfer
is not this test: a Draft has not moved ERP stock and follows the normal Draft release path.

1. Submit a Material Transfer for Manufacture whose scanned WIP Bin Load is `Ready`.
2. Confirm the source Stock Tag was reduced when a tagged source was used.
3. Cancel that submitted Stock Entry using an authorized ERPNext user.

Expected result:

- the original Load becomes `Reversed` and the physical WIP bin becomes `Exception`, not `Empty`;
- an Open reconciliation with **Cancelled ERP Movement = Transfer Cancellation** and a Critical
  Exception are created;
- the Cycle/Card receives the normal cancelled-Stock-Entry hold;
- ERPNext returns stock to the source Warehouse; and
- when a source Stock Tag was used, CFG Kanban restores its quantity but immediately reserves that
  same quantity so it cannot be used before physical reconciliation.

#### Outcome A — material physically returned to source

1. Physically return the complete Item/Batch/quantity from the WIP bin to its original source.
2. Open the red reconciliation block using a Supervisor QR with Override permission.
3. Select **Material Returned to Source**.
4. Scan the affected WIP bin. If the original transfer used a source Stock Tag, scan that exact
   source tag as the next scan. Enter the reason and confirm. `CFG:SELECT:1` may select this outcome.

Expected result:

- a wrong WIP bin or wrong source tag is rejected;
- the source-tag safety reservation is released without changing its restored current quantity;
- the original Load remains `Reversed`;
- no new Ready load is created;
- the reusable WIP bin becomes `Empty`; and
- the reconciliation, Critical Exception, event evidence and final Cycle/Card release are audited.

#### Outcome B — material physically remains in the WIP bin

1. Leave the exact physical material in the affected WIP bin.
2. Create and submit a new ERPNext `Material Transfer for Manufacture` after the hold was raised.
   It must contain one unused row for the same Work Order/Job Card, Item, Batch, Stock UOM, exact
   quantity, original source Warehouse and WIP Warehouse.
3. Select **Material Remains in WIP after ERP Correction**, scan the affected WIP bin, link the new
   submitted correction, enter the reason, and confirm. `CFG:SELECT:2` may select this outcome.

Expected result:

- Draft, cancelled, older, wrong-purpose, wrong-Company, wrong-Work-Order/Job-Card, wrong-Item,
  wrong-Batch, wrong-UOM, wrong-Warehouse, wrong-quantity and already-used correction rows are
  rejected;
- the original Load remains `Reversed`;
- a separately linked Load becomes `Ready` against the correction row;
- the reusable bin becomes `Ready` and may follow normal Job Card consumption;
- when a source Stock Tag was used, its safety reservation and quantity are reduced together by the
  exact corrected quantity; and
- the reconciliation and Critical Exception become `Resolved`, with immutable Supervisor and ERP
  evidence.

## 11. Evidence to capture

For each test, record:

- tester name and date/time;
- Company, Master, Card, Cycle, Work Order, and Job Card;
- Stock Entry number and document status;
- source tag current/reserved/available quantity before and after;
- reusable bin identity and WIP Bin State;
- WIP Bin Load number and status;
- quantity-ledger event names;
- screenshots of the scanner dialog and any rejection message; and
- pass/fail plus exact unexpected result.

## 12. Current result form

| Test | Result | Evidence / notes |
|---|---|---|
| Deployment and command-label smoke check | Pending | |
| Permanent WIP-bin identity validation | Pending | |
| WIP Bin Pool validation | Pending | |
| Master material-row configuration | Pending | |
| Mixed material-policy configuration | Pending | |
| Serial-controlled Item rejection | Pending | |
| Work Order release | Pending | |
| Required source transfer scanner | Pending | |
| ERP-only source transfer scanner | Pending | |
| Optional source transfer scanner | Pending | |
| Draft allocation cancellation | Pending | |
| Complete-row submission guard | Pending | |
| ERP transfer cancellation reversal | Pending | |
| Ready-bin consumption Draft | Pending | |
| Consumption scan cancellation/retry | Pending | |
| Consumption submission to Consumed/Empty | Pending | |
| Job Card and Manufacture completion guards | Pending | |
| Submitted consumption cancellation/Exception | Pending | |
| Supervisor restored-material recovery to Ready | Pending | |
| Supervisor ERP-corrected empty-bin recovery | Pending | |
| Submitted transfer cancellation creates Exception/source hold | Pending | |
| Supervisor material-returned-to-source recovery | Pending | |
| Supervisor material-remains-in-WIP recovery | Pending | |

## 13. Final decision for this gate

Activate a live Master using Standard Quantity Reusable WIP Bins only after Sections 4–10 pass and
the captured evidence proves that ERPNext stock, WIP Bin Load status, physical bin state, and Job
Card scope agree at every stage.

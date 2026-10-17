# Standard Quantity WIP Bin — Transfer Scanner Gate Test Guide

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Test gate:** Draft transfer allocation foundation  
**Status:** Partial acceptance only — do not use on a live production Master yet  
**Date:** 16 October 2026

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

The next package will add scanning and consuming the Ready bin against the correct Job Card. Until
that is complete, CFG Kanban deliberately blocks Work Order creation for any Master containing the
WIP-bin method. This prevents a transfer-only deployment from placing material in WIP without a
controlled floor consumption path.

## 2. Acceptance rule for this gate

This gate may be recorded as **configuration and safety checks passed**, but it must not be recorded
as a complete production-flow acceptance test.

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
| Allow Supervisor Partial Exception (`allow_supervisor_partial_exception`) | Disabled |

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

## 9. Current Work Order safety-stop test

1. Create and print a test Production Kanban Card from the configured Master.
2. Scan the Card in the Production Operator panel.
3. Trigger the production signal and complete the normal Supervisor approval step.

Expected result:

- no Work Order is created;
- no Job Card is created;
- no Stock Entry is created;
- no WIP Bin Load is created;
- no Handling Unit quantity ledger entry is created; and
- the message explains that Draft transfer scanning is installed but operation-time consumption
  scanning is not enabled yet.

This is the correct result for the current gate.

## 10. Deferred full transfer-scanner acceptance test

Run this section only after the next WIP-bin consumption package removes the Work Order safety
stop. It is included now so the final feature can be tested without inventing a new procedure.

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
| Work Order safety stop | Pending | |
| Required source transfer scanner | Deferred until consumption gate | |
| ERP-only source transfer scanner | Deferred until consumption gate | |
| Optional source transfer scanner | Deferred until consumption gate | |
| Draft allocation cancellation | Deferred until consumption gate | |
| Complete-row submission guard | Deferred until consumption gate | |
| ERP cancellation reversal | Deferred until consumption gate | |

## 13. Final decision for this gate

The current gate passes only when Sections 4–9 pass. Do not activate a live Master using Standard
Quantity Reusable WIP Bins yet. Full production acceptance requires Sections 10.1–10.7 plus the next
Job Card consumption and Empty-bin lifecycle test.

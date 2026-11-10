# CFG Kanban Acceptance Test — Minimal PPHU Production

Status: development acceptance procedure; not production acceptance

Revision: 1.0

Date: 10 November 2026

## 1. Purpose and minimum scope

This procedure runs one complete, scanner-first PPHU production test using the minimum practical
number of production cards and ERP manufacturing records:

- one Production Kanban Master;
- one Physical Batch Card;
- one Work Order;
- one Job Card and controlled Operation;
- one reusable Hopper identity;
- one batch-controlled raw-material Stock Tag; and
- one finished unit.

It validates the current PPHU traceability slice: initial output serial, Hopper boundary, and
material Batch boundary. These PPHU events are immutable operational evidence only. They do not
move ERP stock, release QC material, submit manufacturing documents, or control machinery.

## 2. Sample data

Use these names or equivalent isolated records:

| Record | Sample value |
|---|---|
| Company | Wasilah FZD Trading Sdn Bhd |
| Finished Item | `PPHU-TEST-FG` |
| Raw Material | `PPHU-TEST-RM` |
| Raw-material Batch | `PPHU-RM-B001` |
| Source Warehouse | `Raw Mat Stores - FZD` |
| Finished Warehouse | `F02 - FZD` |
| Operation | `PPHU Test Filling` |
| Workstation | `PPHU Test Station` |
| BOM | `BOM-PPHU-TEST-FG-001` |
| Production quantity | `1 Nos` |
| Hopper identity | `PPHU-HOPPER-01` |
| Material Stock Tag | `PPHU-RM-TAG-0001` |
| First output serial | `PPHU-OUT-0001` |
| Production Card | `PPHU-PROD-CARD-01` |

Create the test Operation and Workstation without Crew Requirements, Process Tasks, or additional
workforce policies. This avoids unrelated start gates.

## 3. Prepare ERPNext Items and stock

### 3.1 Finished Item

Create or reuse Item `PPHU-TEST-FG`:

- **Maintain Stock**: enabled;
- **Stock UOM**: `Nos`;
- Batch-controlled: disabled; and
- Serial-controlled: disabled.

Using an ordinary non-batched finished Item avoids output Batch and Serial Bundle complications in
this first test.

### 3.2 Raw Material

Create or reuse Item `PPHU-TEST-RM`:

- **Maintain Stock**: enabled;
- **Stock UOM**: `Nos`;
- **Has Batch No**: enabled; and
- native automatic Batch creation configured according to the site policy.

Create Batch `PPHU-RM-B001`. Place at least `2 Nos` in `Raw Mat Stores - FZD` through a valid
ERPNext Stock Reconciliation, Purchase Receipt, or another submitted native stock transaction.
Never create the authoritative stock quantity through CFG Kanban alone.

## 4. Create the simple BOM

Create and submit `BOM-PPHU-TEST-FG-001`:

| Field | Value |
|---|---|
| Item | `PPHU-TEST-FG` |
| Quantity | `1` |
| Company | Wasilah FZD Trading Sdn Bhd |
| With Operations | enabled |
| Transfer Material Against | Work Order |

Operation row:

| Field | Value |
|---|---|
| Operation | `PPHU Test Filling` |
| Workstation | `PPHU Test Station` |
| Time | `1 minute` |

Raw-material row:

| Field | Value |
|---|---|
| Item | `PPHU-TEST-RM` |
| Quantity | `1` |
| Item Operation | `PPHU Test Filling` |
| Source Warehouse | `Raw Mat Stores - FZD` |

Submit the BOM.

## 5. Configure the test-only Kanban settings

Open **CFG Kanban Settings** and use these values for the shortest scanner-only test:

| Field | Test value |
|---|---|
| Enabled | enabled |
| Auto-submit Work Order | enabled |
| Auto-start Job Card | disabled |
| Auto-submit Job Card at Target | enabled |
| Enable WIP Ledger | enabled |
| Enable Dynamic Forms | enabled |

**Auto-submit Job Card at Target** is required for the minimum scanner-only path: reporting the full
quantity submits the Job Card without a mouse-only completion step.

These are global settings. Record their existing values before changing them and restore them after
testing when this is a shared development site.

## 6. Configure the raw-material trace policy

Create **CFG Kanban Material Trace Policy**:

| Field | Value |
|---|---|
| Enabled | Yes |
| Company | Wasilah FZD Trading Sdn Bhd |
| Item | `PPHU-TEST-RM` |
| Trace Level | Exact Handling Unit |
| Purchase Receiving Tags | No Physical Tag |
| Production Input Tags | Required Physical Tag |
| Production Output Tags | No Physical Tag |
| Warehouse Transfer Tags | No Physical Tag |
| Stock Withdrawal Tags | No Physical Tag |
| Require Batch on Tagged Quantity | Yes |
| Allow ERP Quantity Across Multiple Tags | Yes |

Do not create a trace policy for `PPHU-TEST-FG`. Its output remains ordinary ERPNext stock in this
minimal test.

## 7. Activate one raw-material Stock Tag

Prefer an existing active tag satisfying all these conditions:

- Item: `PPHU-TEST-RM`;
- Batch: `PPHU-RM-B001`;
- Company: Wasilah FZD Trading Sdn Bhd;
- Warehouse: `Raw Mat Stores - FZD`;
- Identity State: `Active`;
- Quality State: `Released`; and
- Available Quantity: at least `1`.

If no suitable tag exists:

1. Register `PPHU-RM-TAG-0001` in an active **CFG Kanban Tag Family** or **CFG Kanban Tag Range Registry**.
2. Open **Logistics Operator Panel** and identify the operator.
3. Scan the Warehouse Operations Card for `Raw Mat Stores - FZD`.
4. Select **Tag Existing ERP Stock**.
5. Enter the following values.

| Field | Value |
|---|---|
| Item | `PPHU-TEST-RM` |
| Batch | `PPHU-RM-B001` |
| Quantity | `1` |
| Unused Preprinted Main Tag | `PPHU-RM-TAG-0001` |
| Handling Unit Type | Container |
| Reason | Minimal PPHU acceptance test |
| Physical confirmation | enabled |

6. Confirm the adoption.

Expected result:

- ERP stock does not increase;
- one active Handling Unit is created;
- current and available tagged quantity are `1`; and
- Batch is `PPHU-RM-B001`.

## 8. Create the reusable Hopper identity

Open **CFG Kanban Handling Unit → New**:

| Field | Value |
|---|---|
| Preprinted Tag / Handling Unit ID | `PPHU-HOPPER-01` |
| Handling Unit Type | Hopper |
| Tag Kind | Reusable Container |
| Reusable Container Role | Logistics Container |
| Permanent Container / Compartment Reference | Test Hopper 01 |
| Inventory Company | Wasilah FZD Trading Sdn Bhd |
| Current Warehouse | `Raw Mat Stores - FZD` |
| Sequence No. | `1` |
| Total Units | `1` |

Do not enter an Item, Batch, UOM, or quantity. The Hopper is a reusable physical identity, not
stock. Save it and print **Bin Slot Standard (100 × 50 mm)** or another suitable Handling Unit label.

Expected result:

- Identity State is `Active`;
- Handling Unit Type is `Hopper`;
- Tag Kind is `Reusable Container`; and
- Inventory Company matches the production Master.

## 9. Create the Kanban Master

Create **CFG Kanban Master**:

| Field | Value |
|---|---|
| Kanban Name | PPHU Minimal Production Test |
| Active | Yes |
| Company | Wasilah FZD Trading Sdn Bhd |
| Item | `PPHU-TEST-FG` |
| BOM | `BOM-PPHU-TEST-FG-001` |
| Control Type | Production |
| Card Representation | Batch |
| Replenishment Qty | `1` |
| Number of Cards | `1` |
| Source Warehouse | `Raw Mat Stores - FZD` |
| Destination Warehouse | `F02 - FZD` |
| Automation Level | Automatic |
| Default Priority | Normal |
| Allow Partial Output | disabled |
| Use ERP BOM Operations | enabled |
| Production Material Mode | Skip WIP Transfer |
| Manufacture Receipt Posting | Create Draft for Tag / Batch Review |

After selecting the BOM, confirm that **BOM Component Material Flow** contains:

| Field | Value |
|---|---|
| BOM Component | `PPHU-TEST-RM` |
| Item Operation | `PPHU Test Filling` |
| Source Warehouse | `Raw Mat Stores - FZD` |
| WIP Presentation | Standard ERP / Tag Flow |

Add one **Operation Profile**:

| Field | Value |
|---|---|
| Operation | `PPHU Test Filling` |
| Sequence | `10` |
| Workstation | `PPHU Test Station` |
| Reference Operation Time | `1 minute` |
| Mandatory | Yes |
| Normal Crew Requirement | blank |
| Execution Mode | Single Workstation |
| Runtime Selection Priority | Oldest Work Order First |
| Interruption Policy | Interruption Prohibited |
| Start Rule | No Dependency |
| Output Reporting Mode | Incremental |
| Allow Incremental Output | enabled |
| Handoff Mode | Full Batch Handoff |
| Completion Rule | Full Qty |

Leave **Process Task Profiles**, **Operator Field Definitions**, **Normal Crew Requirement**, and
**WIP Bin Pool** empty. Save the Master.

## 10. Create the only Production Card

Create **CFG Kanban Card**:

| Field | Value |
|---|---|
| Card Number | `PPHU-PROD-CARD-01` |
| Card Type | Physical Batch Card |
| Kanban Master | PPHU Minimal Production Test |
| Kanban Qty | `1` |
| Active | Yes |
| Enforce Job Owner | disabled |
| Required Job Roles | empty |

Save and select **Print Card with QR**. This is the only Production Card required.

## 11. Prepare the operator

Create or reuse one active **CFG Kanban Operator Profile**:

| Field | Value |
|---|---|
| Active | Yes |
| Kanban Role | Operator |
| Start | enabled |
| Complete | enabled |
| Report Reject | enabled |
| Partial Complete / Progress | enabled |

Allowed Operations and Allowed Workstations may be empty, or explicitly contain `PPHU Test Filling`
and `PPHU Test Station`. The terminal ERP user needs an authorized terminal role such as
**Kanban Terminal**. Print the Employee/operator QR.

## 12. Print only the required command labels

Open **Kanban Operator → Scanner Help → Print Command Labels** and select only:

```text
CFG:CMD:ACTIVATE
CFG:CMD:START
CFG:CMD:REPORT_PROGRESS
CFG:QTY:GOOD:1
CFG:CMD:PREPARE_RECEIPT
CFG:CMD:SCAN_MATERIALS
CFG:CMD:SUBMIT_MATERIALS
CFG:CMD:PPHU_OUTPUT_SERIAL
CFG:CMD:PPHU_HOPPER_CHANGE
CFG:CMD:PPHU_BATCH_CHANGE
CFG:CMD:CONFIRM
CFG:CMD:CANCEL
CFG:CMD:NEXT_CARD
```

`CFG:SELECT:1` is unnecessary because this test has only one execution lane, but it may be printed
for future multi-operation tests. Also prepare a normal physical barcode containing
`PPHU-OUT-0001`. This is an output identity, not a command label.

## 13. Start the terminal and production Cycle

1. Open `/app/kanban-operator` in browser full-screen or kiosk mode.
2. Confirm the scanner appends Enter after each scan.
3. Scan the operator QR.
4. Confirm the green **Scanner Ready** indication.
5. Scan `PPHU-PROD-CARD-01`.
6. Scan `CFG:CMD:ACTIVATE`.

Expected result:

- one Cycle is created;
- one Production Signal is created;
- Automatic mode creates one Work Order;
- Auto-submit Work Order submits it;
- ERPNext creates one Job Card for `PPHU Test Filling`; and
- the Card displays one Process Execution in `Ready` state.

If site policy blocks Automatic release, approve the Signal from **Production Supervisor Action
Center**. Do not create another Card or Cycle.

## 14. Record the initial output serial

Scan in this order:

```text
CFG:CMD:PPHU_OUTPUT_SERIAL
PPHU-OUT-0001
CFG:CMD:CONFIRM
```

Expected result:

- confirmation states that a PPHU event was recorded;
- the dialog closes and Scanner Ready returns;
- the panel shows **PPHU Trace Boundaries**;
- Event Type is `PPHU Output Serial Start`; and
- no Stock Entry is created.

## 15. Record the Hopper boundary

First perform one negative check:

```text
CFG:CMD:PPHU_HOPPER_CHANGE
PPHU-RM-TAG-0001
```

Expected rejection:

```text
Scan an active reusable Handling Unit configured with type Hopper
```

The dialog must remain open and scanner focus must return. Then scan:

```text
PPHU-HOPPER-01
PPHU-OUT-0001
CFG:CMD:CONFIRM
```

Expected event:

```text
Event: PPHU Hopper Boundary
Hopper: PPHU-HOPPER-01
First affected output serial: PPHU-OUT-0001
```

ERP stock, Work Order, and Job Card quantities must remain unchanged.

## 16. Record the material Batch boundary

Scan:

```text
CFG:CMD:PPHU_BATCH_CHANGE
PPHU-RM-TAG-0001
PPHU-OUT-0001
CFG:CMD:CONFIRM
```

Expected result:

- the Stock Tag is accepted;
- Item is `PPHU-TEST-RM`;
- Batch is `PPHU-RM-B001`;
- Warehouse and Company match the active Cycle;
- Event Type is `PPHU Material Batch Boundary`; and
- no stock is consumed yet.

Perform this before submitting the Manufacture entry. After consumption, the tag may have zero
available quantity and must no longer be accepted as an active material source.

## 17. Start and report production

Scan:

```text
CFG:CMD:START
CFG:CMD:REPORT_PROGRESS
CFG:QTY:GOOD:1
CFG:CMD:CONFIRM
```

Expected result:

- Process Execution moves to `In Progress`;
- one immutable progress record is created;
- Good Qty becomes `1`;
- ERPNext Job Card completed quantity becomes `1 / 1`; and
- Auto-submit Job Card at Target submits the Job Card as `Completed`.

Do not scan Good Qty twice. Progress quantities are incremental.

## 18. Prepare and submit the Manufacture entry

Scan:

```text
CFG:CMD:PREPARE_RECEIPT
CFG:CMD:CONFIRM
```

The receipt dialog should default to:

- Accepted Finished Quantity: `1`;
- Finished Goods Warehouse: `F02 - FZD`;
- Finished Batch: blank; and
- raw material `PPHU-TEST-RM`, quantity `1`.

Expected result: one Draft Manufacture Stock Entry is created and no stock changes yet.

Then scan:

```text
CFG:CMD:SCAN_MATERIALS
PPHU-RM-TAG-0001
CFG:CMD:SUBMIT_MATERIALS
```

Expected result:

- the raw-material tag matches the correct Item, Batch, Warehouse, UOM, and pending quantity;
- the Manufacture entry submits;
- raw material decreases by `1` in ERPNext;
- finished goods increase by `1` in `F02 - FZD`;
- the Handling Unit quantity decreases by `1`;
- the Work Order becomes `Completed`;
- the Cycle becomes `Completed`;
- the Production Card returns to `Available`; and
- Active Cycle is cleared.

If the Stock Entry remains Draft, investigate its visible validation message before retrying. Do
not create a second Manufacture entry.

## 19. Verify PPHU audit evidence

Open **CFG Kanban Event** and filter:

```text
Kanban Cycle = the test Cycle
Event Type starts with PPHU
```

Exactly three records should exist:

1. `PPHU Output Serial Start`;
2. `PPHU Hopper Boundary`; and
3. `PPHU Material Batch Boundary`.

Verify the applicable records retain:

- Kanban Card and Cycle;
- Work Order and Job Card;
- Operation and Workstation;
- operator Employee and Operator Session;
- Input Source = `Scanner`;
- Event Datetime and Received On;
- Output Serial Boundary = `PPHU-OUT-0001`;
- Hopper Handling Unit for the Hopper event; and
- Material Item and Batch for the material event.

## 20. Final acceptance checklist

Pass only when every item is confirmed:

- [ ] One Production Card created only one Cycle.
- [ ] One Work Order and one Job Card were created.
- [ ] Routine floor actions were completed with the fixed scanner.
- [ ] A wrong Hopper identity was rejected without losing scanner focus.
- [ ] Exactly three PPHU boundary events exist.
- [ ] PPHU events alone created no Stock Entry or stock change.
- [ ] Only the submitted Manufacture entry changed ERP stock.
- [ ] Raw material decreased by `1`.
- [ ] Finished stock increased by `1`.
- [ ] Work Order and Job Card completed.
- [ ] Cycle completed.
- [ ] Card returned to `Available` with no Active Cycle.
- [ ] Tester name, test date, deployed Git revision, and evidence links are recorded below.

### Test record

| Field | Result |
|---|---|
| Site | |
| Deployed Git revision | |
| Tester | |
| Test date/time | |
| Production Card | |
| Cycle | |
| Work Order | |
| Job Card | |
| Manufacture Stock Entry | |
| PPHU Event IDs | |
| Result | Pass / Fail / Deferred |
| Exceptions or evidence | |

## 21. Controlled recovery

Do not delete the Cycle, Work Order, Job Card, events, or Handling Units.

- Draft Manufacture entry: finish its trace allocation and submit it, or cancel it through the
  controlled production workflow.
- Wrong progress: use the correction-request workflow.
- Failed production: use **CFG Kanban Production Cancellation**.
- Card remains active after ERP completion: scan the Production Card again to trigger idempotent
  reconciliation.
- Stale browser assets: hard-refresh after confirming that server build and cache clearing
  completed.

## 22. Scope boundary

Passing this procedure accepts only the current PPHU scanner-event slice. It does not accept later
FEFO, reconciliation-colour, proportional partial-release, PLC/SCADA, or industrial-command
packages. Package L1 remains a separate pre-production gate under
[`TEST_PACKAGE_L1_TRANSFER_KANBAN.md`](TEST_PACKAGE_L1_TRANSFER_KANBAN.md).

Architecture and safety boundaries are defined in
[`PPHU_HANDOVER_SPEC.md`](PPHU_HANDOVER_SPEC.md). General production and scanner operation are
documented in [`USER_MANUAL.md`](USER_MANUAL.md).

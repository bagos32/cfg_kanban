# RW Noodle — Two-Operation Batch Production Acceptance Test

## 1. Purpose

This document is a complete, repeatable system test for producing **RW Noodle** through two
operations:

1. **Cooking** at workstation **Kettle**
2. **Moulding** at workstation **Moulding Tank**

The test finishes when the ERPNext manufacture transaction is submitted, two preprinted stock tags
are activated for the finished output, and each stock tag is loaded into one fixed reusable
container.

This is an acceptance test, not an instruction to create production accounting entries with
invented values. Run it on the development site first. Replace every value in angle brackets with an
existing ERPNext record belonging to the production Company.

## 2. Test boundary and sample quantities

This test uses the following sample:

| Test value | Sample |
|---|---|
| Finished Item | `RW Noodle` |
| Batch production quantity | `100 Kg` |
| Operation 1 | `Cooking` |
| Workstation 1 | `Kettle` |
| Operation 2 | `Moulding` |
| Workstation 2 | `Moulding Tank` |
| Handoff | Full batch from Cooking to Moulding |
| Fixed reusable container 1 | `RWNO-FIX-01` |
| Fixed reusable container 2 | `RWNO-FIX-02` |
| Finished-output stock tag 1 | `RWNO-0001`, `50 Kg` |
| Finished-output stock tag 2 | `RWNO-0002`, `50 Kg` |

If the actual Stock UOM of `RW Noodle` is not `Kg`, use the Item's real Stock UOM everywhere. If
the active BOM is based on a different output quantity, either use that quantity or let ERPNext
scale its material rows to the 100-unit Work Order.

The first test intentionally uses **No Physical Tag** for raw-material inputs. Raw materials remain
fully controlled by ERPNext stock and the BOM. This isolates the test to production execution,
operation handoff, finished-output tagging, and reusable-container loading. Tagged raw-material
genealogy can be tested later without changing this production route.

## 3. System ownership

- ERPNext is authoritative for the Item, BOM, Work Order, Job Cards, Batch, Stock Entry, warehouses,
  and stock balances.
- CFG Kanban controls the production signal, Cycle, operator execution, WIP handoff, physical tag
  activation, and container-membership evidence.
- A **Reusable Container** is only a permanent physical identity. It never carries an Item quantity
  directly.
- A **Main Stock Tag** carries the Item, Batch, quantity, Company, and ERP warehouse.

Therefore the correct final structure is:

```text
RWNO-FIX-01  (permanent reusable container; no direct stock quantity)
    └── RWNO-0001  (RW Noodle, Batch RWNO-TEST-001, 50 Kg)

RWNO-FIX-02  (permanent reusable container; no direct stock quantity)
    └── RWNO-0002  (RW Noodle, Batch RWNO-TEST-001, 50 Kg)
```

Do not activate `RWNO-FIX-01` or `RWNO-FIX-02` as Stock Tags. Do not place the 100 Kg quantity
directly on a reusable-container record.

## 4. Overall process

```text
ERPNext Item + submitted BOM with two operations
                 │
                 ▼
CFG Kanban Master + one Physical Batch Card
                 │ consume / trigger
                 ▼
Signal → supervisor approval → Work Order
                 │ Work Order submission creates Job Cards
                 ▼
Cooking / Kettle Job Card
                 │ report and complete 100 Kg
                 │ full-batch WIP release
                 ▼
Moulding / Moulding Tank Job Card
                 │ report and complete 100 Kg
                 ▼
Draft ERPNext Manufacture Stock Entry
                 │ stage RWNO-0001 = 50 Kg
                 │ stage RWNO-0002 = 50 Kg
                 ▼
Submit Manufacture Stock Entry
                 │
                 ├── ERPNext posts 100 Kg to Finished Goods warehouse
                 ├── RWNO-0001 activates with 50 Kg
                 └── RWNO-0002 activates with 50 Kg
                         │
                         ▼
Logistics panel: load RWNO-0001 into RWNO-FIX-01
                 load RWNO-0002 into RWNO-FIX-02
```

## 5. Roles needed for the test

Use separate identities where practical.

| Test actor | Minimum purpose |
|---|---|
| Manufacturing manager/supervisor | Configure Master/Card, approve Signal, review Work Order and Job Cards |
| Production operator | Scan the Card, start operations, and report progress |
| Stock or manufacturing user | Create, review, and submit the ERPNext Stock Entry |
| Logistics/container operator | Load the two finished Stock Tags into the reusable containers |

The production operator needs an active **CFG Kanban Operator Profile** with:

- **Start** enabled
- **Complete** enabled
- **Partial Complete / Progress** enabled
- Allowed Operations containing `Cooking` and `Moulding`, or the table left empty to allow all
- Allowed Workstations containing `Kettle` and `Moulding Tank`, or the table left empty to allow all

The container operator needs the **Container Loading** Responsible Role, unless an authorized
Supervisor/manager performs the test.

## 6. Phase A — Verify the ERPNext production foundation

Do not create the Kanban Master until all checks in this phase pass.

### A1. Verify the Item

Open **Item → RW Noodle** and confirm:

- The exact saved Item code that represents RW Noodle.
- **Maintain Stock** is enabled.
- **Default Unit of Measure / Stock UOM** is correct. This guide uses `Kg` only as a sample.
- If lot-level trace is required, **Has Batch No** is enabled and the Batch settings are valid.
- The Item is enabled and is allowed for the selected production Company.

Expected result: ERPNext can use the Item as the production item of a Work Order.

### A2. Verify Operations and Workstations

Confirm these exact ERPNext records exist and are enabled:

| Operation | Workstation |
|---|---|
| `Cooking` | `Kettle` |
| `Moulding` | `Moulding Tank` |

Spelling must match the values selected later in the Kanban Master. A Kanban operation profile does
not create an ERPNext BOM operation.

### A3. Verify the BOM

Open the active submitted BOM for `RW Noodle` and confirm:

- **With Operations** is enabled.
- The BOM has all actual raw-material rows and valid quantities.
- Its operation table contains these rows in order:

| Sequence | Operation | Workstation |
|---:|---|---|
| 10 | `Cooking` | `Kettle` |
| 20 | `Moulding` | `Moulding Tank` |

- The BOM is active and submitted.
- The source warehouse has enough raw materials for the test.

Expected result: an ERPNext Work Order made from this BOM populates required materials and both
operation rows. If either operation is absent, stop: the app deliberately refuses a Kanban Work
Order whose BOM has no valid operation route.

### A4. Record the test warehouses

Write the exact ERPNext names here before testing:

| Purpose | Actual value |
|---|---|
| Production Company | `<Production Company>` |
| Raw-material/source warehouse | `<Raw Material Warehouse>` |
| WIP warehouse | `<Production WIP Warehouse>` |
| Finished-goods warehouse | `<Finished Goods Warehouse>` |

All three warehouses must belong to the same production Company.

## 7. Phase B — Configure deterministic automation

Open **CFG Kanban Settings** and record the values used in the test.

Recommended first-test values:

| Screen label | Test value | Reason |
|---|---:|---|
| Enabled | Yes | Enables the configuration |
| Default Company | `<Production Company>` | Company context |
| Default WIP Warehouse | `<Production WIP Warehouse>` | WIP context |
| Default FG Warehouse | `<Finished Goods Warehouse>` | Output context |
| Default Automation Level | Approval | Keeps the supervisor release visible |
| Auto-submit Work Order | Yes | Ensures submitted Work Order and Job Card creation |
| Auto-start Job Card | Yes | Kanban Start should start the selected ERP Job Card |
| Auto-submit Job Card at Target | Yes | Full reported quantity should submit the Job Card |
| Enable WIP Ledger | Yes | Records Cooking-to-Moulding handoff |

Save the settings. Do not change these settings midway through this acceptance test.

If any automatic option is intentionally disabled, record that deviation. The corresponding ERP
document will require an authorized manual action and its draft state must not be reported as a
Kanban failure.

## 8. Phase C — Configure the physical trace policy and tag identities

### C1. Create the finished-output trace policy

Open **CFG Kanban Material Trace Policy → New**:

| Screen label | Value |
|---|---|
| Enabled | Yes |
| Company | `<Production Company>` |
| Item | `RW Noodle` |
| Trace Level | Exact Handling Unit |
| Purchase Receiving Tags | No Physical Tag |
| Production Input Tags | No Physical Tag |
| Production Output Tags | Required Physical Tag |
| Warehouse Transfer Tags | Optional Physical Tag |
| Stock Withdrawal Tags | Optional Physical Tag |
| Require Batch on Tagged Quantity | Yes when RW Noodle is batch-controlled; otherwise No |
| Allow Receipt Quantity Across Multiple Tags | Yes |

The last field must be enabled because one 100 Kg ERP output row will be divided between two 50 Kg
physical Stock Tags.

### C2. Register a small development tag range

If an active range already covers `RWNO-0001` and `RWNO-0002`, reuse it. Otherwise create
**CFG Kanban Tag Range Registry**:

| Screen label | Sample value |
|---|---|
| Range Registry Code | `RWNO-TEST-0001-0099` |
| Active | Yes |
| Issuing Company / Number Namespace | `<Production Company>` |
| Description | `RW Noodle development output tags` |
| Printed Prefix | `RWNO-` |
| Starting Number | `1` |
| Ending Number | `99` |
| Number Width | `4` |
| Child Separator | `-` |
| Detachable Child Count | `0` |

Expected calculated coverage: first main code `RWNO-0001`, last main code `RWNO-0099`.

Do not manually create active Handling Units for `RWNO-0001` and `RWNO-0002`. They must remain
unused until the submitted Manufacture Stock Entry activates them.

### C3. Create the two fixed reusable containers once

Create two **CFG Kanban Handling Unit** documents. Use these values for the first:

| Screen label | Value |
|---|---|
| Preprinted Tag / Handling Unit ID | `RWNO-FIX-01` |
| Handling Unit Type | Reusable Box, Container, or the true physical type |
| Tag Kind | Reusable Container |
| Allow Mixed Item / Batch Content | No |
| Permanent Container / Compartment Reference | `RW Noodle Fixed Container 01` |
| Sequence No. | 1 |
| Total Units | 1 |

Repeat for `RWNO-FIX-02`, using reference `RW Noodle Fixed Container 02`.

Set **Tag Kind = Reusable Container before saving**. Selecting **Handling Unit Type = Reusable
Box** or **Container** by itself is not sufficient: Handling Unit Type describes the physical shape,
while Tag Kind determines whether the record carries stock. If Tag Kind remains **Main Stock Tag**,
Item, Stock UOM, Company, warehouse, and a positive quantity are correctly mandatory.

Leave Item, quantity, Batch, Inventory Company, and Current Warehouse empty on a new reusable
container. The first Stock Tag loaded into an empty container assigns its Company and warehouse.
The reusable code does not need to belong to a Stock Tag range.

A reusable container can hold a different production Item after its previous contents are unloaded.
Keep **Allow Mixed Item / Batch Content = No** when only one Item/Batch may be inside at a time.
Enable it only when different Items or Batches are allowed inside simultaneously; it is not needed
merely because the container will be reused for another product later.

After saving, use **Kanban Actions → Print Thermal Tag** only if the permanent physical container
does not already carry a scannable `RWNO-FIX-01` / `RWNO-FIX-02` identity.

Expected pre-test result:

- Both reusable containers exist.
- Both are empty.
- Neither has Item quantity.
- `RWNO-0001` and `RWNO-0002` are still unused stock-tag identities.

## 9. Phase D — Create the RW Noodle Kanban Master

Open **CFG Kanban Master → New**:

| Screen label | Value |
|---|---|
| Kanban Name | `RW Noodle – Cooking to Moulding – 100 Kg` |
| Active | Yes |
| Company | `<Production Company>` |
| Item | `RW Noodle` |
| BOM | The active submitted RW Noodle BOM |
| Control Type | Production |
| Card Representation | Batch |
| Replenishment Qty | `100` |
| Stock UOM | Item Stock UOM; expected `Kg` in this sample |
| Number of Cards | `1` |
| Source Warehouse | `<Raw Material Warehouse>` |
| WIP Warehouse | `<Production WIP Warehouse>` |
| Destination Warehouse | `<Finished Goods Warehouse>` |
| Automation Level | Approval |
| Default Priority | Normal |
| Allow Partial Output | Yes |
| Use ERP BOM Operations | Yes |
| Revision | 1 |

Add these **Operation Profiles**.

### D1. Cooking profile

| Screen label | Value |
|---|---|
| Operation | `Cooking` |
| Sequence | `10` |
| Workstation | `Kettle` |
| Reference Operation Time (Minutes) | Actual standard or a recorded test value |
| Mandatory | Yes |
| Execution Mode | Single Workstation |
| Runtime Selection Priority | Oldest Work Order First |
| Start Rule | No Dependency |
| Output Reporting Mode | Incremental |
| Allow Incremental Output | Yes |
| Handoff Mode | Full Batch Handoff |
| Destination Operation | `Moulding` |
| Completion Rule | Full Qty |

Leave **Dependency Operation** empty for Cooking.

### D2. Moulding profile

| Screen label | Value |
|---|---|
| Operation | `Moulding` |
| Sequence | `20` |
| Workstation | `Moulding Tank` |
| Reference Operation Time (Minutes) | Actual standard or a recorded test value |
| Mandatory | Yes |
| Execution Mode | Single Workstation |
| Runtime Selection Priority | Oldest Work Order First |
| Dependency Operation | `Cooking` |
| Start Rule | Full Batch Available |
| Output Reporting Mode | Incremental |
| Allow Incremental Output | Yes |
| Handoff Mode | Full Batch Handoff |
| Destination Operation | Leave empty; this is the last operation |
| Completion Rule | Full Qty |

Save the Master.

Expected result: no validation error, operations remain in sequence 10 and 20, and the Item/BOM/
warehouse values belong to the same Company.

## 10. Phase E — Create and print the production batch card

Open **CFG Kanban Card → New**:

| Screen label | Value |
|---|---|
| Kanban Master | The RW Noodle Master created above |
| Card Number | `RWNO-BATCH-01` |
| Card Type | Physical Batch Card |
| Active | Yes |
| Kanban Qty | `100` |
| Controlled Operation | Leave empty |

The Item, Company Snapshot, Stock UOM, source warehouse, and destination warehouse are copied from
the Master. A Physical Batch Card controls the entire two-operation route, so do not restrict it to
Cooking or Moulding.

Save the Card, then select **Print Card with QR**. Confirm the printed/scanned identity resolves to
this Card and not to a Handling Unit.

Expected result: Card state is **Available**, Active Cycle is empty, and Print Count is at least 1.

## 11. Phase F — Trigger and approve the batch

### F1. Identify the production operator

Open **Kanban Operator** (`/app/kanban-operator`). Scan the operator credential. Confirm the visible
Active Operator is the intended employee.

### F2. Scan and trigger the batch card

Scan `RWNO-BATCH-01`, confirm that the screen shows:

- Item `RW Noodle`
- Quantity `100` in the Item Stock UOM
- the correct Master
- Card Type `Physical Batch Card`
- Card state `Available`

Select or scan the **Consume / Trigger** command.

Expected result:

```text
Card: Available → Consumed → Signal Created
Cycle: New → Signalled
Signal: Waiting Approval
```

Record the created references:

| Record | Test value |
|---|---|
| Card | `RWNO-BATCH-01` |
| Cycle | `KCY-________________` |
| Signal | `____________________` |

### F3. Supervisor approval

Open **Production Supervisor Action Center**, find the waiting RW Noodle Signal, verify the Item,
quantity, Company, BOM, and warehouses, then choose **Approve and Create Work Order**.

Expected result:

```text
Signal: Completed
Cycle: Released
Card: Production Released
ERP Command: Completed
Work Order: created and submitted
```

### F4. Mandatory Work Order inspection

Open the Work Order before floor execution and verify:

- Production Item is `RW Noodle`.
- Quantity is `100` in the correct Stock UOM.
- BOM is the selected submitted RW Noodle BOM.
- Required Items is populated.
- Operations contains `Cooking` and `Moulding` in the correct order.
- Job Cards exist for both operations.
- Cooking Job Card workstation is `Kettle`.
- Moulding Job Card workstation is `Moulding Tank`.
- The Work Order links back to the CFG Kanban Cycle.

Stop the test if any row is missing. Do not manually create an unrelated second Work Order.

### F5. Satisfy the ERPNext material-transfer prerequisite

Inspect **Skip Transfer** on the generated Work Order:

- If **Skip Transfer is enabled**, continue to Phase G. ERPNext permits direct material
  consumption during Manufacture.
- If **Skip Transfer is disabled**, use the Work Order's standard ERPNext action to create and
  submit **Material Transfer for Manufacture** for the required materials before operation
  execution. Confirm the transfer goes from `<Raw Material Warehouse>` to
  `<Production WIP Warehouse>`.

Because this first test sets raw materials to **No Physical Tag**, no Handling Unit input scan is
required. ERPNext stock remains authoritative.

## 12. Phase G — Execute Cooking and hand off the full batch

Return to **Kanban Operator** and scan the batch Card again.

Expected initial route state:

| Operation | Expected state |
|---|---|
| Cooking | Ready |
| Moulding | Not Ready or Blocked pending Cooking |

### G1. Start Cooking

On the Cooking execution at `Kettle`, select **Start**.

Expected result:

- Cooking execution becomes **In Progress**.
- The linked Cooking Job Card becomes **Work In Progress** when Auto-start Job Card is enabled.
- The Card/Cycle show production in progress after ERP feedback.

### G2. Report Cooking completion

Select **Report Progress** and enter:

| Field | Value |
|---|---:|
| Good Qty | `100` |
| Reject Qty | `0` |
| Notes | `RW Noodle test batch – Cooking completed at Kettle` |

Submit the progress. Quantities are incremental; enter `100` only once.

If **Complete** remains available after the Job Card reaches target, select it. If Auto-submit Job
Card at Target has already completed the Job Card, refresh the Card instead of submitting the same
quantity again.

Expected result:

- Cooking Good Qty is `100 / 100`.
- Cooking execution and summary become **Completed**.
- Cooking Job Card completed quantity is `100` and status is Completed/submitted.
- A WIP Ledger **Released** entry records `100` from Cooking to Moulding.
- Moulding changes to **Ready** with input available quantity `100`.

Do not start Moulding if it remains Not Ready. First check Cooking completion, released quantity,
the destination operation, and the Full Batch Available rule.

## 13. Phase H — Execute Moulding

### H1. Start Moulding

On the Moulding execution at `Moulding Tank`, select **Start**.

Expected result: Moulding execution and linked Job Card become **In Progress**.

### H2. Report Moulding completion

Select **Report Progress** and enter:

| Field | Value |
|---|---:|
| Good Qty | `100` |
| Reject Qty | `0` |
| Notes | `RW Noodle test batch – Moulding completed at Moulding Tank` |

Complete the operation if the action remains available. Do not report another 100 after refreshing.

Expected result:

- Moulding Good Qty is `100 / 100`.
- Moulding execution and summary become **Completed**.
- Moulding Job Card completed quantity is `100` and status is Completed/submitted.
- Both Process Executions remain linked to the same Cycle and Work Order.

## 14. Phase I — Create the ERPNext Manufacture entry

From the effective Work Order, create the standard ERPNext **Manufacture** Stock Entry for the full
accepted quantity.

Before saving, verify:

- Purpose/Stock Entry Type is exactly `Manufacture`.
- Company matches the Cycle.
- Work Order is the effective Kanban Work Order.
- Source warehouse follows the Work Order's Skip Transfer/WIP configuration.
- Target warehouse is `<Finished Goods Warehouse>`.
- The finished Item row is `RW Noodle`, quantity `100`, correct Stock UOM.
- If RW Noodle is batch-controlled, the output row contains one valid Batch, for example
  `RWNO-TEST-001`.

Save the Stock Entry as **Draft**. Do not submit it before staging both output tags.

Expected operator-panel result: after rescanning the batch Card, **Production Material Trace** lists
the Draft Manufacture Stock Entry with action **Scan Material Tags**.

## 15. Phase J — Stage two finished-output stock tags

This can be performed from the floor Operator panel or from the saved Stock Entry. The floor method
is preferred for this acceptance test.

### J1. Open the trace dialog

In **Kanban Operator**:

1. Identify the operator.
2. Scan `RWNO-BATCH-01`.
3. Under **Production Material Trace**, find the Draft Manufacture Stock Entry.
4. Select **Scan Material Tags**.

The output row should show `RW Noodle` and a remaining quantity of `100`.

### J2. Stage the first output tag

Under **Stage Preprinted Output Tag** enter:

| Screen label | Value |
|---|---|
| ERP Output Row | The RW Noodle finished-output row |
| Unused Preprinted Main Tag | `RWNO-0001` |
| Stock Quantity | `50` |
| Handling Unit Type | Container or Reusable Box |

Select **Stage Output Tag**.

Expected result: a Pending output trace line shows `RWNO-0001`, `50 Kg`; remaining output quantity
becomes `50 Kg`.

### J3. Stage the second output tag

Repeat with:

| Screen label | Value |
|---|---|
| ERP Output Row | The same RW Noodle output row |
| Unused Preprinted Main Tag | `RWNO-0002` |
| Stock Quantity | `50` |
| Handling Unit Type | Container or Reusable Box |

Expected result: two Pending output lines total exactly `100 Kg`, and remaining output quantity is
zero.

If the wrong tag or quantity was staged, use **Cancel** on that pending trace line before submitting
the Stock Entry. Never edit or delete a confirmed Handling Unit to correct a Draft scan.

## 16. Phase K — Submit the Manufacture Stock Entry

The authorized Stock/Manufacturing user must open and review the ERPNext Stock Entry. The floor
Operator panel deliberately does not submit ERP stock.

Confirm:

- ERP finished output total is `100`.
- Pending tagged output total is `50 + 50 = 100`.
- Item, Batch, Company, warehouse, and UOM match.
- There are no duplicate or unexpected output tags.

Submit the Stock Entry.

Expected result:

- ERPNext posts 100 units of RW Noodle to `<Finished Goods Warehouse>`.
- The Material Trace becomes **Confirmed**.
- `RWNO-0001` is an active Main Stock Tag with 50 units.
- `RWNO-0002` is an active Main Stock Tag with 50 units.
- Both tags show the same finished Batch when the Item is batch-controlled.
- Both tags show the Work Order and submitted Manufacture Stock Entry as origin evidence.
- Both tags have `available_qty = 50` and `reserved_qty = 0`.
- The Cycle receives Manufacture Stock Entry feedback.

Current expected limitation: the Cycle may show **Waiting FG Receipt** after Manufacture submission.
The app does not yet combine final FG receipt confirmation and return of the reusable physical
Kanban Card into one automatic closure action. This is not a failure of output tag activation.

## 17. Phase L — Load the two stock tags into the fixed reusable containers

### L1. Load container 1

1. Open **CFG Kanban → Logistics Operator Panel** (`/app/kanban-logistics`).
2. Identify an operator authorized for **Container Loading**.
3. Keep the scanner in normal tag-lookup mode.
4. Scan `RWNO-FIX-01`.
5. Select **Manage Contents**.
6. Scan `RWNO-0001` under the Stock Tag input.
7. Select **Load Tag**.

Expected result:

- `RWNO-0001` is shown as Loaded inside `RWNO-FIX-01`.
- The container inherits `<Production Company>` and `<Finished Goods Warehouse>`.
- The stock tag remains 50 units; loading does not create or change ERPNext stock quantity.

### L2. Load container 2

Repeat with:

```text
Container: RWNO-FIX-02
Stock Tag: RWNO-0002
```

Expected result: `RWNO-0002` is shown as Loaded inside `RWNO-FIX-02`, with the same Company,
warehouse, Item, Batch, and 50-unit balance.

Do not physically remove a loaded Stock Tag later without first using **Unload** and entering the
reason.

## 18. Final acceptance checklist

The test passes only when every applicable check below is true.

### ERPNext records

- [ ] One submitted Work Order exists for the test Cycle.
- [ ] The Work Order has required materials and both operation rows.
- [ ] One Cooking Job Card exists at Kettle and is completed for 100.
- [ ] One Moulding Job Card exists at Moulding Tank and is completed for 100.
- [ ] One submitted Manufacture Stock Entry posts 100 RW Noodle to the FG warehouse.
- [ ] The output uses the intended Batch when RW Noodle is batch-controlled.

### CFG Kanban execution

- [ ] One Physical Batch Card created only one active Cycle/Signal/Work Order chain.
- [ ] Cooking started Ready while Moulding waited.
- [ ] Completing Cooking released exactly 100 to Moulding.
- [ ] Moulding became Ready only after the full Cooking batch was available.
- [ ] Operation Progress, Process Executions, Operation Summaries, WIP Ledger, ERP Commands, and
      Events retain the test evidence.

### Tags and containers

- [ ] `RWNO-0001` is active for 50 RW Noodle in the FG warehouse.
- [ ] `RWNO-0002` is active for 50 RW Noodle in the FG warehouse.
- [ ] Both stock tags reference the correct Work Order, Manufacture Stock Entry, and Batch.
- [ ] `RWNO-FIX-01` contains `RWNO-0001`.
- [ ] `RWNO-FIX-02` contains `RWNO-0002`.
- [ ] The reusable containers themselves carry no Item quantity.
- [ ] Combined tagged quantity is exactly 100, matching the submitted ERP output.

## 19. Genealogy verification

Open **CFG Kanban → Material Genealogy Explorer** and scan `RWNO-0001`, then `RWNO-0002`.

For each tag confirm:

- Item is RW Noodle.
- Quantity is 50 in the correct Stock UOM.
- Company and warehouse match ERPNext.
- Batch matches the Manufacture output when applicable.
- Origin evidence links to the submitted Manufacture Stock Entry and Work Order.
- Container membership shows the correct fixed reusable container.

The two Stock Tags should share the same production origin but have independent physical
identities and quantity-ledger histories.

## 20. Stop conditions and diagnosis

Stop the test instead of bypassing control when any of these occurs:

| Symptom | Check first |
|---|---|
| Work Order has no operations | BOM **With Operations**, submitted BOM operation rows |
| No Job Cards | Work Order submitted, operation rows present, ERPNext Job Card creation completed |
| Moulding is ready before Cooking completes | Moulding dependency and Start Rule |
| Moulding stays Not Ready after Cooking | Cooking execution Completed, 100 released, destination is Moulding |
| Work Order remains Not Started | Material Transfer for Manufacture or Skip Transfer setting |
| Job Card stays Draft/zero | Auto-start setting, ERP Command status/error, linked progress reference |
| Production Material Trace not shown | Draft supported Stock Entry, linked Work Order, active scanned Cycle |
| Output tag field rejects code | Active range registry, unused main tag, exact prefix/number width |
| Second 50-unit tag is rejected | **Allow Receipt Quantity Across Multiple Tags** must be enabled |
| Stock Entry submission is blocked | Required tag coverage must total the ERP output row exactly |
| Container rejects Stock Tag | Company/warehouse mismatch, tag reserved, tag already loaded, mixed-content policy |
| Cycle remains Waiting FG Receipt | Current known physical-card closure limitation; verify tags and ERP stock separately |

Do not solve a failed test by deleting Cycle, Progress, Event, Material Trace, or Handling Unit
history. Record the failing reference and use controlled cancellation, reconciliation, or recovery.

## 21. Test evidence sheet

Complete this table and attach screenshots where needed:

| Evidence | Actual reference/result |
|---|---|
| Kanban Master | |
| Batch Card | `RWNO-BATCH-01` |
| Cycle | |
| Signal | |
| Work Order | |
| Cooking Job Card | |
| Moulding Job Card | |
| Batch | |
| Manufacture Stock Entry | |
| Material Trace | |
| Output Stock Tag 1 | `RWNO-0001` |
| Output Stock Tag 2 | `RWNO-0002` |
| Reusable Container 1 | `RWNO-FIX-01` |
| Reusable Container 2 | `RWNO-FIX-02` |
| Final ERP FG quantity | |
| Final combined tagged quantity | |
| Cycle final status | |
| Tester | |
| Test date/time | |
| Pass/Fail | |
| Defect/exception references | |

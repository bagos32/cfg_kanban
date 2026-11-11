# Minor-Batch Expiry and Serial Pouch Printing

## Purpose

This guide configures and tests a small, repetitive printing operation where an operator:

- takes blank premade plastic pouches from a purchased box of approximately `3,000 Nos`;
- prints an expiry date and a sequential operational serial on each pouch;
- reports work in small runs of approximately `100 Nos`;
- packs the accepted printed pouches as one outer quantity of `1,000 Nos`, with inner bundles of
  `100 Nos`;
- retains the purchased pouch Batch, printed-output Batch, operator, workstation, quantity, time,
  and first serial boundary for traceability; and
- uses the printed-output Batch expiry for later FEFO selection.

This is a pilot configuration and acceptance guide. It does not by itself approve the process for
production use.

> **Process Certificate migration note:** This currently executable pilot uses a separate printed
> output Item because the scanner runtime originally had no controlled same-Item state change. The
> Process Certificate foundation can now model `PLS_ABC` as one Item with exact states such as
> `SANITISED` and `SANITISED + PRINTED`, including native Stock Ledger filtering. Do not change this
> pilot to the single-Item model until the scanner-first certificate issuance/Repack package and its
> acceptance test are complete. See `PROCESS_CERTIFICATE_ARCHITECTURE.md`.

## 1. Recommended operating model

Use one reusable **Production Card** to represent `1,000 Nos` of accepted printed pouches. Inside
that Card Cycle, use ten or more **Operation Material Runs**. Each Material Run normally consumes
`100 Nos` of blank pouches and ends when the operator reports the corresponding good and reject
quantities.

The purchased `3,000 Nos` box remains one physical source Stock Tag. The same source tag may supply
three Production Card Cycles, provided each Material Run scans only the quantity physically taken.
Kanban protects the unposted Material Draw reservations so two workstations cannot declare the
same tagged balance at the same time. ERPNext stock and the Handling Unit ledger change only when
the final Manufacture entry is submitted.

The minimum physical control set is:

| Identity | Quantity represented | Purpose |
|---|---:|---|
| One reusable Production Card | `1,000 Nos` good output | Starts the minor production Cycle |
| Purchased blank-pouch Stock Tag | Initially `3,000 Nos` | Identifies the exact received box and source stock |
| One preprinted output main Stock Tag | `1,000 Nos` | Identifies the completed printed-pouch pack |
| Up to ten detachable child tags | `100 Nos` each | Optional; activate only when a bundle is separated |
| Optional permanent Process/Station Card | No stock quantity | Useful only when several Work Orders queue at the printer |

Do not create ten Production Cards for the ten inner bundles. The Material Runs provide the
high-frequency trace, while the one Production Card controls the `1,000 Nos` ERP production lot.

## 2. Important identity rules

### 2.1 Raw pouch Stock Tag versus ERPNext Batch

The Kanban Stock Tag and ERPNext Batch are different identities:

- **Stock Tag** identifies one exact physical box/container and links it to Purchase Receipt,
  supplier, Item, Warehouse, quantity, scans, movements, and later consumption.
- **Batch** groups stock that shares a supplier/manufacturing lot, expiry, or regulated quality
  identity. Several separately tagged boxes may belong to one Batch.

For ordinary purchased blank pouches, use the Stock Tag alone and leave ERPNext **Has Batch No**
disabled. Do not copy the tag number into the Batch field. The source tag is sufficient to trace
the exact `3,000 Nos` box through the Material Run and genealogy.

Enable ERPNext Batch control only when the supplier provides a real lot number, several boxes must
be grouped under one lot/quality result, the material has expiry control, or a regulatory rule
requires Batch stock accounting. Even then, keep the Stock Tag and Batch as separate values.

### 2.2 Printed-output Batch and expiry

Create the printed-output ERPNext Batch before releasing the Work Order. Its **Expiry Date** is the
authoritative date for FEFO. Assign that Batch to the Kanban Cycle before supervisor approval creates
the Work Order.

Use ERPNext Item **Shelf Life in Days** only when the expiry is always calculated from the production
date by one fixed rule. If the printed expiry depends on product/customer instructions, create the
Batch with the exact approved expiry date instead of relying on a generic shelf-life calculation.

The expiry printed on the pouch must exactly match the Cycle's ERPNext Batch expiry. Never treat an
operator-typed date as the FEFO authority.

The current Production Operator Panel does not automatically compare the text printed on the pouch
with the ERPNext Batch expiry. For the pilot, a supervisor must set/verify the printer before the
operation starts, and the first-pouch boundary scan should include the printed expiry as evidence.
If operators must independently receive and verify the expiry without supervisor setup, add a
future scanner-first Batch-expiry verification gate before production acceptance; do not replace it
with unrestricted manual typing.

### 2.3 Printed pouch serial

In the current build, **First Output Serial / Boundary** is operational evidence. It is not an
ERPNext Serial No and the application does not yet reserve or validate every individual serial in
the 100-piece interval. Therefore:

- keep both blank and printed pouch Items non-serial-controlled in ERPNext;
- configure the printer to increment the printed serial for every attempted pouch, including a
  rejected print;
- never reuse the serial of a rejected pouch;
- retain or destroy rejected printed pouches under the site's controlled reject procedure; and
- treat `first serial + processed quantity` as a trace interval only when the printer is confirmed
  gapless.

If regulation or customer policy requires proof of every exact pouch serial, automatic last-serial
calculation, duplicate/gap detection, or exact rejected-serial membership, stop at pilot use. That
requires the deferred exact-serial Material Run package; the current boundary field is not enough
for legal serial release evidence.

## 3. Sample data

Replace these examples with real Item and Warehouse names.

| Record | Sample value |
|---|---|
| Company | `FZD Manufacturing` |
| Raw Item | `POUCH-BLANK-250G` |
| Printed output Item | `POUCH-PRINTED-250G` |
| Stock UOM | `Nos` |
| Raw purchase UOM | `Box` |
| Stock quantity per Box | `3000` |
| Production BOM output | `1000 Nos` |
| BOM raw pouch quantity | `1000 Nos` |
| Operation | `Print Expiry and Serial` |
| Workstation | `Pouch Coding Station 1` |
| Raw source Warehouse | `Raw Packaging - FZD` |
| Printed output Warehouse | `Printed Packaging - FZD` |
| Production Card quantity | `1000 Nos` |
| Normal Material Run quantity | `100 Nos` |
| Purchased source tag | `FZD-PCH0001` with `3000 Nos` |
| Raw supplier Batch | Not used for the normal tag-only example |
| Printed-output Batch | `PP-2026-1111-01` |
| Approved printed expiry | `2027-11-11` |
| First printed serial | `PP250G-000001` |
| Output tag family | `FZD-PP1001` plus children `-1` through `-10` |

## 4. ERPNext Item setup

### 4.1 Blank pouch Item

Open the raw blank-pouch Item and set:

1. **Maintain Stock** = enabled.
2. **Stock UOM** = `Nos`.
3. **Has Batch No** = disabled for tag-only box traceability.
4. **Has Serial No** = disabled.
5. **Default Purchase UOM** = `Box`, when the supplier purchases it by box.
6. In the Item UOM conversion table, set `1 Box = 3000 Nos`.

The purchase transaction may use `1 Box`, while the Purchase Receipt and Kanban Handling Unit
retain the converted stock quantity of `3,000 Nos`. If a genuine supplier lot is required later,
enable Batch control through an approved Item/process change; never use a physical tag code as a
surrogate Batch number.

### 4.2 Printed pouch Item

Open the printed-pouch Item and set:

1. **Maintain Stock** = enabled.
2. **Stock UOM** = `Nos`.
3. **Has Batch No** = enabled.
4. **Has Serial No** = disabled.
5. Configure a Batch naming rule suitable for printed-pouch production.
6. Set **Shelf Life in Days** only if it produces the exact date that must be printed.

The output Item is a genuine intermediate stock Item. Do not use the blank pouch Item as both input
and output because that would hide the printing conversion and its genealogy.

## 5. ERPNext BOM setup

Create and submit one BOM for `POUCH-PRINTED-250G`:

1. **Quantity** = `1000 Nos`.
2. Enable **With Operations**.
3. Add Operation `Print Expiry and Serial` and Workstation `Pouch Coding Station 1`.
4. Add raw Item `POUCH-BLANK-250G`, quantity `1000 Nos`.
5. In the raw-material row, set **Item Operation** = `Print Expiry and Serial`.
6. Add ink/ribbon only if the business maintains it as an ERPNext stock component. Leave such an
   Item on normal ERP material control unless physical tag evidence is genuinely required.
7. Select Work Order-level material control for the simplest one-operation pilot. Job Card-level
   material control is also supported, but it is not required for this setup.
8. Submit the BOM.

The raw-pouch BOM ratio is `1 Nos input / 1 Nos output`. CFG Kanban calculates this ratio in the
Master; do not type a different ratio to compensate for rejects. Rejects are recorded through
processed quantity.

## 6. Purchase and tag the 3,000-pouch box

Use the normal Purchase Replenishment and Purchase Receipt flow:

1. Receive the blank pouch Item in ERPNext without a Batch for the normal tag-only flow.
2. Confirm the Purchase Receipt quantity converts to `3,000 Nos`.
3. During receipt tagging, scan an unused preprinted main Stock Tag such as `FZD-PCH0001`.
4. Confirm the tag shows:
   - Item `POUCH-BLANK-250G`;
   - Batch blank, unless a genuine supplier lot was supplied;
   - Warehouse `Raw Packaging - FZD`;
   - Stock UOM `Nos`; and
   - Available Qty `3,000`.
5. Release the quantity only after the submitted Purchase Receipt confirms ERPNext stock.

Do not split the 3,000-pouch source tag merely to support printing. Material Runs can reserve small
quantities from the shared source tag without physically splitting it.

## 7. CFG Kanban Master setup

Create one **CFG Kanban Master** with these values:

| Exact field label | Recommended value |
|---|---|
| Kanban Name | `Printed Pouch 250G - 1000` |
| Active | enabled |
| Company | manufacturing Company |
| Item | `POUCH-PRINTED-250G` |
| BOM | the submitted `1000 Nos` BOM |
| Control Type | `Production` |
| Card Representation | `Batch` |
| Replenishment Qty (Stock UOM) | `1000` |
| Number of Cards | `1` for the pilot |
| Source Warehouse | `Raw Packaging - FZD` |
| Destination Warehouse | `Printed Packaging - FZD` |
| Automation Level | `Approval` |
| Allow Partial Output | enabled |
| Use ERP BOM Operations | enabled |
| Production Material Mode | `Skip WIP Transfer` |
| Manufacture Receipt Posting | `Create Draft for Tag / Batch Review` |

`Approval` is recommended because the supervisor must assign and verify the printed-output Batch
and expiry before ERPNext creates/releases production documents.

### 7.1 BOM Component Material Flow row

Load the BOM rows, then set the `POUCH-BLANK-250G` row:

| Exact field label | Value |
|---|---|
| BOM Component | `POUCH-BLANK-250G` |
| Item Operation | `Print Expiry and Serial` — loaded from the BOM |
| Source Warehouse | `Raw Packaging - FZD` |
| Material Run Tracking | `Source Tag Quantity` |
| Material Run Scan Warehouse | `Raw Packaging - FZD` |
| WIP Presentation | `Standard ERP / Tag Flow` |

After saving, verify **Material Qty per Output Unit** is `1`. Leave ink, cleaning material, or other
components at **No Run Tracking** unless they require the same physical source trace.

### 7.2 Operation Profile row

Set the `Print Expiry and Serial` Operation Profile:

| Exact field label | Recommended value |
|---|---|
| Sequence | `10` |
| Workstation | `Pouch Coding Station 1` |
| Mandatory | enabled |
| Execution Mode | `Single Workstation` |
| Quantity Allocation | `ERP Job Card Quantity` |
| Start Rule | `No Dependency` |
| Output Reporting Mode | `Incremental` |
| Allow Incremental Output | enabled |
| Material Run Control | `Required Before Progress` |
| Output Boundary Requirement | `Every Material Run` |
| Allow Unused Material Carry-forward | enabled |
| ERP Settlement Timing | `At Work Order Manufacture Receipt` |
| Handoff Mode | `Full Batch Handoff` |
| Completion Rule | `Full Qty` |

Carry-forward is useful if the operator scans a small reserve and reports a smaller processed
quantity. For the strictest floor routine, scan exactly the number of pouches physically taken in
each run; the carry balance should normally return to zero.

`At Work Order Manufacture Receipt` avoids creating a separate ERP Stock Entry for every small
run. The earlier source scans are adopted automatically into the final Manufacture entry.

## 8. Production Card and optional Process Card

1. Create one reusable physical **CFG Kanban Card** from the Master.
2. Print its normal Production Card QR.
3. Use this Card for repeated `1,000 Nos` Cycles.
4. Do not enable owner enforcement unless the business requires one operator-in-charge for the
   whole Cycle.
5. Create a permanent Process/Station Card only if the coding workstation regularly chooses among
   several queued Work Orders. For a single pilot Work Order, the main Production Card is enough.

The Process Card does not replace the Production Card. It selects an eligible Job Card/operation
inside an already released production Cycle.

## 9. Output Stock Tag setup

Register or reuse a **CFG Kanban Tag Range Registry** for printed-pouch output tags:

| Exact field label | Sample value |
|---|---|
| Printed Prefix | `FZD-PP` |
| Starting Number | `1001` |
| Ending Number | according to the controlled preprinted stock |
| Number Width | `4` |
| Child Separator | `-` |
| Detachable Child Count | `10` |

One main tag can identify the `1,000 Nos` outer pack. Its ten detachable identities can identify
`100 Nos` bundles. Do not activate all children automatically unless the bundles will move
independently.

Recommended stock practice:

1. Receive Manufacture output against the main tag for `1,000 Nos`.
2. Keep the main tag balance at `1,000 Nos` while the outer pack remains intact.
3. When one `100 Nos` bundle is physically removed, use the controlled split action to move
   `100 Nos` from the main tag to one unused child tag.
4. The child inherits Item, Batch, expiry, Company, Warehouse, and genealogy.

This avoids creating ten active stock identities when the outer pack is still intact.

## 10. Prepare the printed-output Batch before approval

For every new Card Cycle:

1. Scan the Production Card to create the new Cycle and Approval signal.
2. Before approving the signal, create/open the ERPNext Batch for `POUCH-PRINTED-250G`.
3. Set its approved Expiry Date, for example `2027-11-11`.
4. Open the new **CFG Kanban Cycle** and set **Batch** = `PP-2026-1111-01`.
5. Verify the Batch belongs to `POUCH-PRINTED-250G`.
6. Approve/release the production signal so the Work Order snapshots the planned Batch.
7. Confirm the operator sees the correct Cycle, Work Order, production Item, and Batch before
   printing starts.

If the Cycle was released with a wrong Batch/expiry, do not overwrite the running evidence. Use
controlled production cancellation and create a fresh Cycle with the correct Batch.

## 11. Print the scanner command labels

From **Print Command Labels**, select only the commands needed at this workstation:

- `CFG:CMD:START`
- `CFG:CMD:START_MATERIAL_RUN`
- `CFG:QTY:MATERIAL:100`
- `CFG:QTY:MATERIAL:+10`
- `CFG:QTY:MATERIAL:+1`
- `CFG:CMD:CONFIRM`
- `CFG:CMD:CANCEL`
- `CFG:CMD:CANCEL_MATERIAL_RUN`
- `CFG:CMD:REPORT_PROGRESS`
- configured Good quantity labels, such as `CFG:QTY:GOOD:+100`, `+10`, and `+1`
- `CFG:QTY:REJECT:+1`
- `CFG:CMD:PREPARE_RECEIPT`
- `CFG:CMD:SCAN_MATERIALS`
- `CFG:CMD:SUBMIT_MATERIALS`

Also keep the physical Production Card, Employee tag, source Stock Tag, and output Stock Tags at
the workstation. Those are identity labels, not command labels.

## 12. Scanner-only production flow

### 12.1 Start the Cycle and operation

1. Open the Production Operator Panel in kiosk/full-screen mode.
2. Scan the Employee tag.
3. Scan the released Production Card.
4. Scan `CFG:CMD:START` and select the operation with `CFG:SELECT:n` only if prompted.
5. Confirm the panel shows `Print Expiry and Serial`, the correct Job Card, and the planned output
   Batch.

### 12.2 Run one 100-pouch interval

Repeat this sequence for every physical take from the raw box:

1. Verify the printer displays the approved output Batch and expiry.
2. Scan `CFG:CMD:START_MATERIAL_RUN`.
3. Scan the first printed pouch serial/boundary. A recommended scanner-readable boundary is:

   `BATCH=PP-2026-1111-01|EXP=2027-11-11|SER=PP250G-000001`

   CFG Kanban stores this as one immutable boundary string; it does not parse or validate its
   internal parts.
4. Scan `CFG:QTY:MATERIAL:100`.
5. Scan source Stock Tag `FZD-PCH0001`.
6. Verify the dialog resolves:
   - Item `POUCH-BLANK-250G`;
   - source Stock Tag `FZD-PCH0001` and Batch blank for the normal tag-only flow;
   - source Warehouse `Raw Packaging - FZD`;
   - UOM `Nos`; and
   - quantity `100`.
7. Scan `CFG:CMD:CONFIRM` to open the Material Run.
8. Print/process the 100 physical pouches.
9. Scan `CFG:CMD:REPORT_PROGRESS`.
10. Enter the actual result. Example: `98 Good` and `2 Reject`. The processed quantity is `100`,
    so the Material Run uses `100 Nos` of blank pouches.
11. Scan `CFG:CMD:CONFIRM`.
12. Verify the run becomes **Progress Posted**, records the operator/session/time, and no open run
    remains.

Start the next Material Run with its own first serial boundary. Continue until cumulative Good Qty
reaches `1,000 Nos`. Reject quantity does not satisfy the `1,000 Nos` good-output target.

### 12.3 Source tag changes inside one Cycle

If `FZD-PCH0001` is exhausted during the Cycle:

1. Finish and report the current Material Run.
2. Start a new Material Run.
3. Scan the next quantity and the new source Stock Tag.
4. Confirm the new source Stock Tag. If genuine ERPNext Batch control is enabled, also confirm its
   supplier Batch.

Do not change source tags in the middle of one open run. The final Manufacture preparation will
split ERP input rows by the exact scanned Batches when necessary.

## 13. Finish manufacture and tag the 1,000-pouch output

After all required Job Card progress is complete:

1. Scan `CFG:CMD:PREPARE_RECEIPT`.
2. Verify one Draft **Manufacture** Stock Entry is created.
3. Open **Production Material Trace** with `CFG:CMD:SCAN_MATERIALS`.
4. Verify the earlier Material Run Draws already appear as input trace lines. Do **not** scan the
   same source tag quantities again.
5. Verify the input trace lines show the exact source Stock Tags used by the Material Runs. Batch
   may remain blank in the tag-only flow.
6. Verify the finished-output row uses planned Batch `PP-2026-1111-01`.
7. Scan output quantity `1,000` using the appropriate Good quantity label.
8. Scan unused output main Stock Tag `FZD-PP1001` and stage the output.
9. Verify the staged tag shows:
   - Item `POUCH-PRINTED-250G`;
   - Batch `PP-2026-1111-01`;
   - expiry snapshot `2027-11-11`;
   - quantity `1,000 Nos`; and
   - destination `Printed Packaging - FZD`.
10. Scan `CFG:CMD:SUBMIT_MATERIALS`.

Expected result:

- ERPNext consumes the scanned blank-pouch quantities once;
- ERPNext receives `1,000 Nos` printed pouches once;
- the raw Stock Tag balance falls from `3,000` to `2,000` after the first successful Cycle;
- every Material Draw becomes **Bound to ERP**;
- the output tag carries the printed-output Batch and expiry snapshot; and
- no unused Material Transfer or Material Consumption Draft remains.

## 14. Inner bundles of 100

When the outer `1,000 Nos` pack remains intact, retain the full quantity on the main tag.

When physically separating a bundle:

1. Open the main Handling Unit or the authorized logistics split action.
2. Scan main tag `FZD-PP1001`.
3. Enter/scan quantity `100`.
4. Scan unused child `FZD-PP1001-1`.
5. Confirm the child shows `100 Nos`, the same Batch and expiry, and the same Warehouse.
6. Repeat only when another bundle is physically separated.

Never create quantity on a child without reducing the parent. The Handling Unit ledger total across
parent and children must remain `1,000 Nos`.

## 15. Connect the printed pouch to downstream packaging

The printed pouch is an intermediate Item, not the final packed food Item. To retain traceability
through packaging:

1. Add `POUCH-PRINTED-250G` as an input in the downstream finished-product BOM.
2. Physically issue a printed-pouch main/child Stock Tag to the packaging operation.
3. Configure that packaging operation to scan the printed-pouch tag through its applicable
   Production Material Trace or Material Run rule.
4. Verify the scanned tag's printed-pouch Batch and expiry before packaging progress is accepted.
5. The downstream Manufacture entry must consume that exact Batch/tag quantity and receive the
   final food Item into its own ERPNext Batch.
6. Verify genealogy connects:

   supplier Purchase Receipt and blank-pouch Stock Tag → printing operator and Material Runs → printed-pouch Batch/tag
   → downstream packaging operator and other raw-material Batches → final-product Batch/tag.

The printed-pouch Batch and final-product Batch are separate ERPNext Batch records belonging to
different Items. They may share a controlled reference suffix and approved expiry, but must not be
treated as the same Batch record. If the downstream final-product expiry differs from the date
already printed on the pouch, place the printed-pouch tag on Hold and do not consume it.

## 16. FEFO use after printing

FEFO is driven by the Batch/Handling Unit expiry, not by the printed serial text.

1. Confirm every output main/child tag has the correct Batch and expiry snapshot.
2. Keep expired, Hold, Quarantined, or Rejected tags unavailable for dispatch/consumption.
3. Use Kanban dispatch/allocation so the earliest eligible expiry is presented first.
4. When equal expiries exist, preserve the site's receipt/packing sequence as the tie-breaker.
5. A later Cycle may reuse the Production Card, but it must create a new Cycle and use its own
   approved Batch/expiry.

## 17. Acceptance tests

### 16.1 Positive test

1. Start with source tag `3,000 Nos`.
2. Complete ten Material Runs whose processed quantities total at least the inputs needed for
   `1,000 Good`.
3. Include at least one reject in one run.
4. Submit the Manufacture entry and stage one `1,000 Nos` output tag.
5. Split one child bundle of `100 Nos`.
6. Verify:
   - source tag available balance decreased by actual processed input;
   - output parent plus child balances total `1,000 Nos`;
   - source Purchase Receipt and blank-pouch Stock Tag are visible in genealogy;
   - output Batch and expiry are visible on parent and child;
   - Material Runs show operator, workstation, time, first boundary, and progress;
   - ERP Stock Ledger matches the submitted Manufacture entry; and
   - the output is available to FEFO selection.

### 16.2 Rejection tests

Verify the system visibly rejects and restores scanner focus for:

1. wrong source Item tag;
2. correct Item in the wrong Warehouse;
3. inactive, Hold, Quarantined, Rejected, or empty source tag;
4. quantity above the operationally available source-tag balance;
5. progress when **Required Before Progress** has no open Material Run;
6. a second workstation attempting to reserve the same already-reserved balance;
7. output tag Batch different from the Cycle planned Batch;
8. Cycle closure with a used but unsettled Material Draw;
9. Cycle closure with an unsubmitted production Stock Entry; and
10. child split quantity greater than the parent available balance.

### 16.3 Serial-boundary manual check

For one Material Run:

1. record its first printed serial;
2. record Good and Reject quantities;
3. inspect the physical first and last printed pouch, including rejected samples;
4. confirm the printer incremented every attempted print without reuse; and
5. record any gap as a controlled exception rather than editing the immutable Material Run.

This manual check is mandatory until exact per-piece serial reservation is implemented and accepted.

## 18. Evidence for the testing record

Record the following in the test result:

- deployed Git revision;
- CFG Kanban Master, Card, Cycle, Work Order, Job Card, and Process Execution names;
- source and output Handling Unit codes;
- raw source Stock Tag and Purchase Receipt, optional genuine supplier Batch, output Batch, and
  output expiry;
- all Material Run and Material Draw identifiers;
- first serial boundary and progress for each run;
- source quantity before and after ERP submission;
- output parent/child quantity total;
- Manufacture Stock Entry and Material Trace;
- Stock Ledger evidence;
- genealogy screenshot from raw Purchase Receipt/Stock Tag to printed output tag; and
- every accepted exception or deferred risk.

Use these companion acceptance documents for the engine-level tests:

- `docs/TEST_OPERATION_MATERIAL_RUN_DRAWS.md`
- `docs/TEST_OPERATION_MATERIAL_RUN_SETTLEMENT.md`
- `docs/OPERATION_MATERIAL_RUNS.md`

## 19. Practical operating summary

For the operator, the repeated floor sequence is deliberately short:

1. **Start Material Run**.
2. Scan first printed serial/boundary.
3. Scan `Material Qty 100`.
4. Scan the shared raw-box Stock Tag.
5. Confirm.
6. Print the physical take.
7. Report Good/Reject progress.
8. Repeat until `1,000 Good`.

For the supervisor, the critical controls are:

1. create and verify the output Batch/expiry before approval;
2. make the Cycle use that planned Batch;
3. verify the printer's expiry and serial rule;
4. review exceptions and rejects; and
5. release the final output only after ERPNext Manufacture submission confirms stock and trace.

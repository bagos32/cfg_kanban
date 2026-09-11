# CFG Kanban User Manual

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Manual version:** 0.1  
**Updated:** 11 September 2026  
**Scope:** Functions implemented in the current development build

## 1. Purpose of this manual

This manual explains how to configure and operate CFG Kanban from an empty installation through
the first production signal. It covers normal reusable-card replenishment, Sales Order stock
proposals, customer make-to-order production, operation reporting, printing, handling-unit tags,
and audit records.

CFG Kanban is the process-control layer. ERPNext remains the official system of record for Items,
BOMs, Operations, Work Orders, Job Cards, Batches, Stock Entries, stock balances, deliveries, and
accounting.

> **Development-stage warning:** Use the app on a development server first. The current build does
> not yet include the final supervisor action that closes a completed cycle, clears the card's
> Active Cycle, and returns the reusable card to Available. Delivery Note batch enforcement and
> automatic batch selection in Manufacture Stock Entry are also not yet implemented.

## 2. Choose the correct production flow first

Do not begin by creating a card. First decide which of these two policies applies.

| Question | Stock Replenishment | Customer Make-to-Order |
|---|---|---|
| Why production starts | Stock falls below a warehouse target or a reusable card is consumed | A particular customer submits an order |
| Quantity | Fixed quantity represented by one or more cards | Sales Order outstanding quantity, optionally including PO-authorized tolerance |
| Existing finished stock | May be considered | Prohibited by policy |
| Reusable card | Required for physical-card flow | Not reserved or consumed |
| Batch | Normal ERPNext batch practice | One dedicated Batch per Sales Order line |
| Order consolidation | May be possible operationally | Prohibited |

Use **Stock Replenishment** for products made repeatedly for inventory. Use **Customer
Make-to-Order** where every order must have its own batch and common expiry date, and unused stock
must not be supplied to that customer.

## 3. Roles and responsibilities

### System Manager

- Installs and migrates the app.
- Maintains CFG Kanban Settings.
- Can configure Masters and perform supervisor approvals.
- Investigates technical failures and ERP Commands.

### Manufacturing Manager

- Creates and maintains Kanban Masters and Cards.
- Approves Signals and Sales Demand proposals.
- Replaces cards and handling-unit tags.
- Reviews and resolves operational Exceptions.

### Manufacturing User

- Uses the Kanban Operator page.
- Reads Signals, Cycles, progress, and exceptions allowed by role permissions.
- Starts or completes linked Job Cards and reports operation progress where authorized in ERPNext.

ERPNext permissions still apply. A Kanban role does not automatically grant permission to Items,
BOMs, Work Orders, Job Cards, Stock Entries, Warehouses, or Batches.

## 4. ERPNext prerequisites

Complete these records before configuring CFG Kanban:

1. **Company** — the production company.
2. **Warehouses** — source/raw-material, WIP, and finished-goods destination warehouses.
3. **Item** — a stock Item with the correct Stock UOM.
4. **BOM** — active and default where appropriate, with the required materials and Operations.
5. **Operations and Workstations** — in the same sequence used by the BOM.
6. **Manufacturing permissions** — users must be able to access the ERPNext records their work
   requires.

For a batched MTO product, also configure the Item as follows:

- **Has Batch No:** enabled.
- **Shelf Life in Days:** set to the customer/product requirement.
- **Default BOM:** set and valid.

For stock-based Sales Order proposals, add a warehouse row under **Item → Reorder** and set the
**Warehouse Reorder Level** for the same warehouse used as the Master's Destination Warehouse.

## 5. Open the CFG Kanban workspace

From ERPNext Desk, open **CFG Kanban** in the sidebar. The workspace is organized into:

- **Start Here:** Settings, Masters, and Cards.
- **Production Control:** Cycles, Process Executions, and Exceptions.
- **Signals and ERP Control:** Signals, ERP Commands, and Events.
- **Related Records:** progress, WIP, handling units, Sales Orders, Work Orders, Job Cards, and
  Stock Entries.

The operator interface is available at:

```text
/app/kanban-operator
```

## 6. Initial system settings

Open **CFG Kanban Settings**. Only a System Manager can maintain this Single DocType.

Recommended pilot configuration:

| Setting | Recommended starting value | Meaning |
|---|---|---|
| Enabled | Yes | Configuration flag; full server-side blocking when disabled is not yet wired |
| Default Company | Your production company | Default business context |
| Default WIP Warehouse | Pilot WIP warehouse | Intermediate production location |
| Default FG Warehouse | Pilot finished-goods warehouse | Completed-product location |
| Default Automation Level | Approval | Keeps Work Order creation under supervisor control |
| Allow Manual WO for Kanban Item | No initially | Avoids bypassing the Kanban signal during the pilot |
| Require Manual Override Reason | Yes | Preserves an audit reason for exceptions |
| Auto-submit Work Order | No initially | Allows review before ERPNext submission |
| Auto-start Job Card | No initially | Reserved setting; current operators start work deliberately |
| Enable WIP Ledger | Yes | Enables quantity handoff records |
| Enable Dynamic Forms | Yes | Shows Master-defined operator fields |
| Command Retry Limit | 3 | Intended retry control; automated retry orchestration is not complete |
| Exception Email Role | Manufacturing Manager | Intended notification audience; email automation is not complete |

Save the Settings before creating the pilot Master.

## 7. Guided setup: create the first stock-replenishment Kanban

Use one test product and one simple route. Do not start with multiple products.

### Step 1 — Create the Kanban Master

Open **CFG Kanban Master → New** and complete:

| Field | Example | Guidance |
|---|---|---|
| Kanban Name | Chili Sauce 500 ml – FG Loop | A clear loop name, not only the Item code |
| Active | Yes | Only active Masters should be used |
| Company | Your company | Must match the BOM and warehouses |
| Item | Finished Item | Item to be produced or moved |
| BOM | Default active BOM | Required for production Work Orders |
| Control Type | Production | Current vertical slice is production-focused |
| Card Representation | Batch or Container | What one card physically represents |
| Replenishment Qty | 400 | Quantity represented by one normal card |
| Stock UOM | Nos | Must match the Item/BOM context |
| Number of Cards | 2 | Planned physical cards for the loop |
| Source Warehouse | Raw-material/source | Used by the Work Order command |
| WIP Warehouse | Production WIP | Used by ERPNext manufacturing |
| Destination Warehouse | Finished Goods | Stock target and finished output destination |
| Automation Level | Approval | Recommended until the process is proven |
| Default Priority | Normal | Applied to Signals and Cycles |
| Allow Partial Output | As required | Policy indicator for the loop |
| Use ERP BOM Operations | Yes | Keep ERPNext Operations as the route source |
| Revision | 1 | Increase when the controlled design changes |

The Replenishment Qty is the card quantity. It is not the warehouse minimum stock level.

### Step 2 — Add operation profiles

Add one row for every controlled operation, in sequence. For example:

```text
10 Cooking
20 Bottling
30 Cartoning
```

Important profile fields:

| Field | Purpose |
|---|---|
| Operation | ERPNext Operation used by the BOM/Job Card |
| Sequence | Unique processing order within this Master |
| Workstation | Preferred workstation |
| Mandatory | Whether the operation is required |
| Allow Parallel | Allows overlapping Job Cards when process conditions permit |
| Dependency Operation | Upstream operation controlling readiness |
| Start Rule | When the operation may begin |
| Minimum Qty / Percentage | Threshold used by the applicable start rule |
| Transfer Multiple | Smallest quantity released digitally, such as 12 bottles per carton |
| Output Reporting Mode | Completion-only or incremental reporting |
| Handoff Mode | How output becomes available downstream |
| Destination Operation | Operation receiving the released quantity |
| Completion Rule | Full quantity, operator completion, or threshold |

Handoff modes:

- **Full Batch Handoff:** downstream waits for the complete upstream batch.
- **Digital Quantity Handoff:** reported good quantity is released in Transfer Multiple increments.
- **Physical Card Handoff:** a card scan creates the handoff ledger entry.
- **Automatic Handoff:** reserved for controlled automatic behavior; validate on the pilot before use.

Example pilot:

| From | To | Recommended handoff |
|---|---|---|
| Cooking | Bottling | Full Batch Handoff |
| Bottling | Cartoning | Digital Quantity Handoff; transfer multiple = carton size |
| Cartoning | FG | Full Batch Handoff |

### Step 3 — Add dynamic operator fields

Use **Operator Field Definitions** for process information not represented by standard ERPNext Job
Card fields. Example Cooking fields:

```text
Field Key: cooking_temperature
Label: Cooking Temperature
Field Type: Float
Mandatory: Yes
Unit: °C
Minimum Value: 85
Maximum Value: 95
Capture On: Progress
```

Rules:

- Field Key should be stable, lowercase, and use underscores.
- Select options must be one option per line.
- Numeric minimum and maximum values are validated by the server.
- Mandatory fields must be supplied in the operator progress dialog.
- `Map to Job Card` and `Job Card Field` describe intended mapping, but generic automatic mapping to
  arbitrary Job Card fields is not yet complete.
- Current Operator Desk implementation displays definitions captured on **Progress**. Start and
  Complete capture screens are not yet implemented.

Save the Master. Duplicate operation sequence numbers are rejected.

### Step 4 — Create the physical cards

Open **CFG Kanban Card → New**. Create the number of cards defined by the Master.

Complete:

| Field | Guidance |
|---|---|
| Kanban Master | The pilot Master |
| Card Number | Unique visible identifier, for example `CDL-001` |
| Card Type | Physical Unit, Physical Batch, Process, or Station Card |
| Item | Same Item as the Master |
| Kanban Qty | Normally the Master's Replenishment Qty |
| Active | Yes |
| Revision | Start with 1 |
| Current State | Available |
| Current Warehouse/Station | Optional physical location |

UUID and QR Code are generated by the server if left empty. Do not copy a QR identity from another
card.

### Step 5 — Print and verify the card

Open the saved Card and use **Print Kanban**:

- **Print Standard Card:** reusable A6 landscape, two pages for front and reverse instructions.
- **Print Operational Card:** reusable A6 landscape, single-sided operational version.

For Standard Card on A4 stock, select four pages per sheet and duplex printing in the printer
dialog. Always test front/back orientation before a production print run.

The first print increments Print Count. Every reprint requires a reason and creates an Event.

### Step 6 — Trigger the first replenishment

Use either method:

1. Open **Kanban Operator**, scan the QR code or enter the Card Number, then select **Consume /
   Trigger**; or
2. Open the Card and use **Kanban Actions → Consume / Trigger**.

Expected result:

```text
Card: Available → Consumed → Signal Created
Cycle: New → Signalled
Signal: Waiting Approval
```

Repeated submission with the same request identity does not create another chain. A card with an
Active Cycle returns the existing Cycle and Signal.

### Step 7 — Approve and create the Work Order

Open the Signal and select **Approve and Create Work Order**. This action requires Manufacturing
Manager or System Manager.

Expected result:

```text
Card: Signal Created → Replenishment Requested → Production Released
Signal: Validated → Executing → Completed
ERP Command: Pending → Running → Completed
Cycle: Signalled → Released
ERPNext: one Work Order created
```

If Auto-submit Work Order is disabled, review and submit the Work Order in ERPNext. ERPNext then
creates the Job Cards according to its BOM and manufacturing rules.

## 8. Production operation workflow

When ERPNext creates Job Cards, CFG Kanban mirrors matching BOM Operations into **CFG Kanban
Process Execution** records. Operations missing from the Master profile are not mirrored.

### Start work

In **Kanban Operator**, scan the reusable card and locate the Process Execution. When its status is
Ready, select **Start**. The app sends the action through an auditable ERP Command to the linked
ERPNext Job Card.

### Report progress

Select **Report Progress** and enter:

- Good Qty — accepted output in this progress entry.
- Reject Qty — rejected output in this progress entry.
- Notes — optional operator explanation.
- Dynamic operation checks — fields defined on the Master.

Progress entries are incremental. If the execution already contains 100 good units and the next
entry is 50, the execution total becomes 150. Do not enter the cumulative total unless it is truly
new output.

Progress records are immutable. Corrections require a future explicit adjustment workflow; do not
delete or edit production history directly.

For Digital Quantity Handoff, the app releases only completed Transfer Multiples. Example:

```text
Transfer multiple: 12
Total good output: 29
Eligible release: 24
Previously released: 12
New WIP release: 12
```

### Complete work

When a linked Job Card is In Progress, select **Complete**. ERPNext Job Card feedback updates the
Process Execution. ERPNext Work Order feedback moves the Cycle into In Production and later
Production Complete.

Submitting a linked Manufacture Stock Entry records an Event and moves the Cycle to **Waiting FG
Receipt**.

> Current limitation: do not expect the card to reset automatically after receipt. Final cycle
> closure and reusable-card return are the next required control stage.

## 9. Stock-based Sales Order proposals

This mode uses a submitted Sales Order as an evaluation event but still replenishes a warehouse
stock target.

### Master configuration

Configure:

- Enable Sales Order Trigger: Yes.
- Production Policy: Stock Replenishment.
- Threshold Source: ERPNext Warehouse Reorder Level, recommended; or Kanban Override.
- Demand Scope: General, Customer, Sales Territory, or Production Line.
- Demand Scope Value: exact value for a non-General scope.
- Master Priority: higher number wins where valid scopes overlap.
- Minimum Shortage to Propose: optional noise threshold.
- Maximum Cards per Sales Order: safety cap.

The app selects by Sales Order warehouse, then most-specific scope, then highest priority. It
rejects duplicate active Masters with the same Item, destination warehouse, scope, and scope value.
A remaining tie creates a configuration Exception instead of producing duplicate Work Orders.

### Calculation

```text
Shortage = inventory target
           − ERPNext projected quantity
           − open Kanban cycle supply
           − other waiting proposal supply

Cards required = shortage rounded up by Master replenishment quantity
```

Sales Order outstanding quantity is displayed for audit but is not added again because submitted
Sales Order demand is already represented in ERPNext projected quantity.

### Approve the proposal

Submit the Sales Order. Evaluation runs automatically. A manager can also use **Create → Evaluate
Kanban Demand** on the submitted Sales Order.

Open **Sales Demand Proposals**, review a Waiting Approval record, and select **Approve and
Release**. The app reserves the required Available cards, creates one Signal and Cycle, and creates
the Work Order through the ERP gateway.

If insufficient cards are available, the Demand becomes Blocked and an Exception is created.

## 10. Customer Make-to-Order workflow

Use this for a customer whose product is made only against an order, with a dedicated batch and
common expiry date.

### Master configuration

Create a Customer-scoped Master:

```text
Enable Sales Order Trigger: Yes
Demand Scope: Customer
Demand Scope Value: exact ERPNext Customer ID
Production Policy: Customer Make-to-Order
MTO Extra Production Tolerance %: maximum allowed by internal policy
Plan Work Order to Maximum Permitted Qty: Yes or No
MTO Batch Policy: One Batch per Sales Order Line
Existing Stock Usage: Prohibited
Order Consolidation: Prohibited
```

The same Master is reused for different order quantities. Do not create a new Master for every
quantity.

### Sales Order customer-PO controls

In the Sales Order's **CFG Kanban Demand** section, record:

- Customer PO Allows Extra Quantity.
- Customer PO Extra Tolerance %.
- PO Tolerance Reference — PO clause, amendment, or written authorization.

Effective tolerance is the lower percentage:

```text
Master permits 5%
Customer PO permits 3%
Effective tolerance = 3%
```

Without explicit PO authorization, effective tolerance is zero.

For an outstanding quantity of 1,000 and effective tolerance of 3%:

```text
Base order quantity:       1,000
Maximum authorized output: 1,030
```

If **Plan Work Order to Maximum Permitted Qty** is enabled, the proposal recommends 1,030. If it is
disabled, the proposal recommends 1,000 while still allowing accepted output up to 1,030.

### Approval and batch creation

Submit the Sales Order, open its CFG Kanban Demand, and select **Approve and Release**.

Expected result:

- No reusable card is reserved.
- One Cycle is created for that Sales Order line.
- One ERPNext Batch is created and linked to the Demand, Cycle, and Sales Order.
- Batch expiry is calculated from Item Shelf Life in Days.
- One Work Order is created for the recommended quantity.
- Work Order Production Origin is Sales Order.

Every Sales Order line has its own idempotency identity, so separate lines or orders are not
consolidated into one MTO Cycle.

### Manufacture Stock Entry control

When submitting an MTO Manufacture Stock Entry:

- The finished Item row must use the Cycle's planned Batch.
- Blank or different finished Batch is rejected.
- Cumulative accepted production cannot exceed Maximum Authorized Qty.
- Output above the base outstanding quantity but within the authorized maximum is recorded as
  PO-authorized excess.

The planned Batch is currently not filled automatically into the Stock Entry. Select it manually
and verify it before submission.

The app does not silently increase a submitted Sales Order. Delivery or invoicing of additional
quantity remains governed by ERPNext amendment and over-delivery controls.

## 11. Handling-unit tags

A Handling Unit identifies one physical pallet, mesh, tote, or container. It is different from a
reusable Kanban Card and cannot trigger replenishment.

Create **CFG Kanban Handling Unit → New** after a Cycle exists. Enter:

- Handling Unit Type and unique visible ID.
- Kanban Cycle.
- Quantity and UOM.
- Carton/container count where applicable.
- Immediate Source and Immediate Destination.
- Sequence No. and Total Units, for example `1 of 3`.

Item, Batch, Work Order, reusable Card, and description are copied from the Cycle when available.
The Opaque Token is generated automatically; users should not type or reuse it.

Use **Kanban Actions → Print Thermal Tag**. The PDF canvas is 45 mm × 250 mm for portrait-feed
thermal stock, with the horizontal tag design rotated onto that canvas.

Handling-unit scan lifecycle:

```text
Issued → Attached → Dispatched → Received
   └──────────────→ Void
```

Received, Void, and Replaced are terminal states. A repeated terminal scan returns the existing
state without triggering production.

Reprints require a reason. Replacement creates a new tag identity and revision, marks the old tag
Replaced, and preserves the relationship between both records.

## 12. Android scanning

The current user-facing method is a browser session on the Android device:

1. Connect the device to a secure network that can reach ERPNext.
2. Open the ERPNext HTTPS address in Chrome.
3. Log in with an authorized Manufacturing User account.
4. Open `/app/kanban-operator`.
5. Use an Android scanner that types QR content as keyboard input, or manually enter the Card
   Number.
6. Select **Find Card**, then perform the available action.

The current page accepts scanner keyboard input but does not yet open the phone camera itself. A
camera-based Progressive Web App, offline queue, and device enrollment are not implemented.

The server scan APIs support stable event tokens for retry/idempotency. Custom scanner clients
must retain the same event token when retrying the same physical scan.

## 13. Understanding system records

| Record | What it means | Normally edited by users? |
|---|---|---|
| CFG Kanban Master | Controlled definition of one replenishment or MTO loop | Managers only |
| CFG Kanban Card | Reusable physical/digital trigger identity | Managers create; operators scan |
| CFG Kanban Demand | Sales Order evaluation and approval record | Managers approve |
| CFG Kanban Signal | Validated request to initiate replenishment | Managers approve |
| CFG Kanban Cycle | One production/replenishment instance | Mostly system-controlled |
| CFG ERP Command | Audited instruction sent to ERPNext | Read-only investigation |
| Process Execution | Kanban view of one Job Card operation | Operated through console |
| Operation Progress | Immutable incremental operator report | Created, not edited |
| WIP Ledger | Quantity releases and handoffs | System-created |
| Event | Audit timeline entry | System-created |
| Exception | Something needing review | Managers acknowledge/resolve |
| Handling Unit | Identity of a pallet/container within a Cycle | Created and scanned operationally |

## 14. State references

Reusable Card states:

```text
Available
→ Consumed
→ Signal Created
→ Replenishment Requested
→ Production Released
→ In Production
→ Produced
→ In Transit
→ Available
```

Blocked can be entered from operational states. Inactive is used for retired/replaced cards.
Although the state model includes the complete path, automatic transitions after In Production are
not yet fully wired in the current vertical slice.

Cycle states:

```text
New → Signalled → Released → In Production
→ Production Complete → Waiting FG Receipt → Completed
```

Hold, Blocked, and Cancelled represent exceptions or stopped work. Final completion controls remain
under development.

## 15. Troubleshooting

### “Card cannot move from … to …”

The requested action skipped a controlled state. Open the Card, Cycle, Signal, and Event Timeline
to identify the last successful step. Do not manually overwrite the state. For approval flow, the
expected pre-Work-Order sequence is Signal Created → Replenishment Requested → Production Released.

### No Sales Demand was created

Check:

- Sales Order is submitted.
- Sales Order Item warehouse matches the Master Destination Warehouse.
- Master is Active and Enable Sales Order Trigger is enabled.
- Item matches exactly.
- Customer/Territory/Production Line scope value matches the Sales Order.
- There is no equally ranked matching Master.
- For stock policy, a shortage actually exists.

### Demand is Blocked because no reorder level exists

For Stock Replenishment, add the matching warehouse under Item → Reorder, or intentionally select
Kanban Override and enter a positive Minimum Stock Override on the Master.

### Demand is Blocked because cards are unavailable

Review Cards for the Master. A card must be Active, Available, have no Active Cycle, and not be
reserved for another Demand. Do not create additional cards merely to clear an unexplained block;
first reconcile the physical cards and active production.

### MTO approval says the Item must have Batch enabled

Open the Item, enable Has Batch No, set Shelf Life in Days, and confirm the BOM. Re-evaluate and
approve only after the product's batch policy is correct.

### MTO Manufacture Stock Entry rejects the Batch

Open the related CFG Kanban Demand or Cycle and use its Planned Batch on the finished Item row. Raw
materials may use their own appropriate batches; the restriction described here is for the MTO
finished output Item.

### MTO output exceeds authorized maximum

Do not bypass the validation. Obtain a revised customer PO authorization and update/amend the
commercial document through the approved ERPNext process. The current released Demand does not
automatically recalculate after approval, so supervisor/technical review is required.

### Work Order was not created

Open the related CFG ERP Command:

- Pending — not yet executed.
- Running — execution began but did not complete.
- Failed — review Last Error and correct the ERPNext prerequisite.
- Completed — open Target Document.

Common causes include missing/default BOM, company mismatch, warehouse configuration, ERPNext
permissions, or invalid Work Order data.

### Job Cards do not appear in Kanban Operator

Confirm the Work Order has generated ERPNext Job Cards and that each Job Card Operation exactly
matches an Operation Profile on the Master. Refresh or update the Work Order so ERP feedback can
synchronize them.

### Print format fails or shows A4

Confirm the current app version is deployed, migration and build completed, cache was cleared, and
the correct CFG Kanban print format was selected with no letterhead. Browser preview may display
surrounding whitespace; verify the downloaded PDF page dimensions and printer scaling.

## 16. Audit and control rules

- Do not manually create ERPNext Work Orders to bypass a blocked Kanban Signal.
- Do not photocopy, duplicate, or manually edit QR/opaque identities.
- Use Replace Card or Replace Tag so the former identity becomes unusable.
- Supply a stable event token when a scanner retries the same action.
- Review Events for who, when, state transition, quantity, device, and linked document.
- Review ERP Commands for every controlled ERPNext write.
- Treat WIP Ledger and Operation Progress as audit records, not editable worksheets.
- Resolve Exceptions with an explanation instead of deleting them.

## 17. Deployment and update procedure

Before every development-server deployment, take a site backup. Then update the server:

```bash
cd ~/frappe-bench/apps/cfg_kanban
git pull upstream main

cd ~/frappe-bench
bench --site site1.local migrate
bench build --app cfg_kanban
bench --site site1.local clear-cache
bench restart
```

After deployment, confirm:

```bash
bench --site site1.local list-apps
```

Then perform one controlled test before using the new behavior with production data.

## 18. First-pilot acceptance checklist

- [ ] Development site backup completed.
- [ ] App migration and build completed without errors.
- [ ] Settings configured in Approval mode.
- [ ] Test Item, BOM, Operations, and Warehouses verified.
- [ ] One Master created with unique operation sequences.
- [ ] Dynamic progress fields tested.
- [ ] Physical card identity printed and scanned.
- [ ] One Signal approved.
- [ ] Exactly one Cycle and Work Order created.
- [ ] ERPNext Job Cards mirrored as Process Executions.
- [ ] Progress and WIP releases verified.
- [ ] Reprint audit verified.
- [ ] Handling-unit tag printed and lifecycle tested.
- [ ] Stock Sales Order calculation verified, if used.
- [ ] MTO PO tolerance, dedicated Batch, and maximum-output validation verified, if used.
- [ ] Events, ERP Commands, and Exceptions reviewed.
- [ ] Known incomplete cycle-closure behavior understood by pilot users.

## 19. Current limitations and planned manual updates

The following are not complete in the current build:

- Final FG receipt confirmation, Cycle closure, reusable-card release, and return to Available.
- Automatic planned Batch selection on Manufacture Stock Entry.
- Delivery Note enforcement of the Sales Order's dedicated MTO Batch.
- Controlled assistant for Sales Order quantity amendment/accepted excess.
- Underproduction and incomplete-batch supervisor disposition.
- Camera scanning, PWA installation, offline scan queue, and device management.
- Full Start/Complete dynamic-field capture and arbitrary Job Card field mapping.
- Automated email alerts and complete command retry orchestration.
- Supplier Kanban and Sales Order fulfillment allocation beyond the implemented demand controls.

This file is the maintained manual source. Update its version, date, affected sections, and revision
history whenever a user-visible workflow changes.

## 20. Revision history

| Version | Date | Change |
|---|---|---|
| 0.1 | 11 September 2026 | Initial manual covering the current stock, Sales Order, MTO, printing, scanning, execution, WIP, and audit functions |

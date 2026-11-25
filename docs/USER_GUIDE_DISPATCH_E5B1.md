# Guided dispatch leftover return / transfer — E5B1

Development increment, 20 November 2026. Native ERP, migration, concurrency and device acceptance
are not yet recorded. This reuses the existing Movement Manifest, Material Transfer and D3 count;
it does not create another delivery or stock-posting engine.

## Set up once

1. Create an active **CFG Kanban Logistics Route** for each approved destination:
   - Route Type: **Internal Warehouse Transfer**.
   - Source Company and Destination Company: the Dispatch Plan's Company.
   - Source Warehouse: the original lorry Warehouse.
   - Destination Warehouse: the return warehouse, or another configured lorry Warehouse.
   - Internal Transfer Posting Mode: **Direct Transfer**.
   - Set **Dispatch Responsibility** and **Supervisor Responsibility**.
   - Choose **Submit Internal Dispatch on Operator Confirmation**. Enabled posts on confirmation;
     disabled creates an ERP Draft for authorized Stock Manager review/submission.
2. The operator must be a **Supervisor** (or Development Proxy), have **Override**, Start and
   Complete permissions, the Plan's Dispatch Responsibility, **Logistics Reconciliation**, and
   both responsibilities on the chosen recovery route. The existing Supervisor view-all policy applies.
3. Source and destination must be active leaf Warehouses in that Company. Lorry Warehouses need
   their vehicle flag/reference. Intercompany, transit and destination-selected-at-receipt routes
   are outside this increment. Even one eligible route requires an explicit numbered selection.
4. Migrate and build this revision before use; new Review/Manifest fields and the scanner asset
   are required. Print the new commands from **Kanban Operator → Scanner Command Labels**.

## Operator / supervisor sequence

1. Finish or cancel unfinished customer work, including proof. Start the existing **Dispatch Review**
   from the loaded Plan. The Review freezes further fulfilment; it does not move stock.
2. Select **Return / Transfer Leftovers** on the Plan, or **Prepare Return / Transfer** inside its
   Review. Scanner: `CFG:CMD:RECOVER_DISPATCH`, then scan the Plan (`DPL-...`), Review (`KDR-...`)
   or an already-created recovery Manifest (`KMF-...`).
3. Choose the numbered approved destination route, enter the Supervisor reason and **Confirm**.
   The checklist contains **all remaining prepared allocations**, after actual delivered quantities,
   to **one destination**. This creates a Draft Manifest and no stock withdrawal.
4. Scan each physical Stock Tag. If it is inside a reusable container, scan that container; every
   contained tag must belong to this recovery. Each exact source turns **Confirmed**.
5. For each loose-stock row, select its number, physically count the Item/Batch in its stock UOM,
   enter that exact quantity and Confirm. Tagged and loose rows can be confirmed in either order.
   A changed quantity requires investigation; this action cannot change the reviewed balance.
6. **Prepare and Reserve** after every source is confirmed. Tags use the existing quantity ledger;
   loose stock retains its existing Plan commitment, without a second reservation or an invented tag.
7. Review the destination and **Post / Create ERP Movement**, then Confirm. Mandatory ERP fields
   use the same scanner/touch scalar and table controls as customer delivery. If the route creates
   a Draft, an authorized ERP user submits that saved Stock Entry and then **Refresh** reads feedback.
   Stock and tag/container locations change only through native submitted Stock Entry feedback.
8. Evaluate and close a fresh balanced **D3 lorry stock count after posting**. An existing open count
   may be re-evaluated; a count already closed before the movement cannot be reused.
9. Select **Finish Review**. Its movement/disposition are read from the linked completed Manifest.
   Scan the closed `KREC-...` count, enter the closing reason and Confirm. The original Plan is
   reconciled, its old commitments released and its loading/vehicle history preserved.

Complete step 9 before using the recovered stock. Stock transferred to another lorry is available
through existing controlled stock selection after settlement; this action creates no receiving
Dispatch Plan and does not reassign the old Plan's lorry. A normal two-to-three-day trip still uses
one active Plan; do not start recovery or an end-of-trip review for an ordinary overnight stop.

## Scanner commands

All command names below use the `CFG:CMD:` prefix:

| Command | Action |
| --- | --- |
| `RECOVER_DISPATCH` | Open the recovery checklist; scan Plan/Review/Manifest |
| `RECOVERY_REASON` | Arm the next scanned reason |
| `RECOVERY_SOURCE` | Arm a physical source scan |
| `RECOVERY_PREPARE` | Select preparation; Confirm reserves confirmed sources |
| `RECOVERY_POST` | Select ERP creation/posting; Confirm reviews required ERP inputs |
| `RECOVERY_CANCEL` | Select cancellation of an unused recovery; enter a new reason, Confirm |
| `RECOVERY_REFRESH` | Read recorded server state |
| `RECOVERY_CAMERA` | Open camera scanning |
| `FINISH_DISPATCH_REVIEW` | After movement posting, open final Review completion |
| `CONFIRM` / `CANCEL` | Submit displayed step / close the dialog safely |

Use `CFG:SELECT:1`–`CFG:SELECT:10` for routes or loose rows, and
`CFG:CMD:NEXT_MATERIALS` / `CFG:CMD:PREVIOUS_MATERIALS` for pages.
`CFG:QTY:MATERIAL:5` enters a counted loose quantity of five in the displayed stock UOM.
In a mandatory ERP-input dialog, select numbered fields and scan their values. Tables use
`DELIVERY_ADD_ROW`, `DELIVERY_NEXT_ROW`, `DELIVERY_PREVIOUS_ROW`, numbered columns and scanned
values; `DELIVERY_INPUTS` returns to the field list. `DELIVERY_CAMERA` opens that dialog's camera.
Tablet camera buttons and Tab/Enter scanner suffixes use the same controller. Cancel closes a
nested input dialog without posting; closing the outer dialog does not cancel its saved Manifest.

## Corrections and boundaries

- Reopen/Refresh reads the existing Manifest. Repeated creation for the same Review cannot create
  a second active recovery. Uncertain submissions keep their original token and details for retry;
  after closing/reopening, read recorded state before changing anything.
- **Cancel Unused Recovery** releases its tag reservations once, retains the audit record, and
  permits a new destination/checklist. It is available only before ERP work is created. A pending
  ERP command or saved Draft must be resolved through its existing document/retry path. Recovery
  Stock Entries cannot be deleted to abandon the movement or substituted with another Draft.
- A Review cannot resume, close as stock-stays or use unrelated movement while a linked recovery
  remains active. After posting, it must settle with that exact Stock Entry and disposition.
- Whole physical tags only. If physical tag quantity differs from the prepared remainder, or a
  container contains other Plans' stock, resolve/split/repack it through the existing controlled
  tools before recovery. The checklist does not sweep up unrelated lorry inventory.
- Certificates, expiry, serial identity and tag provenance use the existing immutable logistics
  snapshot. Loose Batch stock keeps its exact ERP Batch. Serial-controlled stock requires its tag;
  loose stock cannot borrow or infer certificate identity from nearby certified stock.
- Expiry/quality decisions are not rewritten. This is a return/transfer, with no QC decision,
  write-off, new certificate, quantity adjustment or customer credit.
- Mixed per-line dispositions, multiple destinations, follow-on recovery Plans, vehicle
  reassignment and wider partial/refused known-customer fulfilment remain later E5 increments.

See [E5B1 acceptance checklist](TEST_DISPATCH_E5B1_RECOVERY.md) and
[E5A final review/count rules](USER_GUIDE_DISPATCH_E5A.md).


## Trip Handover and per-item leftovers — E5B2 extension

Open **Delivery Trip / Driver Route → Trip Handover** for the full-page balance/return view.
Authorized Supervisors may assign remaining sources to multiple approved destinations and retain
selected sound stock on the lorry. Existing scans/native movements, a fresh balanced D3 count and
Review settlement still apply. Whole tags/held sources stay together; old returns use their existing
QC receipt, with no duplicate receipt/credit. Office closure now requires old-return physical receipt,
while inspection/accounting may continue. See [E5B2 setup and scanner guide](USER_GUIDE_DISPATCH_E5B2.md)
and [acceptance checklist](TEST_DISPATCH_E5B2_RECOVERY.md). Implementation does not establish live acceptance.

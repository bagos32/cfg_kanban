# Trip Handover and per-item leftover recovery — E5B2

Development increment, 24 November 2026, above `d466852`. Native ERPNext, warehouse,
database-concurrency and tablet/scanner acceptance remain pending.

## Set up the destinations

Use the existing **CFG Kanban Logistics Route** records. Each destination needs an active,
same-Company **Internal Warehouse Transfer / Direct Transfer** route from the original lorry
Warehouse. Configure the receiving stock warehouse, appropriate QC/quarantine warehouse, or
another lorry as the destination. Dispatch and Supervisor responsibilities remain mandatory.
The route's existing Draft/automatic Stock Entry submission policy still applies.

The terminal user needs native Read permissions for the Trip, Plan, Review, routes, Company,
Warehouses, Items, Batches and Stock Tags involved. The deciding operator must be a Supervisor
with **Override** and **Logistics Reconciliation**, plus the Plan/route responsibilities. Start
and Complete permissions apply to their existing steps. Driver/assistant access is read-only
and limited to assigned Trips; scanning a Trip does not grant another driver's access.

## One full-page handover view

Open **CFG Kanban Delivery Trip → Trip Handover**, or **Driver Route → Trip Handover**.
The Desk route is `/app/kanban-trip-handover`. A Trip QR, Plan or Review number can open the
same view. A standalone loaded Plan without an office Trip is available only to an authorized
reconciliation Supervisor.

The page shows:

- loaded, delivered, refused and prepared remaining quantities for each Plan, Item/Batch/tag/UOM;
- the current ERP lorry balance, explicitly including other Plans and unassigned stock;
- collected old customer returns and company-owned QC refusals with their existing Case status;
- frozen recovery instructions and each destination Manifest's posting status.

**Refused quantity is included in the prepared remainder while held.** Do not add it to that
remainder again. Old customer returns are separate non-stock custody and are not added to ERP
lorry stock or used to replace missing prepared quantities. Their quantities keep their own UOM.

## Supervisor sequence

1. Finish or cancel unfinished delivery/proof work. On Trip Handover select the exact Plan.
2. Choose **Begin Review**, then **Confirm**. This reuses the E5 Review and freezes new fulfilment.
   A route spanning two or three days need not be reviewed at each overnight stop.
3. Select **Remaining Items**, choose the exact source, then **Select Destination**. Explicitly
   choose an approved route or **Keep on Lorry**. Enter the quantity in stock UOM and **Add Choice**.
4. Repeat until every prepared remainder is accounted for. Loose stock may have several quantity
   rows/destinations. Each physical Stock Tag and held refusal/cancelled source must stay together.
   For different destinations from one physical tag, use controlled split/repack **before** this
   Review; the handover does not silently generate new tags or divide held custody.
5. **Review / Remove Choices** shows all unsaved instructions. Selecting a numbered choice removes
   it. Enter a Supervisor reason, **Approve Per-item Decisions**, then **Confirm**. Approval creates
   one Draft recovery Manifest per route in one transaction. It does not post ERP stock.
6. **Open Recovery Movements** lists the destinations. Select each exact Manifest. Use the existing
   source scans/loose physical confirmations, **Prepare**, and **Post / Create ERP Movement**.
   Mandatory ERP inputs and authorized native submission of saved Drafts remain unchanged.
   Finish every destination group before final settlement.
7. **Open Lorry Count** uses the existing D3 count. Count all actual lorry stock, including other
   Plans/unassigned stock, and close a fresh balanced count after every recovery has posted.
8. Select the Plan again, choose **Finish Review**, use **Mixed Leftover Dispositions**, scan the
   closed `KREC-...` count, enter the reason and Confirm. Each exact submitted movement, tag ledger,
   kept source quantity, count freshness and absence of open work are rechecked server-side.
9. Settle every linked Plan, then use the normal Delivery Trip **Close Planning / Cancel Planning**
   action with its reason. The Trip page and history remain the office closing authority.

Example: one tag of 5 Nos stays on the lorry, while a loose source of 6 Kg is split between
3 Kg to the warehouse and 3 Kg to a second approved destination. Quantities are not combined
across Nos/Kg. Goods with an existing QC hold retain that hold at their receiving destination.

**Keep on Lorry closes the old Plan at final settlement and releases its old commitments.**
It does not move stock, assign another Trip or authorize resale of held/rejected material.
Next-trip use requires the ordinary eligibility/allocation checks. To keep the *same* Plan
active overnight, use the existing whole-Plan **Continue Same Plan Overnight → Resume** path
before approving a per-item recovery.

## Collected returns and QC receipt

Choose **Collected Returns / QC**, then the exact Case to open the existing Customer Return QC
page. QC staff confirm physical receipt and inspection there. Existing accepted-return stock
disposition and accounting decisions continue independently; this page creates neither a second
Material Receipt nor a customer Credit Note. A company-owned quality refusal keeps its existing
owned-stock hold and recovery linkage rather than being received as new customer stock.
Owned-stock release or disposal confirmation must wait until the frozen per-item Review is settled;
QC cannot change that approved stock budget halfway through recovery. Physical receipt and
inspection may proceed.

A Delivery Trip cannot close while an uncancelled old customer return still lacks its recorded
physical QC receipt, including Cases hidden from the closing user's worklist. QC completion,
credit and final physical disposition may continue after receipt and Trip closure. Native Case
permissions control which details each operator can see.

## Corrections, retries and audit

- Before **any** group has an ERP command/Draft, **Cancel Unused Decisions** plus a new reason
  and Confirm cancels the whole arrangement and restores reservations/return custody once.
  Review and Manifest history is retained. You may then approve corrected instructions.
- Individual groups cannot be cancelled independently. Once any ERP work starts, retain the
  frozen recipe and resolve its saved documents; do not discard the other destinations.
- Unknown submissions keep their original quantities, reason, balance hash and event token in
  browser storage for that ERP user/operator. Web Locks serialize submissions across tabs; a supported
  HTTPS browser is required for mutation. A concurrent pending action cannot be overwritten. Retry the original action after reopening. Back,
  Cancel or Refresh never certifies that an uncertain request failed or that stock moved.
- A confirmed first validation rejection allows correction. An unresolved retry/conflicting
  identity remains locked. Native permissions and original actor checks still apply on retry.
- Recovery evidence cannot settle another Plan or be cancelled after final settlement. Use an
  audited follow-on movement for later corrections. Original E3 loading/lorry history remains intact.
- The original **Return / Transfer Dispatch Leftovers** action remains available for legacy
  whole-remainder recovery. Per-item groups can be reopened by their own `KMF-...` identity.

## Scanner and tablet controls

Use Enter or Tab suffixes. Camera buttons use the same controller. Scanner Ready focus returns
after completion, error or cancellation; operator changes remove prior private data.

All action names below use `CFG:CMD:`:

| Command | Action |
| --- | --- |
| `TRIP_HANDOVER` | Open the full-page Trip/Plan handover from Operator, Logistics or Driver Route |
| `HANDOVER_PLANS` / `HANDOVER_ITEMS` | Show numbered Plans / remaining sources |
| `HANDOVER_BEGIN_REVIEW` | Select Begin Review; Confirm freezes fulfilment |
| `HANDOVER_DESTINATION` | Show numbered routes plus explicit Keep on Lorry |
| `HANDOVER_ADD` | Add the selected source quantity/destination to the unsaved instructions |
| `HANDOVER_CHOICES` | Show all unsaved decisions; a numbered choice removes it |
| `HANDOVER_REASON` | Arm the next scanned Supervisor reason |
| `HANDOVER_APPROVE` | Select approval; Confirm freezes all quantities and destinations |
| `HANDOVER_MOVEMENTS` | Select an exact destination's existing scan/post recovery checklist |
| `HANDOVER_CANCEL_DECISIONS` | Select whole-arrangement unused cancellation; reason and Confirm |
| `HANDOVER_RETURNS` | Select an existing Return Case / QC follow-up |
| `HANDOVER_COUNT` | Open the existing D3 count with scanner-operable inputs |
| `HANDOVER_FINISH` | Open final Review with mixed disposition and fresh-count checks |
| `HANDOVER_CAMERA` | Scan with the tablet camera |
| `REFRESH` / `HELP` / `CANCEL` | Re-read (clears unsaved choices), scanner guidance, safe Back |

`CFG:SELECT:1`–`CFG:SELECT:10` selects the visible numbered choice. Next/Previous Materials page
choices. `CFG:QTY:MATERIAL:3` enters stock quantity 3. A displayed physical Stock Tag may select
its predefined source directly. Unclear/unlisted identities do not silently choose another source.

For D3 in Logistics use **START_ROUTE_COUNT**, select the exact Company lorry (the originating
Trip may prefill its known lorry), then Confirm. **ROUTE_COUNT_SCAN** arms physical tag/container
scans. **ROUTE_COUNT_LOOSE** opens the existing table: numbered field, **DELIVERY_ADD_ROW**,
numbered Item/Batch/Qty column and scanned values; **DELIVERY_INPUTS** returns to headers.
**ROUTE_COUNT_EVALUATE** compares against ERP; **ROUTE_COUNT_CLOSE** opens closing/correction
inputs, then Confirm. **DELIVERY_CAMERA** opens the input dialog's camera. These controls reuse
the existing server count/variance rules; they do not post a quantity correction.

See [acceptance record](TEST_DISPATCH_E5B2_RECOVERY.md). Follow-on Trips/vehicle reassignment are now covered by
E5B3. No commit, deployment or live ERP acceptance is implied by this guide.

E5B3's [follow-on guide](USER_GUIDE_DISPATCH_E5B3.md) includes confirmed old-return custody takeover.
The [combined E5 acceptance procedure](TEST_DISPATCH_E5_COMBINED.md) covers E5B2, follow-on stock
and returns, and recovery before departure; site acceptance remains unrun.

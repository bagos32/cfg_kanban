# Lorry stock, customer routes and the Logistics floor

Development extension, 20 November 2026. This guide describes local implementation;
migration, native ERP/database, PDF and real kiosk/tablet acceptance remain unverified.

## What changed

| Requirement | Behaviour |
| --- | --- |
| Stock disappears from lorry card after dispatch completes | Warehouse Operations lorry scans now read current ERP stock independently of open Manifests. Tagged and untagged quantities remain visible after loading completes. |
| Customer/route disappears after loading | Assigned loaded Plans and their customer stops remain visible; active Route Sheets show customer names, addresses, order and visit status. |
| Driver needs a route reference before a Customer QR scan | Lorry Route Sheet opens from a lorry card or Plan. Driver reads the assigned sequence before arrival and selects the exact stop. |
| Floor needs upcoming dispatch/loading work | Dashboard Profile **Logistics and Delivery** now shows Upcoming Preparation, Ready to Load and assigned lorries without production workstations. |
| Reusable customer sequence | **CFG Kanban Route Template** stores the ordered Customer Sites and instructions; select it while operating the Dispatch Card. |
| Supervisor needs simple reordering | **Plan / Approve Route Sequence** supports drag/drop, touch arrows and scanner Move Up/Down before approval. Approved order and template snapshots are retained. |

The original gap was in the read view: it listed claimable Plans/open movements and omitted
current stock/loaded Plans. This does not prove stock was lost in the user's development database.

## 1. Permanent lorry card

1. Maintain a separate ERPNext Warehouse for each selling Company owning stock on the physical
   lorry. Enable **Is Vehicle Warehouse** and fill **Vehicle Reference**.
2. Create an active, unblocked **Location Card → Warehouse Operations** with that Current Warehouse
   and matching Company. Fix this permanent card to the lorry.
3. Keep the existing same-Company **Direct Internal Warehouse Transfer** loading route and Dispatch
   Profile/E3 setup. Goods-in-Transit does not become direct loading through this extension.
4. Give drivers the applicable Plan/route **Dispatch Responsibility**, **Customer Delivery** and
   **Start / Complete** permissions. Supervisors planning/approving need **Supervisor** Kanban role
   and **Override** permission. Combined routes require access to every included Plan.
5. The terminal ERP user needs read permissions/user-permission scope for the Company, source and
   lorry Warehouses, Items, Dispatch Plans, Customer Sites and Addresses used by the route.

Scan the lorry card in **Kanban Logistics**. The view includes:

- **Current Lorry Stock:** current posted ERP quantities by Item/Batch/UOM, tag coverage, untagged
  remainder, physical tag/container codes, quality, certificates and expiry where recorded.
- **Customer Route Sheets:** approved/planning itinerary, customers, delivery addresses and status.
- **Assigned Loads and Customer Stops:** includes loading and Loaded work after its loading
  Manifest reaches Received.
- **Upcoming Dispatch Preparation** and the existing **Ready Loads for this Lorry** claim action.

Tag coverage identifies part of the ERP balance; it is not added to that balance. A tag/ERP
variance is shown for reconciliation. Posted non-stock operational identities are labelled
separately. Reservations do not remove physically present stock from this read view. A permission
filter can hide Item rows; the view indicates when that happens. Refresh/re-scan reads current
balances, and selected Warehouse ledger/tag changes participate in the existing live refresh.

Goods from legacy/manual transfers are visible even without a Dispatch Plan. Customer allocation
cannot be inferred from an Item: use the appropriate Plan/route to assign it. E5-settled leftover
stock may legitimately remain on the lorry without an active customer commitment.

## 2. Create the customer sequence template

Open **CFG Kanban Route Template** through Desk search. Stock Manager, Sales Manager or System
Manager can create/update it.

- Set a descriptive Template Name and Selling Company.
- Add the existing **Customer Sites** in the normal visiting order, with optional instructions.
- Drag the child-table rows into the desired default order and save.

Customer Sites remain the existing address/pricing/proof master. A physical Customer QR label is
optional when the Supervisor selects the assigned-stop verification mode below. No new customer,
price list, Delivery Note or delivery engine is created by saving a template.

Template changes increment its revision. Plans/Route Sheets keep captured snapshots; editing a
master template does not rewrite an active trip. Repeated visits are permitted for Open Route
stock, using distinct stop identities.

Office planning is also available through **CFG Dispatch Control → Office Delivery Trips**.
Templates now support region/direction and Visit Only rows. These visits are retained in the new
office planner and omitted from this guide's existing stock-delivery execution sequence. See the
[office Delivery Trip guide](USER_GUIDE_OFFICE_DELIVERY_TRIP.md) for the SO route inbox and LIFO
loading instructions. Existing Route Sheet approval and driver controls below continue unchanged.

## 3. Dispatch Profile setup

Use **CFG Kanban Dispatch Profile** with Vehicle Delivery:

| Setting | Recommended for the requested combined workflow |
| --- | --- |
| Route Sequence Scope | **Combined Lorry Trip** |
| Default Customer Route Template | Select the template from section 2 |
| Require Route Approval Before Customer Visits | Enabled automatically for Combined Lorry Trip |
| Customer Stop Sequence | **Planned Order** for enforced order; **Flexible Order** for driver choice |
| Customer Verification at Stop | Supervisor selects **Require Customer Site QR** or **Allow Assigned Stop Selection** |

**Per Dispatch Plan** remains available during setup. Enable Route Approval there when visits must
use an approved Sheet. The existing workflow remains available for legacy/per-Plan work without
route approval. Existing historical Plans are not silently converted or given relaxed QR rules.

A combined Sheet groups Customer Order and Open Route Stock Plans assigned to the **same
Company-specific lorry Warehouse**. It does not combine ownership across Companies. If member
policies differ, the Sheet uses the stricter requirements: any Planned Order member makes the
Sheet planned; any QR-required member makes it QR-required. Each Plan/customer delivery retains
its existing Session, allocations, Delivery Note and proof. Several Plans for one customer remain
separate fulfilment records, visible as separate assigned stops.

## 4. Operate and approve

1. Scan the Dispatch Operations Card and choose its workflow. The **Customer Route Template**
   field defaults from the Profile and can select another active template in that Company.
2. Prepare/reserve and complete E3 physical loading as usual. Lorry selection remains late.
3. Supervisor scans the lorry, selects **Plan / Approve Route Sequence**, and selects the exact
   combined trip or individual Plan if several are eligible.
4. Review the preset customer sequence and addresses. If several stock Plans could serve a stop,
   select its **Assign Plan** explicitly. The system does not guess ambiguous stock origins.
5. Add/remove customer stops if needed. Every active Plan in the selected scope must be represented;
   a Customer Order Plan has one exact prepared customer stop. Company, Site, territory and route
   restrictions continue to apply.
6. Drag stops into order, or select a row and use **↑ / ↓**. **Save Draft → Confirm** records planning.
7. Select **Approve Sequence**, review the complete order, then use the primary **Approve** button
   or scanner **Confirm**. Every assigned Plan must be Loaded. The route order is now frozen.

If older manually planned Open Route visits are outside a replacement itinerary, the Supervisor
must explicitly skip those unwanted visits before approving it; they are not deleted silently.
An unstarted approved Sheet can be cancelled with a reason and replaced. The existing reasoned,
policy-enabled Open Route stop-order approval remains available for that individual Open Route
visit; it does not rewrite the approved Sheet or bypass another visit's unfinished proof.

## 5. Driver workflow

1. Scan the lorry and select **Open Customer Route**, or **Lorry Route Sheet**. Read customer names,
   full addresses, instructions, sequence and statuses before visiting the first customer.
2. Select the exact stop. Planned Order normally requires the next pending stop. Flexible Order
   permits another assigned pending stop. A current visit/proof must finish before another starts.
3. If QR is enforced, scan the matching Customer Site QR. Otherwise selecting the assigned stop
   and Confirm is sufficient. Wrong Site scans and changed Customer/address assignments are rejected.
4. Confirm starts/reopens the existing Customer Delivery Session. Known-customer prepared loads
   reuse their allocations. Open Route visits use the existing **Add Route Stock** controls for the
   quantities actually delivered.
5. Continue **Confirm Customer Allocation → Create Delivery Note → Delivery Proof** as configured.
   No stock moves merely because the route was viewed, reordered, saved or approved.

Two/three-day trips remain active across midnight. At the actual trip end, use **Close Route**
when the deliveries and proof are complete. CFG checks only the member Plans and their posted
records, settles them and closes the Sheet together. It does not require an E5 count of unrelated
lorry stock. Remaining or uncertain stock still uses the guided E5 workflow below. Unvisited stops
remain Skipped / Closed Incomplete; no delivery or proof is invented. Continue Same Plan Overnight
keeps the trip active rather than releasing it for a new route.

### Stop/cancel an older Route Sheet

In **Kanban Logistics**, identify a Supervisor, open **Plan / Approve Route Sequence** and scan
the existing Route Sheet number (or scan its lorry and choose that exact Sheet). This also works
when its original Plans have already been settled; today's other loads are excluded.

1. Choose **Stop / Cancel Route**, enter a decision reason and Confirm. A never-started Sheet
   cancels immediately. A started Sheet enters **Cancellation Pending**, blocks new visits and
   retains its original Plan links and all delivery history.
2. The pending panel lists each original Plan, its E5 status and open Delivery Sessions. Choose
   **Open Deliveries**, then the exact numbered Session. Finish its existing Delivery Note/proof
   workflow, or use its controlled allocation release/cancellation if the delivery will not occur.
   A submitted Delivery Note/Invoice is not reversed by Route Sheet cancellation.
3. Reopen the same Sheet. Choose **E5 Plan Reviews**, then a numbered Plan. Complete the existing
   E5/D3 review and any controlled leftover return/transfer for every original Plan. A closing
   **Stock Remains on Lorry** decision can retain physical goods while settling commitments.
   **Continue Same Plan Overnight** keeps commitments active and cannot finalize cancellation.
4. Reopen/Refresh that Sheet. Once all original Plans are **Reconciled / Settled**, with no open
   Delivery Sessions or active visits, enter the final reason and **Finish Route Cancellation →
   Confirm**. It becomes **Cancelled** and releases only its own route links. If the original
   Plans are already settled, step 1 can finalize directly.

The Sheet's request actor/time/reason, request snapshot and final event remain auditable. Completed
visits, Delivery Notes, proof and stock history remain intact. An active office **Delivery Trip**
must use its existing stop-cancellation workflow; settle/close that Trip before historical Sheet
cleanup. Do not edit statuses, unlink stock or delete audit records manually.

## 6. Kanban Floor setup

Create **CFG Kanban Dashboard Profile**:

| Field | Value |
| --- | --- |
| Profile Name | For example `Sales Dispatch / Lorries` |
| Active | Yes |
| View Type | **Logistics and Delivery** |
| Access Mode | **Read Only** is sufficient; this display does not edit routes |
| Company | The selling Company |
| Warehouse | Blank = all readable Company lorries; lorry Warehouse = that lorry; source Warehouse = its dispatch work |
| Workstations | Leave empty |
| Refresh Interval | For example 30 seconds; minimum 10 |
| Queue Depth | Number of visible loads per column; overflow count is shown |

The terminal needs a Stock User/Manager, Sales User/Manager or System Manager role and read access
to the Profile/Company/Warehouses. Open **Kanban Floor**, choose this Profile and use Full Screen.
It shows preparation, ready loads and each lorry's assigned work. Loads fixed to another vehicle
are excluded from a single-lorry display. Loaded quantities on the board are loading history;
scan the lorry for its current ERP balance. Leave the optional Customer filter blank for a general
Open Route loading board.

## 7. Scanner/tablet controls

Print from **Kanban Operator → Scanner Command Labels**. Both Production and Logistics dispatch
`CFG:CMD:VIEW_LORRY_ROUTE` and `CFG:CMD:EDIT_ROUTE_SEQUENCE`.

Within the dialog: `ROUTE_TEMPLATE`, `ROUTE_ADD_STOP`, `ROUTE_ASSIGN_PLAN`, `ROUTE_STOPS`,
`ROUTE_MOVE_UP`, `ROUTE_MOVE_DOWN`, `ROUTE_REMOVE_STOP`, `ROUTE_SAVE_DRAFT`,
`ROUTE_APPROVE_SEQUENCE`, `ROUTE_CANCEL_SHEET`, `ROUTE_CLOSE_SHEET`, `ROUTE_SHEET_REASON`,
`ROUTE_SHEET_REFRESH`, `ROUTE_SHEET_CAMERA`, `ROUTE_VOID_PENDING`, `ROUTE_OPEN_DELIVERIES` and
`ROUTE_REVIEW_PLANS` all use `CFG:CMD:`. `ROUTE_CANCEL_SHEET` chooses Stop/Cancel initially and
Finish Route Cancellation after settlement; scan a reason and Confirm. Recovery choices use the
same numbered 1–10 selection/paging and open the existing Session/E5 panel.
Use standard `CFG:SELECT:1`–`10`, Next/Previous Material Choices, Confirm and Cancel. Tab/Enter
suffixes and camera input are supported. Touch arrows provide the reordering alternative on tablets.

Unknown submissions retain the original operator, action and payload across reopening/refresh.
Confirm retries the original. Refresh reads the outcome; Not Recorded alone does not permit
correction. A reasoned Void If Unrecorded prevents late execution of the abandoned token.
Cancel closes safely and preserves pending details. Submission uses the previously confirmed
HTTPS/Web Locks browser setup; do not clear storage to resolve an uncertain action.

See [the acceptance checklist](TEST_LORRY_ROUTES_AND_FLOOR.md). The existing L1 acceptance gate is
separate and is not closed by these offline development checks.


## 8. Close Route using posted documents

1. Finish every delivery and its required proof; complete or explicitly skip every visit.
2. Open the existing **Lorry Route Sheet** from the lorry or Plan. An authorized Supervisor sees
   **Ready to Close → Close Route**. Enter a closure reason and **Confirm Close Route**.
3. CFG validates submitted Delivery Notes against the exact allocations, customer, Company,
   lorry, Item, Batch, stock UOM, quantity and tag. It also checks required proof and unfinished
   Sessions, ERP commands, prepared allocations, Loose Tags and linked Manifests.
4. If all member Plans pass, they become **Reconciled / Settled** and the Sheet becomes
   **Completed** in the same transaction. Review audit records show **Settlement Basis: Posted
   Documents**, the operator/time, actual delivery outcome and supporting document references.
   No D3 count, new Manifest, Stock Entry, Delivery Note or stock movement is created.

Stock belonging to other Plans can remain on the lorry and is unchanged. A delivered tag reused
for different stock is not treated as this route's leftover stock. If one member fails validation,
none of the route or Plan closures is retained. The message identifies the blocking document or
quantity. **E5 Plan Reviews** and **Open Deliveries** remain available for controlled recovery.
An existing completed E5 settlement is retained rather than recreated.

Permissions stay with the existing route closure: **Start**, Supervisor/Development Proxy with
**Override**, authorized Dispatch responsibilities and native read access for every member Plan,
Company, lorry and supporting ERP document. Ordinary drivers without that authority cannot close.

Scanner: **CFG:CMD:ROUTE_CLOSE_SHEET**, **CFG:CMD:ROUTE_SHEET_REASON**, scan the reason, then
**CFG:CMD:CONFIRM**. Camera and touch use the same action. An unknown result retains its original
request; retry it or use Route Sheet Refresh to read the receipt. Cancel returns scanner focus
without discarding a pending request.

## 9. Close an Open Route Stock Plan already returned to a Warehouse

This is for a standalone Plan with no active Route Sheet. For a linked itinerary use Close Route
or its existing E5 review. Do not make a second transfer merely to satisfy a closure screen.

1. Open the **Open Route Stock** Plan in **Kanban Logistics** and select **Close Plan**.
2. CFG suggests the exact completed return **Movement Manifest** if there is one match. If more
   than one matches, select its numbered choice or enter the exact Manifest in **Existing
   Completed Return Manifest**. Choices page in groups of ten; a camera scan is available.
3. Enter the closure reason and Confirm. The Manifest must be Received. Its submitted Material
   Transfer(s) and stock ledger must prove every exact remaining source, Item, Batch, stock UOM,
   quantity and physical tag, from this Plan's Company/lorry into an active non-lorry Warehouse in
   that Company. Goods-in-Transit requires both submitted legs. Tag custody must have its posted
   quantity/location ledger. Loose quantities need their Dispatch Allocation provenance;
   matching SKU totals alone cannot prove which Plan's loose stock was returned.
4. A return posted before the Review opened is accepted when this evidence is complete and it
   follows the Plan's load. A Stock Entry already used to settle another Plan is rejected.
   A later legitimate use of returned stock does not itself create a new Plan remainder.
5. The review records **Returned to Warehouse** and the actual delivered total / prior outcome.
   Partial or undelivered Plans close as **Closed Incomplete**, not as a fabricated full delivery.
   The completed transfer is referenced; no new stock posting is made.

**Loaded loose, tagged later:** if **Tag Existing ERP Stock** assigned a tag on this lorry after
loading, Close Plan can follow its **Stock Adoption → original Pack / Activate ledger → received
Manifest → submitted transfer / stock and tag location ledgers**. The return must cover the whole
unchanged adopted tag. CFG compares its frozen Item, Batch, stock UOM, Company, lorry and quantities
with this Plan's loose load and the deliveries actually posted before adoption. Several tags from
the same loose pool and mixed original-tag / later-tag returns are supported. The loading allocation
stays untagged in history; the closure audit records each new tag and its original allocation(s).

Use the same Close Plan steps above and select the **existing completed return Manifest** if CFG
does not suggest it. Do not tag again, re-reserve, alter the loading allocation or transfer again.
Native read permission for the Stock Adoption and tag is required alongside the permissions below.
Another Plan's competing loose stock, surplus unassigned loose stock, unrelated loose movements
before adoption, a partial/repacked/consumed tag, or missing posting evidence prevents automatic
closure. CFG names the blocker; keep the existing E5 review/reconciliation path for that audit.
Later use of the stock after its completed return does not invalidate its historical return.

Close Plan uses existing **Logistics Reconciliation**, **Complete**, authorized Plan responsibility,
Supervisor **Override** and native source/document read permissions. Held/Overnight reviews,
per-item recovery decisions, unresolved variances or uncertain ownership must use existing E5.
A mismatch names the Item/tag/document and expected versus recorded quantity.

Scanner: **CFG:CMD:CLOSE_DISPATCH_PLAN**, scan DPL, numbered return choice if needed, or
**CFG:CMD:CLOSE_PLAN_RETURN** then scan KMF; **CFG:CMD:DISPATCH_REVIEW_REASON**, scan reason,
then **CFG:CMD:CONFIRM**. Existing Review Camera / Refresh and Next/Previous Material Choices work.
Retries reuse the request token and cannot create another settlement or transfer.

## 10. Guided E5: count one lorry once for several Plans

Use **Lorry Route Sheet → Guided Closure / Leftovers**, or **Kanban Trip Handover → Next Guided Step**, when leftovers or audit issues require E5.
The page displays the current step, the next Plan/document and, when eligible, the shared count.
Scan a Trip, Route Sheet or standalone Plan. The guide covers that selected group’s Plans; it does not freeze or settle unrelated Plans silently.

1. **Open every Plan Review first.** Select each Plan and Confirm Begin Review. Finish any open
   delivery/proof before reviewing it. No count is needed yet.
2. **Resolve leftovers for all those Plans.** Confirm what stays on the lorry, return stock or
   transfer stock through the existing guided recovery. Finish every Movement Manifest/ERP
   posting before counting. Old customer-return pickups keep their separate receiving/QC custody.
3. **Count the lorry once.** Use Open Lorry Count, scan tags and enter exact loose quantities,
   evaluate and close one balanced **D3 Route Reconciliation**. It covers the entire stock of
   this Company/lorry, including other Plans and unassigned stock.
4. **Settle each Review using that same count.** Refresh Trip Handover. Next Guided Step opens
   the next unsettled Plan's Finish Review with the shared count selected. Check the disposition,
   any existing transfer evidence and the reason, then Confirm. Repeat Next Guided Step until
   all Plans are settled. You are reusing one count, not doing a recount for each Dispatch Plan.
5. **Close Route / office Trip** using its existing controls. Return custody must be handed over
   before office Trip closure where required.

The same count can support other E5 Plans on the **same Company and lorry**, including another
Trip, if their Reviews were also opened before it. Reviews opened after the count need a new
count. Any later stock movement or changed tag/count evidence requires a fresh count. Native E5
revalidates the selected count and Plan disposition on every confirmation; suggestions never
bypass that validation. A count from another Company/lorry or with unresolved variance is invalid.

Scanner: **CFG:CMD:TRIP_HANDOVER**, scan Trip/Plan, then **CFG:CMD:HANDOVER_NEXT_STEP**.
Begin Review and approval still need Confirm. Numbered choices, quantities, reasons, camera and
safe Cancel remain available. All commands are printable in Kanban Operator → Scanner Command Labels.

Implementation and offline checks: [document-closure verification](TEST_DISPATCH_DOCUMENT_CLOSURE.md).
Native ERP/database concurrency, real devices and scanner-only kiosk acceptance remain pending.

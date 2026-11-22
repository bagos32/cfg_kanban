# Driver Route — orders, optional sales, refusals and old returns

Refusal/collection development prepared on 21 November 2026 above `bb22248`. Offline verification is separate from
native-site acceptance; deployment, real posting and device acceptance remain pending.

Open **CFG Dispatch Control → Driver Route**, **Kanban Logistics → Driver Route**, or **Driver
Route** on a saved **CFG Kanban Delivery Trip**. The separate full page is
`/app/kanban-driver-route`; `/app/kanban-driver-route/KTRIP-…` opens an exact trip. Office route
configuration stays on the normal Delivery Trip DocType form.

## Office setup

1. Prepare the trip with [Office Delivery Trip](USER_GUIDE_OFFICE_DELIVERY_TRIP.md). Assign the
   actual driver's Employee, Company, submitted SO quantities and exact customer stops. Save as
   **Planned**. A loaded Draft may receive this status-only office sign-off without changing
   its frozen assignments or itinerary. Active multi-day trips remain available after midnight.
2. Enable Trip-driven dispatch generation with the configured Customer Order/Open Route Profiles,
   or retain manual links to existing **Customer Order / Vehicle Delivery** Plans.
   Complete existing E3 lorry loading for every planned physical quantity. A submitted loading
   Stock Entry is required; an assigned reservation or Draft Stock Entry is insufficient. Every
   Delivery stop needs preparation. Use **Visit Only** for a no-order visit. With a Customer Site it can sell from the generated
   shared pool; without a Site it stays informational.
3. All linked sources must use one actual lorry. Obtain the existing **Route Sheet** approval
   when the captured Dispatch Profile requires it. Trip planning does not publish or approve a
   Route Sheet. Its Plan/Site mapping must match this trip without outside or ambiguous visits.
4. Give the operator **Customer Delivery**, the existing Plan's dispatch responsibility, **Can
   Start** and **Can Complete**. Assigned Driver or an Assistant Drivers row must match that Employee. Supervisor/Development
   Proxy access to other drivers additionally requires **View All Responsibilities**.
5. The terminal user needs Page access and native read permissions for Trip, Company, Customer,
   Address, Customer Site, SO, Item, Warehouses, Dispatch Plans/allocations, loading Manifest/Stock
   Entry, Delivery Session/allocations/Note, Route Sheet and Delivery Proof as applicable. **Stock
   User** with suitable native Company permissions is a usual starting point. **Kanban Terminal
   alone does not grant all these reads.** No new operator Company selector is introduced.
6. Keep the existing **Draft / auto-submit Delivery Note** and proof policy on the Customer Site/
   Dispatch Profile. For photo/signature evidence configure the existing private S3 media service.
   Driver execution needs HTTPS, browser storage and Web Locks. Camera/GPS need device permission.
7. For refusals/collection enable **Customer Returns** in CFG Kanban Settings. Give the driver
   **Customer Return** responsibility as well as delivery permissions. Quality refusals require
   **Enable Customer Return QC** and an **Inspection Custody Location** on the Customer Site.
   Give QC staff **Customer Return QC** responsibility. Inspection Location is temporary custody,
   not another ERP Warehouse receipt. The terminal needs native read access to Return Case and
   Delivery Outcome, including related Items/Batch/Location.
8. On **CFG Kanban Dispatch Profile**, set **Sound Refused Goods** to **Require Supervisor
   Release** (default) or **Allow Resale After Delivery**. This is captured on new Plans; changing
   the Profile does not change an already prepared Plan's captured policy. Damage/quality goods
   always remain held for QC.
9. Deploy through the usual owner-managed migration/build procedure: this extension adds Delivery
   Outcome/Line audit DocTypes, Profile policy, links and owned-stock/collection Return Case fields. Never edit those
   fields manually to repair delivery.

## Driver steps

1. Sign in with the existing operator QR/PIN or reuse the current session. **Scan with Camera**
   supports a tablet; the Scanner field accepts Enter/Tab wedge suffixes. Choose **My Delivery
   Trips** or scan the Trip ID. Use **Change Operator** for a different credential.
2. Review the trip, lorry and next stop. Press **Start Route**, review the departure panel and
   confirm. This records departure and freezes its execution itinerary. **It does not deliver to
   the first customer, create a customer Session or post a Delivery Note at the warehouse.** A
   lorry cannot have two active driver routes.
3. At the customer, select **Complete Stop**. The inline panel shows that stop's prepared products
   and quantities. The stop card retains SO/customer PO, Stock Tags, Batch and untagged source
   details. The **Accepted / Refused** table shows each exact prepared Item/tag/Batch in stock UOM.
   Accepted defaults to the full load. For a refusal reduce Accepted and select its condition and
   reason; **Refused = Loaded − Accepted**. Confirm reviews changes before the second confirmation
   records them. **Return to Edit** allows correction before recording. Keep a routine full
   delivery at its defaults for the existing one-confirmation path. Scan the Customer Site only if its captured
   verification policy requires it; an assigned-stop selection is allowed only by that policy.
4. The panel starts the exact existing prepared Delivery Session, confirms its saved allocations
   and requests the native ERPNext Delivery Note. Routine stages advance after this confirmation.
   They do not ask the driver to allocate or scan every loaded tag again. Only accepted quantities
   reach the native DN, retaining the original prepared sources/SO references. Required native ERP
   inputs pause for entry, including mandatory table rows. After Begin Delivery succeeds, the
   recorded quantity decision cannot be edited or replaced through this panel.
5. With **auto-submit**, native submitted feedback advances to proof. With **Draft**, the panel
   shows **Awaiting authorized ERP submission** and the DN reference. An authorized ERP user must
   review/submit it through the existing workflow. Use **Check saved outcome / Refresh** afterward;
   the driver page does not bypass that approval or create a second draft.
6. When proof is required, choose its permitted disposition, enter recipient/reason/notes and use
   **Camera photo**, **Upload evidence** or the signature pad. Press **Save signature** and wait
   for upload completion. Camera photos retain the image and include server time/reference/GPS.
   Required GPS is captured at submission. **Submit delivery proof** uses the existing native
   proof service. Missing name/signature/photo/location keeps the stop open. No Proof Required
   retains native automatic closure after the submitted DN.
7. For quantities accepted, a stop completes only after **every** linked delivery has a submitted
   non-return DN, a closed native Session, completed Plan feedback and required submitted proof.
   An entirely refused Plan has an audited zero-accepted outcome and Closed native Session with
   no DN, stock consumption or proof; its visit can complete without pretending it was delivered. Several SO Plans retain
   their separate native DNs/proof records; the panel moves through them before completing the
   stop. Existing delivery completed elsewhere can be acknowledged without posting it again.
8. For **Visit Only**, use **Sell from Lorry** if the customer buys (see below). Otherwise
   **Complete Stop** records notes and a no-sale completion without stock, allocation, DN or proof. After the last stop the driver's route becomes **Completed**. Native
   E5 stock/returns/trip reconciliation remains a separate required workflow.

## Optional customer sales from the shared Trip pool

The office creates one shared Open Route Plan for all no-order customer visits. It can request
extra warehouse goods, which require ordinary E3 loading, or use only existing eligible stock
already on the lorry. The latter is **Ready for Fulfilment**, with no new loading transfer. Both
use the same driver sale flow and require one actual Company-specific lorry and configured approval.

1. Start the Trip, then at the saved **Visit Only** customer stop choose **Sell from Lorry**.
   Scan its Customer Site if the captured policy requires it; otherwise assigned-stop selection
   supplies the saved customer/address. Enforced Trip/Route Sheet sequence still applies.
2. Choose **Add Product / Scan Stock**. The existing native stock selector accepts a Stock Tag,
   container, or Item/Batch and quantity for eligible untagged ERP stock. Choose the displayed
   prepared-pool or unassigned-lorry origin when both are available. Confirm each selection.
3. Review the selected stock list. **Finish Selection / Create DN** confirms allocations and
   continues through the existing Delivery Note/proof steps. Mandatory native document inputs,
   Draft submission and photo/signature/GPS policies remain in force. Sale quantities and posted
   tags are also visible on the stop's main page.
4. Complete the native delivery/proof before leaving the stop. Each customer gets its own Session
   and DN; the pool is shared stock, not a single customer's order. A visit with no purchase can
   finish directly with notes. Once allocations exist, use controlled release/recovery before
   abandoning them; Complete Stop cannot discard an unfinished sale.

Customer-order commitments, another Plan's stock, QC holds, old returns, expired stock and native
Company/custody/UOM/certificate checks retain their controls. No customer stock is invented by
opening a sale. Informational rows without a Customer Site offer no sale action.

Scanner `CFG:CMD:ROUTE_ALLOCATE_STOCK` opens the native selector from the selected-stock step.
That selector supports its existing camera, quantity, numbered-origin, Confirm, Cancel and retry
commands. A pending stock submission must be reconciled there before confirming the DN. Closing
or reopening the parent preserves native pending requests. **Start Route** and driver completion
remain separate from D3/E5 count and settlement for both customer Plans and the shared pool.

See [Trip generation/shared-pool acceptance](TEST_TRIP_DISPATCH_GENERATION.md). Native-site results
for this extension remain **Not run**.

## Refused goods from today's load

Refused goods remain company stock on the lorry. A regular nonserialized Stock Tag can have a
partial accepted quantity; the remainder keeps the same tag/Batch/UOM/certificates and a refusal
reservation. Serialized tags must be accepted/refused whole; split them through the controlled
stock workflow first. Whole-number UOM rules still apply. Untagged refusals are held by exact
Company/Warehouse/Item/Batch alongside native ERP availability checks.

- **Good / Unwanted** for an order reduction: the captured Profile policy either holds the stock
  for Supervisor release or releases it for resale after accepted DN/proof completion. Automatic
  release retains a hold if expiry prevents resale. Actual resale still uses normal native
  delivery allocation, pricing, FEFO/certificate and stock checks.
- **Damage/quality/other concerns**: creates one linked existing **Return Case** for QC, marked
  **Stock Already Owned**. QC can receive/start inspection, attach existing return evidence and
  record disposition. It cannot create a customer credit or another Material Receipt.
- QC **Release Own Stock** must approve the complete refused quantity for that exact source.
  An authorized Supervisor (**View All Responsibilities**, **Can Override**, native access)
  selects **Release Refused Stock**, the held rows and a reason. Accepted delivery/proof must be
  complete. Release rechecks current custody and tag/Batch expiry. QC approval alone does not
  unreserve stock. The owned case closes after all its sources are released.
- Held goods can use the existing **E5 Dispatch Review → return/transfer recovery Manifest**.
  The refusal hold follows them to the destination and is restored if an unused recovery is
  cancelled. This movement does not receive the stock a second time or approve resale.
- For QC **Accept for Disposal**, a Stock/Quality/System Manager uses a normal submitted ERPNext
  **Material Issue**, then **Confirm Refused Stock Disposal** on the Return Case. The Issue must
  cover exactly that whole case's held quantities, Company, custody Warehouse, Item/Batch/UOM.
  The confirmation mirrors native disposal into the tag ledger once; it posts no second stock
  document. One Issue cannot be reused for another case. Finalised Issue evidence is protected
  against cancellation; a later reversal needs an audited recovery. Mixed QC results stay held
  for supervised resolution; this action does not silently discard only part of a case.

The stop shows refused quantities, custody/hold state and linked QC cases. **Completed with
refusal** describes the handled visit; the SO's undelivered quantities remain undelivered in ERP.
Reconciliation deducts stock released for resale/disposed from that original Plan's remaining
commitment without counting it as delivered. Remaining held stock stays in E5 review/counts.

## Collect old customer goods

At the saved stop press **Collect Old Customer Return**. This is separate from reducing today's
accepted delivery and is also available for Visit Only stops. The route must have started; it
can have finished driving, but office planning must still be Planned.

1. If a Temporary Return Note already exists, scan/enter its number or QR. Review and confirm the
   complete case. It must be the same Company/customer, awaiting QC receipt, and uncollected.
   The existing case and original creator are preserved; collector/trip/stop/lorry are recorded.
2. Without a note, leave that field empty. Select Inspection Custody Location, enter customer
   reason, physical Items/quantities in stock UOM, known Batch/expiry/tag references and optional
   customer representative/original delivery reference. Company/customer/address come from the
   saved stop. No Customer Site QR is required for this old-return intake; required delivery QR
   verification remains in force for today's delivery.
3. **Review Collected Return**, check the canonical Item/UOM quantities, then confirm to issue
   one Temporary Return Note. Return to Edit permits changes before issuance. The original
   source reference is reported information; it does not select an accounting invoice.
4. Warehouse/QC staff open/scan the case in **Kanban Logistics** and confirm physical receipt by
   starting QC. Follow the existing QC, accounting-source decision, optional credit document and
   stock-disposition workflow. Collected old goods are not saleable lorry stock and collection
   itself posts no ERP receipt or credit.

The driver's stop displays collected case numbers and QC/inspection/disposition progress, with
**Temporary Return Note** print and **Open Return Case** links. QC's existing open-case queue also
includes owned refusals awaiting stock disposition. No separate QC engine is introduced.

**Open existing delivery** remains available for the established Logistics workflow. These new
quantity decisions apply before a prepared Session starts. For an already-started Session, use
its established allocations and supervised reconciliation. Cancellation of an accepted DN with
a linked refusal outcome is blocked to preserve stock custody; use controlled return/follow-on
recovery. This extension does not invent an automatic reversal of that immutable outcome.

## Sequence and quantities

The office order is shown unless one approved active Route Sheet maps completely and exactly to
all delivery stops. Adjacent Plans for one office stop can form one displayed stop. Visit-only
rows absent from an operational Sheet keep their office positions; conflicting enforced delivery
order must be reconciled before departure. **Planned Order** on either the Trip or a mapped Sheet
enforces the next stop. Flexible routes permit selecting another eligible stop, but an unfinished
customer DN/proof must be completed first. Looking at a stop alone performs no action.

**Planned** means office assignment. **Loaded** requires submitted loading feedback. **Delivered**
requires submitted non-return DN feedback. **Not prepared** is the assignment without prepared
sources. **Remaining to deliver** is loaded assignment less posted delivery and recorded refusal, in
stock UOM. Refused goods remain separately visible with their hold/custody status; this figure
is not free lorry stock. A pending DN/proof stays current. If native delivery finished outside the
page, **Awaiting stop completion** retains the driver acknowledgement rather than skipping it.
A driver Visit Only completion shows **Visit completed**. Closed planning does not prove delivery.

Starting freezes the itinerary, driver, lorry, source identities and approved route revision for
this execution. Resolve a changed source/operational route through existing supervised controls;
live order changes use the controlled workflow below. Stop removal/cancellation remains a later phase. For an incomplete/abandoned route, first settle
or cancel linked Plans using the existing E5/recovery workflow. An authorized office manager may
then close/cancel the saved Trip with a reason. It records **Closed Incomplete**, releases the
active lorry and preserves unfinished stops; it does not mark them delivered. Completed driver
routes also retain the normal office/E5 closure rules.

## Scanner, retries and refresh

The action panel accepts `CFG:CMD:CONFIRM`, `CFG:CMD:CANCEL`, `CFG:CMD:REFRESH` and `CFG:CMD:HELP`.
Numbered `CFG:SELECT:1`–`10` chooses displayed inputs; scan their values. Existing
`DELIVERY_RECIPIENT`, `DELIVERY_INPUTS`, `DELIVERY_ADD_ROW`, `DELIVERY_NEXT_ROW`,
`DELIVERY_PREVIOUS_ROW`, `NEXT_MATERIALS`/`PREVIOUS_MATERIALS` and `DELIVERY_CAMERA` commands
remain usable with the `CFG:CMD:` prefix. For the quantity table, select its field and `DELIVERY_NEXT_ROW`, then numbered editable
columns. `CFG:QTY:MATERIAL:3` sets Accepted for that row. Prepared/release source rows cannot be
added/deleted. Old-return rows support `RETURN_ITEMS`, `RETURN_ADD_ITEM`, `RETURN_NEXT_ITEM`,
`RETURN_PREVIOUS_ITEM`, `RETURN_REASON`, `RETURN_INPUTS`, `RETURN_CAMERA` and `RETURN_EDIT`
with the `CFG:CMD:` prefix. Camera and touch entry use the same controls. Success,
error, cancel and camera closure restore scanner focus. A required photo/signature uses its tablet
evidence controls rather than pretending a command scan is a physical signature or photograph.

An uncertain submission retains its **original actor, payload and token** across Close, reload
and tabs. Reopen **Continue / Check saved action** even if native completion has already advanced
the trip. **Retry original request** uses those exact details; **Check saved outcome** reads its
server receipt. **Not Recorded alone does not allow correction**: the first request may still be
running. Only an explicit first rejection permits correction. An unknown result followed by a
retry rejection remains locked. An authorized Supervisor with View All, Can Override and a reason
may **Void if unrecorded**; the server lock fences a late original request. Do not clear browser
storage to bypass an unknown result. Another operator cannot edit/retry the original request.

Pending action input (including entered proof recipient/GPS when applicable) is temporarily kept
in local browser storage for recovery. Credentials, file bytes and presigned URLs are excluded
from that action record. Acknowledgement replaces it with an identity-only marker. Evidence
remains in the existing private media workflow. Closing/hiding/changing operator prevents late
responses from changing another operator's screen.

The view refreshes every 15 seconds outside an action panel. During an action, use its explicit
Refresh to preserve entered fields. Background reads do not renew inactivity expiry. Expiry or
native permission/ownership rejection clears protected details; network failure marks **Not
refreshed**. Returning to the page rereads authorized sources.

Live vehicle tracking and Bluetooth printing remain later phases. Use [execution acceptance](TEST_DRIVER_ROUTE_EXECUTION.md)
after manual deployment; [the original view checklist](TEST_DRIVER_ROUTE_VIEW.md) remains historical.

Use [refusal/old-return acceptance](TEST_DRIVER_ROUTE_REFUSALS_RETURNS.md) for this extension;
its native posting, concurrency and device results remain **Not run**.

## Share the route with assistant drivers

The office can preset several **Assistant Drivers** on the normal Delivery Trip form. The lead
Assigned Driver can also open **Add Assistant Driver** on the driver route page before departure
or during an In Progress route. Select the active Employee, or scan their **Employee ID**, and
confirm. The assistant signs in separately with their own operator credential and chooses the
same Trip in **My Delivery Trips**.

Either member can start the route and continue the same active stop's DN/proof, optional sale or
old-return collection while the lead concentrates on the vehicle. Existing permissions still
apply: Customer Delivery, the Plan Dispatch responsibility, required start/complete flags and
native Company/source access; Customer Return is additionally required for collections. The team
list does not grant Supervisor release, QC authority or ERP submission permissions.

The lead and assistant list appear above the itinerary. Each action is recorded against the
person who performs it; continuing a Session does not replace its original creator. The route's
current stop, sequence, stock commitments and proof gates stay shared. A stale second confirmation
must refresh; it cannot create a parallel route outcome.

Only the lead adds assistants from this page. Office presets are editable before departure;
started/completed Trips retain their assignment history. If an earlier action is uncertain,
reidentify its original operator or use authorized Supervisor reconciliation. Another teammate
cannot replace its token or payload. Add Assistant uses the existing scanner, camera,
Confirm/Cancel and durable retry controls. Verify [the assistant checklist](TEST_TRIP_TEAM.md)
after migration/build; offline tests do not establish device or native ERP behavior.

## Change a live delivery order

After **Start Route**, between customer stops, the driver or an assigned assistant can open
**Change Stop Order**. Move unfinished customers by drag and drop, or the tablet **Up / Down**
buttons, then save. The office itinerary, Sales Orders, tags, loaded quantities and LIFO loading
record stay as released. Completed stops cannot move or disappear. Finish an active customer
Delivery Note and all required proof before changing order.

**Flexible Order** permits saving the new remaining order directly. **Planned Order** on the Trip,
an approved native Route Sheet or a participating Open Route Plan requires a Supervisor request.
The button becomes **Request Stop Order Change**: put the requested next customer first, arrange
all other remaining customers, enter a reason and confirm. The currently approved order remains
authoritative while the request is Pending. A requester or the lead may **Cancel Route Request**
with a reason; closing the panel only leaves the request intact.

The office opens **Kanban Supervisor Action Centre → Delivery Route Changes → Review Request**.
Sign in with a Supervisor operator credential if needed. The profile needs **View All
Responsibilities**, **Can Override**, **Can Complete**, native Company/Trip/request access, and
the existing delivery/Dispatch access used by that Trip. A Desk manager role alone does not
supply the operator's approval authority. Review the current and proposed remaining customers,
choose **Approve** or **Reject**, enter a decision reason, and on approval choose:

- **Next Customer Only**: visit the requested first customer next, then resume the prior relative
  order of all other unfinished customers.
- **Entire Proposed Order**: use the complete proposed order for the unfinished customers.

For a delivery or optional-sale customer, the captured Dispatch Profile must permit **Allow
Controlled Supervisor Override**. One-next approval requires that permission for the requested customer's
Plans; entire-order approval requires it for all affected customer Plans. Informational visits
with no delivery Plan still require the Supervisor's Trip decision when the Trip is enforced.
The original operational Route Sheet stays approved at its existing revision; the audited Trip
runtime order supplies only this exact sequence exception. Required Customer Site QR, stock,
Company, Delivery Note submission, proof and QC restrictions continue to apply. No stock or ERP
document is created by a route edit or its approval.

The driver sees Pending/Approved/Rejected/Cancelled status, approval scope and the Supervisor
reason after refresh. The page refreshes between actions; use **Refresh** to check sooner. If the
Trip has progressed since the proposal, the Supervisor must reject it or the driver must submit
an updated request (the older Pending request is retained as Superseded). Approval also checks
current sources and active deliveries. Closed or stale requests can still be rejected from the
Supervisor Centre. Historical request forms offer **Review in Supervisor Centre** for outcome
lookup/recovery. The latest link and the normal **CFG Kanban Route Change Request** list retain
request and decision history.

Route-order panels share the existing durable original actor/token/payload retry controls. An
uncertain request/decision must be read back or retried intact; do not send a replacement because
the response was lost. Reopen the request's review or the Trip's saved-action panel to recover it.
Supervisor queue refresh pauses while identity/review is open, preserving entered choices.

Scanner: in the order editor, `CFG:SELECT:1`–`10` selects a displayed customer, then
`CFG:CMD:ROUTE_MOVE_UP` / `CFG:CMD:ROUTE_MOVE_DOWN` moves it. `NEXT_MATERIALS` /
`PREVIOUS_MATERIALS` pages the numbered list. `CFG:CMD:ROUTE_REASON` arms the reason. Confirm
saves/requests; Cancel safely closes. Supervisor review uses numbered input selection and scanned
values for Decision, Approval Scope and Reason. Its camera button and Enter/Tab credential entry
use the same identity check. The existing action camera, Confirm/Cancel/Refresh and focus
restoration remain available. These are delivery actions; no Production floor command is added.

Manual migration and asset build are required. Use [route-order acceptance](TEST_DRIVER_ROUTE_SEQUENCE.md).
Offline tests cover behavior with dependency doubles; native transactions, multi-user timing,
permissions and tablet/driver acceptance remain **Not run**.


## Customer pins and directions

On the normal **CFG Kanban Customer Scan Point** form, open **Delivery Location Pin**. Office
users with existing Site create/write permissions can enter **Latitude** and **Longitude**, press
**Set Pin**, check the marker, then **Save**. The numbers use latitude first in these inputs;
for example `3.139` and `101.6869`. Set Pin replaces the old marker. Alternatively use the native
map's marker tool, retaining exactly one marker. Remove extra markers and drawn shapes before
saving. **View Pin in Google Maps** checks the saved/entered point. **Clear Pin**, then Save,
removes it. Choose the unloading entrance, rather than an approximate town/customer head office.

The pin belongs to that exact Site, Company, Customer and Address. Route Templates/Trips reuse
their selected Sites; no separate pin entry is needed on every trip. A Visit Only stop may use a
Site for its pin even without an SO. A visit without a Site uses its saved address for search.
Legacy Sites may leave the pin empty. No automatic geocoding or location guess is performed.

**Driver Route** shows numbered pins in the effective current Trip sequence, with Next/Current,
Completed, Pending and Check status. Select a pin to see customer, address, product quantities,
SO/customer PO and **View Stop**. Several visits at the same coordinate share a pin with separate
numbered choices; selecting one views its details, never silently chooses which visit to deliver.
Missing pins are counted in the `X / Y stops have a delivery pin` message.

Under the next/current customer, tap **Google Maps** or **Waze**. These use that exact saved
coordinate and let the mapping app determine the origin/device location. Looking at another
customer's pin/details does not change the next-navigation target. A flexible reorder or approved
route change updates the pin numbers and target after refresh. When the current stop still has
an unfinished DN/proof, it remains the current target. Completed/closed trips offer no next-stop
navigation. Navigation may be previewed before departure; it does not record **Start Route**.

Without a valid pin, **Google Maps — Address** requests directions by the saved delivery address;
**Waze — Search Address** opens an address search. Check its result before navigating. An absent
address or an address too long for the supported map URL offers no guessed destination: office
must set/correct the Site pin or address. Invalid imported pin data does not block route viewing
or delivery; it is excluded from the map and explicitly uses address search until corrected.

Pin corrections saved by the office appear on the next authorized route refresh, including an
active multi-day Trip. They do not alter its frozen customer/address assignment, original
itinerary, LIFO/loading record, stock, approval, DN, proof or return history. Changing actual
Company/Customer/Address remains governed by the existing identity checks.

The map uses Frappe's existing Leaflet assets and configured tile provider; it keeps the viewport
on ordinary refresh and groups repeated coordinates. If map assets/tiles are unavailable, use
the directions buttons and existing delivery controls; **Retry Map** retries an asset failure.
No pins means no map-library/tile load. Directions are disabled during refresh or a stale route
read. Page hide/operator change clears map data; late loads cannot draw the previous driver's
Trip. Returning from the external maps app triggers a passive route refresh without renewing the
operator's inactivity timeout or recording delivery.

Google/Waze links open only on the driver's tap and contain a destination coordinate or address;
no operator credential, Trip ID, SO or customer PO is put in those links. Opening a map or tapping
View Stop does not start/complete a visit, approve a sequence exception or satisfy a QR/proof gate.
This phase does not track/transmit the driver's GPS; proof-of-delivery GPS still uses its existing
policy and capture flow. Native app/browser handoff, device permissions and road routing depend
on the device/provider and require device acceptance. The pin map shows customer locations;
road directions are supplied by the external map app.

No Google Maps API key is used by these universal direction links. The implementation follows
[Google Maps URLs](https://developers.google.com/maps/documentation/urls/guide) and
[Waze Deep Links](https://developers.google.com/waze/deeplinks). Native Frappe v15 map assets and
existing map defaults supply the in-page map. Real-time vehicle GPS, supervisor tracking maps,
route optimization and thermal printing remain separate later work.

Migrate/build manually, configure test pins, then run
[pin and directions acceptance](TEST_DRIVER_ROUTE_MAPS.md). Native-site/device results are
**Not run**; offline parser/controller tests do not establish those results.

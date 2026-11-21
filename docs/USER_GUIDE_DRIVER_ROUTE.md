# Driver Route — delivery, refusals and old returns

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
2. Link the existing **Customer Order / Vehicle Delivery** Dispatch Plans to the exact stops.
   Complete existing E3 lorry loading for every planned physical quantity. A submitted loading
   Stock Entry is required; an assigned reservation or Draft Stock Entry is insufficient. Every
   Delivery stop needs preparation. Use **Visit Only** for an information-only visit.
3. All linked sources must use one actual lorry. Obtain the existing **Route Sheet** approval
   when the captured Dispatch Profile requires it. Trip planning does not publish or approve a
   Route Sheet. Its Plan/Site mapping must match this trip without outside or ambiguous visits.
4. Give the operator **Customer Delivery**, the existing Plan's dispatch responsibility, **Can
   Start** and **Can Complete**. Assigned Driver must match that Employee. Supervisor/Development
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
8. For **Visit Only**, Complete Stop records visit notes and an audited completion without stock,
   allocation, DN or proof. After the last stop the driver's route becomes **Completed**. Native
   E5 stock/returns/trip reconciliation remains a separate required workflow.

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
this phase adds no live resequencing/skip approval. For an incomplete/abandoned route, first settle
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

Map directions/live tracking, driver route-edit approval and Bluetooth printing remain later phases. Use [execution acceptance](TEST_DRIVER_ROUTE_EXECUTION.md)
after manual deployment; [the original view checklist](TEST_DRIVER_ROUTE_VIEW.md) remains historical.

Use [refusal/old-return acceptance](TEST_DRIVER_ROUTE_REFUSALS_RETURNS.md) for this extension;
its native posting, concurrency and device results remain **Not run**.

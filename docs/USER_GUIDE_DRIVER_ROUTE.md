# Driver Route — Start Route and Complete Stop

Development prepared on 21 November 2026 above `754708d`. Offline verification is separate from
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
7. Deploy through the usual owner-managed migration/build procedure: this phase adds read-only
   Trip departure/revision/snapshot fields and stop completion audit fields. Never edit those
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
   details. Confirm the full prepared delivery. Scan the Customer Site only if its captured
   verification policy requires it; an assigned-stop selection is allowed only by that policy.
4. The panel starts the exact existing prepared Delivery Session, confirms its saved allocations
   and requests the native ERPNext Delivery Note. Routine stages advance after this confirmation.
   They do not ask the driver to allocate or scan every loaded tag again. Required native ERP
   inputs pause for entry, including mandatory table rows. Quantities and sources cannot be
   changed in this panel.
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
7. A stop completes only after **every** linked delivery has a submitted non-return DN, a closed
   native Session, completed Plan feedback and required submitted proof. Several SO Plans retain
   their separate native DNs/proof records; the panel moves through them before completing the
   stop. Existing delivery completed elsewhere can be acknowledged without posting it again.
8. For **Visit Only**, Complete Stop records visit notes and an audited completion without stock,
   allocation, DN or proof. After the last stop the driver's route becomes **Completed**. Native
   E5 stock/returns/trip reconciliation remains a separate required workflow.

**Open existing delivery** remains available for the established Logistics workflow. The driver
page in this phase handles full prepared known-customer deliveries. Partial acceptance, refusal,
old returns, cancellation and recovery use existing controlled Logistics/Supervisor workflows;
it does not infer that refused goods were delivered.

## Sequence and quantities

The office order is shown unless one approved active Route Sheet maps completely and exactly to
all delivery stops. Adjacent Plans for one office stop can form one displayed stop. Visit-only
rows absent from an operational Sheet keep their office positions; conflicting enforced delivery
order must be reconciled before departure. **Planned Order** on either the Trip or a mapped Sheet
enforces the next stop. Flexible routes permit selecting another eligible stop, but an unfinished
customer DN/proof must be completed first. Looking at a stop alone performs no action.

**Planned** means office assignment. **Loaded** requires submitted loading feedback. **Delivered**
requires submitted non-return DN feedback. **Not prepared** is the assignment without prepared
sources. **Remaining from load** is loaded assignment less posted delivery, in stock UOM; it is
not free lorry stock. A pending DN/proof stays current. If native delivery finished outside the
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
remain usable with the `CFG:CMD:` prefix. Camera and touch entry use the same controls. Success,
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

Map directions/live tracking, driver route-edit approval, integrated refusal/return collection/QC
queues and Bluetooth printing remain later phases. Use [execution acceptance](TEST_DRIVER_ROUTE_EXECUTION.md)
after manual deployment; [the original view checklist](TEST_DRIVER_ROUTE_VIEW.md) remains historical.

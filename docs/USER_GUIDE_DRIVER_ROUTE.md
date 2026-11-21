# Driver Route — trip and stop view

Development prepared: 21 November 2026, above `91ab7da`. Native-site acceptance is pending.

Open **CFG Dispatch Control → Driver Route**, **Kanban Logistics → Driver Route**, or the
**Driver Route** button on a saved **CFG Kanban Delivery Trip**. The separate full page is
`/app/kanban-driver-route`; a specific trip can open at `/app/kanban-driver-route/KTRIP-…`.
The trip list and stop details are on the page, without a route-planning popup.

## Office setup

1. Prepare the trip using [Office Delivery Trip](USER_GUIDE_OFFICE_DELIVERY_TRIP.md).
2. Set **Assigned Driver** to the actual driver's Employee and save. An empty driver does not
   expose the trip to every operator. This page does not assign the driver or lorry automatically.
3. Assign the submitted SO lines to exact delivery stops. Link the existing Vehicle Delivery
   Customer Order Dispatch Plans to those stops and save. These links supply actual stock tags,
   untagged allocations and delivery feedback. Unlinked orders remain visible as planned quantities.
4. Perform existing E3 loading and, when required, existing Route Sheet approval. Trip planning
   itself still creates no stock movement or delivery authority.
5. For the terminal login, grant Page access and native read access to the Trip and its relevant
   Company, Customer, Address, Customer Site, SO, Item, Warehouses, Dispatch Plans, allocations,
   loading Manifest/Stock Entry, Delivery Session/Note and Route Sheet. **Stock User** plus suitable
   native Company permissions is a usual starting point. **Kanban Terminal alone does not grant all
   these document reads.** Restrict Companies through native User Permissions.
6. Give the operator an active profile with **Customer Delivery** responsibility. The operator's
   Employee must match the trip driver. Existing delivery execution permissions remain separate.

A Supervisor/Development Proxy sees other drivers' trips only with **View All Responsibilities**
and the necessary native read permissions. Native manager roles alone do not bypass the operator
session or assigned-driver check. No new Operator Company selection is introduced.

## Driver use

1. Open Driver Route. An existing operator session is reused. Otherwise scan the operator QR,
   or enter the credential/PIN and press **Open / Sign in**. **Scan with Camera** supports tablets;
   a keyboard-wedge scanner may terminate with Enter or Tab.
2. Select a trip from **My Delivery Trips**. Its date and optional return date remain visible for
   a two/three-day trip; active trips do not disappear at midnight. Paging and **Show closed trips**
   are available. A Trip ID scanned before login is held for after login, not sent as a credential.
3. Read **Current stop**, **Next delivery stop** or **Next planned stop**, and the source of that
   sequence. Tap any stop to inspect it; looking at a later stop does not start, approve or deliver it.
4. The stop shows Customer/Site, captured address, instructions, SO/customer PO references,
   product quantities, physical tag codes, Batch and untagged stock. Each quantity retains stock UOM.
5. Where an existing active Delivery Session belongs to this operator (or an authorized viewing
   Supervisor), **Open existing delivery** opens that exact session in the established Logistics
   workflow. Its allocation, Delivery Note, proof and permission checks continue there. The button
   does not start another Session or post a document.

Use **Change Operator** before scanning another raw credential. A normal trip view needs no
Customer QR scan. Actual delivery still follows the existing configured Customer Site verification
policy. This phase does not add Start Route, Complete Stop, visit-only check-in, cancellation,
refusal, collection or resequencing actions to the driver page.

## Quantity and progress meaning

- **Planned** is the office trip assignment; it is not evidence of a load.
- **Loaded** is the assigned allocation supported by a submitted loading Stock Entry. A Draft,
  cancelled or missing posting does not count as loaded.
- **Delivered** uses Delivered allocations backed by a submitted, non-return Delivery Note.
  Draft/cancelled/return notes do not count as delivered by this trip.
- **Not prepared** is the office quantity still without an active prepared allocation.
- **Remaining from load** is loaded assignment minus its posted delivery; it is not free lorry
  stock and does not include an unprepared order balance. Use the existing lorry overview for
  current ERP/tag inventory and reconciliation.
- A partially loaded stop is labelled **Partially loaded**. A posted delivery awaiting proof stays
  **Awaiting proof** and remains the current stop. Full delivery advances only after the existing
  Session closes with completed feedback. A closed short delivery is **Closed Incomplete**.
- Visit Only stops show their instructions and **Visit planned**. This read view never invents a
  completion event or silently advances past an unrecorded visit.
- Closed/Cancelled planning records retain source details but propose no next stop. Closing
  planning is not proof that every delivery was completed.

## Which sequence is shown

One approved active Route Sheet takes precedence when all its Plan/Site rows map exactly and
unambiguously to all trip delivery stops. Adjacent Plans for the same office stop may form one
stop. The view retains each original office number separately; it does not rewrite either record.

With missing approval, multiple/conflicting Sheets, unlinked operational stops, repeated ambiguous
visits or Visit Only rows absent from the operational Sheet, the view labels its sequence
**Office plan** and explains that the operational route needs review. It does not guess another
Customer or expose unrelated operational stops. Existing enforced-order and QR checks remain the
execution authority. The office itinerary is not automatically published or approved as a Sheet.

An active delivery/proof task takes precedence over a proposed next stop. Multiple active customer
Sessions or conflicting lorries produce a review warning and no guessed next stop.

## Refresh and access changes

The visible page refreshes every 15 seconds and shows the last successful timestamp. Network
failure marks the view **Not refreshed**. Expiry or permission/ownership rejection clears the
protected details; it is not treated as a new login for an unrelated scanned tag. Operator changes
and late responses cannot replace the new operator/trip view.

Automatic background reads do not renew inactivity expiry. Explicit navigation/Refresh counts as
manual use. Hiding the page stops its timer/camera; returning rereads authorized data. The browser
stores only the existing operator token and last trip ID per Employee, not customer/stock snapshots.

Maps/GPS, new route publication/approval actions, simplified delivery/returns, QC monitoring and
Bluetooth printing remain later phases. Run [the native acceptance checklist](TEST_DRIVER_ROUTE_VIEW.md)
after manual deployment. Local offline tests do not verify live behavior.

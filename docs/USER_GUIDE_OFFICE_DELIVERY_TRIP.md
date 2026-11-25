# Office Delivery Trip — setup, dispatch generation and loading

Development prepared: 21 November 2026. Native-site acceptance is pending.

This phase provides a normal Desk DocType form for office route and trip planning. Open
**CFG Dispatch Control → Office Delivery Trips** or search for **CFG Kanban Delivery Trip**.
**Standard Routes / Templates** opens the existing **CFG Kanban Route Template** master.
These forms use ordinary tabs and child tables, not a planning popup.

A standard route is a reusable customer itinerary for a Company, region or direction. A Delivery
Trip is one dated use of that route, optionally lasting several days and assigned to a driver and
lorry. Several trips can use the same standard route.

## 1. Permissions and source masters

- Office editors need Stock Manager, Sales Manager or System Manager. The Kanban maintenance
  role can edit trips when it also has the necessary native source-document access.
- Stock User and Sales User can read trips. Being a Kanban Supervisor alone does not grant Desk
  manager permissions.
- Native read access is checked for Company, route, Customer, Address, Customer Site, Sales Order,
  Item, Warehouse, linked Dispatch Plan and allocations. Grant only the relevant Companies.
- A delivery stop uses an existing active **CFG Kanban Customer Scan Point** belonging to the
  selling Company. This is the Customer Site/address master; configuring it does not require the
  driver to scan its QR when the existing verification policy permits assigned-stop selection.
- A lorry Warehouse must be an active leaf Warehouse of the Company, marked as a vehicle
  Warehouse with its vehicle reference. Driver is an active Employee accessible to the planner.

## 2. Set up the standard route

1. Open **Standard Routes / Templates → New**.
2. Enter Template Name, Selling Company, Active, Region and Direction / Corridor.
3. Select the default Customer Stop Sequence: **Flexible Order** or **Planned Order**.
4. Add stops in normal delivery order. For **Delivery**, select a Customer Site; its Customer and
   address fill from the Site. For **Visit Only**, select a Customer and optionally its address or
   an existing Site. Enter visit/delivery instructions.
5. For Trip-driven preparation enable **Generate Dispatch on Mark Planned**. Select the active
   **Customer Order Dispatch Profile** and **Shared Open Route Dispatch Profile** needed by the
   route. Both must use **Vehicle Delivery**, the same Company and loading source Warehouse.
   Their Dispatch Operations Cards must be active, unblocked and in that Company/source. The Open
   Route Profile must cover the visits' Logistics Route or Territory. Keep the existing approval,
   stock rotation, QR, proof and route-sheet policies on those Profiles.
6. Drag the table rows into sequence and save.

Visit Only records an office visit without a Sales Order. With automatic generation and a
Customer Site, it can optionally sell from the Trip shared pool. Without a Site it remains an
informational visit. Merely planning a visit creates no stock allocation or delivery. Customers may occur more than once at distinct stops. A Customer Address
must actually belong to that Customer. Disabled Customers/Addresses and wrong-Company Sites fail
validation.

Business changes increment the template revision. Saved trips retain their captured template
snapshot and their own customized stop order. Editing a template does not rewrite existing trips.
A route's Company cannot change after Sales Orders or trips reference it.

The existing dispatch/Route Sheet template selector continues using Delivery stops. Visit Only
rows are omitted there. Trip-generated requests supply their exact office visits to the existing
Route Sheet service, including all-visit routes; do not replace those visits with the legacy selector.

## 3. Sales selects the route; office chooses the dated trip

On a normal **Sales Order**, choose **Standard Delivery Route** next to Delivery Date. The choices
are active templates for the SO Company containing that Customer. Save the order. The existing
**Customer PO No** (`po_no`) is the customer PO reference shown in the route inbox.

**Open Route Inbox** opens the template's normal form. Its inline inbox shows saved open Sales
Orders and their Items, customer PO, delivery date, ordered/delivered quantities, outstanding trip
assignments and unassigned balances. Quantities use stock UOM, including the SO conversion factor.
Saved Draft orders are visible for information. Assignment requires a submitted, open order.

Selecting a route never silently selects a dated trip. The office makes that assignment below.
Route, Company, Customer or shipping-address changes are blocked while that SO has active trip
assignments; release the planning first. Ordinary native delivered-quantity/accounting feedback
continues when those identity fields have not changed, even if the old template was deactivated.

## 4. Prepare a dated Delivery Trip

1. From the template inbox choose **New Delivery Trip**, or open **Office Delivery Trips → New**.
2. Set Company, Standard Route / Template, Trip Date and optional Expected Return Date. Multi-day
   trips are permitted. Set driver, source Warehouse and lorry if known; these can be left empty
   during early planning. In **Assistant Drivers**, add one or more active Employees with an
   active Customer Delivery Operator Profile. A lead Assigned Driver is required when assistants
   are selected; the same Employee cannot appear twice or be both lead and assistant.
3. Click **Load Route Template**. The form captures its revision, stops, region/direction and
   default policy and dispatch-generation defaults. Loading a template replaces the stop table; first save without assigned orders
   and linked Plans if replacing the route on an existing trip.
4. In **Customer Stops**, customize instructions, add/remove visits and drag rows into delivery
   order. Customer stops keep stable identities, so moving a row does not change an order's customer.
5. In **SO Route Inbox**, choose the exact matching delivery stop and enter stock quantity, then
   **Assign / Update**. Ambiguous repeated Customer/Site stops require an explicit choice.
6. Review **Order Assignments** and save. Quantities can be edited there; remove an unused row to
   release its planning quantity before dispatch execution. Use the inbox to change its stop.
7. Use **Planning Status → Mark Planned** when the office plan is ready.

A saved Draft already holds its assigned planning quantity. Draft and Planned trips are both
included in duplicate-planning checks. Different trips may split the remaining quantity of the
same SO row; their outstanding assignments cannot exceed its undelivered stock quantity. The same
SO Item row appears once within one trip; use the inbox to update it. These are planning holds,
not ERP stock reservations. Saving the trip creates no Stock Entry, Delivery Note or Invoice.

Inbox **Planned Elsewhere / Here** shows outstanding assignments. Submitted Delivery Notes from
linked Dispatch Plans reduce those planning holds using their exact SO Item references; duplicate
source joins are not counted twice. Native SO delivery balances remain authoritative.

## 5. Generate linked dispatch work and read LIFO

Enable **Generate Dispatch on Mark Planned** on the Trip or inherit it from the Route Template.
Under **Linked Dispatch Plans**, select the two Profiles as applicable and enter any **Extra Goods
for Shared Open Route** in stock UOM (optional Batch). Save the Trip as Draft, then **Mark Planned**.
The office no longer needs to prepare separate Plans before assigning the Trip:

- Each exact **Sales Order + customer stop** creates one linked Customer Order Plan, limited to
  this Trip's assigned SO rows and quantities. Repeated Items on different SO rows remain distinct.
- All **Visit Only** stops with a Customer Site share **one Open Route Plan**. Extra goods become
  its warehouse preparation lines. Warehouse staff reserve, select the actual lorry and load them
  through existing E3 controls, alongside the customer orders.
- If there are no extra goods, the shared request uses **existing lorry stock only**. Approval is
  still required when configured. Assign the actual lorry on the Trip, or inherit it at departure
  from the loaded customer Plans. It becomes **Ready for Fulfilment** without a Manifest or invented
  loading Stock Entry. Eligible unassigned lorry stock is checked when a customer buys.
- Generation submits the requests for existing Profile approval, or makes them Approved when that
  policy permits. It reserves/posts no stock and approves no Route Sheet.

Repeated saved planning reuses the same requests/visits. **Generate / Refresh Dispatch** also works
on a saved, clean Draft or Planned Trip, before execution. Unused changes replace requests while
retaining cancelled history. Reservations/loading/route approval freeze the sources; use existing
controlled release/cancellation/reconciliation after execution begins. Keep loaded stock unchanged.

If dispatch was generated while the Trip was still Draft, reload the Trip and use **Planning
Status → Mark Planned**. Saving the unchanged generated links and generation time is supported;
the existing requests are reused. Do not clear or edit these read-only fields to change status.
Mark Planned does not replace or reopen warehouse work that has already started.

**Manual mode remains available:** leave automatic generation off and link existing compatible
Customer Order Plans. Do not enable generation over manual Plan links; keep manual mode or remove
unused links first. Existing trips are not silently converted.

A linked Plan must match Company, Customer Site, SO, assigned Item/UOM quantities and any specified
source/lorry Warehouse. All linked Plans with assigned vehicles must use one lorry. A Plan cannot
belong to another trip while its historical link remains. Settled/cancelled Plans cannot be newly
assigned. Release reservations through the existing dispatch workflow before unlinking a Plan.

In **LIFO Loading Sequence**, the last delivery stop is listed first. For stops **A → B → C**, load
**C, then B, then A**. Informational visits and non-stock SO Items do not create physical load rows. Shared extra goods
appear after the customer load rows, marked **Shared Open Route Stock**; keep them accessible
across visits. They are not assigned to one customer or treated as a second load at each stop.

- Real tagged allocations show their Stock Tag and Batch.
- Untagged ERP allocations show their stock kind and quantity.
- The remaining planned balance is **Not Prepared** until prepared through Dispatch Plans.
- **ERP-Loaded Qty (Historical)** is a posted loading quantity, not current lorry availability.
- **Refresh Loading Details** reads current linked sources without saving or moving stock. Save
  the trip to refresh its saved loading table. Use normal Desk Print to share the office form.

Warehouse staff use this loading order with the existing E3 physical confirmation and Manifest
workflow. This phase supplies loading instructions; it does not enforce the physical loading scan
order. FEFO/FIFO, expiry, certificates, reservations and posting keep their existing controls.

Once a linked Plan has entered vehicle/loading/delivery execution, its office planning snapshot
cannot be rewritten. Its source stage and allocation details can still refresh. Assign the trip's
editable header lorry before execution if needed; linked Plan rows show subsequent actual lorry
selection from the operational workflow.

**Start Route** validates the single actual lorry from the loaded customer/shared Plans and saves
it into the Trip's **Lorry Warehouse** together with the departure. It becomes read-only after
departure. The driver trip list and current-stock print use the same recorded lorry.

For an older started Trip whose header is blank, an office planner with write permission opens
the saved Trip, reloads it and selects **Sync Lorry Assignment**. This restores only the lorry
already recorded in its departure snapshot; no manual warehouse selection, new route or stock
transfer is needed. The action retains the exact snapshot, execution revision and active-lorry
key, so pending deliveries, route-order decisions and GPS can continue. Missing/inconsistent
departure evidence requires Supervisor reconciliation. Do not change the field manually.

## Driver GPS and identity settings

The normal **Route Template / Delivery Trip** form includes **Driver GPS**. Choose an interval
of 15/30/60/120/300 seconds and optionally enable **Auto-start GPS on Start Route** (default off).
Template loading copies these defaults into the Trip. Start the route from the actual assigned
driver/assistant phone if automatic sharing is wanted; browser location permission is still
required, and another device's active source is never replaced automatically.

An office planner with native write/Company access can change the interval on a running Trip and
save it. A GPS-only change preserves the frozen departure and delivered quantities. It is applied
at the next source publish/read-back. Other business edits retain their existing execution guards.
Use **Driver Route → Check Saved GPS Source** on the source device to apply a changed interval
without waiting for its next scheduled publish.

**Assigned Driver — Name and ID** shows the selected Employee's name and ID together. It is
server-derived and also populated when older records open. Driver/assistant labels, Supervisor
views and the Trip stock list retain their IDs beside names. Customer/Trip status legends and
**Fit Selected Customer** are available on Driver Route and Supervisor Live Map; KL remains the
empty-map default and Fit Locations continues to fit all real points.

## 6. Close or cancel planning safely

Enter **Closure / Cancellation Reason** in **Notes and History**, save any planning changes first,
then choose **Close Planning** or **Cancel Planning**. Each linked customer Plan **and the shared Open Route Plan** must first be Reconciled or
Cancelled through the existing controlled workflow. Office closure does not settle stock, issue
credit or bypass E5.

Closed/Cancelled trips retain stops, assignments, source links and history. Their planning holds
are released; they cannot be reopened or deleted. Native change tracking records planning edits.
Use the existing E5 recovery and reconciliation for physical stock and delivery corrections.

## Phase boundary and acceptance

The original office phase records an itinerary and LIFO instructions without publishing an
operational Sheet. Driver execution now retains the Trip sequence and any mapped approved
Sheet; Planned Order on either enforces the next stop. Existing Dispatch Profile/Sheet QR and
approval policies remain mandatory. The office trip does not automatically approve that Sheet.

The separate [Driver Route page](USER_GUIDE_DRIVER_ROUTE.md) reads assigned saved trips and
existing operational feedback and guides departure, native delivery and proof completion. Trip-driven
dispatch generation and optional shared-pool sales are now implemented. Live resequence approval, customer maps/directions and Supervisor GPS visibility are described below. Bluetooth printing remains later development. Local tests do not verify live-site behavior. Run
[the Phase 1 site checklist](TEST_OFFICE_DELIVERY_TRIP_PHASE1.md) after manual deployment.


## Driver departure and customer completion

The separate [Driver Route](USER_GUIDE_DRIVER_ROUTE.md) now supports **Start Route** and
**Complete Stop** using the existing known-customer prepared delivery, native DN and proof
workflow. Mark the Trip **Planned**, assign its driver and exact Plans, complete all physical
loading and obtain any required operational Route Sheet approval before departure. An existing loaded Draft can be marked Planned as an office
status-only sign-off while its saved assignments/itinerary remain unchanged; returning it to
Draft or changing those sources remains blocked. Planned Order
on either the Trip or mapped approved Sheet is enforced. Once started, the Trip's itinerary,
source assignments and driver are retained; direct form edits cannot forge its execution facts.

Driver completion does not settle E5. If a route ends incomplete, first reconcile/cancel its
linked Plans using existing controls, then close/cancel the office Trip with a reason. Its driver
state becomes Closed Incomplete and releases the active lorry; undelivered stops stay unfinished.
Shared Open Route sales are described below and in the Driver Route guide. Driver route-edit approval and maps/GPS visibility are described below; Bluetooth printing remains later scope. Native-site acceptance is pending.


### Refusal and old-return extension

The linked [Driver Route](USER_GUIDE_DRIVER_ROUTE.md) now supports Accepted/Refused quantities
before Begin Delivery and old-return intake/reuse at a saved stop. Configure **Sound Refused
Goods** on the Dispatch Profile before creating the Plan. Enable Customer Returns, Site return
QC/Inspection Location and operator Customer Return/QC responsibilities for quality/old-return
handling. The trip shows refusal holds and existing QC case progress. These controls reuse the
native delivery, Return Case and E5 recovery workflows and do not post another stock receipt for
company-owned refusals. Native acceptance remains pending in
[the extension checklist](TEST_DRIVER_ROUTE_REFUSALS_RETURNS.md).

## Trip-driven generation acceptance

Run [the Trip generation/shared-pool checklist](TEST_TRIP_DISPATCH_GENERATION.md) after migration
and asset build. This extension is developed above `bc1a493`; offline checks do not establish
native database, ERP posting, multi-company or tablet acceptance.

## One Trip with a lead and assistants

Use **Trip Details → Assigned Driver** for the lead and **Assistant Drivers** for the office
presets. Every member signs in with their own operator credential. Assistants see this Trip in
**My Delivery Trips** and may start/continue its existing customer stops, Delivery Notes, proof,
optional sales and old-return collection, subject to their own permissions. One Trip, lorry,
sequence, stock pool and completion status remain shared.

Every assistant needs active Employee/Operator records, **Customer Delivery**, the appropriate
Dispatch responsibility and start/complete flags for the actions performed. Collection additionally
requires the existing Customer Return permissions. Native Company, Trip and source reads still
apply. The lead needs native Employee read access when selecting an assistant on Driver Route.
Membership grants no Supervisor, QC, posting or override authority.

Office may edit presets before departure. Once execution starts the table becomes read only; the
lead may use **Driver Route → Add Assistant Driver** before departure or while In Progress. Select
an Employee or scan their Employee ID and confirm. Other assistants cannot extend the team.
Completed/closed Trips retain their team history. Existing single-driver Trips continue to work.

Assignment records who added each assistant, when, and whether it came from office or the lead.
Each operational action keeps its real actor; the original Session creator is retained. Team
additions have a separate revision and do not rewrite the frozen itinerary/loading snapshot.
Unknown requests still require the original actor or authorized Supervisor reconciliation.
See [assistant acceptance](TEST_TRIP_TEAM.md); native-site acceptance remains pending.

## Change a live delivery order

After Start Route, **Driver Route → Change Stop Order** lets the lead or an assistant reorder
unfinished customers on a Flexible Order route using drag/drop, tablet arrows or the scanner.
A Planned Order Trip, native Route Sheet or participating Open Route Plan instead requires a
reasoned **Request Stop Order Change**. The current approved order continues until approval.

Review in **Kanban Supervisor Action Centre → Delivery Route Changes**. A Supervisor with
View All Responsibilities, Can Override, Can Complete and native source access chooses
**Next Customer Only** (then prior remaining order) or **Entire Proposed Order**, or rejects
with a reason. Captured Profiles must permit **Allow Controlled Supervisor Override** for the
affected customer Plans. Completed stops stay fixed; active delivery/proof blocks route edits.
The order change preserves office/LIFO/loading history and required QR/stock/DN/proof controls.

See [the driver and Supervisor steps](USER_GUIDE_DRIVER_ROUTE.md#change-a-live-delivery-order)
for setup, scanner commands, cancellation, stale-request handling and uncertain-result recovery.
Run [native route-order acceptance](TEST_DRIVER_ROUTE_SEQUENCE.md) after migration/build;
results remain **Not run**. Offline tests do not verify native site/device behavior.


## Customer location pins and driver directions

On the normal **CFG Kanban Customer Scan Point → Delivery Location Pin** form, enter Latitude
and Longitude, **Set Pin**, check the marker and Save, or keep one marker using the native map.
Clear Pin and Save removes it. Existing manager/source permissions apply. The Trip/Template
reuses its selected Customer Sites; legacy Sites may leave the optional pin empty.

Driver Route displays numbered customer pins, current status and SO/customer PO/product details.
Google Maps/Waze buttons navigate to the server's current next stop. Without a pin, the buttons
clearly use address search; no coordinate is guessed. Office corrections refresh on active Trips
without rewriting stock or execution history. Map taps never bypass route, QR, DN or proof gates.

See [pin setup and driver directions](USER_GUIDE_DRIVER_ROUTE.md#customer-pins-and-directions)
and [native acceptance](TEST_DRIVER_ROUTE_MAPS.md). Directions use universal links; explicit Trip GPS sharing and the Supervisor Live Map are available as described below. Native-site/mobile acceptance is **Not run**.


## Supervisor lorry GPS map and Kuala Lumpur defaults

Open **CFG Dispatch Control → Supervisor Live Map** (`/app/kanban-trip-monitor`) or use the saved
Delivery Trip / Supervisor Action Centre button. Identify a Kanban Supervisor with View All
Responsibilities and Customer Delivery; native Stock/Manufacturing/System Manager and Company,
Trip and lorry read permissions apply. Select a Trip to see its effective customer stop sequence,
status, products, tags, planned/loaded/delivered/remaining quantities and the last real device fix.
The active list includes multi-day Trips. Completed history is optional.

One assigned driver/assistant uses **Driver Route → started Trip → Share GPS** on the lorry's
HTTPS phone/tablet. Keep the page visible and grant location permission. Updates are scheduled
15 seconds after each sampling attempt, while the device permits them. Browser/OS background
or lock may pause them. The source has its own 12-hour Trip-only publishing permission; it does
not renew operator delivery-action inactivity or grant posting authority. Explicit operator change,
Stop, source release/replacement, revocation or Trip end prevents further updates.

Age/accuracy are always shown. Live is a fix at most 90 seconds old; poor accuracy over 100 m is
labelled Low Accuracy. Stale/paused/stopped/expired/ended positions are grey and last known.
Missing GPS creates no lorry marker. Source Start/Stop/release has audit/retry protection; only the
latest fix per Trip is retained, with no GPS trail. An Override-authorized Supervisor can release
a matching unavailable source with a reason before another assigned device starts sharing.

Empty/new maps, including the native Customer Site pin editor and existing Driver Route map,
now default to **Kuala Lumpur: 3.139, 101.6869; zoom 13**. Saved pins/selected Trips focus their
actual coordinates. Kuala Lumpur / Fit Locations controls restore the default or fit real points;
Follow Lorry is optional. Native tile provider/attribution remain configured by Frappe.

Map interactions do not approve a route exception, deliver, post stock, replace a Customer Site QR,
or satisfy proof. Google/Waze direction links retain their existing next-stop behavior.
See [driver/supervisor steps](USER_GUIDE_DRIVER_ROUTE.md#trip-gps-sharing-and-supervisor-live-map)
and [native acceptance checklist](TEST_SUPERVISOR_LIVE_MAP.md). Native GPS/map/site acceptance
remains **Not run**; offline tests do not establish live-site correctness.


## Cancel a saved customer visit

Open the saved normal Delivery Trip form and select **Driver Route** (or **Open Trip / Customer
Stop Controls** on Supervisor Live Map). Select the exact unstarted customer. Drivers/assistants
request cancellation; every route policy requires Supervisor approval. Review is inline in the
existing Supervisor Action Centre, with exact SO/customer PO, loading and stock details. The
Supervisor chooses whether undelivered loaded goods stay reserved for return or are released for
same-trip sale. Physical stock stays on the lorry until normal transfer or delivery posting.

The cancelled visit stays read-only in the normal form and in separate driver/map history. It is
omitted from active pins, next-stop sequence, LIFO picking instructions and regenerated preparation.
Order quantities remain historical; the SO is not cancelled. Its cancelled planning hold is released
for another Trip in the route inbox. Other visits, SOs and the shared Open Route pool remain intact.
A Trip with cancellation history retains its itinerary/order/driver sources; plan replacement work
on another Trip. Delivery/ERP work already started needs native recovery first.

See [driver steps, holds, recovery and scanner commands](USER_GUIDE_DRIVER_ROUTE.md#cancel-a-customer-stop-safely)
and [native acceptance](TEST_DRIVER_STOP_CANCELLATION.md). This adds controlled links, a request
type and a cancellation-stock child table; owner-managed migrate/build is required. Existing
sequence-change requests retain their previous behavior. No existing stops are cancelled by migration.


## Trip Handover and per-item leftovers — E5B2 extension

Open **Delivery Trip / Driver Route → Trip Handover** for the full-page balance/return view.
Authorized Supervisors may assign remaining sources to multiple approved destinations and retain
selected sound stock on the lorry. Existing scans/native movements, a fresh balanced D3 count and
Review settlement still apply. Whole tags/held sources stay together; old returns use their existing
QC receipt, with no duplicate receipt/credit. Office closure now requires old-return physical receipt,
while inspection/accounting may continue. See [E5B2 setup and scanner guide](USER_GUIDE_DISPATCH_E5B2.md)
and [acceptance checklist](TEST_DISPATCH_E5B2_RECOVERY.md). Implementation does not establish live acceptance.


## Follow-on takeover — E5B3

Use **Plan Follow-on Trip** on the original normal Delivery Trip form after E5 settlement.
The embedded section selects still-required deliveries/visits, a receiving lorry and team,
confirmed existing stock and complete pending customer-return Cases. Original deliveries/proof
remain intact; no duplicate warehouse withdrawal/loading Stock Entry is created. The new linked
Trip remains Draft for normal office sign-off and required route approval. See
[E5B3 setup/scanner guide](USER_GUIDE_DISPATCH_E5B3.md) and
[combined acceptance checklist](TEST_DISPATCH_E5B3_FOLLOW_ON.md). Live testing is deferred, not passed.

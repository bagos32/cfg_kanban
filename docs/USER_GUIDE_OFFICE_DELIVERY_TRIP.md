# Office Delivery Trip — Phase 1 setup and use

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
5. Drag the table rows into sequence and save.

Visit Only means an office instruction such as collect information; it creates no order, stock
allocation or delivery. Customers may occur more than once at distinct stops. A Customer Address
must actually belong to that Customer. Disabled Customers/Addresses and wrong-Company Sites fail
validation.

Business changes increment the template revision. Saved trips retain their captured template
snapshot and their own customized stop order. Editing a template does not rewrite existing trips.
A route's Company cannot change after Sales Orders or trips reference it.

The existing dispatch/Route Sheet template selector continues using Delivery stops. Visit Only
rows are omitted there; an all-visit template cannot create a stock-delivery execution sequence.

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
   during early planning.
3. Click **Load Route Template**. The form captures its revision, stops, region/direction and
   default policy. Loading a template replaces the stop table; first save without assigned orders
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

## 5. Connect the existing dispatch workflow and read LIFO

Prepare Customer Order Dispatch Plans through the existing Dispatch Operations workflow. In the
trip's **Linked Dispatch Plans** table, select each existing Plan and its delivery Stop No, then
save. Phase 1 links Vehicle Delivery Customer Order Plans; Open Route Stock fulfilment remains in
the existing operational workflow and will join the new driver terminal in a later phase.

A linked Plan must match Company, Customer Site, SO, assigned Item/UOM quantities and any specified
source/lorry Warehouse. All linked Plans with assigned vehicles must use one lorry. A Plan cannot
belong to another trip while its historical link remains. Settled/cancelled Plans cannot be newly
assigned. Release reservations through the existing dispatch workflow before unlinking a Plan.

In **LIFO Loading Sequence**, the last delivery stop is listed first. For stops **A → B → C**, load
**C, then B, then A**. Visit-only stops and non-stock SO Items do not create physical load rows.

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

## 6. Close or cancel planning safely

Enter **Closure / Cancellation Reason** in **Notes and History**, save any planning changes first,
then choose **Close Planning** or **Cancel Planning**. Each linked Plan must first be Reconciled or
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
existing operational feedback and guides departure, native delivery and proof completion. Automatic office-trip publication to operational routes, live
resequence approval, maps/GPS and Bluetooth printing remain
later development. Local tests do not verify live-site behavior. Run
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
Open Route Stock, driver route-edit approval, maps/tracking and Bluetooth printing remain outside
this execution package. Native-site acceptance is pending.


### Refusal and old-return extension

The linked [Driver Route](USER_GUIDE_DRIVER_ROUTE.md) now supports Accepted/Refused quantities
before Begin Delivery and old-return intake/reuse at a saved stop. Configure **Sound Refused
Goods** on the Dispatch Profile before creating the Plan. Enable Customer Returns, Site return
QC/Inspection Location and operator Customer Return/QC responsibilities for quality/old-return
handling. The trip shows refusal holds and existing QC case progress. These controls reuse the
native delivery, Return Case and E5 recovery workflows and do not post another stock receipt for
company-owned refusals. Native acceptance remains pending in
[the extension checklist](TEST_DRIVER_ROUTE_REFUSALS_RETURNS.md).

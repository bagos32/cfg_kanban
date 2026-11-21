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

Two/three-day trips remain active across midnight. At the actual trip end, complete the existing E5
review/count/return-or-overnight decisions for each Plan. After every Plan is **Reconciled / Settled**,
the Supervisor uses **Close Settled Trip** with a reason. Unvisited stops settled through E5 are
shown as **Closed Incomplete**; no customer delivery/proof is invented. Continue Same Plan Overnight
keeps the trip active rather than releasing it for a new route.

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
`ROUTE_SHEET_REFRESH`, `ROUTE_SHEET_CAMERA`, `ROUTE_VOID_PENDING` all use `CFG:CMD:`.
Use standard `CFG:SELECT:1`–`10`, Next/Previous Material Choices, Confirm and Cancel. Tab/Enter
suffixes and camera input are supported. Touch arrows provide the reordering alternative on tablets.

Unknown submissions retain the original operator, action and payload across reopening/refresh.
Confirm retries the original. Refresh reads the outcome; Not Recorded alone does not permit
correction. A reasoned Void If Unrecorded prevents late execution of the abandoned token.
Cancel closes safely and preserves pending details. Submission uses the previously confirmed
HTTPS/Web Locks browser setup; do not clear storage to resolve an uncertain action.

See [the acceptance checklist](TEST_LORRY_ROUTES_AND_FLOOR.md). The existing L1 acceptance gate is
separate and is not closed by these offline development checks.

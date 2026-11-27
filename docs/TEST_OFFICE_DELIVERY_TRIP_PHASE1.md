# Office Delivery Trip — Phase 1 acceptance

Prepared: 21 November 2026. **Native-site acceptance: Not run.**

Local offline checks execute actual planning functions and Desk handlers with document, DB and
RPC doubles. They do not establish successful Frappe schema migration, browser rendering, native
permissions, MariaDB locking/concurrency or ERP posting. Record the deployed Git revision, site,
operator/manager users and evidence below before accepting this phase.

Scope: normal office Delivery Trip form, reusable route template, SO route inbox, order assignment
and LIFO instructions. Existing operational Route Sheet approval, stock posting, delivery and E5
remain separate authorities. Driver/map/printing phases are not covered by this implementation.

## Native checklist

| Case | Procedure and expected evidence | Result |
| --- | --- | --- |
| Migration / normal pages | Manually migrate/build. Open CFG Dispatch Control → Standard Routes / Templates and Office Delivery Trips. Create, reload and print ordinary full forms; verify all tabs/tables and controller imports. No planning popup. | Not run |
| Existing templates | Open an existing template with legacy Delivery rows. Save without changing business values; verify defaults/revision behavior and existing Dispatch Card/Route Sheet use. | Not run |
| Template customization | Set region, direction, Flexible/Planned Order; drag stops, save and verify revision increments only for business changes. | Not run |
| Visit only | Add Customer/address without Site as Visit Only; reject disabled/mismatched Customer/Address. No SO, load, stock or delivery is created for that visit. Legacy dispatch selector ignores visits and rejects all-visit templates for stock delivery. | Not run |
| Company and source access | Use A/B Companies and native restricted users. Reject wrong/inactive route, wrong-Company Site, disabled Customer/Address/Item and unrelated Address. Test direct API reads/writes and native form permission errors. No data from unauthorized sources is returned. | Not run |
| SO route selection | Select active Company/customer route on Draft and submitted SOs; preserve native SO events and Kanban demand evaluation. Customer PO shown is native `po_no`, not a supplier PO. | Not run |
| Inbox | Saved Draft is visible but cannot be assigned. Submitted open SO is assignable. Closed/cancelled/completed/on-hold SO is excluded. Verify delivery-date ordering, paging, stock conversion and Customer PO. Unsaved SO does not appear. | Not run |
| Route membership | Reject selecting a route that does not list the SO Customer, including direct API attempts. Route stays optional. | Not run |
| Exact stop and SO row | Repeat Customer/Site on two stops and use SOs with differing shipping addresses. Require exact stop choice and exact SO Item row; reject wrong Company/route/Customer/address, Visit Only targets and duplicate assignment rows. | Not run |
| Planning quantity | Split an SO line over two trips. Draft and Planned assignments hold planning capacity. Reject excess, nonfinite, zero/negative, inappropriate whole-UOM fractions and excess precision. No ERP reservation or stock transaction is created. | Not run |
| Native concurrency | Two managers/tabs assign the same remaining SO quantity simultaneously. Only valid total assignments may commit. Repeat across different templates, route changes, stale trip saves and linked Plan assignment. Check current reads/transaction rollback, deadlocks and useful retry behavior under MariaDB. No partial child rows survive failure. | Not run |
| Partial delivery | Link exact SO Plans, submit a partial native DN and verify only outstanding trip commitments remain in inbox. Other trips retain their valid planning balance. Cancel/recreate a DN via existing workflow and check balances again; Draft/return DNs must not reduce planning holds. | Not run |
| Native SO feedback | With saved assignments, block route/Company/Customer/shipping-address changes until released. Unchanged source identity permits native delivery/accounting feedback even after template deactivation. Verify no regression to native cancellation/status feedback. | Not run |
| Template snapshot | Load a template into a trip, customize stop order, save; edit template and confirm the trip stays unchanged. Stale initial template revision fails. Replacing a saved template requires first saving without orders/Plans. Snapshot JSON cannot be forged. | Not run |
| Multi-day / lorry | Use departure and return dates over three days. Reject reversed dates, wrong-Company/inactive driver, invalid source Warehouse, nonvehicle Warehouse and conflicting linked lorries. Last-minute lorry selection remains in existing E3; derived Plan link shows its actual lorry. | Not run |
| Linked Plans | Link Vehicle Delivery Customer Order Plans to exact stops. Reject wrong Company/Site/SO, excessive requested/allocated quantities, conflicting Warehouse, duplicate/reused historical Plan and newly linked settled/cancelled Plan. Reservations must be released before unlinking. | Not run |
| Mixed LIFO | Plan A → visit-only → B → C. Link tagged and untagged allocations and leave one unprepared balance. Load list must be C → B → A, preserve quantities/UOM/Batch/tag identity and omit visits/non-stock Items. Reorder stops before execution and recheck the same SO/stop identities. | Not run |
| Source refresh | Change reservation/loading stages using existing dispatch actions. Refresh shows current sources without saving, changing stock or dirtying the trip; save updates stored loading instructions. Historical ERP-loaded quantity is not displayed as current available balance. | Not run |
| Existing loading | Print the office instructions and execute existing E3 scan/confirm/Manifest posting. Validate FEFO/FIFO, certificates and expiry still apply. Physical scan order is not newly enforced. | Not run |
| Execution freeze | After linked vehicle/loading/delivery execution begins, block changes to stop order, orders, Company/route, planning status and header assignment. Preserve snapshot; allow source detail refresh and controlled final close after E5. | Not run |
| Safe status failure | Attempt Close without reason and with unsettled Plans. No terminal state persists; client restores previous Planning Status and allows correction. | Not run |
| Closure / audit | Complete existing E5 then close/cancel planning with reason. Retain all rows/links, record user/time and change history, release planning holds. Reject reopen/delete/history rewrite. No stock reset or credit is generated by planning closure. | Not run |
| Browser races / text | Change Company/route/Site while a lookup is delayed; add an assignment while template lookup is delayed. No late response may replace new scope/rows. Source text renders escaped. Check on desktop/tablet normal Desk forms. | Not run |
| Legacy routes | Use unchanged existing known-customer, Open Route, direct delivery/pickup, proof, approved Route Sheet and E5 flows. Trip planning must not change their authority or allow approved sequence edits. | Not run |

## Local checks

Python: office planning, existing Route Sheets and schema contracts, plus existing Dispatch
quantity, E3 loading, E4A/E4B/E4C fulfilment and E5 reconciliation/recovery tests.

JavaScript: actual office inbox/form handlers plus existing Route Sheet, Dispatch quantity,
known-customer, Open Route, warehouse fulfilment, Dispatch Review and recovery UI scripts.

Native SQL queries and locks are inspected/exercised through doubles, not a MariaDB server.
These checks verify local behavior contracts only. Package L1 and other outstanding native
acceptance records remain independent and open.

## Execution record

- Deployed revision: **Not recorded**
- Site / migration result: **Not run**
- Manager and restricted users: **Not recorded**
- Native concurrency and partial-DN evidence: **Not run**
- Acceptance owner / date: **Not recorded**
- Exceptions or deferred defects: **Not recorded**


## Recorded offline verification — 21 November 2026

- 128 Python tests passed: new office planning tests, existing Route Sheets and DocType schema checks.
- 202 existing Python tests passed: Dispatch quantities, E3 loading, E4A/E4B/E4C fulfilment,
  E5 reconciliation and recovery.
- 14 new Node Desk helper/form checks passed. The 16 existing Route Sheet UI checks passed.
- Existing E3 quantity, E4A/E4B/E4C delivery, E5 review and recovery Node suites passed.
- Changed Python/JSON files parsed successfully; `git diff --check` passed.

These use local document/DB/RPC doubles. They do not execute Frappe migrations, native Desk grids,
MariaDB locks/concurrent posting, device operation or the development server. Every native
acceptance case above remains **Not run**. Base HEAD was `2e4bdeb`; changes remain uncommitted.

## Follow-up: ad hoc Trip stops and SOs without a preset route — 27 November 2026

Base `bd56dab`. The owner confirmed this case has a **Sales Order awaiting delivery**, rather than
only an unpaid Sales Invoice. The original inbox and `_order()` guard both required an SO's
`cfg_delivery_route` to equal the template. That prevented a legitimate ad hoc Trip stop from
selecting an unrouted SO, even though the Trip already held its exact Customer/Site.

- The Trip inbox scopes to validated Delivery Sites in the current form, including unsaved new
  stops, and reads same-Company open SOs with either this route or no route. Native `get_list` and
  per-document read checks remain; Site/Company/Customer/address are rederived and checked server-side.
- The reusable Route Template inbox retains its strict preset-route filter. An SO explicitly routed
  elsewhere is excluded and cannot bypass the guard by manually inserting an assignment row.
- Trip save permits an unrouted SO only for its exact validated Delivery stop. Existing current
  SO locks, cross-Trip quantity/stock-UOM limits, status, duplicate-row, source, execution-freeze
  and template-snapshot rules remain. No source SO route or reusable template is updated.
- Cancelled and Visit Only stops cannot take assignments. Late inbox responses are discarded when
  Company/route/Trip identity or the current stop scope changes. Site selection refreshes the inbox.
- Existing dispatch generation is reused in separate-Plan and Consolidated Customer Orders modes.
  Both retain exact SO Item identities and quantities, and planning creates no ERP stock movement.

Changed files:

- `cfg_kanban/services/delivery_trips.py`
- `cfg_kanban/public/js/office_delivery_trip.js`
- `cfg_kanban/cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js`
- `cfg_kanban/tests/test_office_delivery_trip.py`
- `cfg_kanban/tests/test_ad_hoc_trip_orders.py`
- `cfg_kanban/tests/test_office_delivery_trip_ui.cjs`
- `docs/USER_GUIDE_OFFICE_DELIVERY_TRIP.md`
- `docs/USER_MANUAL.md`
- This acceptance document.

Offline verification: **332 Python tests passed**, including 17 ad hoc inbox/save/generation tests
plus office planning, dispatch generation, consolidated dispatch, fulfilment, driver actions, route
scope, direct lorry sales, stop cancellation, continuation and schema regressions. **50 Node tests
passed** across office, consolidated and continuation UI suites; 29 exercise office form/helpers.
Tests cover unrouted ad hoc SOs before/after saving, strict template/foreign-route filters, source
permissions, Company/address/status, current quantity/conversion, cross-template overbooking,
pagination, cancelled/Visit Only scope, forged/malformed inputs, stale responses and generated demand.

No new schema or data migration is required. Deploy the Python and Desk JavaScript together, build
CFG assets, clear cache and reload Desk using the owner's existing procedure. No live records were
accessed. These results do not establish native Frappe permissions, SQL isolation or ERP posting.

| Additional native-site case | Result |
|---|---|
| Customer absent from template, submitted SO with no route: add an unsaved Trip Delivery Site, refresh inbox, assign/save/reload/Mark Planned | Not run |
| Repeat using separate and Consolidated Customer Orders; load through E3 and deliver with native SO Item/UOM feedback | Not run |
| Restricted Company/Site/SO users; wrong address/route, cancelled/Visit Only stop and Draft/closed SO rejection | Not run |
| Two planners assign an unrouted SO through different templates; native current-read/rollback/stale-save protection | Not run |
| Confirm no SO/template rewrite, duplicate Plan, stock reservation or ERP movement from inbox/planning | Not run |

# Mock Draft Trip route planner

Prepared 28 November 2026 above `bf38c61`. This is the first office-planner package, using a mock
provider. It makes no Google request, uses no OAuth credentials, and produces no road, traffic,
distance or savings estimate. A flexible route is reversed as a deterministic test; each leg is
simulated as ten minutes. A Planned Order stays in its saved order. Both must satisfy the entered
service windows. This fixture is not an optimization algorithm or a production recommendation.

The planner is a tab on the normal **CFG Kanban Delivery Trip** form. Existing SO Inbox,
consolidated preparation, manual sequencing, dispatch, driver delivery and ERP posting remain
their existing workflows. This package introduces no floor/scanner action.

## Supported pilot

- One company setup, one assigned company lorry and depot, one departure/return day. The start
  and return gates can differ but both must be verified.
- Saved, unstarted **Draft** Trips with submitted customer stock Sales Orders. At most 50 stops
  and 250 exact SO Item assignments, further limited by the company setting.
- Distinct `stop_key` identities, including two visits to the same Site. A single SO Item still
  follows the existing rule: combine it into one Trip assignment. Different orders/items may
  belong to separate visits.
- Exact SO stock-UOM quantities remain unchanged. Planning weight does not change ERP UOMs.
- An empty ERP lorry Warehouse, with no active dispatch execution for that lorry. This first
  package excludes shared/Open Route stock, Visit Only stops, follow-on Trips, multi-day trips
  and any Trip whose dispatch work has already been generated. Use their existing controls.
- Packed weight is the modelled capacity. Office staff must also verify volume, stacking,
  segregation and local vehicle/site access; the mock has no Malaysian truck-road model.

## Permissions

Trip proposals and decisions require native Trip **write** permission, Company access and an
office role: Stock Manager, Sales Manager, System Manager or CFG Kanban System Maintenance.
Company, template, customer/site/address, Warehouse, SO and Item read checks remain in force.
An Operator QR or Kanban Supervisor designation alone grants no office access.

Create/edit **CFG Kanban Route Planner Settings** as Stock Manager, System Manager or CFG Kanban
System Maintenance. Sales Manager can read the setup. Those four office roles can read Planning
Runs; creation, updates and decisions are controlled by the service, and deletion is rejected.
Audit User/Run links do not introduce user-permission filtering into ordinary Trip lists.
Run lists use the native visible Trip scope; opening a Run also checks its captured source
documents. Internal JSON snapshots have no ordinary-role field access. The inline authorised
Trip comparison is the normal review surface. These are deny-only
[Frappe permission hooks](https://docs.frappe.io/framework/user/en/python-api/hooks#document-permissions);
they do not grant ERP permissions.

## 1. Configure the company pilot

Search for **CFG Kanban Route Planner Settings**, or use **Company Planner Settings** in the
Trip's **Mock Route Planner** tab. This opens a normal DocType form.

1. Select Company. Only one settings record is allowed for that Company. Keep **Provider** as
   **Mock (test only)**. **Enable Mock Pilot** defaults off.
2. Select the active leaf **Depot Source Warehouse** and company-specific **Assigned Lorry
   Warehouse**. They must differ. The lorry needs the existing vehicle-Warehouse flag/reference.
3. Enter **Usable Packed Payload (grams)**, including the effect of any physical capacity
   reduction. For example, 500,000 grams means 500 kg. This pilot cannot include other ERP stock
   already in that lorry; move/reconcile it through its owning workflow first.
4. Enter same-day **Depot Departure (MYT)** and **Depot Return Deadline (MYT)**, such as 08:00 and
   18:00. The deadline must follow departure. The model uses dated Asia/Kuala Lumpur times.
5. Place one marker for each verified depot departure and return entrance. Empty map defaults
   continue using the existing Kuala Lumpur map setup. Review the pins and check **Both Depot
   Gates Verified**. Changing a gate or Warehouse clears verification; review and save again.
6. Set **Maximum Visits** (default 20, hard maximum 50) and **Maximum Mock Attempts per Trip**
   (default 10, hard maximum 100). Retries count; duplicate clicks on the same pending request
   do not. Finally enable the mock pilot and save.

Changing setup makes earlier proposals stale. Company cannot be moved after planning history
exists; create the other Company's setup separately.

## 2. Verify customer entrances

On each normal **CFG Kanban Customer Scan Point** form, confirm its Company, Customer/address
and **Delivery Location Pin**. Check **Entrance Pin Verified for Route Planning** as an office
editor. The server records the verifier and time.

Editing the pin, Company, Customer or address clears verification. Save the corrected data,
review it, then verify and save again. Existing direction links, site QR, proof requirements,
signature/photo/GPS policy and ordinary deliveries retain their existing behavior. Unverified
pins block this optional planner, not the manual delivery workflow.

## 3. Prepare the Draft Trip

1. Create a new test Trip through the normal office form, load its template and assign exact
   submitted SO Item rows through **SO Inbox for Trip Stops**. Existing ad hoc blank-route SO
   assignment and **Consolidated Customer Orders** remain supported.
2. Set **Trip Date** and leave Expected Return Date blank or use that same date. Assign the
   source and lorry Warehouses matching the company pilot setup. Do not generate dispatch yet.
3. For every **Customer Stops** row, enter **Planner Service Minutes**, **Planner Receiving
   Opens/Closes (MYT)** and, if required, **Finish Service Before Closing**. Windows must fit the
   single-day departure/return window. A finish-by-close window subtracts service duration from
   the latest allowed start. Each visit needs at least one assigned stock SO Item.
4. On each physical **Assigned Sales Orders** row enter **Packed Grams per Stock UOM**. Include
   packaging. For example, three Nos at 1,500 g/Nos contribute 4,500 g. Fractional gram totals
   round up, never down. These values are per-Trip planning inputs, not ERP conversion factors.
5. In **Mock Route Planner**, select **Enable Mock Route Planner** and confirm **Packed load
   and lorry/site fit verified** after reviewing the actual load and access restrictions. Save.

Planning fields are optional for normal Trips. They cannot be changed after planning leaves
Draft or dispatch work begins. Service/windows are entered per Trip in this first package;
route-template defaults and live routing belong to later packages.

## 4. Request, compare and decide

1. Open **Mock Route Planner → Refresh Readiness / History**. Correct each listed blocker. No
   dispatch plan, reservation or stock movement is created by readiness or proposal generation.
2. Select **Generate Mock Proposal** once. A **Route Planning Run** is saved as Queued and the
   short-queue worker is enqueued after commit. The Trip remains unchanged. Repeated requests
   for identical saved inputs return that Run. The worker releases its claim lock before calling
   the mock and guards result writes by Run/attempt, with a 30-second mock deadline.
3. Review the inline **Original order / Mock proposed order / Simulated service start** table.
   One row represents each stable visit. The mock does not compare road savings. Planned Order
   is preserved; manually change/save the Draft order first if its required order must change.
4. Enter a decision reason (1–500 characters), then **Accept Mock Proposal** or **Reject
   Proposal**. Acceptance rechecks native permissions, current Trip revision, exact SO balances
   and assignments, stop set, pins, lorry, settings and dispatch stage. An unknown, duplicate,
   omitted/skipped visit, wrong vehicle, invalid timing or stale input blocks acceptance.
5. Acceptance uses normal Trip validation to reorder the existing stop rows and rebuild LIFO.
   Stop IDs, SO Item IDs and quantities are preserved. The native form reloads. Run history and
   a Kanban Event retain actor, time, reason and source/result revisions. A retry of an accepted
   Run returns its receipt and never reorders a later edit. An unchanged accepted order may
   retain the same planning revision; the decision audit still records its acceptance.
6. Use **Mark Planned** and the existing generate/approve/pick/load controls when office planning
   is ready. The optimizer does not approve a Route Sheet, reserve goods, start a route or create
   a Movement Manifest, Stock Entry, Delivery Note or stock ledger movement.

SO validation checks currently undelivered/unassigned stock-UOM demand under the existing office
locks. It does not reserve physical warehouse stock; physical availability and posting are still
validated by dispatch. Rejected/failed proposals leave manual sequencing available. History
displays the latest ten Runs; older records remain in the normal **Route Planning Run** list.

## Recovery

| Situation | Office action |
| --- | --- |
| Input changed | Save/reload, refresh readiness and generate a new proposal. The old Run remains stale history. |
| Reply lost | Refresh history first. Reuse the exact Run for the decision/retry; do not invent a second acceptance. |
| Failed or Timed Out mock | Enter a reason and use **Retry Original Mock** with unchanged inputs. Prior attempt and decision facts remain in history. |
| Worker stays Queued/Running | Check the Bench short-queue worker. After 90 seconds, an authorised office editor can enter a reason and **Mark Interrupted**. Then explicitly retry. A late old attempt cannot overwrite the newer attempt. |
| Trip attempt cap reached | Review the pilot usage. An authorised settings editor may change the cap; that settings change makes old inputs stale, so generate a fresh proposal. |
| Rejected result | Keep/manual-sequence this Trip, or change and save planning inputs before generating a different proposal. |
| Dispatch already exists | Use the existing preparation/recovery/route-change workflow. This pilot cannot rewrite committed dispatch work. |

## Migration and verification

Owner runs the usual CFG migration, asset build, cache clear and restart. Migration adds two
DocTypes and optional/default-off fields. The new `cfg_route_planner.bundle.js` uses Frappe's
content-hashed asset loader. No dependency installation, Google credential, API enablement,
Frappe/ERPNext upgrade or stock backfill is required. Existing settings/Trips are not enabled.

See [the test and native acceptance record](TEST_MOCK_ROUTE_PLANNER.md). Offline fixtures are not
live acceptance. Verify real Company/source permissions, after-commit worker execution, concurrent
edits/duplicate actions and database rollback on the ERPNext test site, then the unchanged normal
loading → Delivery Note → proof → reconciliation path. The separate Package L1 same-Company
Transfer acceptance remains partially tested and must be completed before any production
recommendation for this pilot.

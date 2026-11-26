# Driver Route execution — acceptance record

Prepared 21 November 2026 above `754708d`.

**Status: offline verification only; all native-site checks below are Not run.**
Record actual deployed revision, site, tester, time, document references and observed results.
Offline RPC/document/DOM doubles do not prove MariaDB transactions, native migration or live ERP posting.

## Scope

Start Route and Complete Stop on the existing separate Driver Route page. Reuse the existing
prepared Customer Order Vehicle Delivery, Route Sheet, Delivery Session, ERP command/DN and proof
engines. No new stock or financial engine. Office route planning stays on the normal DocType form.
Existing E5/returns/recovery and the separate L1 acceptance gate remain open.

## Local verification — 21 November 2026

- Nine targeted Python modules: **251 tests passed** (driver orchestration/view, office trip,
  Route Sheets, prepared/warehouse fulfilment, media, direct returns and dispatch recovery).
- Nine JavaScript suites: **77 Node runner tests passed**. The five legacy script-style suites
  additionally report their individual 18/16/20/26/27 checks within their file-level results.
- Changed Python/JavaScript syntax, both DocType field orders and `git diff --check` passed.
- These use source-document, RPC, storage/lock and DOM doubles. No Frappe site, database worker,
  real ERP transaction, S3 service, camera, GPS or physical scanner was exercised here.

## Setup

- Migrate/build using the owner-managed deployment procedure. Verify new readonly Trip execution
  and stop audit fields, and the nullable unique active-driver-lorry key. Preserve existing trips.
- Use an assigned operator with Customer Delivery, the Plan's dispatch responsibility and start/
  complete flags. Give the terminal user actual native Company/source/proof reads.
- Prepare a Planned trip on one lorry with two customers, submitted loading Stock Entries and
  both tagged and untagged stock. Approve its existing exact Route Sheet where policy requires it.
- Include a same-stop second SO Plan, a Visit Only stop, required-proof and No Proof Required
  policies, auto-submit and Draft DN cases, mandatory ERP scalar/table fields and private S3 media.
- Use two supported HTTPS tabs, a wedge scanner, a tablet camera/signature pad and device GPS.

## Native checks — each Not run

| Check | Expected result | Result / evidence |
|---|---|---|
| Existing trips after migration | Default Not Started; no invented historical departure or completion | Not run |
| Loaded Draft sign-off | Office can mark the unchanged Draft Planned; changing quantities/driver/itinerary or returning to Draft remains blocked | Not run |
| Departure review/confirmation | One driver audit/revision; no customer Session, DN, stock or proof at departure | Not run |
| Draft Trip, wrong driver/Company, missing responsibility/flag/read | Denied before business mutation | Not run |
| Partial loading, Draft/cancelled Stock Entry, unprepared stop, mixed lorries | Departure rejected with useful explanation | Not run |
| Required approval, Draft Sheet, outside/ambiguous mapping | Blocked; no automatic approval or customer guess | Not run |
| Strict Trip/Sheet sequence | Later stop rejected; current DN/proof must finish | Not run |
| Flexible route | Eligible alternate stop allowed; existing active stop still blocks another | Not run |
| Required Customer Site QR | Correct scan accepted; missing/wrong scan rejected; camera and wedge agree | Not run |
| Assigned-stop selection policy | No unnecessary Customer Site scan; saved exact customer remains authoritative | Not run |
| Complete full prepared stop | Same native allocation/ERP engine; no repeated per-tag scans or allocation edits | Not run |
| Native required ERP scalar/table data | Pauses for values; scanner/table row entry preserves required data | Not run |
| Auto-submit / No Proof Required | Exactly one submitted native DN; native closure then stop completion | Not run |
| Draft DN | Remains pending until authorized ERP submission; no duplicate draft or forced posting | Not run |
| Required proof | Missing recipient/signature/photo/GPS rejected; no driver stop completion | Not run |
| Private camera photo | Actual image, server timestamp/reference and GPS stamp; private S3 media Available | Not run |
| Signature encoding/upload, failed upload | Cannot overtake pending evidence; failure recoverable; no false proof completion | Not run |
| Media open/archive, operator switch | Same native proof scope and permissions; no stale opening/upload after switch | Not run |
| Optional/unattended dispositions | Existing native policy rules retained; no automatic attended proof | Not run |
| Two Plans/SOs at one stop | Separate native DNs/proof, one stop closes only after both | Not run |
| Finish elsewhere then return | Refresh/Complete Stop acknowledges existing feedback without reposting | Not run |
| Visit Only | Notes, Employee/time/revision/Event; no stock, DN, allocation or proof invented | Not run |
| Last stop | Driver route Completed and lorry released; existing E5 not falsely completed | Not run |
| Multi-day trip/session timeout | Trip retained; reidentify same Employee, continue original pending action | Not run |
| Lost request/reply at each mutation; reload/close | Exact original actor/payload/token retained; receipt readback/retry yields one result | Not run |
| First explicit rejection vs unknown then rejection | Only first confirmed rejection permits correction | Not run |
| Readback while original is delayed | Not Recorded keeps original pending; no replacement details | Not run |
| Supervisor void raced against delayed original | One serialized result; Voided fences original; recorded action cannot be voided | Not run |
| Changed payload with same token | Rejected without replacing existing receipt/native outcome | Not run |
| Two tabs / two departure workers | Web Lock guards browser; Trip lock/unique lorry key guard server; no duplicate posting | Not run |
| Two different Trips claim same lorry | One active departure; friendly denial for the other | Not run |
| Route/source revision changes after departure | Frozen snapshot rejects stale execution; no silent resequence or source replacement | Not run |
| Office direct editing of readonly driver fields | Cannot forge departure, revision, active lorry or stop completion | Not run |
| Incomplete trip recovery | Existing Plans first reconciled/cancelled, office reasoned close/cancel releases lorry as Closed Incomplete; stops remain unfinished | Not run |
| Cancelled DN/proof after completion | Existing native review/recovery retained; UI never counts cancelled/return DN as delivery | Not run |
| Tab/Enter, Help, numbered fields, Cancel, camera close | Correct input and scanner focus; no late action on another trip/operator | Not run |
| Existing Logistics proof/returns | Shared photo/geotag helpers retain existing evidence behavior and native media policy | Not run |
| Polling, page hide and native read revocation | Fields preserved during action; no activity renewal by polling or protected stale details | Not run |

## Offline coverage

### Departure lorry binding / legacy repair — 23 November 2026

Working changes above `abb6e37`. The previous release was reproduced with a blank Trip header:
Start Route saved `vehicle = LORRY` in the snapshot but left both the header and trip-list lorry
empty. The stock helper returned no rows from that header. New departure now binds the header
in the same departure update, after its loading/Company/single-lorry checks. Older trips display
and print the frozen lorry; authorized **Sync Lorry Assignment** restores the blank header while
retaining the exact snapshot, active key, execution revision and original action scopes.

| Native-site case | Expected evidence | Result |
| --- | --- | --- |
| Last-minute lorry | Leave header blank, complete real E3 loading, Start Route; header/list/driver show the one verified Company lorry; next delivery succeeds | Not run |
| Legacy started Trip | Office reload + Sync Lorry Assignment restores the snapshot lorry; repeat/late request cannot overwrite it or duplicate departure | Not run |
| Pending work | A pending delivery, enforced-order approval and active GPS publisher continue after repair; frozen snapshot and active-lorry key remain identical | Not run |
| Permissions/conflicts | Native Trip write + planner roles, Company and Warehouse reads, configured lorry and current modified timestamp enforced; wrong/missing snapshot or changed source cannot select a substitute | Not run |
| Current-stock print | Normal ERPNext and direct 80mm paths use recorded lorry and current ERP/tag balances; current quantities, expiry, native tag read gates and QC labels stay intact | Not run |
| Atomicity/concurrency | Real database failure/duplicate active-lorry races leave no partial assignment, departure or audit; native rollback and locking checked | Not run |

Offline verification: **716 Python tests passed**, with 5 native Frappe naming tests skipped;
**244 Node test entries passed**. Coverage includes 17 new Python regressions and three new
office-form UI cases. Changed Python/JavaScript/JSON syntax and patch whitespace checks passed.
These use framework/database/UI substitutes. Native migration, ERP stock/PDF/bridge output,
database concurrency and live-site quantities remain unverified; the site table is **Not run**.

`test_driver_route_actions.py` executes the actual orchestration functions over the existing
Trip/view fixtures and native-service doubles: departure gates, receipts/void, source snapshots,
strict/flexible sequence, native delegation, Draft holds, proof barriers, same-stop multiple Plans,
Visit Only, lorry release and protected native-form recovery.

`test_driver_route_actions_ui.cjs` executes the actual durable controller and inline action panel.
`test_delivery_proof_tools_ui.cjs` exercises the shared private-media/GPS/canvas adapter.
`test_driver_route_ui.cjs` retains view/session/privacy tests and adds action-host/lifecycle checks.
Existing office, prepared-delivery, warehouse, route, media and recovery checks remain regression
coverage. Results recorded in chat are local tests only; fill the table with real site evidence.

Deployed Git revision: **Not recorded**  
Site / tester / date: **Not recorded**  
Accepted exceptions / follow-up: **Not recorded**

## Open Route identified-session regression — 26 November 2026

The new test reproduces native Start Route → Sell from Lorry → Customer Identified → driver
context. Before correction, context incorrectly returned Blocked; it must return Select Route
Stock on the same Session, with **Add Product / Scan Stock** and an empty selection.

Required offline checks:

- New/reopened Customer Identified Session offers goods selection without a state rewrite,
  new Session, stock movement or reservation release.
- Allocate goods, confirm and create the native DN; original-request replay creates only one
  DN/consumption and completes only the appropriate customer stop.
- Current operator/Company/route permissions and existing frozen-pack allocation gates remain.
- A linked Draft/submitted DN never reopens goods selection. Genuine exceptions remain blocked
  with exact Session/state, document/exception links and actionable recovery guidance.
- The actual driver adapter shows the product button and Session reference, opens its stock
  child on click or the printable ALLOCATE_ROUTE_STOCK command, and restores focus on close/error.

**Live acceptance: Not run.** On the affected site, verify both a new sale and an existing stuck
Session, tagged and untagged Item/Batch quantities, Draft/auto-submit policy, proof and actual
posting feedback. Follow `USER_GUIDE_OPEN_ROUTE_SESSION_RECOVERY.md`; retain record references
and the deployed Git revision. Offline document/RPC/DOM doubles do not establish live behaviour.

Local result for this correction: **238 Python tests passed**, including the native identified-
Session regression, same-Session selection/DN flow and replay, operator isolation, existing
Draft/submitted-DN rejection, frozen-pack guard, and genuine-exception visibility. **112 Node
results passed**, including the actual driver adapter and an existing legacy harness with 36
named checks. Python/JavaScript syntax and diff-whitespace checks passed. No live site or physical
device was used. The original regression failed with `Blocked != Select Route Stock` before the
correction and passed afterward.

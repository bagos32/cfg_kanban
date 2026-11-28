# Mock Draft Trip planner — test and native acceptance

28 November 2026. Working base `bf38c61`. All development uses test data in this checkout's test
copy. No live Trip, Sales Order, warehouse balance, Google project or credential is accessed.
Provider mock only; no live routing or Google authentication is implemented in this package.

## Offline workflow

Use the existing Python unittest and Node test workflow. The Python tests run actual service
bodies and the normal office Trip validator with explicit DB/document/RQ doubles. The browser
fixture builds the actual hashed JS entry and uses fake RPC on localhost, with fresh temporary
profiles. No generated assets are committed.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_route_planner_model cfg_kanban.tests.test_route_planner cfg_kanban.tests.test_office_delivery_trip cfg_kanban.tests.test_trip_dispatch cfg_kanban.tests.test_consolidated_dispatch cfg_kanban.tests.test_customer_locations cfg_kanban.tests.test_doctype_schema
node --test cfg_kanban/tests/test_route_planner_ui.cjs cfg_kanban/tests/test_office_delivery_trip_ui.cjs
node cfg_kanban/tests/run_route_planner_browser.mjs
CFG_BROWSER=firefox node cfg_kanban/tests/run_route_planner_browser.mjs
```

The browser runner uses the sibling Frappe app's installed esbuild. Outside a Bench, set
`CFG_ESBUILD` to an existing compatible executable. It installs no dependencies. Optional
`CFG_PLANNER_SCREENSHOT` records a Chrome fixture screenshot in a temporary destination.

Coverage: opaque provider labels; same-site separate visits; dated MYT service/finish windows;
rounded-up load and capacity; wrong vehicle, missing/unknown/duplicated/skipped visits; Planned
Order preservation; disabled/default-off manual planning; native Company/role/Trip/source checks;
current reads and office lock ordering; exact unchanged SO identities/quantities and reversed
LIFO after acceptance; stale Trip/SO balance/pin/vehicle/settings/assignment; generated or active
dispatch; existing lorry stock; lost replies; duplicate requests/worker jobs/decisions; explicit
bounded retry and interrupted-attempt fencing; controlled history; pin/gate verification reset;
source HTML escaping and late UI responses. The success path compares the native-document/stock
inventory before and after. Audit-write failure restores Trip/Run data at the simulated POST
rollback boundary; it does not prove real MariaDB rollback or distributed concurrency.

## Recorded offline results

- **396 Python tests passed.** The focused modules above plus ad hoc SO assignment, optional
  route pools, Trip sequencing, driver routes/actions, Trip continuation and E3 loading were run
  together. Includes deny-only history permissions and internal JSON field-access contracts.
- **167 Node tests passed.** Includes the planner/office-form modules above, driver route/action,
  Trip continuation and Customer Site location UI regressions. The real office refresh handler
  retains normal planning controls if the optional planner asset fails to load.
- **21 browser checks passed in Chrome 158 and 21 in Firefox 153.** Each run compiled the actual
  `cfg_route_planner.bundle.js`, loaded it by a hashed URL, and exercised the inline form with fake
  RPC. Includes stale results, lost/late replies and unsaved edits during acceptance.
- Changed Python/JavaScript syntax and all changed schemas parsed. Fields are uniquely ordered,
  with no new hidden-mandatory-without-default field. New text files have no trailing whitespace.

No result above proves real native permissions, database locking/rollback, Redis/RQ delivery,
Bench migration/build or actual ERP execution. Those acceptance rows remain open below.

## Native-site acceptance — not run

Record deployed revision, test Company/settings, test Trip/Run, expected/actual results and
references. Use a new single-day Draft and two small submitted test orders; do not alter existing
operating Trips merely to make them eligible.

| Case | Required evidence | Result |
| --- | --- | --- |
| Migration/default off | Two DocTypes sync; old Trips/Customer Sites retain ordinary operation. No new hidden/mandatory-without-default field failure. | Not run |
| Setup/Company/roles | Native User Permissions and Trip/source write/read checks; denied Companies/users cannot request or decide. Run read/list/export cannot expose hidden source JSON or another Trip's history. | Not run |
| Data readiness | Verified depot/customer entrance pins, dated windows and packed grams per stock UOM; exact missing/overweight blocker. Pin edits clear verification. | Not run |
| After-commit worker | New Run Queued, job created only after request commits, short worker returns Ready without Trip mutation; no worker job after a rolled-back request. | Not run |
| Two-visit proposal | All visits once, exact same physical lorry, independent repeated-site visits; native inline comparison usable at tablet/desktop sizes. | Not run |
| Accept/LIFO | Manager reason recorded, only existing stop order changes, same SO Item stock quantities, normal LIFO reversed; one-per-order and consolidated modes. | Not run |
| Concurrent request/edit/accept | Separate DB sessions, duplicate requests/jobs/accepts, source balance or settings edit while queued, no stale apply, no deadlock-driven partial state. | Not run |
| Failure/rollback | Lost reply, timed-out/killed worker, interruption/retry fencing, audit/save failure; one coherent Trip/Run outcome after actual database rollback. | Not run |
| No posting | Compare Manifest, Stock Entry, DN, allocation and Stock Ledger counts/balances before/after all planner actions. | Not run |
| Normal execution regression | Mark Planned, dispatch generation, LIFO picking/loading, site check, submitted DN, required proof and route reconciliation unchanged. | Not run |
| Provider disabled | Manual office planning and existing dispatch still function without planner setup, weights, verification or worker availability. | Not run |

Live Google adapter, Cloud Shell access, worker identity, policy/retention review, paid request
limits and live optimization acceptance remain later work. The mock's estimates are explicitly
simulated and are not copied into the operational Leaflet map. Package L1 acceptance remains a
separate open gate; see [the L1 test record](TEST_PACKAGE_L1_TRANSFER_KANBAN.md).

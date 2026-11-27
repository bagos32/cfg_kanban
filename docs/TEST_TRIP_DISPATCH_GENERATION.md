# Trip-driven Dispatch and shared Open Route acceptance

Development prepared 21 November 2026 above `bc1a493`. No deployment/site acceptance is claimed.
All native-site cases below are **Not run**. Record deployed Git revision, documents, actor,
expected/actual quantities and evidence after owner-managed migration/build.

## Setup

- Use a test Company, active route template, Driver Employee, configured source/lorry Warehouses
  and permitted terminal/native Desk users. Do not reuse production deliveries for acceptance.
- Template/Trip: enable **Generate Dispatch on Mark Planned**, select Customer Order and Shared
  Open Route **Vehicle Delivery** Profiles with matching Company/source and valid Dispatch Cards.
- On the Trip, explicitly select **Allow Sales from Existing Lorry Stock** for optional sales with
  no extra goods. Also test its default-off behavior with empty extra goods and Visit Only Sites.
- Configure both approval choices, both stop sequence choices, Site-QR/selection policies and
  normal Draft/auto-submit DN plus proof policies. Open Profile Route/Territory must cover Sites.
- Stops: known-order customer A, Visit Only B, Visit Only C; include a repeated Customer Site for
  exact-visit tests. Informational visit without a Site must remain supported.
- Assign submitted SO stock-UOM quantities, including two rows of the same Item on one SO, a split
  order across Trips and an SO conversion factor. Include mixed tagged/untagged loading sources.

## Native cases

| Case | Expected evidence | Result |
| --- | --- | --- |
| Load Template | Full DocType form inherits generation/Profile defaults, captured revision and stable stops; no popup or mutation of old Trips | Not run |
| Save Draft then Mark Planned | Exact Customer Order requests; one shared Open Route Plan only for extra goods or explicit existing-lorry sales, with exact native sale visits | Not run |
| Generate on Draft, reload, Mark Planned | Fresh Desk/server request accepts the unchanged generation timestamp as JSON text versus the database datetime; Trip becomes Planned using the same Plan/visit IDs and no new stock posting | Not run |
| Generated-field integrity across browser saves | Notes/status save succeeds with unchanged links/date, including fractional seconds and an empty optional pool; changed/cleared timestamp or Plan link and forged insert facts remain rejected | Not run |
| Warehouse work already started | Mark Planned retains generated Plans, allocations, Manifest and load history; source/quantity changes remain protected by existing execution guards | Not run |
| Informational visits | Empty extra goods and default-off existing-lorry sales create no empty Open Route Plan, require no Open Route Profile/approval and preserve Visit Only stops | Not run |
| Existing lorry stock only | Explicit office checkbox + eligible Visit Only Sites create controlled request, no Manifest/Stock Entry/reservation; approval + actual lorry needed for Ready for Fulfilment | Not run |
| Cancelled unused empty context | Reload driver page and start loaded customer route; no binding/reapproval/recreation of cancelled Plan, no extra documents or stock moves; retained audit/reference | Not run |
| Cancelled context with history | Real quantities/reservations, Manifest, Session, active visit/pack/review, unresolved Exception or active Sheet reject with recovery diagnostic; customer loading/approval/driver gates still apply | Not run |
| Extra goods | One shared loading request with Item/Batch/UOM quantities; E3 actual reservation/loading/submitted transfer remains required | Not run |
| Approval | Both Profiles retain Awaiting Approval when configured; required request/route approval cannot be skipped at departure | Not run |
| Repeated save/refresh/two office tabs | Same requests/visits reused; stale modified timestamp rejected; no duplicates or partial parent/child commit | Not run |
| Office correction | Unused quantities replace requests with cancelled history; reverting an earlier quantity creates a fresh request; reservations/loading block replacement | Not run |
| Immutable identity | Manual Plan source edits, foreign Trip/stop links and forged generated/pool fields rejected | Not run |
| Manual mode | Existing manually linked Trips still work; enabling generation over those links fails without creating duplicate work | Not run |
| Invalid source | Wrong Company/profile/Card/warehouse, inactive source, invalid Batch, zero/nonfinite/whole-UOM quantity, duplicate extra Item/Batch rejected atomically | Not run |
| LIFO | A→B→C orders load C→B→A; shared extra goods appear once as accessible common stock; real allocations/tags/Batch refresh | Not run |
| Combined approved route | Exact office known/optional order including repeated Site visits seeds the existing Sheet; no omitted/duplicate/outside visits; saved draft reorder retained | Not run |
| Departure | Only assigned authorized driver; all real goods loaded, one lorry, existing pool approved/bound, required Sheet approved; no DN created at warehouse | Not run |
| Optional sale from prepared pool | Sell from Lorry opens exact native Site/visit Session, allocates partial tag or untagged goods, confirms native DN/proof and marks only this stop complete | Not run |
| Optional sale from free existing stock | Prepared and eligible unassigned stock choices remain explicit; known-customer commitments, reservations, QC holds and old returns cannot be taken | Not run |
| Source identity | Native expiry, certificate/Batch, serialized tag, container and ERP stock checks apply unchanged; same source cannot be oversold across stops/tabs | Not run |
| Repeated Sites and strict order | Exact office stop selected; required physical Site QR cannot be replaced by selection; Trip/Sheet strict order enforced on driver and direct Logistics calls | Not run |
| No-sale visit | Complete Stop retains notes/audit, skips only that native unused optional visit, creates no allocation/DN and permits next stop | Not run |
| DN/proof | Draft awaits authorized ERP submission; required recipient/photo/signature/GPS keeps current visit open; main stop shows selected/delivered sources | Not run |
| Retry | Lost Begin Sale/stock/confirm/DN/proof responses survive Close/reload/tabs; original identities reconcile without duplicate Session/reservation/DN | Not run |
| Tablet and wedge | Add Product/Scan Stock camera and Enter/Tab controls work; child and parent Cancel restore scanner focus and ignore late callbacks/changed operator | Not run |
| Driver/E5 closure | Driving completion alone never settles pool; native D3 count/E5 settles known and shared Plans (including no-loading context) before office closure | Not run |
| Multi-day trip | Trip survives midnight with same pool and exact source/approval snapshot; overnight native E5 choices retain their existing semantics | Not run |
| Cancellation/recovery | Unfinished stock/Session/Sheet requires native controlled release/recovery; cancelled documents and history retained; no direct metadata repair | Not run |
| Transactions and permissions | Real MariaDB rollback, unique identities, lock order, concurrent generation/selection/submission, role/Company/user-permission rejections verified | Not run |

## Offline verification

Tests exercise actual CFG Python functions and JavaScript controllers with in-memory Frappe,
ERP/DOM/storage doubles. They cover generation/idempotency, exact SO rows, approval gates,
shared prepared/free tagged/untagged sales, no-sale progression, route-sheet mapping, native
allocation/DN/ledger feedback, E5 counts, scanner/camera adapter scope and durable retry controls.

These checks do not establish migration, ERP ledger posting, real database transactions/locking,
print, S3 evidence or device acceptance. Existing logistics/L1 gates remain separate.

Verified locally for this change: **421 Python tests passed**, **93 Node test-runner cases
passed** (including scripts with their own internal checks), changed Python/JavaScript syntax
and DocType field/schema consistency passed, and `git diff --check` passed. The Python selection
includes all three new Trip suites and the existing order quantity, E3, fulfilment, route,
warehouse/pickup, E5 recovery, lorry visibility, office and driver/refusal/collection suites.
These are offline results; every native-site result above remains Not run.

### Mark Planned after generated Draft — 23 November 2026

Working correction above `3b9a092`: the reported rejection was reproduced by generating a Draft,
serializing/reloading its timestamp through JSON, then saving Planned with fresh server flags.
The guard now compares parsed datetimes at full precision and normalizes empty optional values;
changed/cleared links or audit times and forged insert facts remain rejected. Existing generated
requests, visits and loaded Manifest references are retained on the status change.

**528 Python tests passed** across 21 trip, office, driver, dispatch/E5, route and lorry modules;
**142 Node test entries passed** for the office form, driver, route, GPS/monitor and dispatch
adapters. This includes eight new generation/save regression cases. Python syntax and patch
whitespace checks passed. These tests use offline database/framework/UI substitutes; native Desk,
database rollback/concurrency and live-site Mark Planned acceptance remain **Not run**.

### Explicit optional sales and cancelled empty request — 27 November 2026

Prepared above `bd56dab` with the pending ad hoc SO correction preserved. The owner chose: create
the shared pool for extra route goods or an explicit office option. Ordinary Visit Only stops must
not force an empty stock request. The original functions reproduced both reported failures offline:
default-off/empty extra goods still generated a pool, and preparing a cancelled empty context raised
`Approve the shared existing-stock request before starting the route`.

`Allow Sales from Existing Lorry Stock` is a new default-off Check on the normal Delivery Trip form.
Extra goods still create a real shared loading request independently of that checkbox. Explicitly
enabled existing-stock sales retain Profile approval and lorry/route checks. An already-generated
active request is not discarded merely by reading an older Trip with the new option unset; started
route hashes retain compatibility when the option is absent/zero. Office request regeneration and
replacement still use existing permissions, source guards and audit.

A cancelled empty pool is ignored only when its header has no quantities/commitments, active
visit/session/pack/review, unresolved Exception or active Route Sheet; there must also be no
Manifest, Session, active reservation, executing visit or noncancelled Loose Tag behind the header.
Completed/cancelled Sheet and resolved Exception references remain valid history. Native document
read and Trip/Company ownership checks still apply. Plans with real goods or activity remain blocked
with a recovery diagnostic. Required customer loading, source authorization, driver action permission
and operational Sheet approval are unchanged.

The same check governs optional-sale projection, departure snapshot/vehicle binding and the office
unused-request save path. An unused cancelled Plan is not rebound, approved, recreated or mutated;
its old lorry cannot conflict with the actual customer load. Its Trip reference, reason, actor,
visits and released reservation audit remain intact during departure. A safe pre-execution Generate /
Refresh may clear the obsolete link; records remain linked back to their office Trip. Cancelling the
last optional visit retains its existing pool and skipped history for reconciliation.

Changed files for this correction:

- `cfg_kanban/services/trip_dispatch.py`
- `cfg_kanban/services/trip_sales.py`
- `cfg_kanban/services/driver_routes.py`
- `cfg_kanban/services/driver_route_actions.py`
- `cfg_kanban/services/delivery_trips.py`
- `cfg_kanban/cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.json`
- `cfg_kanban/cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js`
- `cfg_kanban/tests/test_trip_dispatch.py` — shared-pool fixture explicitly opts into sales.
- `cfg_kanban/tests/test_optional_route_pool.py`
- `cfg_kanban/tests/test_office_delivery_trip_ui.cjs`
- `docs/USER_GUIDE_OFFICE_DELIVERY_TRIP.md`
- `docs/USER_MANUAL.md`
- This test document.

Offline verification: **406 Python tests passed**, including 19 new optional-pool cases and the
pending 17 ad hoc SO cases. Coverage includes generation, office save, cancellation, loaded mixed
customer departure, view/lorry projection, repeated Start Route, no-sale completion, unchanged
Plan/visit/released-audit/stock snapshots, approval and operator denials, and refusal to hide real
stock or unfinished records. Existing dispatch, consolidated, driver, trip scope/sales, handover,
continuation and schema regressions passed. **132 Node tests passed** across office, consolidated
and driver view/action suites. No site or live document was accessed.

Migration: the owner must run the normal CFG update, **site migrate**, asset build, cache clear and
Desk reload to add/show the checkbox. No ERPNext/Frappe upgrade is needed. There is no stock
backfill, Plan cancellation, header rewrite or audit cleanup during migration. Older active requests
remain subject to their saved approval/stock policy; no live request is automatically approved.

All native-site cases above remain **Not run**. In particular, verify the real cancelled-empty case,
Company/driver permissions, approval policies, MariaDB current reads/rollback/concurrent start,
native Desk checkbox behavior and unchanged ERP/tag balances after the owner deploys. Offline
document/DB/RPC doubles are not native ERPNext acceptance.

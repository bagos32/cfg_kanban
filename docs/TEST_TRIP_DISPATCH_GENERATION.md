# Trip-driven Dispatch and shared Open Route acceptance

Development prepared 21 November 2026 above `bc1a493`. No deployment/site acceptance is claimed.
All native-site cases below are **Not run**. Record deployed Git revision, documents, actor,
expected/actual quantities and evidence after owner-managed migration/build.

## Setup

- Use a test Company, active route template, Driver Employee, configured source/lorry Warehouses
  and permitted terminal/native Desk users. Do not reuse production deliveries for acceptance.
- Template/Trip: enable **Generate Dispatch on Mark Planned**, select Customer Order and Shared
  Open Route **Vehicle Delivery** Profiles with matching Company/source and valid Dispatch Cards.
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
| Save Draft then Mark Planned | One Customer Order Plan per SO + stop with exact SO Item/quantity; one shared Open Route Plan and exact native visits | Not run |
| Existing lorry stock only | Empty extra-goods table creates controlled request, no Manifest/Stock Entry/reservation; approval + actual lorry needed for Ready for Fulfilment | Not run |
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

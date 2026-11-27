# Acceptance: lorry visibility, route templates and Logistics floor

Implementation is local development. **Native/site acceptance: Not run.**

## Accepted requirements and boundaries

Source: the owner's six reported issues and follow-up answers on 20 November 2026.

1. Lorry scans must show stock after loading dispatch completes, not just open movements.
2. Assigned customers/routes must remain readable after receipt into the lorry.
3. Drivers need a customer/address/sequence reference before any Customer Site QR scan.
4. Kanban Floor must show upcoming dispatch preparation and ready loads for lorries.
5. Customer sequences must be reusable templates selectable from the operating Card workflow.
6. Supervisors must be able to drag/reorder before approval, with scanner/touch alternatives.
7. Setup supports both separate per-Plan and combined lorry-trip sequences. The owner selected
   combined sequence for the current workflow while retaining the setup option.
8. Supervisor-controlled setup decides whether a Customer Site QR is enforced or an assigned-stop
   selection and explicit confirmation is sufficient.

ERPNext owns stock, allocations post through the existing customer-delivery services, and proof/
E5 remain authoritative. A route is company-specific, does not merge Companies or native customer
Delivery Notes, and does not optimize roads/distances. Multi-day trips do not close at midnight.
Historical Plans are not rewritten to relax their captured policy. The separate L1 transfer gate
remains open; this extension cannot establish production acceptance of L1 or the E5 roadmap.

## Setup and evidence prerequisites

Use [the operator/setup guide](USER_GUIDE_LORRY_ROUTES_AND_FLOOR.md). Deploy to the isolated test
site using the owner's manual Git/migrate/build process. Record the deployed revision below.
Use one Company, one source Warehouse, two company-specific lorry Warehouses, at least three
Customer Sites/addresses, a Customer Order Plan and an Open Route Stock Plan. Include tagged and
untagged stock, a Batch, expiry/certificate identity, an overnight/older load, two drivers, a
restricted operator and a Supervisor. Test native user-permission restrictions independently from
Kanban responsibilities.

## Site checklist

| Test | Expected result | Recorded evidence |
| --- | --- | --- |
| Complete E3 loading then re-scan lorry | Submitted ERP stock remains visible even though the loading Manifest is Received and absent from open movements | Not run |
| Partial delivery from lorry | Current ERP balance falls only on submitted native posting; loaded quantity remains separately labelled history | Not run |
| Tagged/untagged/operational identities | Tags cover part of ERP stock without adding it twice; untagged remainder, UOM, Batch, certificate/expiry and container identity are readable; variance is explicit | Not run |
| Company and Item permissions | Wrong-Company card/Plan/Site rejected; restricted Items/warehouses hidden without leaking customer stock | Not run |
| No active Plan but stock remains | Earlier/settled stock is still visible; no customer commitment is invented | Not run |
| Lorry/Plan live refresh | Stock Entry/DN/tag changes refresh the selected view; manual refresh re-reads it; stale responses do not overwrite a newer context | Not run |
| Floor setup without workstations | Logistics and Delivery shows preparation, ready loads and assigned lorries; production workstation modes retain their behaviour | Not run |
| Source and single-lorry floor scope | Company/source/vehicle filters and fixed-destination rules exclude unrelated work; overflow count is visible | Not run |
| Stock/Sales terminal roles | Logistics profiles accessible; Stock/Sales-only user cannot open a production supervisor queue | Not run |
| Template and captured revision | Company/Site validity enforced; reordering increments revision; existing Plan/Sheet snapshots unchanged | Not run |
| Template selection on Dispatch Card | Default visible; another permitted active Company template can be selected and captured | Not run |
| Ambiguous source Plans | Operator/Supervisor explicitly assigns the exact Plan; every active member represented; no stock origin guessed | Not run |
| Supervisor drag and approval | Draft order changes through drag, touch arrows and scanner arrows; non-Supervisor/approved route edits rejected | Not run |
| Both route scopes | Per Dispatch Plan and Combined Lorry Trip work; multiple scope choices require numbered selection | Not run |
| Planned/flexible and differing policies | Planned next stop enforced across Plans; Flexible permits assigned choice; strictest combined policy is visible | Not run |
| QR enforcement vs selection | Required QR blocks missing/wrong scans; permitted selection starts exact assigned Site without an invented physical scan | Not run |
| Known and Open Route engines | Known load reuses exact prepared quantities; Open Route allocates actual quantities; native Sales Order/rate/UOM, stock and proof gates remain | Not run |
| Proof and cancellation | Delivered/Invoiced without completed proof cannot advance; cancelled Open Route visit follows its controlled replacement; ownership respected | Not run |
| Existing reasoned Open Route exception | Only policy-enabled, reasoned approval permits that Open Route stop out of order; no approved sequence rewrite or proof bypass | Not run |
| Two/three-day trip | Same route/stock remains visible across midnight and overnight; no auto-reset/release | Not run |
| Route close and leftovers | Close Route validates posted delivery/proof and Plan-only balances, settling all members atomically; unresolved leftovers retain E5. One current lorry count can back multiple pre-opened Reviews. Unvisited settled stops retain their outcome. See TEST_DISPATCH_DOCUMENT_CLOSURE.md. | Not run |
| Concurrent requests | Two tabs/drivers/Supervisors, delivery start vs route approval/read, E3 claim and E5/proof feedback; one active scope, no duplicate stock/Session/receipt | Not run |
| Lost response and refresh/reopen | Original action/payload/token retained; recorded read-back reopens it; Not Recorded alone stays locked; reasoned void blocks late execution | Not run |
| Native transaction failure | Failed approval/start rolls back all related records; exact replay returns original outcome before mutable gates | Not run |
| Scanner-only kiosk | Open, exact numbered template/stop/Plan, paging, reorder, reason, confirm/cancel/reconcile through completion without mouse/keyboard | Not run |
| Tablet camera/touch | Camera handles one scan, late callbacks ignored, arrows work, focus returns after success/error/cancel; real drag behaviour assessed on supported devices | Not run |
| Print/Desk records | New DocTypes migrate, readable naming/links/permissions, snapshots/history and command-label printing work with deployed Frappe/ERPNext | Not run |

## Offline verification

Results against the local implementation above base commit `d59648e` on 20 November 2026:

- **364 Python tests passed** across Route Sheets, lorry/floor views, E3, E4A/E4B/E4C,
  E5A/E5B1, stock identity, direct returns, DocType schema and live refresh.
- **252 JavaScript UI checks passed** across the new route/lorry/floor controls and the
  existing dispatch quantities, prepared/open-route/warehouse delivery, E5 review/recovery,
  container repack, isolation and direct-return controls.
- Source/schema checks and `git diff --check` passed.

Tests exercise actual service/controller functions and UI adapters with dependency/database
substitutes. They include configured delivery-entry scope locking before Plan locking, proof/order
controls, replay/void handling and stale-view guards. They do not establish native schema migration,
transaction isolation/rollback, concurrent database locks, permissions, PDF output, media, or real
scanner/tablet behaviour. No development-server or live-site behaviour was verified.

The existing `cfg_kanban.tests.test_logistics_foundation` module could not be imported locally:
`ModuleNotFoundError: No module named 'frappe'`. Its native/Frappe-environment run remains pending;
it must not be counted as passed or as a recorded site acceptance.

## Recorded acceptance

### Legacy Route Sheet cancellation recovery — site checks pending

Use isolated legacy Sheets with both per-Plan and combined lorry scopes. After deploying/migrating
the correction, record actual IDs and the deployed Git revision below. All cases are **Not run on
site**; local service/UI tests do not verify database locking/rollback, real scanners or live ERP.

| Case | Required result | Site result |
| --- | --- | --- |
| Never started | Supervisor reason/Confirm cancels Sheet and skips planned visits; no stock movement/reservation release or fake delivery | Not run |
| Started old Sheet | Stop/Cancel enters Cancellation Pending, retains links and request audit; new visits blocked through Sheet and direct known/Open Route APIs | Not run |
| Open/draft/posted delivery | Open Deliveries opens the exact Session; resolve draft/allocation or complete posted delivery/proof through existing controls; no financial/ERP reversal from Sheet action | Not run |
| E5 recovery | Numbered E5 Plan Reviews opens original Plan; actual D3 count/return/transfer or stock-stays disposition settles it; Overnight does not finalize | Not run |
| Already settled | An older started Sheet cancels without active-candidate lookup; completed visits, documents and proof stay intact | Not run |
| Mixed / stale state | Every original Plan must settle; open Session, proof, active visit or unsettled member keeps cancellation pending with visible blocker | Not run |
| New lorry loads | Cancelling historical Sheet does not add newer Plans, clear newer scope/pointers, release their reservations or change their quantities | Not run |
| Office Trip | Active Delivery Trip directs to existing customer-stop cancellation and Trip closure; terminal Trip permits historical Sheet cleanup | Not run |
| Revision / permissions | Wrong parent/scope/row identities, changed revision, non-Supervisor, missing reason and Company/Plan/Sheet/Warehouse read denial reject without partial mutation | Not run |
| Concurrent / lost response | Proof/E5 vs stop/finalize, concurrent new visits and a newer lorry Sheet retain correct ownership; no deadlocks/duplicates; original token replays and Refresh reads outcome | Not run |
| Kiosk / tablet | Cancel command, reason, Confirm, numbered Session/Plan choice, E5 recovery and finalization work; camera/touch supported and focus restored after errors/cancel/handoff | Not run |

Local verification on 23 November 2026, working changes above `8f44741`: **691 Python tests
passed**, with 5 native Frappe naming tests skipped because Frappe is unavailable; **241 Node test
entries passed**, including the Route Sheet adapter's 22 scanner/controller checks. The Python
run includes 48 Route Sheet/scope tests and the existing E3/E4/E5/office-Trip/return/printing suites.
Syntax/JSON and patch whitespace checks passed. These results use offline dependency/database/UI
substitutes and do not establish site acceptance, native migration, transaction concurrency or
physical scanner/tablet behaviour.

- Local regression evidence: run `cfg_kanban.tests.test_route_sheets` and
  `cfg_kanban/tests/test_route_sheet_ui.cjs`, plus dispatch/E5/office-trip/customer-delivery suites.
- Deployed recovery revision, Sheet/Plan/Session/DN/proof/review/count/Stock Entry IDs and result:

- Deployed Git revision:
- Site / isolation / restore reference:
- Test date, terminal user and operator/Supervisor:
- Warehouse cards, template revisions, Plans, Route Sheets:
- Native Stock Entries, Delivery Notes, proof and E5/D3 records:
- Failed cases and accepted/deferred exceptions:
- Acceptance decision:

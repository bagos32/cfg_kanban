# CFG Kanban Dispatch Planning Baseline

**Baseline identifier:** `CFG-DISPATCH-E3`
**Decision status:** Locked
**Current status:** E1–E3 implemented; E4A/E4B/E4C, E5A, E5B1 and E5B2 development implemented; follow-on recovery Plans/reassignment and wider native hardening remain pending
**Implementation status:** Dispatch Profiles, permanent Dispatch Operations cards, the read-only
operator launcher, Dispatch Plans, approval/cancellation, controlled tagged/untagged reservation,
late lorry claim, physical loading confirmation, Manifest generation and controlled direct Material
Transfer are implemented. E4A adds whole-load known-customer fulfilment through the existing
Customer Delivery Session, tagged/untagged allocations, native Delivery Note and proof workflow.
E4B adds Open Route multi-customer Stops, configurable flexible/planned order, controlled stock
origins, partial quantity containers and persisted action reconciliation. E4C adds direct warehouse
fulfilment/pickup with reservation handoff and configurable attended acknowledgement. E4A/E4B/E4C
live acceptance is pending; E3 loading remains a separate lifecycle. E5A adds guarded Plan reviews,
D3 count/evidence linkage and both overnight choices. E5B1 adds whole-remainder recovery and E5B2 adds per-item destinations/retention and Trip Handover
(see later extensions). Follow-on recovery Plans/reassignment and wider native hardening remain
pending; implementation is not acceptance of the whole E5 roadmap.

## 1. Objective

Keep warehouse operators, drivers, and supervisors inside CFG Kanban while ERPNext remains the
system of record. Operators must not need to understand or open native Stock Entries, Delivery
Notes, or other ERP documents during normal floor work.

The solution must support:

1. known customer and quantity with the lorry assigned later;
2. unknown customers with a total route-stock quantity prepared in advance;
3. direct customer delivery or pickup from a Sales Company warehouse without a lorry;
4. existing ad-hoc customer delivery from stock already held in a lorry warehouse;
5. tagged, untagged, and mixed stock;
6. optional Goods-in-Transit routing when the final destination is genuinely unknown after
   physical dispatch;
7. end-of-route stock reconciliation and controlled recovery.

## 2. Central design decision

Introduce one user-facing **CFG Kanban Dispatch Plan** rather than separate unrelated planning
systems.

The Dispatch Plan authorises and reserves stock. It does not itself move ERP stock. Existing CFG
Kanban Movement Manifests, Handling Units, Customer Delivery Sessions, Delivery Allocations,
Delivery Notes, delivery proof, and Route Reconciliation remain the execution and audit records.

Two initial Plan Types are required:

| Plan Type | Customer required at planning | Purpose |
|---|---:|---|
| Customer Order | Yes | Reserve and prepare a known customer requirement before vehicle assignment |
| Open Route Stock | No | Prepare a general quantity for mobile/route sales to customers identified later |

## 3. Fulfilment modes

| Fulfilment Mode | ERP chronology |
|---|---|
| Vehicle Delivery | Sales Warehouse → Material Transfer → Company-specific Lorry Warehouse → Delivery Note |
| Direct Warehouse Delivery | Sales Warehouse → Delivery Note |
| Customer Pickup | Sales/Pickup Warehouse → Delivery Note plus pickup acknowledgement |
| Existing Ad-hoc Lorry Delivery | Existing Lorry Warehouse stock → Customer Delivery Session → Delivery Note |
| Goods in Transit | Source → Transit Warehouse → destination selected at receipt → final Warehouse |

Goods in Transit is optional and should follow the primary packages. It is justified only when
goods physically depart before the destination Warehouse is known.

Direct delivery must use a Warehouse belonging to the Selling Company. If stock remains owned by a
Manufacturing Company, the intercompany handover must complete into a Sales Company Warehouse
before customer delivery. Two Company-specific Warehouses may represent the same physical factory.

## 4. One-card operator experience

Extend the existing permanent Location Card with a **Dispatch Operations** purpose. One permanent
Dispatch Point Card identifies the operating context:

- Company;
- source Warehouse;
- physical dispatch point;
- available manager-controlled Dispatch Profiles.

The operator selects the business work, not the technical ERP method:

```text
Scan operator
  → Scan Dispatch Point Card
  → View prioritised eligible work
  → Scan/select the work context
  → System resolves the Dispatch Profile
  → Show only necessary data capture
  → Review and activate
```

Automatic resolution rules:

| Scanned context | Action |
|---|---|
| Existing Dispatch Plan | Resume that Plan |
| Sales Order | Use the eligible Customer Order Profile |
| Customer Site | Use eligible Direct Delivery, Pickup, or prepared Customer Plan |
| Route code | Use the eligible Open Route Stock Profile |
| Lorry Warehouse card | Show prepared loads eligible for that vehicle |
| Stock Tag | Show eligible active preparation/load work for the Item |
| No second scan | Show authorised preset work queue |

If exactly one workflow is eligible, open it automatically. When more than one is valid, show a
small business-language choice rather than ERP document names or technical routing modes.

## 5. Dispatch Profiles

Add a manager-controlled **CFG Kanban Dispatch Profile** containing:

- business-facing label, instructions, colour, priority, and active state;
- Company and Dispatch Point/source Warehouse;
- Plan Type and Fulfilment Mode;
- permitted route, territory, Customer Site, or destination scope;
- staging Warehouse and Goods-in-Transit Warehouse where applicable;
- destination assignment policy: Fixed, Select Before Dispatch, or Select at Receipt;
- tag policy: tagged, untagged, or mixed;
- FIFO/FEFO suggestion policy;
- approval and supervisor-override policy;
- ERP auto-submit policies;
- proof policy and responsible operational roles.

The selected Profile is snapshotted into the Dispatch Plan. Later Profile edits must not alter
active or historical Plans.

## 6. Preparation and reservation

Sales or a supervisor creates the business request. The warehouse operator only prepares it.

### Known customer

Capture Customer Site or optional Sales Order, Item/quantity, required date, and priority. Vehicle
assignment is not required during preparation.

### Open route stock

Capture route/territory, trip date, Item/total quantity, and priority. Customer and vehicle are not
required. Example: prepare 100 pieces for route sales, then allocate actual quantities to individual
customers during the trip.

Tagged stock reserves exact Handling Units. Untagged stock reserves Company, Warehouse, Item,
optional Batch, UOM, and quantity. Mixed Plans may use both. Reservation changes Kanban available
quantity but does not post ERP stock movement.

Suggested preparation states:

```text
Draft → Awaiting Approval → Approved → Picking → Ready for Vehicle
```

Cancellation before loading releases every active reservation while preserving audit history.

## 7. Late vehicle assignment

The warehouse operator is not required to know the lorry. A driver scans the Company-specific lorry
Warehouse card and sees **Loads Awaiting Vehicle Assignment**.

The driver claims one prepared Plan. The claim must be atomic so two drivers cannot claim the same
load. After assignment, the operator scans/verifies the physically loaded stock and confirms
loading. The backend creates the controlled ERPNext Material Transfer without exposing the native
Stock Entry UI.

Preferred mode:

```text
Prepared, destination unassigned
  → driver claims with Lorry Card
  → destination Warehouse locked
  → one Material Transfer from source/staging to lorry
```

After ERP submission, destination reassignment is prohibited. Correction requires controlled
cancellation or reverse movement.

## 8. Customer delivery

For a Customer Order Plan, scanning the Customer Site retrieves the prepared delivery. For Open
Route Stock, the driver scans each Customer Site and allocates the actual quantity from current
lorry stock. Each customer receives a separate Delivery Note and proof record.

A genuinely unknown Customer cannot receive a compliant Delivery Note. The operator must scan or
select an existing Customer Site, use an approved walk-in Customer policy, or request authorised
Customer creation. Drivers must not freely type accounting Customer identities or prices.

## 9. Route reconciliation

The system must reconcile:

```text
opening lorry load
  - submitted customer Delivery Notes
  - approved damage/loss
  - returned stock
  = expected closing balance
```

Remaining stock may stay in the lorry overnight, return to a Warehouse, move to another authorised
lorry, or go on Hold for discrepancy investigation.

## 10. Minimal data model

New records:

1. **CFG Kanban Dispatch Profile** — reusable manager-controlled policy.
2. **CFG Kanban Dispatch Plan** — user-facing business authorisation and lifecycle.
3. **CFG Kanban Dispatch Plan Line** — requested Item quantities.
4. **CFG Kanban Dispatch Allocation** — exact tagged or untagged reservations.

Existing records to reuse:

- CFG Kanban Card with Dispatch Operations Location purpose;
- CFG Kanban Movement Manifest and Manifest Line;
- CFG Kanban Handling Unit and quantity ledger;
- Warehouse/lorry cards and Customer Scan Points;
- CFG Kanban Delivery Session and Delivery Allocation;
- ERPNext Stock Entry and Delivery Note through the ERP gateway;
- CFG Kanban Delivery Proof and Route Reconciliation.

No additional physical card is mandatory beyond the Dispatch Point, Stock Tag, Warehouse/Lorry,
and Customer Site cards already in the architecture.

## 11. Guardrails

- ERPNext submission remains the stock system-of-record event.
- Operators remain in CFG Kanban panels during normal work.
- Company, source Warehouse, document type, price, and posting policy come from the Profile.
- Wrong-Company tags, Warehouses, vehicles, and Customers are rejected.
- One quantity cannot be actively reserved by two Plans.
- One prepared load cannot be claimed by two vehicles.
- Every activation and override is idempotent and audited.
- Supervisor override requires authority and a reason.
- Cancellation releases reservations but never deletes history.
- ERP mandatory fields are supplied by presets; the panel requests only genuinely missing
  operational values.

## 12. Approved implementation sequence

### E1 — Profiles and one-card launcher — implemented

- Dispatch Profiles;
- Dispatch Operations Location Card purpose and print behaviour;
- prioritised queue and automatic Profile resolution;
- no stock movement in this package.

### E2 — Plans and preparation — implemented

- Customer Order and Open Route Stock Plans;
- approval/cancellation;
- tagged, untagged, and mixed reservations;
- preparation state through Ready for Vehicle;
- immutable Profile revision snapshot, idempotent creation/reservation and release audit;
- no staging Stock Entry, vehicle assignment, Manifest, or ERP posting in this package.

### E3 — Vehicle claim and loading — implemented

- last-minute lorry assignment;
- atomic claim;
- Manifest generation;
- controlled ERP Material Transfer.

E3 supports Vehicle Delivery through an active same-Company Direct Internal Warehouse Transfer
route. A Company-specific lorry Warehouse card claims one fully reserved Plan atomically. Tagged
lines require exact reserved-tag loading scans; untagged lines require explicit physical-pick
confirmation. Cancellation before ERP posting releases the vehicle claim while retaining the E2
reservations and audit. Goods in Transit remains E6.

### E4 — Customer fulfilment

**E4A — Prepared known-customer Vehicle Delivery:** development implemented for tagged,
untagged and Mixed loaded stock. The scanned Customer Site must match the immutable Plan context;
loading must have a submitted Stock Entry. The driver reuses exact loaded quantities, then completes
the existing allocation confirmation, Delivery Note and proof workflow. Plan Customer Fulfilment is
independent from E3 Loaded. Reservations/replay, source identity, Batch/expiry, native Sales Order
UOM/rate/context, pre-ERP reset and existing DN/proof reversal guards are enforced. Individual
prepared allocations must fit one native Sales Order row; partial/refused fulfilment requires E5.

On 19 November 2026 the owner confirmed successful site use of last-minute vehicle selection and
lorry loading, and requested E4A with tagged and untagged quantities. Full E3 evidence remains
pending as recorded in its test guide. See [E4A setup/operator guide](USER_GUIDE_DISPATCH_E4A.md) and
[E4A acceptance test](TEST_DISPATCH_E4A_CUSTOMER_FULFILMENT.md). This development checkpoint is not
live ERP, concurrency, kiosk or production acceptance.

**E4B — Open Route Stock customer visits:** development implemented. Both **Flexible Order** and
**Planned Order** are configurable during Profile setup and copied to each Plan, as requested by
the owner on 19 November 2026. Planned and actual sequences, reasoned Supervisor approvals/skips,
separate Customer Sessions/Delivery Notes/proof, prepared and unassigned tagged/untagged origins,
partial posted-stock quantity containers, full mixed logistics containers and persistent retry/
read-back/no-record cancellation controls reuse the existing delivery services. Routine delivery
records do not settle or release the route; that remains E5. Direct/ad-hoc legacy delivery remains
available independently. See [E4B guide](USER_GUIDE_DISPATCH_E4B.md) and
[E4B acceptance test](TEST_DISPATCH_E4B_OPEN_ROUTE.md).

**E4C — Direct Warehouse Delivery and Customer Pickup:** development implemented on 20 November
2026. Customer Order Plans use the selling-company source Warehouse without a vehicle claim,
Manifest or Stock Entry. Fully prepared tagged/untagged reservations hand off atomically to the
existing Customer Delivery Session; exact source/quantity, native Sales Order, Delivery Note and
proof controls are reused. Readiness is Ready for Fulfilment; ERP submission posts quantities and
required proof/acknowledgement closes the Plan. The owner requested setup options for recipient
name, signature, or both; the captured Pickup Acknowledgement requirement adds to Customer Site
evidence and always requires an attended pickup. Early correction uses release-all, empty-session
cancellation and explicit re-preparation. Scanner/camera actions include confirmation, required ERP
scalar/table inputs and acknowledgement. See [E4C guide](USER_GUIDE_DISPATCH_E4C.md) and
[E4C live acceptance checklist](TEST_DISPATCH_E4C_WAREHOUSE_FULFILMENT.md). Offline checks do not
establish native transaction, ERP, media or kiosk acceptance.

### E5 — Reconciliation and recovery

**E5A — Dispatch trip review/settlement:** development implemented on 20 November 2026. The owner
explicitly authorized this work above the pending E4C change set. Review freezes new fulfilment,
preserves prepared-stock snapshots, separates extra unassigned deliveries, links the existing D3
balanced count and validates exact submitted return/transfer evidence. Original vehicle/loading
history stays unchanged. Holds, guarded Resume, evidence reuse/cancellation protection, source and
count freshness, retry guards and scanner/camera controls are included.

The owner specified both overnight choices at closing: release old Plan commitments while stock
stays in the lorry, or retain the same Plan until explicit Resume. Normal long-distance trips use
one Plan for two to three days with separate Customer Sessions and final reconciliation at the
actual trip end. Trip Date is the planned departure date; no forced daily closure/reset is added.
An optional formal overnight pause requires its balanced count and explicit next-day Resume.
See [E5A guide](USER_GUIDE_DISPATCH_E5A.md) and
[E5A acceptance checklist](TEST_DISPATCH_E5A_RECONCILIATION.md). Native/live acceptance is pending.

**E5B1 — Guided return/transfer creation:** development implemented on 20 November 2026 above
`5116653`. From an active Dispatch Review, a Supervisor explicitly selects an approved same-Company
Direct Transfer route from the original lorry, confirms every tagged/container or exact loose
Item/Batch/stock-UOM source, prepares and creates/posts the existing Movement Manifest Stock Entry.
One recovery covers all remaining prepared allocations to one destination. Native feedback preserves
certificates/expiry and original E3 loading/vehicle/allocation links; a fresh balanced D3 count and
E5A settlement are still required. Current reads protect competing loose commitments; guarded
replay/reopen, unused cancellation, saved-Draft validation/delete protection and scanner/camera/
mandatory ERP-input controls are included. See [E5B1 guide](USER_GUIDE_DISPATCH_E5B1.md) and
[acceptance checklist](TEST_DISPATCH_E5B1_RECOVERY.md). Native/live acceptance is pending.

**E5B2** below implements mixed per-line/multiple-destination leftover dispositions. Driver partial/
refused fulfilment is covered by the later Driver Route extension. **Remaining E5B:** follow-on
recovery Plans/vehicle reassignment and native operational hardening. E5B1 creates no quantity correction, write-off, credit or replacement delivery engine.

### Optional E6 — Destination selected at receipt

- Goods-in-Transit-only dynamic destination;
- second controlled Stock Entry from transit to the selected destination;
- implement only after E1–E5 pass end-to-end testing.

## 13. Resume instructions

When this work is resumed, first audit the current repository against this document and the latest
`docs/MULTI_COMPANY_LOGISTICS_ARCHITECTURE.md`. Do not rebuild Dispatch Profiles, Dispatch Plans,
reservation, existing Manifest, Customer Delivery, proof, tag, or reconciliation features. Begin
E4 only after the E3 acceptance test passes. The owner-reported E3 path and authorization to
proceed with E4A on 19 November 2026 are recorded above; unreported acceptance cases remain pending. Keep production execution behaviour separate, add
regression tests, and stop for user-managed commit/deployment before each later package.


## 14. Lorry visibility and approved customer trip sequences — local extension

On 20 November 2026 the owner requested persistent lorry stock/customer visibility after E3,
a logistics loading floor, selectable customer sequence templates and Supervisor drag/reordering
before approval. The accepted setup supports **Per Dispatch Plan** and **Combined Lorry Trip**;
the current requested workflow is **one combined sequence per lorry trip** across known-customer
and Open Route Stock Plans. **Require Customer Site QR** versus **Allow Assigned Stop Selection**
is a Supervisor-controlled setup option. Existing QR enforcement remains the default.

Local development now includes:

- current posted ERP Item/Batch/UOM balance with tag coverage, untagged remainder and identity
  variance, independent of whether a loading Manifest has finished;
- assigned loaded Plans, customer/address/stop details and active approved Route Sheets on lorry
  Warehouse cards, plus preparation/ready/assigned loading work on the Logistics and Delivery floor;
- versioned Company-specific Customer Site templates selectable while creating a Plan;
- explicit source-Plan assignment, Supervisor draft drag/touch/scanner reordering, immutable approved
  order and template snapshots, numbered choices and optional enforced Site QR at delivery;
- one active combined sequence per Company-specific lorry Warehouse, strictest member verification/
  order policy, actual visit ordering, proof barriers, stable retries/read-back/void and E5 closure.

Legacy Route Sheet recovery now adds Supervisor **Stop / Cancel Route → Cancellation Pending →
Finish Route Cancellation**. It freezes further visits, exposes the original Plans' Session/E5
blockers and finalizes after all original Plans are Reconciled/Settled. Never-started sheets retain
immediate cancellation. Historical teardown uses frozen membership, not current lorry candidate
loads, and preserves posted deliveries and stock history. Active office Delivery Trips retain
their own stop-cancellation/closure authority. Offline coverage is separate from site acceptance;
see the recovery checklist in `TEST_LORRY_ROUTES_AND_FLOOR.md`.

This extends the existing E4A/E4B customer-delivery and E5 review engines; it does not merge several
Plans into one Delivery Note, combine Company ownership, optimize routes, infer customers for old
stock or reset two/three-day trips at midnight. Templates/approval may be used per Plan as well.
Legacy Plans retain their captured policy. Every member must be physically Loaded before saving
or approving its trip Sheet; E5 settlement remains required before final Sheet closure.

See [the setup/operator guide](USER_GUIDE_LORRY_ROUTES_AND_FLOOR.md) and
[the requirements and acceptance record](TEST_LORRY_ROUTES_AND_FLOOR.md). Offline verification is
recorded there. Native migration, ERP/concurrency/permission and device acceptance are **Not run**;
the separate L1 gate and outstanding E5B scope above remain open.


## 15. Office Delivery Trip — approved Phase 1 extension

On 21 November 2026 the owner approved a normal office DocType page, reusable route template,
SO route inbox and LIFO loading instructions. A route is a reusable customer/region/direction
itinerary; its dated trip is separate from warehouse-to-lorry dispatch authorization. “PO” means
the customer PO reference on a Sales Order. Selecting a route puts the SO in its order inbox;
the office chooses the dated trip explicitly.

Local development includes Company-checked route selection on Sales Orders, template region/
direction/policy and Delivery/Visit Only stops, native **CFG Kanban Delivery Trip** forms, exact
SO row/stock-UOM planning quantities and stable stop assignments, optional lorry/source/driver,
multi-day dates, revision snapshots, linked existing Customer Order Vehicle Delivery Plans and
a derived reverse-stop loading list of tagged/untagged allocations and unprepared quantities.
Saved Draft and Planned assignments hold planning capacity; submitted linked native DNs reduce
outstanding commitments. Native stock remains outside this planning record. Closed/Cancelled
planning history cannot be deleted/reopened; source execution freezes the office snapshot.

This extension does not create another stock or delivery engine. Existing E3 confirmation,
Manifest posting, FEFO/FIFO/certificate checks, approved Route Sheets, E4 delivery/proof and E5
reconciliation continue. No automatic office-trip-to-driver-route publication, enforced LIFO scan
order, driver terminal, live sequence override, map/GPS, printer subsystem or new QC-return queue
is claimed in Phase 1. Legacy execution templates omit the new Visit Only rows.

See [office setup guide](USER_GUIDE_OFFICE_DELIVERY_TRIP.md) and
[Phase 1 acceptance record](TEST_OFFICE_DELIVERY_TRIP_PHASE1.md). Implementation and offline
verification are separate from native-site acceptance, which is Not run. Preserve the L1 gate,
remaining E5B scope and owner-managed commit/deployment boundary before the next package.


## 16. Driver Route view — Phase 2 visibility

On 21 November 2026 the owner requested a separate driver page linked to the office Delivery Trip,
with a trip list, next/current stop and Item/tag details. Local development above `91ab7da` adds
`kanban-driver-route`, native office/Logistics/workspace launchers, existing operator login reuse,
assigned-Employee and native Company/source read checks, camera/wedge entry, manual/automatic
refresh, source timestamps and safe operator/response handling.

The page distinguishes office assignments, prepared sources, posted loading, posted delivery and
remaining assigned load. Exact approved operational order takes precedence when the mapping is
complete; ambiguous/partial/draft mapping is visibly an office plan requiring review. An unfinished
proof keeps its current stop. Existing accessible Sessions open directly in Logistics without
creating another delivery or stock transaction. Multi-day active trips remain visible.

This package is visibility and established-session navigation. It creates no route publication,
Start Route/Complete Stop/Visit Only completion, customer skip/resequence approval, stock allocation,
DN, proof, refusal/return/QC workflow, mapping/GPS or print integration. Those remain subsequent
packages; existing E3/E4/E5 engines and native read permissions are retained.

See [Driver Route setup](USER_GUIDE_DRIVER_ROUTE.md) and
[native acceptance checklist](TEST_DRIVER_ROUTE_VIEW.md). Native migration, Desk/tablet/scanner,
MariaDB/permissions and live posting acceptance remain **Not run**.


## 17. Driver Route execution — Start Route / Complete Stop

On 21 November 2026 the owner approved direct driver-page departure and customer-stop completion
using the existing Delivery Note/proof workflow. Local development above `754708d` adds readonly
Trip departure/revision/active-lorry/snapshot fields and stop audit facts, a guided inline action
panel and persistent action receipts/reconciliation. It retains normal office DocType planning.

Departure requires Planned/assigned/authorized work, every planned physical quantity loaded into
one lorry through submitted native loading feedback, and exact required operational approval.
Starting records departure only. Complete Stop delegates to existing prepared delivery, Route
Sheet, allocation confirmation, ERP command/native DN and proof services. Mandatory ERP inputs,
Draft submission and proof remain gates. Multiple linked SO Plans retain their separate native
DN/proof records. Visit Only records an audited information visit without fake ERP documents.
Strict sequence applies if either captured Trip or Sheet requires it; active customer/proof work
must finish before another visit. Source/itinerary/approved revision snapshots cannot change
silently after departure.

Durable original-actor/payload/token handling covers unknown outcomes, reopen, browser tabs,
receipt readback and Supervisor reasoned void under the Trip lock. The first explicit rejection
permits correction; Not Recorded or an unknown retry rejection does not. Acknowledged browser
records retain identity only; binaries/presigned URLs stay outside recovery storage. Shared
private proof controls keep existing media/GPS services authoritative.

The last stop releases the driver lorry but does not settle E5. Existing Plan reconciliation/
cancellation followed by reasoned office Trip closure can finalize an unfinished driver route
as Closed Incomplete and release its lorry without marking stops delivered. New route-edit/skip
approval, maps/live tracking, simplified refusal/old-return collection/QC queues and Bluetooth
printing remain future packages. No second delivery/stock/accounting engine is introduced.

See [driver setup/use](USER_GUIDE_DRIVER_ROUTE.md) and
[execution acceptance](TEST_DRIVER_ROUTE_EXECUTION.md). Offline checks are not native migration,
transaction/concurrency, ERP posting, private-storage or tablet/scanner acceptance. Native tests
are **Not run**. Existing L1 gate and outstanding E5 scope remain separate.


## 18. Driver Route — refused quantities and old-return collection

On 21 November 2026 the owner approved direct driver-page refusal/old-return handling above
`bb22248`, including QC cases for damage/quality refusals that are still company-owned stock.
Good order reductions can be sold on the same trip under the captured Profile policy or held
for Supervisor release. Older delivered goods continue through QC before accounting/stock use.

The extension records immutable accepted/refused exact prepared-source outcomes before Session
start, reserves accepted sources in the native delivery workflow and holds refused balances.
Only accepted quantities reach native DN/proof; zero acceptance closes the audited Session with
no DN. Tagged/untagged stock, exact SO mappings and native expiry/certificate/stock controls remain.
Owned refusal QC prohibits customer credit and duplicate receipt. QC-approved Supervisor resale,
existing E5 custody transfers and exact already-submitted Material Issue disposal confirmation
provide controlled resolution. Reconciliation distinguishes delivered, held and resolved stock.
Old return intake/reuse records collection facts on existing Return Cases, retaining native QC,
accounting, disposition and private evidence services. Driver/warehouse see linked QC progress.

Normal full deliveries retain the guided confirmation flow. Quantity changes are reviewed before
recording. Durable original request/receipt/readback/void semantics also cover collections and
Supervisor release. Office DocType planning, LIFO, approved sequence and required Site QR policy
are preserved. Existing started Sessions and linked-outcome DN cancellations require supervised
reconciliation; no automatic custody-outcome reversal is claimed.

See [driver guide](USER_GUIDE_DRIVER_ROUTE.md) and
[extension acceptance](TEST_DRIVER_ROUTE_REFUSALS_RETURNS.md). This supersedes the historical
full-quantity-only boundary in section 17. No separate delivery, stock, credit or QC engine was
introduced. Native migration, ERP posting, MariaDB rollback/concurrency, print and device results
are **Not run**. Existing L1 and remaining E5 scope are unchanged.


## 19. Delivery Trip-driven dispatch and one shared optional-sale pool

Approved on 21 November 2026 above `bc1a493`: office Trip assignments generate known-customer
requests and **one shared Open Route pool per Trip**. Extra goods are office-specified; eligible
unassigned stock already on the lorry can also be sold at saved no-order customer visits.

The normal Template/Trip form controls generation, captured Profiles and extra Item/Batch stock-UOM
quantities. Mark Planned generates one Customer Order Plan per exact SO/stop, with exact SO Item
rows, plus the shared request and native visits. Requests retain existing approval; generation
reserves/posts no stock. Unused updates preserve cancelled history and active work remains guarded.
Legacy manual linking is retained without silently converting existing Trips.

Real extra goods keep E3 Manifest/submitted-transfer controls. With no extra loading quantity, an
explicit existing-stock-only Open Route request uses Ready for Fulfilment after approval/actual
lorry binding. It fabricates no load or ERP movement. Native route, allocation, DN, proof and E5
services understand this controlled context. Approved Route Sheets seed exact office visits,
including repeated Sites; Trip sequence and mandatory physical QR are not bypassed.

The driver opens an optional sale at a saved Visit Only Site, selects native prepared/unassigned
tagged/untagged lorry stock and completes native DN/proof. No-sale visits retain audited completion
without fake delivery. Main stop visibility includes actual optional-sale sources. Known-customer
commitments/QC holds remain protected and native D3/E5 settlement remains required for the pool.

This supersedes prior manual-plan-only and Visit Only informational-only boundaries. Live route
edits, maps/GPS and Bluetooth printing remain later scope. See
[setup](USER_GUIDE_OFFICE_DELIVERY_TRIP.md) and [acceptance](TEST_TRIP_DISPATCH_GENERATION.md).
Native migration, MariaDB rollback/concurrency, ERP posting and tablet results are **Not run**.


## 20. Lead and assistant drivers on one Trip

Owner-approved addition on 21 November 2026 above the pending Trip-generation development: one
lead Assigned Driver and several assistants may handle the same Trip. Office presets the list
on its normal DocType form; the lead can add an active qualified Employee from Driver Route
before departure or while In Progress. Each member signs in independently with existing delivery,
Dispatch, action-flag and native Company/source permissions. Membership grants no new authority.

The same saved itinerary/current stop, customer Session/DN/proof, shared stock pool and E5 rules
apply. Exact Trip/Company/Site/Plan checks permit a teammate to continue an existing Session;
unrelated native Sessions keep their original access rule. Each action retains its actual actor
and original retry identity; Session creators are not rewritten. Team additions serialize on the
Trip, increment team/action revisions, retain audit facts and preserve the frozen source snapshot.
Office presets cannot rewrite started team history; only the lead adds through the runtime action.

See [assistant acceptance](TEST_TRIP_TEAM.md). Native migration, database concurrency/rollback,
ERP feedback, permissions and device acceptance remain Not run.


## 21. Runtime stop order and Supervisor choice of approval scope

Owner-approved on 22 November 2026 above `dba2794`: between customer stops, a lead or assistant may
reorder unfinished Trip customers directly for Flexible Order, or submit a reasoned full proposal
for Planned Order. Enforced policy includes the Trip, mapped native Route Sheets and participating
Open Route Plans. At review the Supervisor chooses **Next Customer Only** (then prior remaining
order) or **Entire Proposed Order**. Both options are required by the latest owner clarification.

Review is inline in the existing Supervisor Centre, with operator identity, View All/Override/
Complete, captured Profile override permission, native Company/source access and immutable decision
history. Runtime order/revision is separate from frozen office/loading/Route Sheet sources.
Completed stops are fixed; active DN/proof blocks changes; stale proposals cannot be approved.
Native prepared and open-route entry points enforce the exact approved runtime target without
relaxing Site QR, stock/commitment, DN, proof, QC or E5 controls. All mutations share the Trip root
lock and original driver receipt/retry controls. Pending request uniqueness and retained terminal
history support cancellation/rejection/supersession and uncertain-result reconciliation.

This supersedes the earlier no-live-order-edit boundary. Customer stop removal, maps/GPS pins/
tracking, thermal printing and the remaining separately documented E5 scope remain later packages.
The pending Dispatch Control icon and Kanban Card breadcrumb corrections stay in the same planned
commit. No commit/push/deploy is performed by this development step.

See [driver setup](USER_GUIDE_DRIVER_ROUTE.md) and [acceptance](TEST_DRIVER_ROUTE_SEQUENCE.md).
Offline implementation checks are distinct from native-site acceptance, currently **Not run**.


## 22. Customer Site pins and next-stop map directions

Owner-approved on 22 November 2026 above `eb4d977`: maintain one optional delivery-entrance pin
on the normal Customer Site form and show the authorized Trip's numbered pins/status on Driver
Route, with Google Maps/Waze directions to its effective current/next stop. Shared/repeated
coordinates keep separate exact visit choices. The existing next-stop, sequence-approval and
DN/proof owners remain authoritative; map interactions view information or launch directions.

Pins are validated/canonicalized single-point GeoJSON on Site save. Ordinary Site read/write and
Company/customer/address checks remain in force. Driver projection returns only finite coordinates
and pin status, never arbitrary URLs or map properties. Missing/invalid pins keep legacy delivery
working and use clearly labelled address search; no destination is invented. Office pin corrections
refresh on active Trips without altering frozen itinerary/load/stock/approval/history sources.

Use local native Leaflet assets and Frappe map defaults for pins; official universal Google/Waze
URLs need no Google API key and omit operator/Trip/order references. No CFG driver GPS capture,
watching, tracking, geocoding, route optimization or automatic delivery/QR/proof confirmation is
introduced. Viewport, stale/identity/hide, asynchronous map load, missing pins and asset/tile
failures are handled independently of delivery actions. Returning from maps passively refreshes
current route data. Existing media/GPS proof controls are unchanged.

This supersedes the earlier customer-pin/direction deferral. Live vehicle/supervisor tracking,
stop removal/recovery and thermal printing remain separately scoped later packages. See
[setup](USER_GUIDE_DRIVER_ROUTE.md#customer-pins-and-directions) and
[acceptance](TEST_DRIVER_ROUTE_MAPS.md). Native migration, permissions, real map tiles and
mobile provider/app handoff acceptance remain **Not run**.


## 23. Foreground Trip GPS source and Supervisor Live Map

Owner-approved 22 November 2026 above `02bd4b5`: one assigned driver/assistant phone/tablet explicitly
shares the started Trip's actual lorry location. A separate normal Supervisor Page displays the
accessible active fleet and selected Trip's effective sequence, customer pins, delivery status and
actual quantities/tags using the existing driver/native delivery projection. Native manager,
Kanban Supervisor/View All/Customer Delivery and Company/Trip/lorry permissions remain required.
Multi-day Trips have no date cutoff; completed history is opt-in and never shown as live.

A 12-hour scoped device lease separates GPS publication from normal operator-action inactivity;
it cannot renew or grant delivery access. GPS source Start/release use durable Driver Action
receipts under the same Trip root lock, without changing delivery revisions. Stop is idempotent.
Source identity, monotonic sequence, capture-time and pause fences reject late/wrong-source or
changed-payload replay; duplicate/older fixes cannot refresh age. Explicit switch/revocation/Trip
end/lorry change/expiry prevents further publication. Supervisor reason/Override releases an
unavailable exact source; lost-response recovery retains the original request.

Store only each Trip's latest position and sharing-control audit, not a route trail. The raw
publishing token stays in the source tab's session storage; server stores its hash. Device requests
are foreground-only, scheduled 15 seconds after each completed attempt. Background/lock/freeze
may suspend delivery of fixes or pause messages. Show age/accuracy, stale after 90 seconds,
poor accuracy over 100 m, and grey last-known/non-live states. No source means no lorry marker.
This is not background telematics, route optimization, geofencing or automatic stop proof.

All Desk native default maps and shared Trip maps start at Kuala Lumpur [3.139,101.6869], zoom 13,
when empty; saved pins/selected real Trip points focus actual coordinates. Preserve native tiles,
attribution and manual viewport; Fit Locations/Kuala Lumpur/optional Follow Lorry are available.
This supersedes phase 22's no-GPS/supervisor-map deferral and no-pins/no-map-load behavior.
Stop removal/recovery and thermal printing remain separately scoped.

See [setup](USER_GUIDE_DRIVER_ROUTE.md#trip-gps-sharing-and-supervisor-live-map) and
[acceptance](TEST_SUPERVISOR_LIVE_MAP.md). Offline tests are implementation evidence only; native
migration, ACL, database concurrency, Leaflet/tiles, real GPS, foreground/background and mobile
acceptance are **Not run**. No commit, push or deployment is performed by this phase.


## 24. Supervisor-approved customer stop cancellation and undelivered stock custody

Owner-approved on 22 November 2026 above `b6e53ed`: **every** saved customer cancellation needs
Supervisor approval. An assigned lead/assistant requests it using the durable Driver Action lane;
a Supervisor may perform the reviewed cancellation directly. Reuse the existing Route Change
Request/Supervisor Centre and retain rejection/withdrawal/approval history. Cancellation targets
an exact unstarted visit and preserves the original SO, itinerary, departure snapshot, Route Sheet
revision and posted loading evidence. Started delivery/DN/proof/quantity history must use native
recovery first. The same Trip root lock, native permissions, source rechecks and current-goods
hash prevent stale or conflicting decisions.

The Supervisor chooses **Keep Reserved for Return** or **Release for Same-trip Sale** for loaded
undelivered goods. Hold uses the operational tag Reserve ledger plus existing prepared loose
commitments. Release records exact source quantities and removes their prepared commitment; it
never manufactures a DN/refusal/return receipt or moves stock. E5 subtracts only that recorded
release. Existing E5 recovery adopts/returns custody and restores it after unused recovery
cancellation. Overnight/Resume retains holds; an unreceived hold cannot be settled as stock-stays.
A Supervisor may detach an exact whole held physical tag from a mixed logistics container without
changing its quantity/reservation. Generic movement checks protect held loose quantities, including
native Stock Entry submission of an older draft and exact Batch availability.

Unused E2/E3 work is cancelled through existing release controls; pending ERP commands/documents
block customer cancellation. Cancelled visits are absent from active driver/map/next-stop/LIFO
preparation but retained as history. SO planning claims return to the route inbox; replacement
work uses another Trip. Visit Only cancellation skips only its exact native visit, preserving the
shared pool and other customers. Retiring the last stop ends driver execution/GPS according to
existing rules; E5 and office closure still apply.

This supersedes the earlier stop-removal deferral. No new delivery engine, native SO cancellation,
stock receipt, credit creation, route optimizer or deployment is introduced. Native acceptance is
**Not run**; see [acceptance](TEST_DRIVER_STOP_CANCELLATION.md) and
[operation](USER_GUIDE_DRIVER_ROUTE.md#cancel-a-customer-stop-safely).


## 25. Dedicated Customer Return QC worklist and follow-up visibility

Owner-requested 23 November 2026 above `2f988ba`: a separate normal **Customer Return QC** Page over
existing customer Returns, owned quality refusals, delivery corrections and historical records.
Oldest active work, all-history/terminal views, bounded pagination, common filters and native
permission-aware grouped counts replace reliance on the Logistics console's 30-recent-case list.
The existing Return Case state/QC results, parallel accounting/physical tracks, ERP feedback and
owned-refusal outcomes remain authoritative. No new return engine or transactional DocType exists.

QC responsibility (or existing unrestricted Supervisor), native Return Case/Company scope and
current operator identity apply to every monitor read. The existing Logistics recent-return
list is also changed from permission-bypassing `get_all` to permission-aware `get_list`. Start/Complete QC now also require native Case and
Company Read before mutation. Case detail/navigation exposes only permitted linked documents and
exact owned-custody lines; UOM quantities remain separate. Existing inspection/media, accounting,
physical disposition and release/recovery/disposal services perform actions. Opening the Page or
its case handoff performs no QC completion, receipt, credit, task creation or stock change.

Rejected/investigation cases and pending financial/physical follow-up remain visible; no automatic
case closure or invented SLA is added. Camera/scanner, print labels, stale/identity/page lifecycle
controls accompany the monitor. Native acceptance remains **Not run**. See
[setup](USER_GUIDE_CUSTOMER_RETURN_QC.md) and [acceptance](TEST_CUSTOMER_RETURN_QC_MONITOR.md).


## 26. Driver native-format mobile printing, invoices and custody labels

Approved scope, 23 November 2026: native ERPNext printing and signed Label Bridge v1 raster
handoff from Driver Route, normal Company profile configuration, browser/Company device
preferences, selectable ERPNext Print Formats for both paths, six 80mm presets, current lorry stock
list, and existing stock-tag reprints. The installed companion app controls Bluetooth pairing.
No runtime CDN, mandatory custom Credit Note app or second print-layout engine is introduced.

The driver may explicitly create a native non-stock Sales Invoice from a submitted DN at this
exact Trip stop. Policy is configurable, **Draft by default**. Auto-submit requires named operator
and native accounting authority. Existing drafts are reused without auto-submission; native
billing quantity, taxes, naming rules and validations remain authoritative.

Collected old-return bundles may receive quantity-bounded custody labels before QC receipt,
marked **Pending QC — not available stock**, with a distinct QR namespace opening the existing
Case/QC workflow. This does not create available stock, a Credit Note or a duplicate receipt.

Prepared print jobs retain source/format hashes and operator statements, not binary content or
signing keys. Explicit handoff and per-segment confirmation distinguish a prepared request from
physical printing. No physical ACK exists in the supplied companion protocol. Lost responses use
existing driver receipts; uncertain physical output needs an explicit reasoned retry. Native/custom
format changes invalidate resumed jobs; all long-document segments and complete copies are kept.

See `USER_GUIDE_DRIVER_PRINTING.md` / `TEST_DRIVER_MOBILE_PRINTING.md`. Development and local
browser checks are separate from migration, native accounting/concurrency and device acceptance.
Earlier historical references to printing/customer invoicing as future scope are superseded by
this section only for this approved increment. Automatic route optimization, payment collection
and other separately deferred reconciliation work remain outside this increment.


## 27. E5B2 — Trip Handover and frozen per-item leftover dispositions

Approved 24 November 2026 above `d466852`: a full-page Trip Handover over the existing office Trip,
Plans, Reviews, native lorry stock and return/QC Cases. Drivers/assistants see their assigned Trip;
Supervisor decisions retain reconciliation/Override, responsibility and native record permissions.
Each exact prepared source is fully accounted for across approved same-Company Direct Transfer
routes and Keep on Lorry. Loose stock can split; physical tags and held sources stay whole.
Frozen decisions create one existing recovery Manifest per route in one transaction. Every group
retains normal source confirmation, reservation, certificate/expiry identity, native ERP inputs,
Draft/submission/feedback and recovery history. Keep releases old Plan commitments only at final
settlement; continuing the same Plan overnight remains the existing separate whole-Plan action.

One fresh balanced D3 lorry count after all movements and the mixed Review choice recheck every
exact movement/kept quantity. No unfinished group, foreign evidence or moved/used tag can settle
the Plan. Whole unused cancellation restores all reservations/custody before ERP work; after any
ERP command/Draft the frozen instructions remain and saved document recovery is required. Unknown
browser actions retain their original payload/event across reopening. Settled evidence cannot
be cancelled or used to explain another Plan, including loose-only recovery movements.

Old customer returns remain separate non-stock custody. Existing QC receipt/inspection and
accounting/physical disposition own them; owned refusals retain holds and create no duplicate
receipt/credit. Office Trip closure now requires physical receipt of uncancelled old returns;
inspection/accounting may continue later. Native permissions restrict visible Case details.

Operator/Logistics/Driver/office entry points, command catalogue/Help, camera, Enter/Tab and focus/
identity lifecycle accompany the normal page. D3 opening, loose table and closing inputs now use
the existing shared scanner controller; count/variance server rules are unchanged.

See [guide](USER_GUIDE_DISPATCH_E5B2.md) and [acceptance](TEST_DISPATCH_E5B2_RECOVERY.md). Offline
checks do not establish native posting, database concurrency, warehouse/kiosk or device acceptance.
Follow-on Trips/vehicle reassignment remain separate scope.

# CFG Kanban Multi-Company Logistics Architecture

**Architecture version:** 1.0  
**Decision status:** Locked baseline  
**Decision date:** 30 September 2026  
**Implementation status:** Package A, Package B intercompany handover, Packages C1-C2B customer delivery, Package D1 proof/closure, Package D2A controlled return intake plus QC disposition, Package D2B accountant-controlled Draft Sales Invoice Return, Package D2C accepted-return ERP stock disposition, and Package D3 end-of-route reconciliation are implemented; customer invoicing and Package E remain approved future scope

This document is the source of truth for CFG Kanban stock-tag logistics across sister companies,
company-specific vehicle warehouses, customer-site delivery, and delayed intercompany billing. It
extends the existing V1 execution architecture without replacing Production Kanban, Purchase
Replenishment, ERPNext stock control, or accounting.

## 1. System boundary

ERPNext remains authoritative for Companies, Customers, Suppliers, Items, UOMs, Price Lists,
Warehouses, Batches, Delivery Notes, Purchase Receipts, Sales Invoices, Purchase Invoices, Stock
Entries, stock balances, valuation, and accounting.

CFG Kanban owns the simplified scan workflow, tag identity, dispatch and receipt orchestration,
vehicle/container visibility, customer-site resolution, route execution, proof of delivery,
exceptions, and operational audit.

Store operators and drivers use Kanban panels. They do not need access to native ERPNext
transaction forms. A controlled server service creates ERPNext documents only after it validates
the active operator, configured route, Company, warehouse, tag quantity, Item/UOM, and requested
action. A Kanban state never claims that stock moved, arrived, or was delivered before the
corresponding ERPNext document is submitted.

## 2. Non-negotiable invariants

1. Every Warehouse belongs to exactly one ERPNext Company.
2. A cross-company handover is never represented as a normal warehouse-to-warehouse Stock Entry.
3. Manufacturer stock leaves through a submitted Delivery Note.
4. Receiving-company stock becomes available only through a submitted Purchase Receipt.
5. Draft or failed ERPNext documents never make stock operationally available.
6. Physical stock movement and intercompany invoicing are separate lifecycles.
7. A tag quantity cannot exist in two locations or Companies at the same time.
8. Every split quantity receives its own active physical identity or enters a scanned reusable
   container whose contents are individually recorded.
9. ERPNext Item/UOM precision, conversion factors, and whole-number restrictions govern all
   quantities.
10. A customer-facing delivery can use only stock already held by the selling Company in the
    selected selling-company Warehouse.
11. Prices come from configured native ERPNext Price Lists. Drivers and store operators cannot edit
    prices, discounts, taxes, accounts, or valuation.
12. All commands, retries, confirmations, overrides, cancellations, and recovery actions are
    idempotent and auditable.

## 3. Business identities

### 3.1 Kanban Card

A reusable Kanban Card remains a replenishment or process-control signal. It is not a persistent
stock identity and must not be used to represent inventory after production.

### 3.2 Handling Unit / Stock Tag

`CFG Kanban Handling Unit` is extended into the persistent physical identity for a pallet, basket,
box, tote, mesh, loose-stock compartment, or other controlled container. It follows the stock
through packing, company handover, warehouse storage, vehicle loading, customer delivery, return,
and quarantine.

### 3.3 Tag Family

A preprinted tag family consists of one main tag and detachable child identities:

```text
STK-1000       main tag
STK-1000-1     child identity 1
STK-1000-2     child identity 2
STK-1000-3     child identity 3
STK-1000-4     child identity 4
STK-1000-5     child identity 5
```

The visible preprinted code is the primary scan identity, following the same pattern as a logistics
waybill number. Barcode and QR symbologies may both encode the same visible value. Each identity
also has a system-generated internal UUID alias for backward compatibility, audit, revocation, and
integration; that UUID is not required on the physical tag. A child begins `Unused`. Activating it
through a controlled split creates or binds its Handling Unit, copies the parent's Item, Batch, packing
timestamp, expiry, inventory Company, quality status, and trace references, and transfers an exact
quantity out of the parent. The parent balance is reduced in the same controlled transaction.

Visible codes must be globally unique within the ERP site and use an issuer/company-controlled
prefix such as `MFG-STK1000`. The issuing Company owns the number namespace; it does not change when
inventory ownership moves to another Company. Resolution accepts the visible code first and the
internal UUID alias second. Replacement revokes the old identity without reusing its printed code.
The printed code is an identifier, not an authentication secret: operator authorization, allowed
routes, state transitions, idempotency, and ERP confirmation protect every consequential action.

For high-volume preprinted series, `CFG Kanban Tag Range Registry` defines the issuer, exact prefix,
fixed-width numeric interval, child separator, and detachable-child count once. An unused scan is a
read-only range candidate and creates no stock or identity rows. On first controlled Handling Unit
activation, the app locks the registry and lazily materializes only that exact Tag Family and its
children. Exact Tag Families remain supported for exceptions and legacy tags. Once any family has
materialized, the registry definition is immutable; the issuer remains permanent while the Handling
Unit's inventory Company changes only through ERP-confirmed movement.

### 3.4 Reusable loose-stock container

A reusable tag may be permanently fixed to a lorry compartment or designated box. The tag
identifies the container, while an immutable quantity ledger identifies its current contents.
Loading requires the source Stock Tag, destination container, Item/Batch, quantity, Company, and
warehouse. Unloading or delivery reduces the same recorded content line.

One reusable container may technically contain several Item/Batch lines, but the UI must warn on
mixing. A configurable route or container policy may require one Item/Batch per compartment.

### 3.5 Customer Scan Point

A Customer Scan Point identifies one Customer delivery site/address for one selling Company. One
Customer with several branches receives a separate code for each branch. Its QR/barcode contains
a stable, prefixed visible site code; the database also retains an internal UUID alias. Neither
identity embeds mutable Customer or address data.

## 4. Company and vehicle model

The same physical vehicle may carry stock for more than one Company, but ERPNext uses a distinct
logical Warehouse for each Company:

```text
Lorry 01 - Manufacturing Company
Lorry 01 - Sales Company
Lorry 01 - Sister Company C
```

The physical vehicle is the custodian/location context. The logical Warehouse determines the
inventory Company. Scanning never silently moves stock between these logical warehouses.

Use the term **inventory Company** for the Company whose ERPNext warehouse stock currently contains
the available quantity. Between source Delivery Note submission and destination Purchase Receipt
submission, the tag is `Intercompany Transit`: it is not available in either Company's operational
Warehouse. The Manifest retains the source and destination Company snapshots. Legal ownership or
revenue recognition may be governed by separate accounting and commercial policy.

## 5. Intercompany route profile

Each permitted source-to-destination relationship is configured as a `CFG Kanban Logistics Route`.
It contains at minimum:

| Field | Purpose |
|---|---|
| Route Name / Active | Stable configuration identity |
| Source Company | Company dispatching the stock |
| Source Warehouse | Approved dispatch Warehouse |
| Transit Warehouse | Optional source-company transit location |
| Destination Company | Company receiving the stock |
| Destination Warehouse | Approved receiving Warehouse |
| Internal Customer | Destination Company represented as source Company's Customer |
| Internal Supplier | Source Company represented as destination Company's Supplier |
| Selling Price List | Native ERPNext source-company Price List |
| Buying Price List | Native ERPNext destination-company Price List |
| Handover Mode | Two Confirmation; Approved Same-Location Confirmation |
| Auto-submit Dispatch DN | Submit the Delivery Note automatically |
| Auto-submit Receipt PR | Submit the Purchase Receipt automatically |
| Billing Frequency | Per Transfer; Daily; Weekly; Monthly; Manual Batch |
| Proof / Evidence Policy | Optional evidence required for the company handover |
| Allowed Responsibilities | Operators permitted to use the route |

The route is directional. A reverse movement requires its own approved route or a controlled return
workflow.

## 6. Intercompany handover workflow

### 6.1 Operator experience

```text
Scan operator
→ scan or select approved logistics route
→ scan Stock Tags / reusable containers
→ confirm quantities
→ confirm dispatch
→ receiving operator scans the same movement and tags
→ confirm receipt
```

Operators never select arbitrary Companies, parties, rates, accounts, or warehouses. Those values
come from the approved route and the resolved tags.

### 6.2 ERP document effects

At dispatch confirmation, CFG Kanban always creates the Manufacturing/source Company Delivery Note.
Source stock moves only when that Delivery Note is submitted.

At receipt confirmation, CFG Kanban always creates the destination Company Purchase Receipt.
Destination stock becomes available only when that Purchase Receipt is submitted.

Automatic submission is configured independently:

| Dispatch DN | Receipt PR | Operational result |
|---|---|---|
| Submitted automatically | Submitted automatically | End-to-end automatic stock handover |
| Submitted automatically | Approval required | Source stock dispatched; destination stock unavailable until PR submission |
| Approval required | Automatic requested | Receipt submission is blocked until the dispatch DN is submitted |
| Approval required | Approval required | Both sides remain pending authorized native-document confirmation |

Receipt confirmation may create a draft Purchase Receipt while dispatch approval is pending, but
it cannot submit the receipt or change the Handling Unit inventory Company. Submission of the
source Delivery Note changes the tag from source-company available stock to `Intercompany Transit`.
Submission of the destination Purchase Receipt changes it from transit to destination-company
available stock.

### 6.3 Handover state machine

```text
Draft
  → Prepared
  → Dispatch Document Pending
  → Dispatched
  → Awaiting Receipt
  → Receipt Document Pending
  → Received
  → Billing Pending
  → Partially Billed
  → Billed
  → Closed
```

`Exception`, `Hold`, and `Cancelled` are controlled side states. Transactional states are derived
from ERPNext document status and cannot be advanced by directly editing a Kanban field.

If a Delivery Note succeeds and the Purchase Receipt fails, the movement remains `Awaiting Receipt`
or `Exception`. The destination Company cannot sell the stock. Recovery retries the same idempotent
receipt command or requires a supervisor disposition; it never creates a second uncontrolled
receipt.

## 7. Billing after physical movement

The baseline does not require a Sales Order or Purchase Order for a direct intercompany handover.
The physical source documents are:

```text
Source Company Delivery Note
Destination Company Purchase Receipt
```

Accounting later creates:

```text
Source Delivery Note → Source Sales Invoice
Destination Purchase Receipt → Destination Purchase Invoice
```

If company policy requires Sales Orders and Purchase Orders, the route may later gain an optional
background order policy. Store operators still do not interact with those documents.

Route activation must preflight ERPNext Selling and Buying Settings and the internal Customer and
Supplier exceptions. A direct route cannot become active if ERPNext requires a Sales Order before
the Delivery Note or a Purchase Order before the Purchase Receipt unless its background order
policy is implemented and enabled.

`CFG Kanban Billing Batch` groups received movements according to the route's frequency. Billing
may be per transfer, daily, weekly, monthly, or manually selected. A billing batch never changes
the physical receipt state and cannot make unreceived stock available.

Rates are resolved from the configured native ERPNext Price Lists. A missing rate, currency
conflict, incompatible UOM, or unacceptable selling/buying-rate difference blocks document
creation and raises an Exception. Operators cannot override rates from a Kanban panel.

## 8. Customer-site delivery

### 8.1 Customer identification

The driver or salesperson scans the Customer Site code. The panel resolves and locks:

- selling Company;
- ERPNext Customer;
- exact delivery Address;
- route/site identity;
- applicable proof policy;
- price and commercial defaults;
- active lorry and selling-company lorry Warehouse.

The selected Customer and full site address remain prominent until the delivery is completed or
explicitly cancelled. Scanning another Customer Site requires confirmation before changing an
active delivery context.

Fallback resolution is allowed in this order:

1. choose a site from today's assigned route;
2. search permitted Customer Sites;
3. use a supervisor-authorized manual override.

### 8.2 Reserved delivery

When exactly one active reserved/draft Delivery Note matches the selling Company, Customer Site,
vehicle Warehouse, route/date, and operator scope, scanning the site opens it. If several documents
match, the system displays clear choices and never guesses.

### 8.3 Unassigned lorry stock

Stock may be loaded into the selling-company lorry Warehouse without a preassigned Customer. At
the Customer site:

```text
scan Customer Site
→ start Delivery Session
→ scan available lorry Stock Tags or container
→ enter/confirm quantities
→ validate price, stock, reservation, Batch, and proof rules
→ create Delivery Note
→ optionally submit Delivery Note
→ optionally create/submit Sales Invoice
```

Delivery Note auto-submission and Sales Invoice creation/submission are separate policies. An
authorized driver or salesperson may trigger both but cannot alter pricing, discounts, tax,
accounts, or Customer identity. An accountant may use controlled native ERPNext correction and
amendment procedures.

### 8.4 Customer-delivery state machine

```text
Ready
  → Customer Identified
  → Allocating Stock
  → Awaiting Confirmation
  → ERP Document Pending
  → Delivered
  → Invoicing Pending (when applicable)
  → Invoiced
  → Closed
```

`Partial`, `Rejected`, `Exception`, and `Cancelled` retain their own quantities and reasons. A
Delivery Session is complete only when the ERPNext Delivery Note is submitted or an authorized
non-delivery disposition is recorded.

## 9. Customer delivery validation

Before creating or submitting a Delivery Note, the system validates:

- Customer Site belongs to the selling Company;
- Customer and site are active;
- source Warehouse is the active selling-company lorry Warehouse;
- scanned tag's inventory Company matches the selling Company;
- ERPNext stock exists in that Warehouse for the Item/Batch;
- quantity does not exceed tag, container, reservation, or ERP stock balance;
- tag is not reserved to another Customer or Delivery Note;
- Batch is not expired, held, quarantined, or otherwise ineligible;
- Customer-specific Item, brand, expiry, and shelf-life rules are satisfied;
- native Price List contains a valid non-editable rate;
- configured credit and commercial controls allow the action;
- proof-of-delivery requirements can be satisfied.

Company mismatch, held/expired stock, or missing ERP stock are hard failures. They require an
Exception and controlled resolution, not a general override button.

## 10. FIFO and customer eligibility

Packing timestamp is the baseline stock sequence. Selection occurs in this order:

```text
eligible selling Company and Warehouse
→ correct Item/specification/brand
→ Customer-specific Batch, expiry, and shelf-life rules
→ quality/hold/reservation eligibility
→ oldest eligible packing timestamp
```

Expiry is therefore an eligibility rule rather than the universal sequence key. This supports
brands or Customers with different expiry requirements while preserving practical FIFO among
eligible stock.

FIFO override requires supervisor identity, reason, selected replacement tag, timestamp, and an
immutable Event. It cannot bypass Company, stock, expiry, quarantine, or legal restrictions.

## 11. Quantity, split, and container ledger

`CFG Kanban Handling Unit Quantity Ledger` is immutable and authoritative. Recommended event types
are:

- Pack / Activate;
- Split Out / Split In;
- Load / Unload;
- Transfer Out / Transfer In;
- Reserve / Unreserve;
- Deliver;
- Customer Return;
- Return to Warehouse;
- Quarantine / Release;
- Damage / Write-off Reference;
- Reconcile Adjustment;
- Empty / Refill.

Every event records an idempotency key, Item, Batch, Stock UOM, transaction UOM and conversion,
quantity, source and destination Handling Units, Companies, Warehouses, ERP reference, operator,
session, device, timestamp, and reason where applicable.

For a tag family, the invariant is:

```text
main remaining quantity
+ active child quantities
+ delivered/returned/disposed quantities
= original activated quantity
```

For a reusable container:

```text
opening content
+ confirmed loads and returns
- confirmed unloads and deliveries
- confirmed disposal
= current content
```

Cached balances may be stored for performance, but they must be reproducible from the immutable
ledger and reconciled against ERPNext stock by Company, Warehouse, Item, and Batch.

## 12. Proof of delivery

Each Customer Scan Point has one policy:

- Required;
- Optional;
- Unattended Delivery Allowed;
- No Proof Required.

Evidence may include recipient name, signature, photograph, GPS, arrival/completion timestamps,
and notes. An unattended site may close without a signature only when its policy permits it; the
configured unattended reason and evidence remain mandatory.

Evidence uses `CFG Kanban Media` and the approved private S3 architecture in
`docs/SHARED_MEDIA_STORAGE.md`. Presigned URLs are never persisted.

## 13. Returns, overnight stock, and exceptions

Supported controlled actions are:

- Customer Return;
- Partial Delivery;
- Delivery Rejected;
- Customer/Site Closed;
- Return to Warehouse;
- Remain in Lorry Overnight;
- Transfer to Another Approved Lorry;
- Damage;
- Quarantine;
- Quantity Variance.

Each action must create or reference the necessary submitted ERPNext document before changing the
corresponding operational stock state. Overnight stock remains in the correct company-specific
lorry Warehouse and is included in the next opening balance.

## 14. End-of-route reconciliation

A route cannot close until this equation is explained:

```text
opening lorry stock
+ submitted loads and customer returns
- submitted deliveries
- submitted returns/transfers/damage dispositions
= scanned closing lorry stock
```

Variance creates a `CFG Kanban Exception`. The supervisor records recount, correction document,
reason, and resolution. Historical ledger or delivery records are never deleted to force a match.

## 15. Proposed additive data model

The names below are the implementation contract unless a migration review finds a Frappe naming
constraint. Existing DocTypes are extended; they are not rebuilt.

### 15.1 New configuration DocTypes

| DocType | Responsibility |
|---|---|
| CFG Kanban Logistics Route | Directional company/warehouse/party/Price List/automation/billing policy |
| CFG Kanban Customer Scan Point | Selling Company, Customer, exact Address, printed site code, internal UUID alias, route/site and proof policy |
| CFG Kanban Tag Range Registry | Issuer-controlled prefix, fixed numeric interval, child format, lazy-materialization audit |
| CFG Kanban Tag Family | Issuing Company namespace, main visible ID, detachable child identities, internal UUID aliases, issue/revocation state |

### 15.2 New transactional DocTypes

| DocType | Responsibility |
|---|---|
| CFG Kanban Movement Manifest | One dispatch/receipt, lorry load/unload, return, or approved transfer aggregate |
| CFG Kanban Manifest Line | Scanned tag/container, Item/Batch, UOM and expected/confirmed quantities |
| CFG Kanban Handling Unit Quantity Ledger | Immutable tag/container quantity and location events |
| CFG Kanban Delivery Session | Driver/customer-site context and ERP delivery lifecycle |
| CFG Kanban Delivery Allocation | Immutable Delivery Note row-to-tag quantity allocation |
| CFG Kanban Route Reconciliation | One Company-specific Vehicle Warehouse opening snapshot, physical closing count, variance and resolution audit |
| CFG Kanban Route Reconciliation Line | Item/Batch opening, ERP movement, expected closing, tagged/loose count and variance |
| CFG Kanban Route Reconciliation Scan | Exact Handling Unit/container-expanded physical count evidence |
| CFG Kanban Route Stop | Planned/actual Customer Site sequence and reserved Delivery Note |
| CFG Kanban Billing Batch | Groups received intercompany movements for later invoices |

### 15.3 Existing DocType extensions

`CFG Kanban Handling Unit` gains:

- Tag Kind: Main Stock Tag; Child Stock Tag; Reusable Container;
- Tag Family, Parent Handling Unit, Root Handling Unit, and Child Index;
- Inventory Company and Current Warehouse;
- Physical Custodian/Vehicle and container reference;
- Packing Timestamp and Expiry Date snapshot;
- Original, current, reserved, and available quantity caches;
- Identity State, Movement State, and Quality State;
- reusable-container and mixed-content policy;
- latest manifest, Delivery Session, ERP reference, and reconciliation timestamp.

The immutable quantity ledger is authoritative over cached quantities.

`CFG Kanban Card` and `CFG Kanban Cycle` gain immutable Company snapshots where required for
existing production/transfer traceability. Logistics movements do not overload Production Cycles;
they use Movement Manifest and Delivery Session aggregates.

`CFG ERP Command` gains controlled command types for creating/submitting:

- intercompany Delivery Note;
- intercompany Purchase Receipt;
- customer Delivery Note;
- customer Sales Invoice;
- same-company Stock Entry;
- return/reversal documents where ERPNext permits them.

Every command stores the resolved route/site snapshot, quantities, rates, source records,
idempotency key, target ERP document, result payload, and recoverable error.

`CFG Kanban Event` and `CFG Kanban Exception` gain neutral links to Movement Manifest, Handling
Unit, Delivery Session, Route Reconciliation, Customer Scan Point, and Billing Batch.

### 15.4 ERPNext trace fields

App-owned read-only custom fields are required on relevant Delivery Notes, Purchase Receipts,
Sales Invoices, Purchase Invoices, and Stock Entries:

- Kanban Controlled;
- Logistics Route;
- Movement Manifest;
- Delivery Session where applicable;
- counterpart Company/document reference;
- Billing Batch where applicable;
- requested operator and scan-event identity.

Fixtures must include only fields owned by the CFG Kanban module.

## 16. Authorization model

An ordinary store operator, driver, or salesperson does not receive broad ERPNext transaction
permissions. The panel authenticates an Employee-based Operator Profile and active Operator
Session, then checks configured Responsibilities, Companies, Warehouses, routes, vehicles, and
actions.

Recommended responsibilities are:

- Logistics Dispatch;
- Logistics Receipt;
- Vehicle Loading;
- Customer Delivery;
- Customer Invoice Trigger;
- Logistics Supervisor;
- Intercompany Billing;
- Logistics Reconciliation.

The server service must never use a broad permission bypass merely because the terminal user lacks
native access. It first performs app-level authorization and business validation, then executes the
minimum controlled ERP command with complete attribution.

## 17. Idempotency and failure recovery

Stable identities are required for:

- scan event;
- manifest action;
- Handling Unit ledger event;
- dispatch Delivery Note command;
- receipt Purchase Receipt command;
- Delivery Session;
- Delivery Note and Sales Invoice command;
- proof confirmation;
- billing batch action.

Repeating a scan or retrying a timed-out request returns the existing result. It must not create a
second ERP document or duplicate quantity event.

Cross-document workflows use explicit recovery states. A partial success is visible and blocks the
next unsafe action. Recovery may retry, cancel where ERPNext legally permits, create a return or
amendment, or require supervisor reconciliation. It never deletes submitted audit history.

## 18. Implementation packages

### Package A — Foundation and migration (implemented)

- Add Company snapshots to existing Card/Cycle records where needed.
- Extend Handling Unit without invalidating existing production tags.
- Preserve every existing internal UUID alias and map the current Issued, Attached, Dispatched, Received,
  Void, and Replaced states into the new identity/movement states without rewriting history.
- Permit reusable-container identities that are not owned by one production Cycle while retaining
  existing Cycle links on historical production tags.
- Add Tag Family and child identities.
- Add range-backed lazy Tag Family registration for high-volume preprinted serial blocks.
- Add immutable Handling Unit Quantity Ledger and reconciliation service.
- Add Logistics Route and Customer Scan Point.
- Add schema, migration patches, permissions, and unit tests.

### Package B — Intercompany handover (vertical slice implemented)

- Add Movement Manifest and lines.
- Add controlled Delivery Note and Purchase Receipt ERP commands that always create a draft on the
  confirmed operation and independently auto-submit each side when configured.
- Add independent submission policies and two-confirmation workflow.
- Add ERP feedback, idempotency, failure recovery, and Exceptions.
- Billing Batch grouping remains the next Package B increment; accounting decisions are not
  automated by the current vertical slice.

### Package C — Vehicle loading and customer delivery

- **Implemented in C1:** company-specific lorry Warehouse validation.
- **Implemented in C1:** Customer Site scan resolution and immutable Delivery Session snapshots.
- **Implemented in C1:** operator-scoped active-session isolation, idempotent start, empty-session
  cancellation, and Event/Exception audit links.
- **Implemented in C2A:** scan-first Stock Tag allocation with full/partial quantity reservation,
  complete reusable-container expansion, concurrent-reservation protection, audited release and
  reconfirmation, ERP stock validation, and genealogy history. Reservation does not move ERP stock.
- **Implemented in C2B:** locked-price customer Delivery Note creation from the exact confirmed
  allocations, per-Customer-Site Draft/auto-submit policy, mandatory ERP parent/child input capture,
  ERP-submission-only tag consumption, reusable-container unloading, cancellation reversal,
  amendment revision, idempotent commands, and Exception audit.
- Add loose-container loading/unloading.
- Add Route Stops and untagged/loose reusable-container delivery quantities.
- Add reserved and unassigned-stock delivery flows.
- Add optional customer Sales Invoice commands. The controlled Delivery Note command is implemented.

### Package D — Proof, returns, and reconciliation

- **Implemented in D1:** configurable proof-of-delivery rules, server-validated closure, recipient
  identity, signature/photo/attachment evidence in the shared private S3 media registry, GPS/time
  capture, and an immutable supervisor-visible proof record.
- **Implemented in D1:** attended, unattended, optional no-proof, and automatic no-proof-required
  dispositions. A submitted proof blocks unsafe Delivery Note cancellation and directs later
  correction to the controlled return workflow.
- **Implemented in D2A:** Customer Return for QC starts from the identified Customer Site without
  requiring the driver to find an old Delivery Note or Sales Invoice. The printable/scannable
  Temporary Return Note snapshots physical Item/Batch/expiry/tag/quantity/condition and non-stock
  custody. QC records received, accepted, rejected, disposition, operator, and time.
- **Implemented in D2A:** accepted QC quantity becomes Accounting Pending; the floor does not select
  an invoice or create a Credit Note/e-Invoice. A separate wrong-Delivery-Note workflow requires the
  exact submitted DN, limits reversal to its rows, and creates only an ERPNext Return Delivery Note.
  Already-invoiced DNs are visibly held as Draft for accounting attention.
- **Implemented in D2B:** an authorized accounting user selects an exact/substitute submitted Sales
  Invoice for the same Company, Customer and sufficient remaining Item quantities, or records No
  Credit with a reason. CFG Kanban creates only a non-stock Draft Sales Invoice Return; ERPNext owns
  tax/e-Invoice review and submission, while submit/cancel hooks update the Return Case audit state.
- **Implemented in D2C:** authorized stock/quality supervision conserves every accepted quantity
  across quarantine, rework, available-stock or disposal splits. Receipt choices prepare a controlled
  Draft Material Receipt and become stock only after ERPNext submission; disposal creates no stock.
  Accounting and physical disposition can finish independently, and the case closes only when both
  controls are complete.
- **Implemented in D3:** add Company-specific vehicle-Warehouse opening snapshots, exact tag and
  reusable-container scans, loose/untagged physical quantities, submitted ERP movement comparison,
  variance Exceptions, controlled recount/correction resolution, and a printable closing report.

### Package E — Operational hardening

- Concurrency and duplicate-scan tests.
- Multi-Company and UOM precision integration tests.
- Rate, tax, credit, Batch, expiry, and stock eligibility tests.
- Permission, cancellation, amendment, and partial-failure tests.
- Pilot dashboards, supervisor recovery screens, and code-verified operating guide updates.

## 19. Explicit exclusions from this baseline

- Vendor-owned or buyer-directed supplier production tracking remains a later V2 scope.
- Offline stock posting is excluded; live stock confirmation requires ERPNext connectivity.
- Route optimization is not implemented here; an ERPNext Delivery Trip or external optimizer may
  provide the planned sequence.
- Drivers cannot edit commercial rates or accounting details.
- Stock Tag details are not duplicated onto Sales Invoices; traceability remains Invoice → Delivery
  Note → Delivery Allocation → Handling Unit/Tag ledger.
- TrackQMS is not a required dependency. Any future SOP or quality integration follows
  `docs/PLATFORM_INTEGRATION_BOUNDARY.md`.

## 20. Acceptance conditions

This architecture is considered correctly implemented only when an end-to-end test proves that:

1. a layman dispatches without opening a native ERPNext document;
2. source stock changes only after Delivery Note submission;
3. a separate receiver confirms the same tags and quantities;
4. destination stock changes only after Purchase Receipt submission;
5. billing may remain pending while received stock is available;
6. one physical lorry safely holds separate company-specific ERP stocks;
7. main, child, and reusable-container tags preserve quantity and Batch traceability;
8. unassigned lorry stock can be sold at a scanned Customer Site using locked prices;
9. wrong Company, Customer reservation, Warehouse, Batch, price, or quantity is blocked;
10. partial delivery leaves the correct balance on the correct tag/container and Warehouse;
11. proof policy, returns, overnight stock, and route reconciliation are auditable; and
12. every ERP document and quantity event is idempotent and recoverable.

# CFG Kanban

For the standalone, code-verified setup and operating source of truth, see the
[CFG Kanban Code-Verified Operating Guide](docs/USER_MANUAL.md).
The consolidated model is documented in
[Enhanced V1 Core Architecture](docs/ENHANCED_CORE_ARCHITECTURE.md).
The approved multi-company stock-tag and customer-delivery extension is documented in
[Multi-Company Logistics Architecture](docs/MULTI_COMPANY_LOGISTICS_ARCHITECTURE.md).
The independent full-flow procedure from buyer-owned purchase replenishment through receiving,
production genealogy, intercompany handover, and the Package C1 Customer Delivery Session is in
[Purchase Signal through Package C1 System Test](docs/TEST_PURCHASE_TO_C1_END_TO_END.md).
The independent tester-facing acceptance procedure for the implemented Customer Site / Delivery
Session foundation is in
[Package C1 Customer Delivery Session System Test](docs/TEST_PACKAGE_C1_CUSTOMER_DELIVERY_SESSION.md).
The next independent procedure is
[Package C2A Customer Stock Allocation System Test](docs/TEST_PACKAGE_C2A_CUSTOMER_STOCK_ALLOCATION.md).
The ERP posting continuation is
[Package C2B Customer Delivery Note System Test](docs/TEST_PACKAGE_C2B_CUSTOMER_DELIVERY_NOTE.md).
The customer acceptance and private-evidence continuation is
[Package D1 Customer Delivery Proof System Test](docs/TEST_PACKAGE_D1_DELIVERY_PROOF.md).
The controlled post-delivery return and correction continuation is
[Package D2A Customer Return Intake System Test](docs/TEST_PACKAGE_D2A_CUSTOMER_RETURN_INTAKE.md).
The accountant-controlled post-QC continuation is
[Package D2B Customer Return Accounting System Test](docs/TEST_PACKAGE_D2B_CUSTOMER_RETURN_ACCOUNTING.md).
The accepted-return physical-stock continuation is
[Package D2C Return Stock Disposition System Test](docs/TEST_PACKAGE_D2C_RETURN_STOCK_DISPOSITION.md).
The end-of-route physical count and ERP variance continuation is
[Package D3 Route Reconciliation System Test](docs/TEST_PACKAGE_D3_ROUTE_RECONCILIATION.md).
The same-Company warehouse replenishment continuation is
[Package L1 Transfer Kanban System Test](docs/TEST_PACKAGE_L1_TRANSFER_KANBAN.md).
The controlled consumable/indirect-stock issue continuation is
[Package L2 Withdrawal Kanban System Test](docs/TEST_PACKAGE_L2_WITHDRAWAL_KANBAN.md).
Package A identity/configuration, Package B intercompany handover, Package C1 customer/vehicle
session foundation, Package C2A customer tagged-stock reservation, and Package C2B controlled
customer Delivery Note posting are implemented. Package D1 adds policy-controlled proof of delivery,
private evidence, unattended delivery, and audited closure. Package D2A separates Customer Return
for QC from wrong-Delivery-Note correction: drivers issue a non-accounting Temporary Return Note at
the Customer Site with optional customer acknowledgement and private timestamped/geotagged evidence,
QC records accepted/rejected disposition, and only wrong-DN correction can create
an ERPNext Return Delivery Note. Package D2B lets authorized accounting users select a valid source
invoice or No Credit and prepares a non-stock Draft ERPNext Sales Invoice Return. ERPNext retains
manual tax/e-Invoice review and submission. Package D2C independently splits QC-accepted quantity
between quarantine, rework, available stock, or controlled disposal; only a submitted ERPNext
Material Receipt changes stock, and the Return Case closes after both tracks finish.
Package D3 closes the logistics route-control loop with a Company-specific vehicle-Warehouse
opening snapshot, exact Stock Tag/container count, loose-stock count, ERP movement comparison,
variance Exceptions, controlled resolution, and a printable reconciliation report. Counting never
changes ERPNext stock.
The additive tagged/untagged material-continuity model is documented in
[Material Genealogy Architecture](docs/MATERIAL_GENEALOGY_ARCHITECTURE.md). Its mixed-trace policy
and submitted Purchase Receipt tag-activation slice are implemented without making tags mandatory
for ordinary ERPNext stock.

`cfg_kanban` is a Frappe/ERPNext v15 process-control app for production Kanban. Kanban decides
**when and why** replenishment or a process handoff is required; ERPNext remains the system of
record for Work Orders, Job Cards, Stock Entries, stock, batches, and accounting.

The app covers production control, an approval-first Sales Order demand proposal flow, and a
buyer-owned purchase-replenishment baseline. Vendor-managed external processing remains a V2 item.

## Included

- Global settings, Kanban masters, physical/digital cards, and replenishment cycles.
- Per-operation profiles with dependency/start rules, parallel operation support, full-batch,
  physical-card, automatic, and digital-quantity handoffs.
- Dynamic operator field definitions stored on the master and snapshotted as execution values.
- Production-linked Process Tasks for preparation, sanitation, quality, clearance, and verification
  gates without creating fake ERPNext Job Cards.
- Standalone scheduled or requested Service Tasks for housekeeping, maintenance, inspections,
  safety, environmental, vehicle, and emergency work.
- Structured checklist and dynamic-field maintenance evidence, independent approval/rejection,
  compliance reports, and a printable verified maintenance record.
- Shared Employee-based operator authorization and dynamic-form validation across production
  executions, production tasks, and standalone service tasks.
- Asset, Location, and Task card identities that expose service work without triggering production.
- Process executions linked to ERPNext Job Cards, immutable progress entries, and an auditable WIP
  quantity ledger.
- Event, signal, ERP command, and exception records.
- End-of-route reconciliation for each Company-specific Vehicle Warehouse, with exact tag/container
  scans, loose-stock counts, submitted ERP movement comparison, variance Exceptions, resolution
  audit, and a printable closing report. Reconciliation never changes ERPNext stock.
- A central card state service and trigger service.
- One ERP gateway for Work Order, Job Card, and Stock Entry actions.
- Purchase-replenishment signals that create ERPNext Material Requests, bind a validated submitted
  Purchase Order, and create draft or receiver-confirmed Purchase Receipts with partial-receipt,
  tolerance, supplier, item, company, and warehouse guardrails.
- ERPNext `doc_events` feedback for Work Order, Job Card, and Stock Entry changes.
- Unique database-backed idempotency keys for signals and commands, plus active-cycle protection.
- Whitelisted scan and incremental progress API skeletons.
- A Desk **Kanban Operator** console for scanning/finding cards, triggering consumption,
  starting linked Job Cards, entering dynamic progress data, and viewing the cycle timeline.
- Form actions on cards, signals, executions, and cycles, including supervisor signal approval.
- Confirmed Sales Order evaluation with projected-stock/open-cycle deductions, fixed-card rounding,
  available-card reservation, idempotent demand proposals, and supervisor approval before release.
- Two reusable English Kanban Card print formats: A6 landscape double-sided Standard Card and
  A6 landscape single-sided Operational Card.
- Optional 45 mm × 250 mm monochrome replacement Handling Unit tags with QR and Code 128
  identities, one per pallet/container, backed by a separate handling-unit transaction and
  lifecycle. Preprinted visible tag/waybill codes are the primary physical scan identity.
- Optional Item/Company material-trace policies. Missing or disabled policies preserve ERP-only
  stock behavior; explicit policies may allow or require physical tags independently at purchase
  receipt, production input, and production output stages.
- Submitted Purchase Receipt tag activation that derives Item, Batch, Company, Warehouse and UOM
  from ERPNext, supports multiple physical containers without exceeding confirmed quantity, and
  keeps an immutable ERP-origin reference on every activated Handling Unit.
- Draft Stock Entry tracing for Manufacture, Repack, Material Transfer, Material Transfer for
  Manufacture, and Material Consumption for Manufacture. Tagged inputs are reserved before
  submission; submitted ERPNext entries confirm consumption/transfer and activate staged
  preprinted output tags. Items configured with No Physical Tag remain ordinary ERP warehouse
  stock. Scoped production operators use the Card panel, while Internal Warehouse Transfer
  operators use the mobile-friendly Logistics panel.
- A read-only Material Genealogy Explorer that accepts any activated preprinted Stock Tag, follows
  exact Handling Unit production/split/replacement relationships upstream and downstream, shows
  ERP movement and Manifest evidence, and produces an A4 genealogy trace report without changing
  ERPNext stock.
- Reusable-container content control in the Logistics panel, with complete-tag loading/unloading,
  optional mixed Item/Batch contents, immutable membership episodes, operator audit, movement
  safeguards, one-scan complete-container intercompany dispatch/receipt, and separate genealogy
  history that never invents an ERP stock movement. ERP rows remain tied to each contained Stock
  Tag rather than to the reusable container.
- Exact ERPNext Serial Number membership for serial-controlled tagged stock, including receipt and
  production assignment, controlled detachable-child split/untouched merge, whole-tag consumption
  validation, cancellation recovery, replacement transfer, immutable history, and
  genealogy/Logistics-panel visibility.
- Packages A-B plus Packages C1-C2B of the approved multi-company logistics architecture: directional Logistics Routes,
  Customer Scan Points, pre-registered main/child Stock Tag families, extended Handling Units,
  immutable quantity ledger, scan-first Movement Manifests, and guarded intercompany Delivery Note
  / Purchase Receipt posting with independent auto-submit policies. Customer Site scans now lock
  the Customer, address, selling Company, price list, proof policy, and Company-specific lorry
  Warehouse into an immutable Delivery Session. C2A adds scan-first full/partial customer stock
  reservation, complete reusable-container expansion, release/reconfirmation audit, and genealogy
  visibility without changing ERP stock. C2B converts a confirmed allocation into a locked-price
  ERPNext customer Delivery Note, supports per-site Draft/auto-submit policy and mandatory ERP child
  tables, posts tag consumption only on ERP submission, and safely restores reservations after an
  allowed cancellation. D1 records recipient/signature/photo/GPS proof in private S3 storage and
  closes the Delivery Session only after policy validation. D2A lets drivers issue a printable and
  scannable Temporary Return Note without finding an old DN/invoice, keeps those goods in non-stock
  QC custody, records QC acceptance/rejection, and hands accepted results to accounting without
  creating credit. Its separate wrong-DN correction path requires the exact submitted DN and creates
  only a controlled Return Delivery Note. D2B adds an accountant-only source/no-credit decision and
  an idempotent non-stock Draft Sales Invoice Return with ERP submit/cancel feedback. Physical
  accepted-return stock is handled separately by D2C through quantity-conserving disposition splits,
  Draft ERPNext Material Receipt preparation, submission/cancellation feedback, and no-stock
  controlled disposal.
- Transfer Kanban cards now release same-Company warehouse replenishment into the mobile Logistics
  Operator Panel. Explicit Internal Warehouse Transfer routes create native ERPNext Material
  Transfer Stock Entries in Direct or Goods-in-Transit mode; optional physical tags, untagged ERP
  stock, cycle/card completion, and cancellation safeguards all remain subordinate to submitted ERP
  stock documents.
- Withdrawal Kanban cards provide a separate mobile Logistics flow for consumables and indirect
  materials that leave inventory without a Work Order or destination Warehouse. The operator may
  select exact Stock Tags or ordinary ERP stock according to the Item/Company trace policy; an
  idempotent ERPNext Material Issue remains the stock system of record, and only submission consumes
  tagged quantity and recycles the Card.

## Control flow

```text
Card scan → Event → Signal → ERP Command → ERPNext document
                                              │
Kanban state / exception ← ERP doc_events ────┘
```

The app does not replace ERPNext manufacturing logic. All ERP writes pass through
`cfg_kanban.integrations.erp_gateway`; API pages and future dashboards should call the Kanban
services, never construct ERPNext documents themselves.

## Dedicated Frappe v15 development server

Use a dedicated bench and site. The commands below assume the official v15 prerequisites,
MariaDB/Redis services, Node/Yarn, and Bench are already installed.

```bash
bench init --frappe-branch version-15 cfg-bench
cd cfg-bench
bench new-site kanban.localhost
bench get-app --branch version-15 erpnext https://github.com/frappe/erpnext
bench --site kanban.localhost install-app erpnext
bench get-app https://github.com/YOUR-ORG/cfg_kanban.git
bench --site kanban.localhost install-app cfg_kanban
bench --site kanban.localhost migrate
bench start
```

For local app development instead of cloning from GitHub:

```bash
cd cfg-bench
bench get-app /absolute/path/to/cfg_kanban
bench --site kanban.localhost install-app cfg_kanban
bench --site kanban.localhost migrate
```

Add `kanban.localhost` to the hosts file if the local resolver does not handle it, then open
`http://kanban.localhost:8000`.

## First configuration

1. Open the **CFG Kanban** workspace from the Desk sidebar. It groups configuration, live
   production control, ERP commands, exceptions, audit history, and related ERPNext records.
2. Open **CFG Kanban Settings**, select the company and warehouses, and begin with **Approval**
   automation while validating the pilot.
3. Create a **CFG Kanban Master** for one production item/BOM. Add the ERP operations in sequence.
4. Add dynamic operator fields on the master and associate each row with its operation.
5. Create cards with unique card numbers and scan tokens.
6. Call `/api/method/cfg_kanban.api.scan.scan` with `token`, `action=consume`, and a stable
   `event_token` supplied by the scanner for retries.

Operators can use `/app/kanban-operator` instead of calling the API directly. Signal approval is
restricted server-side to Manufacturing Manager or System Manager. The console deliberately uses
the ERP command gateway for Job Card actions and Work Order creation.

## Printing and handling units

Use **Print Kanban → Print Standard Card** or **Print Operational Card** from a reusable Kanban
Card. The Standard Card produces two A6 landscape pages; for economical A4 stock select four pages
per sheet and duplex printing in the printer dialog, then verify front/back orientation on a test
sheet. The Operational Card is a single A6 landscape page showing immediate movement only.

Register a large preprinted serial block once in **CFG Kanban Tag Range Registry**, or use **CFG
Kanban Tag Family** for a one-off code. Then scan the printed value (for example `MFG-STK1000`) into
**Preprinted Tag / Handling Unit ID** when activating the physical pallet, mesh, tote, or other
Handling Unit. A range lookup creates no records; the exact family and configured child identities
are materialized atomically only on first Handling Unit activation. QR and Code 128 may both encode
the same human-readable value. The generated UUID is an internal fallback alias and is never
required on a physical label. Use globally unique issuer/company prefixes because the same tag
continues across ownership changes and must resolve unambiguously throughout the ERP site.

**Print Thermal Tag** is an optional replacement/emergency format, not an operational dependency.
Reprints require a reason and increment the print counter. Replacement links old and new records
and makes the old identity unusable. A tag scan can only advance its own Issued → Attached →
Dispatched → Received lifecycle (or Void); it never creates replenishment.

## Sales Order demand proposals

Enable **Sales Order Trigger** on the applicable Kanban Master. By default, the inventory target is
the destination warehouse's **Reorder Level** in ERPNext Item → Reorder. Use **Kanban Override**
only when a loop intentionally needs its own minimum. The Master's replenishment quantity remains
the quantity represented by one card; it is not the inventory threshold.

The proposal deducts ERPNext projected availability, open Kanban cycles, and other waiting
proposals from the target, then rounds the remaining shortage up to the Master's fixed card
quantity. Sales Order outstanding quantity is retained for audit but is not added a second time,
because submitted demand is already represented by ERPNext projected quantity. A Manufacturing
Manager must select **Approve and Release**. Approval reserves the
required available cards, creates one traceable Signal and Cycle, then sends a controlled Work
Order command through the ERP gateway. It does not mark a physical card as consumed or simulate a
shop-floor scan.

Multiple Masters for one item are supported when they represent distinct loops. Selection first
uses the Sales Order warehouse, then the most specific matching Demand Scope (Customer, Sales
Territory, or Production Line takes precedence over General), then the highest Master Priority.
The app rejects duplicate active Masters with the same item, destination warehouse, and scope. A
remaining tie is blocked and recorded as a configuration exception; it never creates two Work
Orders for the same shortage.

If available cards are insufficient, the demand becomes Blocked and an exception is recorded.
Cancelling a Sales Order cancels an unreleased proposal; if production was already released, the
app raises an exception for supervisor review rather than silently cancelling ERP production.

### Customer make-to-order production

For a customer whose product cannot be made for stock, use a Customer-scoped Master with
**Production Policy = Customer Make-to-Order**. Set the Master's maximum extra-production
tolerance and whether the Work Order should be planned to the maximum permitted quantity. On the
Sales Order, record whether the customer PO allows extra quantity, the PO percentage, and the PO
clause or amendment reference. The effective percentage is always the lower of the Master and PO
limits; without explicit PO authorization it is zero.

Approval creates one digital Cycle and Work Order per Sales Order line, without reserving a
reusable Kanban card. It also creates one dedicated ERPNext Batch whose expiry is calculated from
the Item shelf life. Submitted Manufacture Stock Entries are rejected when they use another batch
or would take cumulative accepted output above the customer-authorized maximum. Authorized excess
is recorded against the Demand and PO reference. The app deliberately does not silently increase
the submitted Sales Order; invoicing or delivery of excess remains subject to ERPNext's normal
Sales Order amendment and over-delivery controls.

For the Cooking → Bottling → Cartoning pilot, configure Cooking as full-batch handoff, Bottling as
incremental digital-quantity handoff with the carton transfer multiple, and Cartoning as full-batch
handoff to finished goods.

### Multiple workstations for one operation

One Kanban Card still represents one replenishment loop, and one active Cycle controls one effective
ERPNext Work Order. Each ERPNext Job Card is mirrored as a Process Execution lane. The new Operation
Summary is the authoritative combined result for all lanes belonging to the same operation: allocated,
processed, good, rejected, released, and completed quantities are recalculated from the Job Cards.

Select the Execution Mode on each Master operation profile:

- **Single Workstation** expects one Job Card and blocks the operation if ERPNext produces several.
- **Parallel Workstations** makes all Job Card lanes ready together and combines their live results.
- **Sequential Split** makes only the first lane ready, then releases the next lane when it completes.

Lane allocation follows ERPNext's Job Card `for_quantity`; total allocation above the Cycle quantity
is blocked as a configuration exception. Handoff readiness uses the combined Operation Summary and
operation-to-operation WIP ledger, not an arbitrary individual lane. Printing multiple copies of a
permanent Card does not create lanes or separate orders.

### Reusable Process and Station cards

Process Kanban and Station Kanban cards are runtime selectors, not permanent Job Card assignments.
Scanning an available card proposes one eligible submitted Work Order and open Job Card using the
Master item/company, card operation, optional Station-card workstation, and the operation profile's
Runtime Selection Priority. The operator must confirm the proposal before anything is allocated.

The effective Cycle quantity is always the minimum of the card's permanent nominal quantity, the
remaining Job Card demand after other active/completed runtime allocations, and available upstream
input. A reduced final or input-limited Cycle is clearly labelled and its calculated reason is stored
with the operator confirmation. The permanent Card quantity is never changed.

Each confirmed selection creates a temporary Runtime Allocation linking Card, Cycle, Work Order, Job
Card, workstation, nominal quantity, effective quantity, and final good/reject/notes. Closing that
Cycle returns the reusable Card to Available while leaving an incompletely fulfilled ERPNext Job Card
open for another Cycle. ERPNext Job Card completion remains the manufacturing system-of-record event.

## Custom fields and fixtures

`after_install` creates app-owned, read-only traceability fields on Work Order, Job Card, and Stock
Entry: controlled flag, cycle, signal, and Work Order production origin. The hook exports only
Custom Fields whose module is `CFG Kanban`:

```bash
bench --site kanban.localhost export-fixtures
```

Commit the generated `cfg_kanban/fixtures/custom_field.json`. Do not export unrelated site
customizations. Run `bench --site kanban.localhost migrate` after pulling fixture or DocType changes.

## Verification

Inside the bench environment:

```bash
bench --site kanban.localhost run-tests --app cfg_kanban
ruff check apps/cfg_kanban
```

Before production use, add site-backed integration tests for concurrent duplicate scans, ERPNext
version-specific Job Card methods, Stock Entry mappings, permissions, failure retries, and reversal
flows. The scan endpoint is a server API skeleton, not a finished scanner UI or offline queue.

## Deployment notes

- Use a service account with only the ERP permissions needed by the gateway.
- Restrict operator access to the Kanban UI/API; keep command, event, and ledger records read-only.
- Back up the site before migration and deploy the app and ERPNext from pinned v15 revisions.
- Start with approval mode, reconcile Kanban output against supervisor decisions, then enable
  automatic Work Order creation per master.

License: MIT.

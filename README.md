# CFG Kanban

For setup and day-to-day operation, see the [CFG Kanban User Manual](docs/USER_MANUAL.md).
The consolidated model is documented in
[Enhanced V1 Core Architecture](docs/ENHANCED_CORE_ARCHITECTURE.md).

`cfg_kanban` is a Frappe/ERPNext v15 process-control app for production Kanban. Kanban decides
**when and why** replenishment or a process handoff is required; ERPNext remains the system of
record for Work Orders, Job Cards, Stock Entries, stock, batches, and accounting.

The app covers production control plus an approval-first Sales Order demand proposal flow.
Supplier Kanban remains intentionally deferred.

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
- A central card state service and trigger service.
- One ERP gateway for Work Order, Job Card, and Stock Entry actions.
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
- Disposable 45 mm × 250 mm monochrome Handling Unit tags with QR and Code 128 identities,
  one per pallet/container, backed by a separate handling-unit transaction and lifecycle.

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

Create one **CFG Kanban Handling Unit** per physical pallet, mesh, tote, or other handling unit.
Select **Print Thermal Tag** to produce the monochrome 45 mm × 250 mm tag. Reprints require a
reason and increment the print counter. Replacement actions issue a new opaque token and revision,
link old and new records, and make the old identity unusable. A tag scan can only advance its own
Issued → Attached → Dispatched → Received lifecycle (or Void); it never creates replenishment.

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

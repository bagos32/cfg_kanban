# CFG Kanban

`cfg_kanban` is a Frappe/ERPNext v15 process-control app for production Kanban. Kanban decides
**when and why** replenishment or a process handoff is required; ERPNext remains the system of
record for Work Orders, Job Cards, Stock Entries, stock, batches, and accounting.

This initial vertical slice covers production only. Sales Order-driven and supplier Kanban are
intentionally deferred.

## Included

- Global settings, Kanban masters, physical/digital cards, and replenishment cycles.
- Per-operation profiles with dependency/start rules, parallel operation support, full-batch,
  physical-card, automatic, and digital-quantity handoffs.
- Dynamic operator field definitions stored on the master and snapshotted as execution values.
- Process executions linked to ERPNext Job Cards, immutable progress entries, and an auditable WIP
  quantity ledger.
- Event, signal, ERP command, and exception records.
- A central card state service and trigger service.
- One ERP gateway for Work Order, Job Card, and Stock Entry actions.
- ERPNext `doc_events` feedback for Work Order, Job Card, and Stock Entry changes.
- Unique database-backed idempotency keys for signals and commands, plus active-cycle protection.
- Whitelisted scan and incremental progress API skeletons.

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

For the Cooking → Bottling → Cartoning pilot, configure Cooking as full-batch handoff, Bottling as
incremental digital-quantity handoff with the carton transfer multiple, and Cartoning as full-batch
handoff to finished goods. `allow_parallel` permits ERPNext Job Cards to be active concurrently;
readiness and available quantity remain controlled per execution.

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

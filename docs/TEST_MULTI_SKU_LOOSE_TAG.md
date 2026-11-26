# Multi-SKU Loose Tag acceptance

Implementation baseline: `552707e` plus this working change. Live ERPNext acceptance: **Not run**.
No migration, live transaction, printer, physical scanner or client deployment was performed here.

The deployed site must use the existing supported Frappe/ERPNext v15 stock/delivery flow.
The package adds two CFG DocTypes, two internal Handling Unit references, a Dispatch Plan flag,
server services and browser assets; run the normal CFG migration/build/cache/restart procedure.
Do not update Frappe/ERPNext or convert old bins/tags. No data backfill is needed.

Use two released non-serialized Stock Tags in one source Warehouse: SKU A at least 10 cartons,
SKU B at least 8 cartons (stock UOM cartons), with Batch/certificate/expiry evidence where used.
Prepare an exact customer Delivery stop and a separate Visit Only customer on a shared Open Route
pool. The plans request A=3, B=2; an additional stop is available for wrong-stop checks. Use the
existing operator responsibilities, lorry, sales pricing, customer proof and QC setup in the manual.

| Scenario | Expected evidence | Live result |
| --- | --- | --- |
| Warehouse packs A=3 / B=2 | One Loose Tag QR; two native Dispatch Allocations; source remains A=7 / B=6; each split ledger points to original source; cert/expiry inheritance | Not run |
| Duplicate/conflicting Create; two tabs | Same actor/token returns same pack; changed payload rejects; only one split/reserve set; stale tab cannot create again | Not run |
| Excess Plan/source quantity, repeated source, bad UOM, reserved/expired/foreign Company source | No partial pack, reservation, certificate or balance mutation | Not run |
| Print and E3 loading | Native configurable CFG Loose Tag print, one QR; one loading scan confirms both internal lines; submitted loading SE moves exactly 3 and 2; no whole-source move | Not run |
| Wrong Trip/stop/customer or cancelled stop | Clear rejection, no allocation/ERP movement or arrival acknowledgement | Not run |
| Full acceptance, customer Plan | Both lines visible; one full-acceptance confirmation; native DN has A=3/B=2 and exact source identities; stock changes only after submission feedback | Not run |
| Full acceptance, Visit Only/shared pool | Exact customer pack selection; native route allocations and pricing/DN; another stop cannot take its internal source lines | Not run |
| Refuse B=1 at either kind of stop | DN A=3/B=1; B=1 stays on lorry in existing refusal hold; sound release follows policy/proof; no extra receipt or credit | Not run |
| Quality refusal / full refusal | Company-owned QC case with original source identity; full refusal closes native Session without DN; original customer pickups unchanged | Not run |
| Draft DN / proof / duplicate submit feedback | No premature Processed/stock deduction on a Draft; proof still required; repeated submission feedback creates no second consumption | Not run |
| Cancel unused pack / native Plan cancellation | Reasoned release+merge restores A=10/B=8; old QR unusable; original source incompatibility blocks correction atomically | Not run |
| Loaded cancellation | Unpack blocked across Warehouses; existing Supervisor stop cancellation/recovery governs stock; same QR identifies remaining lines for E5/D3/receipt | Not run |
| Lost response / refresh / readback / reasoned void | Original payload survives; readback resolves recorded pack; void tombstone blocks a late original Create | Not run |
| Native permissions / concurrent reservations | Company restrictions, operator/assistant/roles and server endpoint checks remain; real DB unique keys/locks prevent overlapping stock/Plan claims | Not run |
| Full-screen tablet and keyboard-wedge | Camera and Tab/Enter work; all numbered choices/quantities/reasons/confirm/cancel complete without pointer; focus restored on success/error/cancel | Not run |
| Existing container regression | Quantity Bin single-SKU partial fill, mixed complete-tag Logistics Container and Loose WIP Bin behave as before | Not run |

Offline automated evidence is recorded below after the final run. These tests exercise actual
application functions with explicit document/database/ERP-stock doubles, plus real browser DOM,
localStorage and Web Locks with simulated RPC/camera. They cannot certify native SQL isolation,
ERPNext valuation/serial-batch bundles, installed custom fields, permissions, printing or physical
operation. Record deployed Git SHA, document/ledger references, actual outcomes and exceptions here.

## Offline verification recorded 2026-11-26

- **630 Python tests passed** across Loose Tag, E2 reservations/E3 loading, prepared delivery,
  driver actions, Open Route sales, outcomes, recovery/reconciliation, trip handover/follow-on,
  cancellation, container move/release, certificates, schema/install, WIP, warehouse fulfilment
  and return-QC regression modules. The new Loose Tag module contains **26 scenarios**.
- **133 Node test results passed**, including existing custom harness files containing another
  **141 named assertions**. Coverage includes the real packing controller and real driver-screen
  adapter, two SKUs, accepted/refused editing, wrong-pack rejection, original-payload retry,
  cross-tab pending protection, numbered choices, camera/scanner paths and focus restoration.
- **13 real browser checks passed in Chrome 158 and 13 in Firefox 153**, using isolated profiles,
  a local fixture server, actual DOM/localStorage/Web Locks, and simulated RPC/camera. No live
  Desk page, physical printer or hardware scanner was used.
- Python syntax, JSON parsing and diff-whitespace checks passed. Two stale dependency omissions
  in the existing E4C offline fixture were reproduced at the baseline and repaired in that fixture;
  warehouse fulfilment production behaviour was not changed to satisfy them.

Representative commands, using Python 3.10+ and Node 22+:

```bash
python3 -B -m unittest cfg_kanban.tests.test_loose_tags -v
node --test cfg_kanban/tests/test_loose_tags_ui.cjs cfg_kanban/tests/test_driver_route_actions_ui.cjs
node cfg_kanban/tests/run_loose_tags_browser.mjs
CFG_BROWSER=firefox node cfg_kanban/tests/run_loose_tags_browser.mjs
```

The source/ERP-stock/database doubles in the Python flow test native dispatch reservation,
E3 identity/loading checks, native customer/route allocations, Delivery Note construction and
submission-feedback idempotency. Loading Stock Entry feedback and the Open Route Session-start
boundary are simulated; their independent regression fixtures also pass. Certificate inheritance
calls/provenance are exercised with the existing certificate regression suite, not a live certificate
inventory dimension. Tests do not establish deployed Frappe/ERPNext versions, valuation, native
transaction isolation, serial/batch bundles, real permissions, concurrency or printer output.

Limits to include in live testing: non-serialized stock only; unused-pack unpacking before vehicle
claim; a loaded Visit Only box must be accepted/refused or recovered through E5 before cancelling
that visit. Processed QR remains a remaining-stock identifier for E5/D3, not a new delivery label.

# CFG Kanban PPHU Handover Specification

Status: adopted development baseline, not production acceptance
Revision: V1.8 consolidation
Date: 10 November 2026

## 1. Purpose

PPHU extends CFG Kanban with scanner-first production handling, material-source boundaries,
warehouse-local rotation control, virtual operational inventory, partial manufacturing releases,
and a future industrial integration contract. It does not replace ERPNext manufacturing,
inventory, batch, QC, permission, or accounting records.

The normal floor path must be executable with a fixed keyboard-wedge barcode scanner. A keyboard
or touchscreen may be used for configuration, supervision, and exceptional recovery, but must not
be required for routine PPHU execution.

## 2. Source record and known limitation

This baseline was reconciled from:

- the code-verified CFG Kanban user manual;
- the locked Special DocType Card and DocType Action Engine specification;
- the available PPHU design conversation dated 9–10 November 2026;
- the current repository implementation and `AGENTS.md` product boundaries.

The available design record contains complete V1.5, V1.6, V1.7, and V1.8 discussions. It refers
to V1.1–V1.4, but those revisions were not available as separate retrievable source documents at
handover. This specification does not invent their wording. Any later recovered V1.1–V1.4 material
must be reconciled through the decision register below before it changes this baseline.

## 3. Locked system boundaries

1. ERPNext remains authoritative for Work Orders, Job Cards, Stock Entries, Batches, Serial and
   Batch Bundles, Quality Inspections, stock quantity, and accounting.
2. CFG Kanban owns dispatch, scanner execution, provisional physical movements, operational WIP,
   trace boundaries, handoffs, exception evidence, and reconciliation visibility.
3. A PPHU event is evidence, not an ERP stock transaction and not a QC release.
4. A machine-reported count is never automatically accepted as good stock.
5. ERP/Kanban must never command a PLC around machine safety interlocks. Emergency stops,
   hazardous motion, and real-time safety remain local to the machine/PLC.
6. Submitted ERP and immutable Kanban history are corrected through audited adjustment or reversal,
   never by rewriting released history.

## 4. Scanner-first contract

Every PPHU floor action must ship with all of the following in one package:

- stable `CFG:CMD:*` payload;
- global production-scanner dispatch;
- selectable printable command-label catalogue entry;
- Scanner Help and User Manual instructions;
- persistent scanner field throughout the workflow;
- `CFG:SELECT:1` through `CFG:SELECT:10` for safe ambiguity resolution;
- scanner quantities where a quantity applies;
- `CFG:CMD:CONFIRM`, `CFG:CMD:CANCEL`, and error focus restoration;
- operator-session, operation, workstation, Company, and state authorization;
- idempotent event token and immutable audit;
- automated contract coverage;
- kiosk/full-screen acceptance without mouse, touch, or ordinary keyboard use.

Physical Employee, Card, Station, Handling Unit, Stock Tag, Hopper, WIP Bin, and location identities
remain identity labels. They must not be disguised as command labels.

## 5. PPHU production-event model

The same validated event contract is used for operator scanners today and trusted industrial
adapters later. Initial event types are:

| Event | Physical input | Boundary input | Effect |
|---|---|---|---|
| PPHU Hopper Boundary | active Handling Unit of type Hopper | first affected output serial | records hopper start/change evidence |
| PPHU Material Batch Boundary | active released Stock Tag with Item and Batch | first affected output serial | records raw-material batch change evidence |
| PPHU Output Serial Start | none | first output serial | establishes the initial output serial context |

Each accepted event retains Card, Cycle, execution, Work Order, Job Card, Operation, Workstation,
operator Employee, operator session, terminal user, source type, source event ID, event time,
server receipt time, physical Handling Unit, Item, Batch, and output serial boundary.

Scanner and device retries use the same event token. Replaying the same token and identical payload
returns the original event. Reusing the token for different data is rejected.

The initial implementation records declared boundaries. It does not yet infer the previous ending
serial by subtracting one. That derivation is permitted only after continuous namespace, counter
reset, reject/gap, and transition-range rules are implemented and accepted. Mixed transition
material must support a range linked to both possible sources rather than false precision.

## 6. Industrial integration contract

Future PLC, SCADA, sensor, and edge-gateway adapters must use the same validated event service after
device authentication and Workstation authorization. They must not write Event rows directly.

Two channels remain separate:

- **Production Events**: counts, serial boundaries, hopper or batch changes, machine state, measured
  consumption, process evidence, and alarms.
- **Industrial Commands**: approved recipe/order/configuration instructions with command identity,
  revision, authorized source, target device, acknowledgement, timeout, and permitted device state.

The edge gateway should initiate secured outbound communication, buffer during network loss, and
deduplicate retries. A command receipt is not proof that a recipe loaded successfully. Public
internet access must never expose a PLC control interface directly.

## 7. Warehouse stock visibility and reconciliation

Universal Stock is company-wide visibility, not a company-wide FEFO queue. Every quantity is shown
by Company, Item, warehouse, Batch/lot, quality status, and physical/operational state.

The operator/supervisor indicator contract is:

- **Green**: effective Kanban balance is reconciled with authoritative ERP stock for that scope.
- **Orange**: an outstanding physical/Kanban movement, unposted consumption, pending release, or
  other explainable difference exists.
- **Red**: negative, impossible, unauthorized, expired, quarantined, or unreconciled conflict that
  blocks routine use.

The effective balance must show its components. A colour alone is not an accounting assertion.
ERP posting settles the corresponding provisional movement exactly once; it must not double-count
the earlier Kanban event.

## 8. Warehouse-local FIFO/FEFO

Rotation is evaluated for the actual outbound source warehouse, never over all Company stock.
The control key is Company + Item + source warehouse + eligible Batch/lot + stock/quality status.

The deterministic FEFO sequence is:

1. filter stock physically/effectively available in the configured source warehouse or explicitly
   configured eligible pick warehouses;
2. exclude expired, blocked, quarantined, held, incompatible, or unavailable stock;
3. apply customer minimum remaining shelf-life and other eligibility rules;
4. sort remaining stock by earliest expiry;
5. break equal-expiry ties with a defined warehouse-local receipt sequence;
6. require a scoped authorized override to bypass the resulting priority.

An outbound transfer uses the source warehouse's queue. Inbound receipt preserves Batch and expiry
and recalculates the destination warehouse's queue. Rotation policy is independent of ERP financial
valuation method.

## 9. Work Orders, shared preparation, and activity aggregation

Separate Work Orders may be used when machines or production criteria require separate ERP records.
One preparation station may feed multiple Work Orders, but every physical allocation and event must
identify the receiving Work Order/Job Card and cannot be counted twice.

Many Kanban activities may map to one ERP operation through an Operation Aggregation Profile:

- Manufacturing Operation: contributes eligible quantity/time to one mapped ERP Job Card;
- Production Support Activity: preparation/replenishment/evidence, without independent finished
  quantity;
- Quality/Release Activity: controls acceptance/release without creating artificial production.

Exact ERPNext v15 partial Job Card posting behaviour remains a live-site validation gate. CFG Kanban
must not assume that a submitted Job Card can be resubmitted for each partial release.

## 10. Partial production release and proportional settlement

One Work Order may have multiple Production Release Lots. Each lot freezes eligible output tags,
finished Batch, output quantity, material allocation, process losses, QC result, approval, and ERP
links. Released quantities cannot be released again.

When exact serial/material lineage exists, direct traceable allocation takes priority. Otherwise,
for each material and eligible source pool, cumulative proportional settlement is:

`new material posting = (total validated consumed × cumulative finished quantity released ÷ total validated good quantity produced) − material already posted`

Example: Kanban produced 800 pieces and validated consumption is 800 bags. Releasing 500 pieces
posts 500 bags. A later 200-piece release posts another 200 bags, leaving 100 bags attributable to
the remaining 100 produced pieces.

Rounding is cumulative using stock-UOM precision. Waste, setup consumption, QC samples, abnormal
loss, and final remainder require explicit disposition. Proportional allocation must never invent
Batch lineage. BOM caps, BOM variance controls, Skip-WIP behaviour, and the exact ERP Stock Entry
adapter remain site-tested gates before automatic posting is enabled.

## 11. Permission and QC gates

PPHU authorization is Employee-based and scope-specific. Independent capabilities are required for:

- operation completion;
- Handling Unit closure;
- partial Production Release approval;
- final Master close;
- FIFO/FEFO override;
- material-variance disposition;
- ERP posting/recovery;
- industrial command approval where enabled.

Failed or held QC material remains ineligible. Where procedure requires separation of duties, the
person recording the critical QC result cannot approve their own failed-result disposition.

## 12. Delivery sequence

1. Adopt this specification and immutable scanner/device event backbone.
2. Complete serial namespace, gap/reset, transition-range, Hopper-load, and Batch-boundary rules.
3. Build warehouse reconciliation components and Green/Orange/Red evidence.
4. Build warehouse-local FIFO/FEFO suggestion and scoped override.
5. Add Operation Aggregation Profile and shared-station multi-Work-Order allocation.
6. Add Production Release Lot, exact allocation, cumulative proportional settlement, and explicit
   loss/remainder disposition.
7. Validate ERPNext v15 Work Order, Job Card, Skip-WIP, Batch, QC, and Stock Entry behaviour on the
   deployed site before enabling posting automation.
8. Add authenticated edge/device registry and buffered event ingestion.
9. Add industrial-command channel only after independent safety and hardware validation.

## 13. Acceptance gates

- Existing Employee login, command QR, function keys, scanner quantity, focus recovery, operation,
  WIP, and material workflows continue to pass.
- PPHU dialogs complete in kiosk mode using only a keyboard-wedge scanner.
- Ambiguous operation selection never silently chooses a target.
- Unauthorized Company/Workstation/operation/Handling Unit scans are rejected.
- Same-token/same-payload retry is idempotent; same-token/different-payload is rejected.
- PPHU evidence never changes ERP stock, QC state, or machine state by itself.
- PLC/SCADA inputs pass the same business validation as scanner inputs.
- ERP posting automation remains disabled until site-specific gates are recorded as passed.

## 14. Decision register

| ID | Locked decision |
|---|---|
| PPHU-D01 | Routine PPHU floor operation is scanner/sensor first; keyboard/touch is not mandatory. |
| PPHU-D02 | ERPNext remains the manufacturing, inventory, Batch, QC, and accounting authority. |
| PPHU-D03 | Scanner, sensor, PLC, and SCADA inputs converge on one validated event contract. |
| PPHU-D04 | FEFO/FIFO is evaluated per actual source warehouse, not Company-wide. |
| PPHU-D05 | Transfers preserve Batch/expiry and recalculate rotation in the destination warehouse. |
| PPHU-D06 | Exact trace allocation precedes proportional allocation. |
| PPHU-D07 | Partial settlement is cumulative and cannot double-post consumption. |
| PPHU-D08 | Many Kanban activities may aggregate to one ERP operation without duplicating output. |
| PPHU-D09 | Separate Work Orders may share a preparation station with exact allocation identity. |
| PPHU-D10 | Serial boundaries are change-driven; gaps, resets, and transition ranges prevent false precision. |
| PPHU-D11 | Production events and industrial commands are separate channels. |
| PPHU-D12 | PLC safety control remains local and independent of ERP/internet availability. |
| PPHU-D13 | Missing V1.1–V1.4 source text must be reconciled if recovered; it is not silently invented. |

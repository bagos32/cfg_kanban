# CFG Kanban V2 — Required Planning and Deferred Enhancements

**Status:** Mandatory review list for V2 planning
**Recorded:** 18 October 2026

## Purpose

This file prevents agreed V2 requirements from being lost between development chats. At the start
of V2 planning, review every item with the user. V2 must not be declared complete until each item
is implemented, rejected, or explicitly deferred again with the decision recorded here.

These items do not block V1 acceptance. V1 remains the reliable execution, ERP feedback, scanning,
WIP, closure, recovery, authorization, task, and audit foundation.

## Core V2 TPS scope

- time-study observations with operator, operation, workstation, product, and Cycle context;
- takt calculation using real available production time and demand;
- Standard Work Combination analysis covering manual work, machine work, walking, waiting, and
  overlapping work;
- workstation and line capacity analysis, including parallel lanes;
- actual-versus-standard time and output comparison;
- controlled Kaizen proposals with evidence and revision history; and
- immutable standard/revision snapshots on released Cycles.

## Deferred WIP-bin enhancements that must be reviewed

### State ageing and Andon escalation

- configurable age thresholds by Pool and lifecycle state;
- visual warning and critical bands for `Reserved`, `Ready`, `In Use`, Draft, and Exception states;
- ageing measured from the appropriate immutable lifecycle timestamp; and
- no automatic stock or bin-state mutation when a threshold is crossed.

### Supervisor notifications

- notify only on meaningful threshold crossing, new mismatch, or unresolved reconciliation;
- configurable recipients/escalation path without exposing unrelated Company data;
- deduplication and acknowledgement so repeated refreshes do not create alert noise; and
- direct links to the authoritative load, ERP document, or reconciliation.

### Utilization, turnover, waiting, and capacity

- full/empty cycle count and turnaround time by physical bin and Pool;
- time spent waiting for transfer submission, consumption, or reconciliation;
- available-bin count versus operation demand and parallel workstation capacity;
- shortage/overcapacity indicators without treating Kanban counts as ERP stock; and
- historical reporting based on immutable load episodes rather than overwritten current state.

### Cleaning and inspection readiness

- optional controlled clean/inspect requirement before an Empty bin is released for refill;
- scanner-friendly confirmation and responsible Employee evidence;
- configurable applicability by Pool/bin type so it is not forced on every production process;
- failed inspection places the bin on Hold/Exception and prevents allocation; and
- TrackQMS owns approved sanitation/SOP wording when the optional connector is installed. CFG
  Kanban remains independently usable and stores only its execution evidence and neutral revision
  snapshot.

## V2 entry check

Before starting these enhancements:

1. Complete the V1 server acceptance in
   `docs/TEST_STANDARD_QUANTITY_WIP_BIN_TRANSFER_GATE.md`.
2. Confirm which alerts and thresholds are operationally useful at the Gemba.
3. Confirm the Company, Pool, Workstation, and supervisor visibility boundaries.
4. Agree which statistics are live controls and which are historical Kaizen evidence.
5. Preserve ERPNext as stock/manufacturing authority and preserve every existing audit record.

## V2 exit check

Record one status beside every core and deferred item: `Implemented`, `Rejected`, or
`Explicitly Deferred`. An omitted item is not an accepted decision.

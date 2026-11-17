# Production queue/readiness investigation — 17 November 2026

Base revision: `0fa8e09`. Uncommitted preparation, not site acceptance.

## Confirmed and corrected

- Workstation Queue now reads open Process Executions as its source of truth and
  overlays saved dispatch ordering/priority. Missing or stale dispatch projections
  cannot hide an otherwise eligible execution or misreport its live status. Company
  and operation scopes remain enforced; opening the queue does not write records.
- Normal Work Order Job Card mirroring now snapshots the configured Completion Rule
  when it creates an execution, matching runtime Process/Station Card allocation.
  Previously the missing field inherited the DocType default Full Qty.
- Existing execution snapshots are preserved during resync. A current Master edit
  cannot safely identify the intended release-time setting of an older execution.
  Review the affected records before choosing a controlled correction.

## Still unresolved — affected record/error required

The reported minimum-handover Start rejection is not yet reproduced. Start also
checks crew, certificates, configured Hopper preparation, ERP material readiness,
Before Operation Start tasks and prerequisite After Operation Complete tasks. Meeting
an input threshold alone does not satisfy these independent gates. No gate was
removed or weakened. Request Card/Master, Work Order/Job Card, workstation, exact
Start error and whether the cycle predates the setting change.

Clarify whether “task” means a production execution/Job Card or a non-quantity
Process Task. The Workstation Queue change above concerns production executions;
it does not silently add Process Tasks to an operation dispatch queue.

## Offline validation

82 targeted Python tests passed, including 7 new real-function regression cases,
runtime dispatch, runtime operation-cycle closure and schema contracts.
`git diff --check` passed. No commit, push, pull, migration or deployment was run.

## Site checks — not run

1. Ready execution with missing/stale dispatch row appears at the correct workstation.
   Saved supervisor order/priority and Company/operation restrictions remain intact.
2. Live transitions Ready → In Progress → Paused → Completed regroup/remove the row.
3. New mirrored execution snapshots Operator Complete; blank profile defaults Full Qty.
   Resync does not rewrite an existing execution's snapshot.
4. Reproduce the actual threshold rejection with the provided records/error, inspect
   released/available quantities and every independent Start gate, then add a targeted
   regression and verify the resulting fix on site.
5. Inspect existing affected completion snapshots separately; do not rewrite completed
   history or claim old active cards were repaired by the creation-path fix.

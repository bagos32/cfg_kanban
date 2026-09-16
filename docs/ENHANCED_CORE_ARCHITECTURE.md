# CFG Kanban Enhanced V1 Core Architecture

This document records the consolidated, additive architecture. It does not replace the existing
Production Kanban implementation.

## System boundary

ERPNext remains the system of record for Items, BOMs, Operations, Work Orders, Job Cards, Stock
Entries, Warehouses, Batches, inventory, and accounting. CFG Kanban controls signals, dispatch,
operator identity, incremental progress, WIP handoffs, prerequisite tasks, service work, and
operational visibility.

## Three work types

| Work type | Runtime record | ERP manufacturing document | Quantity/WIP |
|---|---|---|---|
| Production operation | CFG Kanban Process Execution | ERPNext Job Card | Yes |
| Production process task | CFG Kanban Process Task | None | No; may block a production gate |
| Standalone service task | CFG Kanban Task | None | No; independent of production cycles |

## Production control

The existing unlimited and parallel Job Card model remains authoritative. Each effective ERPNext
Job Card has a Process Execution lane. Operation Summary combines parallel lanes and WIP Ledger
controls released and consumed quantities between operations.

Process Task Profiles are configured on the Kanban Master. Runtime tasks are instantiated once per
Cycle and can guard these points:

- Before Cycle Start
- Before Operation Start
- After Operation Complete
- Before WIP Release
- Before FG Release
- Before Cycle Close

Tasks support checklists, dynamic fields, independent supervisor verification, expiry, and reuse of
a still-valid completion for the same Master, asset, or workstation. An explicit invalidation action
expires reusable task completions after a contamination, setup change, safety event, or similar
operational change.

## Standalone service control

Task Schedules define housekeeping, maintenance, inspection, safety, environmental, vehicle, and
emergency work. Trigger types are Time Interval, Calendar Schedule, Meter / Usage, Manual Request,
Condition, and Emergency Event. The scheduler generates time/calendar tasks and marks overdue work;
other triggers use the controlled request API.

Standalone tasks cannot own a Kanban Cycle, Process Execution, Work Order, or Job Card. Their model
validation enforces that boundary.

## Shared operator and form services

All shop-floor mutations use the existing Employee-based Operator Profile and Operator Session.
The same permission map controls production and service task start, completion, and verification.
The dynamic field definition and validation service is shared by Process Executions, Process Tasks,
and standalone Tasks. Historical values are stored as CFG Kanban Execution Value rows.

## Card identities

Production card types remain unchanged. Asset Card, Location Card, and Task Card add non-production
identities. Scanning them displays matching service work and never triggers a production Signal or
manufacturing document. Task Cards may create an idempotent manual service request.

## Audit and recovery

Process Task and standalone Task events use the existing CFG Kanban Event stream. Both domains can
link Exceptions. Transaction history is preserved; cancellation, expiry, invalidation, reconciliation,
and recovery are preferred over deletion.

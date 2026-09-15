# CFG Kanban Control Center — Locked Architecture

## Decision

CFG Kanban will provide one configurable Control Center backed by shared live-data services. It will support unlimited saved screen profiles rather than separate custom code for each physical display.

## Views

1. Management Overview: performance, progress, exceptions, lead time, output, rejection, WIP, ERP synchronization, and historical review.
2. Production Floor: plant queue, supervisor sequence control, and saved station displays.
3. Warehouse Response: warehouse-specific demand, readiness, picking, transfer, dispatch, receipt, shortage, and WIP response.
4. Logistics and Delivery: batch, FG receipt, quality, handling unit, loading, delivery readiness, and exceptions.
5. Sales Progress: customer order, authorized tolerance, production, batch, completion, delivery, and delay visibility.

## Saved display profiles

One profile can select one or many workstations. Profiles may represent a station, area, line, workstation group, whole floor, warehouse, sales view, or logistics view. A profile stores filters, queue depth, refresh rate, layout, access mode, and visible information. Each profile has a stable route such as `/app/kanban-floor?profile=Cooking-Area-TV`.

## Workstation display requirement

Every selected workstation shows current work and its upcoming queue. Multi-workstation profiles also show combined target, completed quantity, remaining quantity, active capacity, available capacity, WIP readiness, blocking reasons, and ERP synchronization alerts.

## Sequence ownership

Operational sequence belongs to a dispatch layer at Process Execution/workstation level, not to the BOM operation sequence and not directly to the whole Cycle. Waiting, Released, and Ready work may be reordered. Active work requires a controlled pause/expedite workflow. Every override requires a reason and creates an audit event.

Read-only floor displays can view sequence. Operators act only on assigned stations. Supervisors may reorder, expedite, pause, and reassign within permission and readiness rules. Warehouse, Sales, Logistics, and Management views cannot silently modify production sequence.

## System boundary

ERPNext remains the system of record for manufacturing and stock documents. CFG Kanban provides process control, queue dispatch, readiness, handoff, WIP, scanning, alerts, and visual management. Dashboard actions must never bypass ERPNext document validation.

## Delivery phases

Phase 1 establishes Dashboard Profiles, shared filtering, live refresh, Plant Queue, saved multi-workstation displays, and persistent supervisor dispatch control with sequence audit.

Phase 2 adds Sales and Logistics views, deeper KPIs, announcements, and team-oriented performance indicators.

## Dispatch Queue and Supervisor Sequence Control

Each workstation receives a persistent `CFG Kanban Dispatch Queue` projection, with one unique row per Process Execution. The queue controls operational dispatch order only. It never rewrites the BOM operation order, Work Order route, or ERPNext Job Card sequence.

System recommendation establishes the initial order from readiness, cycle priority, and creation time. A user with Manufacturing Manager or System Manager role can use a Dashboard Profile in Supervisor mode to drag queued work, move it earlier or later, or mark it urgent. Active or paused work cannot be displaced by a sequence override.

Every supervisor action requires a reason and creates an append-only `CFG Kanban Sequence Change` record plus a Kanban Event. Row locking serializes changes made by two supervisors at the same workstation. Existing Process Executions are reconciled into the queue when a dashboard first loads; future execution changes synchronize through document events.

### Controlled interruption

An Operation Profile defaults to `Interruption Prohibited`. A supervisor may use **Pause and Give Way** only after selecting a Ready replacement on the same workstation and recording the WIP disposition, machine condition, reason, and optional expected resume time. `Compatible Items Only` additionally requires identical Setup Family and Cleaning Class values on the interrupted and replacement operation profiles.

Kanban records the execution as Paused in a separate dashboard section while retaining the Job Card, cumulative output, batch identity, runtime allocation, and remaining quantity. Normally no ERP timer is changed because Kanban progress is posted as completed Job Card time-log entries. If an ERP Job Card timer is genuinely open, the pause closes that row and records the timer mode; resume then opens a new row. **Resume Paused Work** is blocked while another execution remains In Progress on the workstation.

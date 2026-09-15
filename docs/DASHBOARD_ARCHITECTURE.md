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

Phase 1 establishes Dashboard Profiles, shared filtering, live refresh, Plant Queue, saved multi-workstation displays, Management Overview, Warehouse Response, and sequence audit foundations.

Phase 2 adds full supervisor drag-and-drop dispatch, Sales and Logistics views, deeper KPIs, announcements, and team-oriented performance indicators.

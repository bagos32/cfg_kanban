# TrackQMS-Kanban Connector

Optional Frappe integration between independent TrackQMS and CFG Kanban applications.

## Initial scope

1. App availability and version compatibility checks.
2. Stable process/work-step/Kanban mapping records.
3. Approved TrackQMS revision publication into a Kanban update proposal.
4. Immutable standard revision snapshot for newly released Kanban Cycles.
5. Kanban Kaizen proposal submission into TrackQMS change control.
6. Synchronization command, conflict, retry, and audit records.
7. Same-site operation first; versioned API/webhook transport later.

The connector must not make either core application unusable when the other is absent.

# CFG Platform Integration Boundary

## Purpose

This document keeps CFG Kanban, TrackQMS, and their optional connector independently deployable.
It is the Kanban-side contract until a dedicated platform architecture repository is established.

## Independent applications

| Application | Required dependency | Owns |
|---|---|---|
| CFG Kanban | Frappe and ERPNext | Production control, scanning, cycles, WIP, execution observations, takt/capacity analysis, and Kaizen proposals |
| TrackQMS | Preferably Frappe only | Controlled documents, Standard Work Packages, SOP/work-step revisions, DCC approval, quality/safety controls, training, and certification evidence |
| TrackQMS-Kanban Connector | CFG Kanban and TrackQMS | Mappings, publication, synchronization, conformance results, conflict handling, and integration audit |

Installing or removing the connector must not invalidate either core application's records.

## Version terminology

- CFG Kanban V1: reliable execution foundation.
- CFG Kanban V2: time study, takt, Standard Work Combination, capacity, and Kaizen analysis.
- CFG Kanban V3: optional TrackQMS integration.
- TrackQMS Source Guide V4.0: revision of the documentation framework, not a CFG Kanban release.

## Shared aggregate

The shared business aggregate is a **Standard Work Package**. Stable identities are required for:

- process;
- work step;
- controlled document;
- document revision;
- standard-work revision;
- external system and tenant/site.

Labels and descriptions may change. Stable IDs must not be reused for a different logical process
or step.

## Authority matrix

| Data | Authority |
|---|---|
| Approved SOP and work-step wording | TrackQMS |
| Quality, food-safety, safety, and acceptance criteria | TrackQMS |
| DCC status, effective dates, and controlled revision | TrackQMS |
| Training, competence, and certification requirements | TrackQMS |
| Work Orders, Job Cards, Quality Inspections, stock, and batches | ERPNext |
| Dispatch, runtime execution, WIP, and handoff | CFG Kanban |
| Raw time observations and operational deviations | CFG Kanban |
| Takt and capacity calculation | CFG Kanban V2 |
| Approved standard time | TrackQMS after controlled approval of V2/Kaizen evidence |
| Kaizen proposal | CFG Kanban proposal; TrackQMS approval |

## Publication flow

1. TrackQMS approves and publishes an effective Standard Work Package revision.
2. The connector validates identifiers, mappings, signatures/checksum, and effective dates.
3. The connector creates a reviewable Kanban standard update proposal.
4. A production supervisor confirms operational mappings.
5. Kanban activates a local immutable snapshot for new Cycles.
6. Existing Cycles keep their original snapshot.

Draft TrackQMS content must never become a live production instruction automatically.

## Kaizen return flow

1. Kanban records actual performance or a process deviation.
2. An authorized user creates a Kaizen/change proposal containing evidence and affected step IDs.
3. The connector submits the proposal to TrackQMS.
4. TrackQMS performs Gemba, QA/food-safety, supervisor, and DCC review.
5. Approval creates a new controlled revision; rejection leaves the current standard unchanged.
6. An approved revision returns through the normal publication flow.

## Failure isolation

- TrackQMS unavailability must not corrupt or rewrite ERPNext/Kanban transactions.
- Kanban may continue only with a still-valid locally snapshotted revision and applicable policy.
- Withdrawal or expiry of a critical standard may block new Cycles but must not silently rewrite a running Cycle.
- Every cross-app request requires an idempotency key, status, attempt count, last error, and immutable audit event.
- Conflicts require explicit resolution; last-write-wins synchronization is prohibited.

## Neutral references in CFG Kanban

Kanban Core may store values such as source system, external process ID, external step ID, external
revision ID, checksum, effective dates, and snapshot payload. It must not require TrackQMS DocTypes.
The connector may add cross-app UI and Dynamic Links only when both apps are installed.

## Development workspace

Recommended local arrangement:

```text
CFG-Platform/
  cfg_kanban/
  track_qms/
  track_qms_kanban/
  platform_architecture/
```

Use the individual repository projects for core work and the parent `CFG-Platform` project for
cross-application review. Do not commit changes from one repository as part of another repository's
release.

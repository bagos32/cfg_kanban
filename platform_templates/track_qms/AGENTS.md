# TrackQMS Repository Working Rules

## Source of truth

- The TrackQMS functional source is `CFG Shinka Professional Assistant Auto-Document Generation Project Guide V4.0` and later explicitly approved revisions.
- The guide's V4.0 is a documentation-framework revision, not the TrackQMS application release and not the CFG Kanban release.
- Preserve earlier TrackQMS discussions and implementation evidence. Rebuild definitions additively and record superseded decisions rather than deleting history.

## Product boundary

- TrackQMS is an independent controlled-documentation and QMS engine suitable for manufacturing and service organizations.
- TrackQMS Core should depend on Frappe only where practical. ERPNext Quality and CFG Kanban integrations are optional adapters/connectors.
- Never add mandatory CFG Kanban, Work Order, Job Card, or manufacturing-only links to TrackQMS Core.
- TrackQMS owns Standard Work Packages, processes, stable work-step identities, controlled SOP revisions, DCC approval, visual aids, checklists, risk/acceptance criteria, training, competence, and certification evidence.
- Draft content must not be exposed as approved operational instruction.
- Gemba verification, QA/food-safety review, supervisor review, DCC control, training release, and effective dates must remain auditable.
- Approved records are immutable. Corrections create a new revision or controlled supersession.

## Optional integrations

- ERPNext-specific quality integration belongs in an optional `track_qms_erpnext` adapter or guarded integration module.
- CFG Kanban integration belongs in the independent `track_qms_kanban` connector.
- Publish versioned contracts using stable external IDs, effective dates, checksums, and idempotency keys.
- A Kanban Kaizen submission is a change proposal, not an authorized SOP update.

## Git and deployment ownership

- The user performs commits, pushes, pulls, migrations, builds, cache clearing, and restarts manually.
- Codex prepares and validates changes but must not run `git commit`, `git push`, or `git pull` without a specific one-time override.
- Do not automatically deploy or modify a server.
- When deployment is requested, provide one copy-paste Mac Bash block and one copy-paste server Bash block using the actual repository/worktree, configured remote, bench, site, and app name.
- Do not commit credentials, secrets, generated environment files, unrelated changes, or server-specific configuration.

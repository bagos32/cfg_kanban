# TrackQMS-Kanban Connector Repository Working Rules

## Purpose and dependencies

- This is an optional integration app. It may depend on both `track_qms` and `cfg_kanban`.
- Neither core app may depend on this connector.
- Do not move core QMS behavior or core Kanban execution behavior into the connector.
- Follow the platform authority matrix and versioned integration contract.

## Connector responsibilities

- Map stable Standard Work Package, process, work-step, Kanban Master, operation, and workstation identities.
- Publish only approved/effective TrackQMS revisions to reviewable Kanban update proposals.
- Store immutable publication snapshots and checksums; never make running Cycles follow a mutable remote record.
- Send Kanban observations and Kaizen proposals to TrackQMS change control without directly editing approved SOPs.
- Record synchronization commands, idempotency keys, attempts, results, conflicts, and exceptions.
- Provide explicit conflict resolution. Last-write-wins behavior is prohibited.
- Degrade safely when either app or a remote site is unavailable.

## Compatibility

- Declare and test compatible TrackQMS, CFG Kanban, Frappe, and ERPNext version ranges.
- Guard hooks and UI extensions so a disabled integration does not break either core app.
- Support same-site integration first while keeping API contracts suitable for separate sites later.
- Use least-privilege service identities for cross-site operation.

## Git and deployment ownership

- The user performs commits, pushes, pulls, migrations, builds, cache clearing, and restarts manually.
- Codex prepares and validates changes but must not run `git commit`, `git push`, or `git pull` without a specific one-time override.
- Do not automatically deploy or modify a server.
- When deployment is requested, provide one copy-paste Mac Bash block and one copy-paste server Bash block using the actual repository/worktree, configured remote, bench, site, and app name.
- Do not commit credentials, secrets, generated environment files, unrelated changes, or server-specific configuration.

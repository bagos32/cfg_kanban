# CFG Platform Integration Working Rules

## Scope

- This workspace exists for cross-application architecture, compatibility review, and connector development.
- CFG Kanban, TrackQMS, and TrackQMS-Kanban remain separate Git repositories and separately installable applications.
- Do not commit changes from one repository as part of another repository's release.
- Read each child repository's `AGENTS.md` before modifying that repository.

## Authority and dependency direction

- ERPNext owns manufacturing and inventory transactions.
- CFG Kanban owns production control, runtime execution, WIP, takt/capacity analysis, and Kaizen proposals.
- TrackQMS owns controlled Standard Work Packages, SOP/work-step revisions, DCC approval, quality/safety controls, training, and certification evidence.
- The connector may depend on both core apps. Neither core app may depend on the connector or require the other core app.
- Cross-app changes use stable external IDs, immutable revision snapshots, checksums, idempotency keys, and explicit conflict handling.
- Draft QMS content must never silently become a live production standard.

## Git ownership

- The user performs all commits, pushes, pulls, deployments, migrations, builds, cache clearing, and restarts.
- Codex prepares and validates changes but must not run Git commit/push/pull or deploy without an explicit one-time override.
- Preserve unrelated work and never place secrets or environment-specific configuration in a repository.

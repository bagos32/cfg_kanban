# CFG Kanban Repository Working Rules

## Git and deployment ownership

- The user performs all Git commits, pushes, server pulls, migrations, builds, cache clearing, and restarts manually.
- Codex must prepare and validate code changes, but must not run `git commit`, `git push`, or `git pull` unless the user explicitly overrides this rule for that specific action.
- Do not automatically deploy or change the development server.
- When the user says it is time to commit, push, pull, or deploy, provide exactly two copy-paste Bash blocks:
  1. One Mac block containing the correct worktree directory, `git status`, `git add`, `git commit`, and `git push origin HEAD:main`.
  2. One server block containing the app directory, `git status`, `git pull upstream main`, bench directory, migrate, build, clear-cache, and restart commands.
- Keep every related command in its respective single Bash block; do not split commands into separate code blocks.
- Use the actual current Codex worktree path in the Mac block. Never substitute the original project checkout when work was prepared in a Codex worktree.
- Use this development server deployment sequence unless the user supplies different values:
  - Bench: `~/frappe-bench`
  - App: `~/frappe-bench/apps/cfg_kanban`
  - Site: `site1.local`
  - Server Git remote: `upstream`
- Do not commit generated files, unrelated user changes, credentials, server configuration, or environment-specific secrets.

## Product boundaries

- ERPNext remains the system of record for Work Orders, Job Cards, Stock Entries, batches, and stock.
- CFG Kanban is the process-control, dispatch, scanning, WIP, handoff, and operational visibility layer.
- Preserve audit records. Prefer controlled cancellation, reconciliation, and recovery workflows over deleting transactional Kanban history.
- Keep workstation/execution behaviour changes separate from Production Control Dashboard work when they are being developed in different worktrees.

## Version roadmap and TrackQMS boundary

- V1 is the reliable execution foundation: cards, signals, cycles, ERPNext feedback, WIP, operator authorization, tasks, audit, closure, and recovery.
- V2 adds time study, takt, Standard Work Combination, capacity analysis, actual-versus-standard results, and controlled Kaizen proposals.
- V3 adds optional integration with the independent TrackQMS app. TrackQMS guide revision V4.0 is the TrackQMS documentation source revision; it is not CFG Kanban V4.
- CFG Kanban must remain installable and operational without TrackQMS.
- Never add a mandatory Link field, import, hook, migration, or runtime dependency from CFG Kanban Core to a TrackQMS DocType.
- Store optional QMS references as neutral external identifiers and immutable revision snapshots. Cross-app navigation and synchronization belong in the connector app.
- TrackQMS owns approved SOP wording, controlled work-step revisions, quality/safety acceptance criteria, document approval, and competence requirements.
- CFG Kanban owns dispatch, runtime allocation, execution observations, takt/capacity calculations, WIP, handoffs, and Kaizen proposals. ERPNext remains the manufacturing system of record.
- A Kanban Kaizen proposal must never directly overwrite an approved TrackQMS SOP. It must pass through TrackQMS change control and return as a newly approved revision.
- Running and historical Cycles retain the exact standard/SOP revision snapshot used when they were released.
- Follow `docs/PLATFORM_INTEGRATION_BOUNDARY.md` for shared identifiers, publication rules, failure isolation, and connector responsibilities.
- Follow `docs/SHARED_MEDIA_STORAGE.md` and the approved cross-app media architecture for every photo, video, document, and derivative. S3 is the binary system of record; never persist presigned URLs or create a mandatory cross-app media dependency.

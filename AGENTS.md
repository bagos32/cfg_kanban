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

## Pre-production acceptance gate

- Development may continue while detailed package acceptance is deferred, but implementation status must never be presented as production acceptance.
- Before recommending, enabling, or declaring production mode/go-live, explicitly remind the user that Package L1 same-Company Transfer Kanban is only partially tested and must be completed against `docs/TEST_PACKAGE_L1_TRANSFER_KANBAN.md`.
- The Package L1 gate must cover Direct Transfer without tags, tagged and optional-tag transfer, Goods in Transit, draft ERP feedback, cancellation/recovery, authorization rejection, quantity/warehouse rejection, and recorded ERPNext/Kanban audit evidence.
- Do not close this gate from chat recollection. Record the final test results and deployed Git revision in the L1 test document, including every accepted exception or deferred risk.

## Production scanner-first standard

- Every new or changed Production Kanban floor action must be operable by fixed keyboard-wedge scanner as well as by touch/click. A screen-only production action is incomplete.
- Each production action must ship together with: a stable `CFG:CMD:*` payload, global scanner dispatch, a selectable printable command-label catalogue entry, Scanner Help and User Manual guidance, correct focus restoration after success/error/cancel, and automated contract coverage.
- Dialogs opened by a scanner command must remain scanner-operable through completion. Provide scanner commands for confirmation, cancellation, quantities, numbered choices, and physical tag/bin identity wherever those inputs apply.
- When several safe targets are eligible, use the standard numbered `CFG:SELECT:1` through `CFG:SELECT:10` flow. Never silently choose an ambiguous Work Order, Job Card, material row, bin, or operation.
- Physical Card, Employee, Handling Unit, Stock Tag, WIP Bin, Station, and location identities remain their own printable operational labels; do not disguise identity scans as command labels.
- Controlled reversal, correction, or exceptional approval may require a reason and Supervisor authority, but the routine floor path and its safe cancel path must still be scanner-accessible.
- Acceptance is not complete until the action is verified in kiosk/full-screen mode without mouse, touch, or keyboard use beyond the scanner itself.

## Version roadmap and TrackQMS boundary

- V1 is the reliable execution foundation: cards, signals, cycles, ERPNext feedback, WIP, operator authorization, tasks, audit, closure, and recovery.
- V2 adds time study, takt, Standard Work Combination, capacity analysis, actual-versus-standard results, and controlled Kaizen proposals.
- At the start of V2 planning, explicitly remind the user to review `docs/V2_DEFERRED_ENHANCEMENTS.md`. Do not close V2 scope until every listed item is implemented, rejected, or explicitly deferred by the user with the decision recorded.
- The V2 review must include the deferred WIP-bin enhancements: configurable state-age/andon thresholds, supervisor escalation notifications, bin utilization/turnover/waiting/capacity analysis, and controlled cleaning/inspection readiness. These are V2 enhancements, not V1 WIP-bin acceptance blockers.
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

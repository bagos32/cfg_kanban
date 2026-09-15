# CFG Kanban Repository Working Rules

## Git and deployment ownership

- The user performs all Git commits, pushes, server pulls, migrations, builds, cache clearing, and restarts manually.
- Codex prepares and validates changes but must not run `git commit`, `git push`, or `git pull` unless the user explicitly overrides this rule for that specific action.
- When deployment is requested, provide exactly two copy-paste Bash blocks: one Mac block and one server block.
- Keep all related commands inside their respective single Bash block.
- The Mac block must use the current Codex worktree path and include `git status`, `git add`, `git commit`, and `git push origin HEAD:main`.
- The server block must use `~/frappe-bench/apps/cfg_kanban`, `git pull upstream main`, `~/frappe-bench`, migrate `site1.local`, build the app, clear cache, and restart.
- Never commit unrelated changes, credentials, secrets, generated environment files, or server-specific configuration.

## Product boundaries

- ERPNext remains the system of record for Work Orders, Job Cards, Stock Entries, batches, and stock.
- CFG Kanban controls dispatch, scanning, WIP, handoff, operational sequencing, and visibility.
- Preserve transactional audit history through controlled cancellation and reconciliation.
- Dashboard work belongs in this worktree. Workstation/execution engine changes remain in their dedicated worktree until intentionally integrated.

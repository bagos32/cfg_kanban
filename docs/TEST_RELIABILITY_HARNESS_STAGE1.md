# Reliability regression harness: first slice

Status: **Narrow retry and operation-authorization fixes implemented locally, not deployed. Initial baseline failures reproduced, then offline tests passed. No ERP site tests run.**

## What exists

`cfg_kanban/tests/test_certificate_retry_behavior.py` imports the actual certificate service with in-memory Frappe/dependency doubles. It does not connect to a site, database or network. It checks:

1. Replaying committed good60 against selected100 must return existing result, not recount120.
2. Replaying that committed event after closure must remain replayable.
3. Run operation/workstation must reach server authorization even before replay returns data.

The original three-test baseline reproduced two mutable-state/capacity errors and one
missing-scope failure. At the 2026-11-12 handover the backend module had 13 passing checks;
that historical result did not cover frontend retry durability or create/persist/replay.

The current slice adds an explicit outcome endpoint: a validation failure is rolled back to
a savepoint while retaining the pre-acquired Run lock, and only an absent token receives
`rejected`. Existing-token conflicts and legacy rows remain errors. Unexpected errors stay
ambiguous. Neither endpoint explicitly commits. Frappe POST transaction completion must be
verified on the test site before relying on its delivered acknowledgement.

The frontend persists token and evidence before sending, restores pending requests on reopen
and refresh, and accepts only correlated recorded/rejected responses. Only confirmed rejection
unlocks correction. Web Locks serialize tabs on one browser origin; stale dialogs cannot create
another micro-lot when another dialog acknowledges the pending request. Credentials are not
stored with this intent. HTTPS/localhost, Web Locks and working browser storage are required.
Cleared storage, different origins/devices and independent physical re-entry remain outside this
browser safeguard: inspect progress evidence with a supervisor rather than bypassing uncertainty.

Run only this offline module from the app checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_certificate_retry_behavior -v
```

The regression suite must exit zero after this patch. Do not suppress failures, mark them expectedFailure, or weaken assertions merely to get green. Mocks establish control-flow defects, not stock transaction correctness or an exploitable authorization bypass.

## Implemented scope and remaining work

- All six operator certificate mutations now apply persisted operation scope after credential validation. Workstation is forwarded only if present; the current run schema does not define it.
- Partial progress requires a nonempty token and stores an immutable canonical request fingerprint. Authorized identical replay precedes mutable state/capacity checks. Changed payload is rejected.
- Existing progress rows are not rewritten. A replay of a legacy row without a fingerprint is rejected with an evidence-review message; do not resubmit it using a fresh token.
- New fingerprint field requires the user-operated normal migrate before exercising the deployed service. No migration was run here.
- Negative tests cover quantities/evidence changes, missing token, legacy evidence, revoked session, operation/workstation rejection and new-event capacity.

### Current offline verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_certificate_retry_behavior cfg_kanban.tests.test_certificate_process_runtime cfg_kanban.tests.test_certificate_process_recovery cfg_kanban.tests.test_process_certificate_foundation cfg_kanban.tests.test_certificate_process_release_interface -v
node cfg_kanban/tests/test_certificate_progress_retry_ui.cjs
git diff --check
```

The Python tests use in-memory dependencies or source/schema contracts. The JavaScript runner
executes the actual dialog/scanner functions with browser and Frappe doubles; it does not launch
a browser. Neither runner verifies real transaction rollback, database locking, concurrency,
scanner focus, ERP posting, native ledgers or kiosk behavior. Record final observed counts in the
work-chat report; do not equate these with the historical broader inventory.

Observed 2026-11-12: 48 Python checks and 14 JavaScript behavioral checks passed; the panel
also parsed and `git diff --check` passed. JavaScript was executed through the bundled Node
runtime; no standalone `node` executable is on this Mac PATH. The owner confirmed HTTPS
and supported browsers for the Web Locks prerequisite. No live-site tests were run.

### Remaining acceptance sequence

- On the isolated test site, lose the response after commit, retry unchanged, close/reopen,
  refresh, reauthorize, and replay after closure while the original Run context is accessible.
  Once the Card has been released/reused, saved-request reconciliation requires a supervisor;
  cross-device or old-Cycle recovery is not added by this slice. Verify exactly one progress
  row, one audit event and one accumulation for its token.
- Reject invalid evidence, verify the server returns correlated `rejected` and no changes survive
  the savepoint, correct it and confirm one new token. Also lose the rejection response and retry.
- Verify expired/revoked/wrong-operation authorization, changed payload, legacy fingerprint,
  concurrent independent workers, stale tabs, storage denied/corrupt, and unexpected errors.
- Complete a scanner-only kiosk run (quantity/evidence, Confirm, safe Cancel, retry and focus).
- Run real ERPNext closure/repack, cancellation/recovery, rollback and stock-ledger checks.
- Delayed poll error handling in logistics/service panels remains a separate unresolved review.
- The 116-requirement/15-scenario review artifacts mentioned in the handover have not been
  independently recovered in this slice. Original recent development messages confirm the
  owner's consolidated-Repack-at-closure decision; they do not replace the full inventory.

## Site safety: fail closed

The user operates ALL commits, pushes, server pulls, migrations, builds, cache clearing and restarts manually. No automatic deployment.

The user has confirmed a test server exists, but its exact host, bench and site have not yet been identified or its isolation verified. Do NOT assume historical site1.local is disposable. Do NOT run site-mutating tests from this document.

First obtain:
- Exact test host, absolute bench path and exact site name.
- Frappe and ERPNext installed versions (major15) and app Git revision.
- Confirmation of a separate disposable database with synthetic data, separate test media storage/credentials, and no production integrations.
- Confirmation email, SMS, webhooks, accounting/e-invoice and external stock integrations cannot send live effects.
- A restore/reset plan for the disposable site, including committed concurrency tests which ordinary per-test rollback cannot fully undo.

Read-only identification commands for the user, after changing to their KNOWN test bench:
```bash
pwd
hostname
bench version
git -C apps/cfg_kanban rev-parse HEAD
git -C apps/cfg_kanban status --short
```

Do not paste credentials, site_config.json or database passwords back into chat.
These commands do not prove database isolation. Record the identity/isolation confirmation separately.

The eventual test runner should require an explicit exact site argument plus matching expected host, bench path and Git SHA; reject empty values, placeholders and mismatches. An acknowledgement string alone is not isolation proof. Select only named test modules; no all-sites execution. Keep site tests separated from offline discovery. Do not change allow_tests/settings automatically. Capture before/after ledger, audit, target counts and traces.

## Acceptance boundaries

The broader inventory has 15 scenario specifications. This first code slice covers only replay control flow and authorization forwarding. No claim that all15 are implemented or passing. L1 same-company transfer acceptance remains incomplete; no go-live recommendation follows from this harness.

No existing untracked manual was modified.

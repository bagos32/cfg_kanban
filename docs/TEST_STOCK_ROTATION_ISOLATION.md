# Batch, tag and persistent bin isolation acceptance

Agreed 17 November 2026: Batch-wide isolation plus selected Stock Tag isolation;
physical-bin isolation affects current and future loads until released. Explicit
scans remain allowed with all normal validity checks. No whole-Item exclusion.

## Offline scope

Tests execute real selection-isolation helpers, the controlled mutation service,
FEFO and dispatch selection SQL/control flow, inheritance guards and scanner/touch
controller with in-memory dependency doubles and SQLite. They do not establish
Frappe hooks, MariaDB lock behavior/rollback, native ERP stock or kiosk operation.

## Site acceptance — not run

Record deployed SHA, operator/account, Batch, source tag/bin, before/after flags,
source selection, Event IDs and stock balances for each scenario:

1. Non-batch early tag isolated: a later valid tag can start a Material Run without
   a WO override. Explicit scan of the isolated tag still enforces normal validity.
2. Batch and one tag independently isolated: releasing either leaves the other rule
   effective. An unrelated tag of the same Item remains available.
3. Bin isolated while loaded and while empty. Unload/consume, then refill with a new
   tag/Batch: automatic selection still skips its contents until bin release.
4. Move stock out of isolated bin: only its local tag/Batch rules follow it. Tag
   splits/new labels/replacements retain local isolation; mixed-rule merges reject.
5. Isolate one numbered fill without isolating the whole bin. Another fill and
   future bin loads remain available unless their own rules exclude them.
6. Dispatch FIFO/FEFO and matching printed-expiry suggestions omit all excluded
   sources. Explicit transfer scans still pass normal expiry/certificate/stock gates.
7. Expired, held, invalid-certificate, wrong-warehouse or unavailable stock never
   becomes usable through isolation. ERP quantities/valuation remain unchanged.
8. Reject ordinary operator, scoped supervisor, missing Override permission and
   missing/new release reason. Verify ERP Manager Desk form action and audit actor.
9. Lose confirmation response, retry same data/token, reject changed-payload replay.
   Race isolation/release, bin loading/movement and source confirmation in real
   MariaDB transactions: stale context rejects, no silent overwrites or lost rule.
10. Scanner-only kiosk: global open, physical source, numbered 1–10 choice, paging,
    Isolate/Release, scanned reason, Confirm and Cancel. Verify touch and focus after
    success/error/cancel. Verify server rejection and transport-loss recovery.

No commit, push, pull or deployment is performed by the agent.


## Recorded offline result — 17 November 2026

Working changes based on `abd0d59`, including the prepared Move / Repack changes:

- 443 targeted Python tests passed: 22 tag/bin isolation cases plus 421 existing
  repacking, production, hopper, material-run, certificate, expiry, rotation and
  schema checks. Actual dispatch SQL runs against SQLite; no MariaDB acceptance.
- 109 JavaScript checks passed: 13 new isolation controller/dialog/integration cases
  plus 96 existing repack/scanner/receipt/hopper checks.
- Changed Python, JavaScript and JSON schema syntax checks and `git diff --check`
  passed. Protected untracked handover and V2.23 manual were preserved.
- No live site tests, commits, pushes, pulls, migrations or deployment were run.
  All site acceptance scenarios above remain unrun.

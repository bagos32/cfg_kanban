# Station output declaration acceptance

Prepared 17 November 2026, based on `0fa8e09` plus uncommitted changes. Not deployed.

## Agreed behavior

Operators scan a station, choose the exact Work Order, and bundle/tag final-operation
reported good output before any Manufacture Draft, including while the final operation
runs. Finished Items use Batch/printed serials, not ERP unit-serial tracking. Bundles
can use a new main tag, an empty permanent output bin, or both. Supervisor receipt
preparation adopts exact declarations; native ERP submission activates stock.

## Offline boundaries

Real service functions, receipt preparation and native tag/bin factory are exercised
with in-memory document/DB/auth doubles. Scanner/touch code runs with RPC/storage/lock
and dialog doubles. These do not establish actual Frappe hooks, MariaDB concurrency,
rollback, native Batch/stock posting, live layout or scanner-only kiosk behavior.
The earlier queue/completion fixes remain separate uncommitted production corrections;
old completion snapshots are not rewritten by this feature.

## Site scenarios — not run

Record deployed SHA, station/card, Work Order/Job Cards, source good quantity, operator,
declaration IDs, identity/trace rows, input usage, Batch/certificates and native stock
before/after for each case:

1. Report good 3 against target 5 while final Job Card runs; declare bundles 2+1.
   Available becomes 0, ERP output stock remains 0. Add good 2 and bundle it once.
2. Several Work Orders/stations: numbered 1–10 choices and paging; no cross-Company,
   wrong-operation or wrong-workstation declaration. Verify dedicated packing station.
3. Tag-only, bin-only and main-tag-inside-bin. Reject occupied/in-transit/WIP bins,
   unknown/used tags, output quantities above reported good and invalid quantities.
4. Race two declarations, equivalent code/alias scans, ordinary Draft staging, HU
   activation, final progress cancellation and receipt preparation. One physical
   identity can belong to one pending workflow; real transactions roll back failures.
5. Normal operator cannot prepare/post the declared receipt. Supervisor sees bundle
   list, prepares exact quantity, adopts each tag/bin once and retains input Material
   Run scans. Changed warehouse/UOM/trace quantity or cancelled output line blocks posting.
6. Supervisor waits for all Job Cards/material gates. Submit once: correct ERP Batch,
   certificate state, quantities, packing timestamp and bin membership; no double stock.
7. Cancel own unbound bundle; reject other-owner cancellation without Supervisor.
   Cancel bound bundle via Supervisor action and reconcile/recreate Draft. Native
   trace cancellation, abandonment and Draft deletion cannot orphan reservations.
8. ERP receipt reversal after untouched output: retain native reversal/certificate
   history and mark declaration Voided. Moved/reserved output blocks normal reversal.
9. Lost declare/cancel response, double Confirm, refresh/reopen, cross-tab conflict,
   storage/Web Locks failure, confirmed rejection corrections. Inspect existing Draft
   after lost preparation response. Never manufacture a second receipt blindly.
10. Scanner-only kiosk: station, Work Order choice, quantity, tag/bin in either order,
    Confirm/Cancel; cancellation choice/reason; focus after errors and success. Touch
    uses same payload. Pending tag/bin Logistics lookup shows Item/quantity without
    inventing an ERP stock balance.
11. Disabled mode and ordinary ERP receiving/manufacturing remain compatible. Include
    Batch-controlled and unbatched Items and the existing printed-expiry policy gates.

Do not infer production acceptance from offline checks. No commit, push, pull, migration
or deployment is performed by the agent.


## Recorded offline result — 17 November 2026

Against the prepared worktree based on `0fa8e09`:

- 473 targeted Python tests passed: 23 declaration/receipt/factory cases, 7 earlier
  queue/completion cases, and 443 existing relevant production/material/stock tests.
- 124 JavaScript checks passed: 15 declaration scanner/touch/lookup cases and 109
  existing scanner, repacking, isolation, hopper and receipt checks.
- Changed Python, JavaScript and JSON schema syntax checks and `git diff --check`
  passed. The protected handover and V2.23 manual remain unmodified/untracked.
- No real site, migration, ERP submission, MariaDB concurrency/rollback or physical
  kiosk/scanner tests were run. All site scenarios above remain unrun.

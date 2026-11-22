# Delivery Trip customer cancellation — acceptance

Prepared 22 November 2026 above `b6e53ed`. Native-site acceptance: **Not run**. No server migration,
posting, real-browser or concurrency acceptance is inferred from offline checks. Owner deploys
manually and records the tested revision below. Existing L1 acceptance debt remains unchanged.

## Setup

Use a permitted Company-specific Trip with a lead and assistant, two known-customer SO stops,
multiple Plans for one customer, repeated visits to one Site, an informational visit and a shared
Open Route pool. Include tagged/untagged stock, two Batches of one Item, certificate/expiry-bearing
tags and a mixed logistics container. Test Flexible and Planned Order, both pre-departure and
In Progress. Keep an authorized Supervisor with Customer Delivery/dispatch responsibilities,
View All, Override and Complete; retain an unauthorized/other-Company operator case. Complete
ordinary E3 loading where needed. Use normal DocType pages for office planning.

## Cases

| Check | Required outcome | Native result |
| --- | --- | --- |
| Driver/assistant request | Reasoned Pending request only; no stop or stock mutation; exact target cannot start delivery | Not run |
| Every route policy | Flexible and Planned require Supervisor; direct driver API cannot bypass approval | Not run |
| Supervisor direct/review | Exact customer, address, SO/PO, plans, tags/Item/Batch/UOM/qty visible; reason and loaded disposition required | Not run |
| Reject/withdraw | Target becomes deliverable under original order; no stock/ERP mutation; decision history retained | Not run |
| Loading changes while Pending | Supervisor sees current goods; stale confirmation hash rejected; refreshed approval succeeds | Not run |
| Other visit progresses while Pending | Exact cancellation request remains valid if its customer/source facts are unchanged | Not run |
| Untouched pre-loading work | E2 tagged/untagged reservations and entirely unused E3 claim released once; Plan Cancelled; remaining route can start | Not run |
| Loading ERP work exists | Pending command, draft or dispatch state blocks; resolve through existing recovery; no abandoned ERP document | Not run |
| Loaded HOLD | Stock stays on lorry; exact tag reserved; loose commitment retained; no DN/credit/QC receipt/new SE; certificates/expiry unchanged | Not run |
| Loaded RELEASE | Exact customer commitment released; stock stays on lorry; eligible unassigned/shared-pool sale works with native DN/proof/expiry/quality checks | Not run |
| Exact E5 accounting | Released cancellation quantity subtracted once; no fake delivery/refusal; other Plans' remainder unchanged | Not run |
| Unsafe release | Quality hold, expired/moved stock, wrong Company/warehouse or stale identity rejected without partial decision/hold | Not run |
| Generic held-stock use | Manufacturing/repack/delivery/transfer cannot consume held tags; no-tag movement cannot consume held quantity or a held Batch using another Batch's balance | Not run |
| Older loose transfer draft | Native Stock Entry submit rechecks holds created after draft preparation | Not run |
| Mixed logistics container | Whole mixed recovery rejected; Supervisor Unload separates exact held physical tag only, preserving reservation/Batch/certificate/qty; other tags stay packed | Not run |
| Held tag unload rejection | Ordinary operator, partial/internal fill, unrelated reservation or active recovery/open transaction cannot detach it | Not run |
| E5 recovery | Exact scan/loose confirmation → prepare → native transfer receipt; original loading SE unchanged; hold adopted once, destination stock available after receipt | Not run |
| Unused recovery cancel/retry | Hold restored once; new recovery can be received; original request/receipt retries create no duplicate ledger | Not run |
| Multi-day overnight/Resume | Return commitment/reservation persists; stock-stays cannot silently free it; later return works | Not run |
| Fresh D3 count | Stale count cannot settle received transfer; fresh closed count plus correct movement required | Not run |
| Multiple Plans/other customer | Exact whole stop cancelled atomically; next eligible customer delivers with unchanged native DN/proof controls | Not run |
| Shared/repeated optional visits | Only exact visit Skipped; other visit at same Site and pool stock/commitments unchanged | Not run |
| SO route inbox/LIFO | Cancelled assignment available for another Trip; other holds intact; cancelled picking rows omitted; historical SO quantities/links retained | Not run |
| Preparation regeneration | Never recreates/relinks cancelled work; later replacement uses another Trip; ordinary form cannot remove/rewrite cancellation evidence | Not run |
| Started delivery/history | Any quantity decision, Session/DN/proof or active customer blocks cancellation; native recovery remains required | Not run |
| Frozen source/Sheet protection | Cancellation retains original hashes/Sheet revision; later source/Sheet edits still block remaining deliveries | Not run |
| Last pending stop | Driver route completes without fake delivery; GPS ends by existing policy; office/E5 settlement still required | Not run |
| Duplicate/lost response/two tabs | One decision/hold; immutable original token and payload retained across reload; readback/void works only for original request | Not run |
| Simultaneous native start/loading/approval | Root/source locks serialize; stale action rejected; no partial stock/approval/audit or unresolved deadlock | Not run |
| Native rollback | Inject failure during hold/Plan change; all cancellation, child rows, ledgers and receipt roll back together | Not run |
| Scanner/tablet | Exact stop command, reason, numbered disposition, Confirm, camera, safe Cancel/rejection focus; no credential mix-up | Not run |
| Driver and Supervisor maps | Active stop/pins omit cancellation; separate escaped history shows decision/last custody; no stale delivery action | Not run |
| Migration/legacy | New child/links install; existing sequence requests/Trips unchanged; no automatic cancellations | Not run |

## Evidence

Offline checks use actual extracted service/controller functions with native-service dependency
doubles and DOM/RPC harnesses. They cannot establish Frappe migration, MariaDB row locks/rollback,
native User Permissions, ERP submission or actual device behavior. Record offline totals only
after the final reviewed tree passes; they do not change any result above.

Deployed Git revision: _pending_

Tester/date and native document/evidence references: _pending_

Exceptions/deferred risks: _pending_

Offline development checkpoint: **625 Python tests passed** across 24 related modules and **152
JavaScript test entries passed** across 12 UI suites. The new cancellation/recovery tests exercise
37 cases within that Python total. Python/JavaScript syntax and DocType JSON checks also passed.
These are local dependency/DOM tests; every native acceptance result above remains **Not run**.

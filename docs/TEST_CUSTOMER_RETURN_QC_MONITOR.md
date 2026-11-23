# Customer Return QC monitor — native acceptance

Prepared 23 November 2026 above `2f988ba`. Native/site result: **Not run**. No offline dependency,
DOM or syntax check establishes native permissions, database grouping/isolation, ERP posting,
real camera behavior or production acceptance. The owner performs deployment manually. Existing
Package L1 acceptance debt remains separate.

## Setup

Use an isolated test site and native Quality User/Manager plus Kanban Terminal with Company Read,
Return Case Read, a Customer Return QC operator (Start/Complete), a read-only QC operator, a normal
non-QC operator, and an unrestricted Supervisor. Include two Companies and explicit native User
Permissions, plus one individually inaccessible/shared case.

Prepare more than 40 cases with an old unresolved case, customer-site and direct-customer intakes,
a collected multi-day-trip return still awaiting QC receipt, in-progress QC, rejected/investigation
cases, accepted mixed-UOM items with Batch/expiry/tag references, both accounting/physical tracks,
custom Credit Note and standard Sales Invoice Return, drafts/cancelled replacements, a company-
owned quality refusal, a wrong-DN correction and closed/cancelled history. Keep the protected owner
documents unchanged. Sync Page/Workspace/assets through the owner's normal migrate/build.

## Cases

| Check | Required result | Native result |
| --- | --- | --- |
| Normal full page/navigation | Workspace, Logistics and Return Case launch Customer Return QC; exact case deep link works | Not run |
| Identity/responsibility | QC role or unrestricted Supervisor required; empty ordinary Responsibilities denied; native terminal/record reads still required | Not run |
| All pages/oldest queue | Old unresolved case first; every permitted record beyond 30 reachable; no silent cutoff | Not run |
| History | All Returns and Closed / Cancelled show accessible history including posted corrections; no record deleted or automatically closed | Not run |
| Counts | Native grouped counts match the same Company/row/search/date/state filters across all pages | Not run |
| Native permissions | Other-Company and individually denied case absent from rows, counts and exact/UUID/deep-link lookup | Not run |
| Scope changes | Revoked permissions clear cached rows/details/filter data; no workflow action from a stale or old-operator view | Not run |
| Parallel tracks | Accounting Completed case still awaits physical action; physical completion does not hide accounting pending | Not run |
| Native drafts/cancellation | Case feedback and permitted linked document status reflect Draft/Submitted/Cancelled; existing replacement controls remain required | Not run |
| Owned quality refusal | Explicit owned-stock warning; current exact outcome-line custody only; no customer credit or duplicate receipt suggested/created | Not run |
| Old customer goods | Existing QC → accounting/physical workflows remain separate; reading/opening monitor posts no stock/credit/QC/evidence | Not run |
| Collection versus QC receipt | Collected trip goods still show receipt unconfirmed until QC receives/starts; recorded lorry not presented as live custody | Not run |
| Quantities | Claimed/received/accepted/rejected preserve Item/Batch/UOM/tag/expiry; totals separate Kg/Nos; corrupt quantities visibly unknown | Not run |
| Rejected/investigation | Remain in follow-up, with QC/Supervisor owner and reasons; native closure alone moves them to history | Not run |
| Delivery correction | Existing Return DN/accounting follow-up; no Receive/Start QC offered | Not run |
| Permission-aware document links | Unauthorized/wrong-Company/wrong-customer links omitted; custom Credit Note remains optional | Not run |
| Exact inspection handoff | Same current QC operator, case and native Company access rechecked; no automatic Start/Complete/receipt | Not run |
| Native mutation authorization | Direct Start/Complete API to denied Case/Company rejected before quantities/state/audit change; authorized inspection still succeeds | Not run |
| Actor race | Another tab/login/profile employee change during read cannot display/open former actor's case | Not run |
| Scanner | KRTN/UUID and case URL resolve correctly; numbered cases, paging, inspection/form/Refresh/Cancel/Help commands work; blank/modified Tab retains navigation | Not run |
| Tablet camera | One decoded result, safe Cancel/error focus, late callback after hide/operator switch ignored | Not run |
| Native existing inspector | Receipt/Start, QC quantities/evidence, accounting/stock/disposal follow-ups work with original permissions and real ERP feedback | Not run |
| Refresh lifecycle | 15-second visible refresh; no automatic inactivity renewal; stale/offline notice disables navigation; no polling/cache after leaving Page | Not run |
| Field controls/theme/layout | All status choices load; native Link/date filters work; touch/keyboard layouts usable on tablet and desktop | Not run |
| Native failures | No duplicate receipt/credit/QC/evidence from monitor; permission/asset/network failures show a useful message | Not run |
| Large data/concurrent feedback | Actual query timing/grouping and page/count behavior acceptable while authorized QC/accounting/stock updates occur | Not run |

## Evidence and boundaries

Offline tests execute actual Python services with a permission-aware SQLite/dictionary double,
including real native QC start/complete functions; JavaScript tests execute the controller, DOM
lifecycle, asset loader and existing Logistics reader/handoff. They do not replace the native
checks above. The implementation uses permission-aware Frappe `get_list` for both list and grouped
counts, following [the Frappe Database API](https://docs.frappe.io/framework/user/en/api/database).

Rejected/investigation cases can expose existing unresolved custody/closure work. This page shows
that debt and its owning team; it adds no manual override to declare stock/credit/inspection done.

Deployed Git revision: _pending_

Tester/date and native Case/ERP/evidence references: _pending_

Accepted exceptions/deferred risks: _pending_


Offline development checkpoint: **304 Python tests passed; 5 existing native Frappe naming tests
were skipped because Frappe is not installed** (309 tests discovered across 13 related modules).
**143 JavaScript test entries passed** across 11 UI suites. The monitor includes 22 dedicated
Python tests and 22 JavaScript tests. Syntax/JSON checks passed. These results do not change any
native result above; actual migration, permissions, query timing, ERP feedback and device tests
remain **Not run**.

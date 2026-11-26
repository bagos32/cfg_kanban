# Customer stop documents and tagged Product lookup

Development checks: offline only. Live ERPNext, MariaDB concurrency, Label Bridge/Bluetooth,
Android/device return, paper output, scanner/kiosk and Company permissions acceptance: **Not run**.
Record deployed SHA, test users/devices, source IDs and evidence below before acceptance.

## Setup

- Migrate CFG Kanban, build assets, clear cache and restart using the normal app-only workflow.
  No Frappe/ERPNext update is needed.
- Four Customer Scan Point document choices default off. Existing completed stops retain history;
  merely reading a page must not backfill tasks or create ERP documents.
- Office authorizes source Read/Print, Company access, operator Complete and the Company Mobile
  Print Profile. Draft invoices also require native Create. Verify Company Disabled still rejects,
  and existing Automatic Submission operator/Submit controls remain intact.
- Choose native formats (including captured-signature footer for DN where required), approve the
  browser in Label Bridge, and use a known physical printer with the configured dimensions.

## Acceptance

| Case | Expected / evidence | Live result |
| --- | --- | --- |
| Defaults off | Complete delivery normally; no automatic task/invoice/job | Not run |
| DN ×2 only | Submitted DN + required proof; original customer stays selected; prepare one job, two complete copies | Not run |
| Recipient then office | Print first; inspect/confirm/tear; second remains unsent until another tap; both include captured signature | Not run |
| Draft create only | One native mapped Draft, correct naming/taxes/customer/DN rows, `update_stock=0`; never Submit even under Company Automatic Submission | Not run |
| Draft print only | Use one existing exact linked Draft; no implicit invoice; zero/multiple Drafts require review | Not run |
| Create + print Draft | One Draft and one X2 job; office-created Draft reused; mandatory ERP inputs use existing editor/office | Not run |
| Old return collection | Existing Temporary Return Note queued ×2 even before delivery completion; QC custody unchanged, no stock/credit | Not run |
| Quality refusal | Exact QC refusal case queued ×2 after stop completes; no duplicate stock receipt or credit | Not run |
| Full refusal | No DN/invoice invented; eligible QC case still printable | Not run |
| Lost prepare/mapper response | Close/reopen, read back/retry original identity; one task/source/Draft/job; no silent print resend | Not run |
| Unknown paper outcome | Segment retained; explicit reasoned retry required; second copy cannot overtake first | Not run |
| Another operator/manual job | Original job visible; no new copies without original operator or authorized reasoned office closure | Not run |
| Closed automatic job | Not automatically recreated; reviewed manual reprint available | Not run |
| Bad format/signature/profile | Document step pending/actionable; delivered stock/proof stay posted; other confirmed-safe tasks can proceed | Not run |
| Move freely | Choose another allowed stop with pending documents; return to checklist; no new server print gate | Not run |
| Current Customer | Touch and printed command scroll past map, scanner focus stays ready; selection scoped by Trip/operator and survives refresh | Not run |
| Tagged Product browse | Prepared tag and two free tags appear with distinct codes/keys; exact selected tag reserves/posts through existing DN | Not run |
| Batch/serial browse | Tag supplies Batch; untagged exact Batch required; serial-controlled tagged quantity remains full-unit only | Not run |
| Container browse | Contained tag explains physical-container scan; Quantity Bin partial and mixed container full delivery still work | Not run |
| Invalid/stale source | Other Company/lorry absent; reserved/expired tag unavailable; concurrent balance change rechecked before allocation | Not run |
| Native regressions | Existing untagged, Loose Tag partial refusal, proof, return collection, pending request recovery unchanged | Not run |

## Offline development workflow

Use the repository Python unittest and Node contract tests. Focus suites:
`test_stop_documents`, `test_mobile_invoicing`, `test_mobile_printing`, `test_driver_route_actions`,
`test_delivery_note_printing`, `test_route_delivery`, `test_trip_sales`, `test_loose_tags`, and their
Driver Route / route delivery / mobile printing Node suites. `run_mobile_print_browser.mjs` runs
actual DOM/raster/Web Locks with RPC/ERP/printer doubles in Chrome and Firefox. These results do
not prove live ERP posting, rollback isolation, scan hardware or physical paper.

## Acceptance record

Deployed SHA: ___ · Date: ___ · Company: ___ · Test operator/user: ___ · Device/browser: ___
Printer/app version: ___ · Native document/task/job IDs: ___ · Evidence: ___ · Exceptions: ___

## Development results (26 November 2026)

The offline mobile-print fixture passed 101 checks in Chrome and 101 in Firefox, including a lost
preparation response, original-request readback, three documents with two separately requested
copies each, and operator-session expiry. This uses RPC/ERP/printer doubles, not a connected site.

The broader pre-existing `test_dispatch_fulfilment_ui.cjs` fixture fails with
`ReferenceError: active_loose_tag is not defined` when it extracts the global Logistics scanner.
The same failure was reproduced in the untouched `c02b550` checkout. Its fixture is left unchanged;
this result is not counted as a passing regression or as evidence of a live posting failure.
Native permission tests skip automatically when Frappe is unavailable; run them on the site.

The final offline Python regression ran 594 tests: 563 passed and 31 native Frappe permission
tests skipped because Frappe is unavailable. The selected Node suites passed 164 runner tests
(including the route adapter's 38 internal checks). The baseline failure described above is separate.

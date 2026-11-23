# Driver mobile printing and invoicing acceptance

Status: **development implemented; live native ERPNext and physical-device acceptance NOT RUN**.
Prepared 23 November 2026. Record site, deployed SHA, tester, native versions, device/browser,
Label Bridge version, printer model/DPI/printable width, and evidence for every test below.
Do not equate offline tests or the companion-app launch with physical printing or accounting acceptance.

## Isolated test-site prerequisites

Use a restorable test Company and completed/part-completed Driver Trip with lead and assistant,
known-customer tagged/untagged DNs, a visit-only optional sale, old-return Cases, native permissions,
configured custom mandatory scalar/table Invoice fields, and representative naming rules. Enable
only the explicit test Company's invoice policy. Confirm the office policy before testing automatic
submission. Do not send real accounting/e-Invoice integrations during an isolated test.

## Native installation, scope and ERP documents

| Test | Required result | Evidence |
|---|---|---|
| Migrate/build | Four new DocTypes, six Print Formats, workspace/setup links and assets load | Not run |
| Company profile | One per Company; Accounts Manager/System Manager policy; formats filtered by matching DocType | Not run |
| Company/User Permissions | Other Trip/Company/customer/documents cannot be enumerated, printed or invoiced | Not run |
| Native read AND print | Denial removes document / prevents preparation; Draft/Cancelled native Print Settings apply | Not run |
| Completed stop | Can select historical stop and print linked DN/Invoice without reopening delivery | Not run |
| Native format edit | Custom duplicate changes BOTH native print and direct raster; several layouts selectable | Not run |
| Invoice Draft default | Exactly one native SI; correct DN rows/taxes/currency/series/Document Naming Rule; no stock issue | Not run |
| Native mandatory data | Permitted scalar/Sales Team/custom values work; Item references/quantities/rates/accounts stay read-only; missing accounting defaults require office setup | Not run |
| Changed office policy | Stale Draft review cannot become auto-submit; original recorded result still reconciles | Not run |
| Native existing draft | Reused; not auto-submitted even under automatic policy; multiple drafts rejected | Not run |
| Partial billing/returns | Native mapper creates only remaining billable quantities; fully billed/returned creates none | Not run |
| Native custom workflow | Validation/workflow rejection rolls back invoice, command and driver receipt together | Not run |
| Authorized auto-submit | Explicit Company policy + named Employee + native Create/Submit + Kanban Complete required | Not run |
| No implicit credit/payment | Print does not create credit/invoice; Invoice action does not receive payment or post stock | Not run |
| Concurrent native office/driver | Race native office draft/submit with two driver tabs; no duplicate billing/extra stock; resolve DB deadlock/rollback via original token | Not run |
| Concurrent driver/assistant | Trip/DN locks and current reads prevent duplicate driver invoices and over-labelled returns | Not run |
| Lost response | Invoice, custody label and print confirmation replay exact request; changed payload conflicts | Not run |

Native billing protection is reused, not replaced by a second accounting ledger. Concurrency with
ERPNext Desk, hooks and custom apps requires the database tests above; mocks cannot establish it.

## Custody labels and QC

| Test | Required result | Evidence |
|---|---|---|
| Split returned row | Bundle labels sum to collected quantity; UOM/precision/Batch/expiry preserved | Not run |
| Illegal quantity/state | Zero/negative/NaN/over-quantity/fractional whole UOM/QC-started/uncollected/owned refusal rejected | Not run |
| No stock or credit | Creating/printing custody label adds neither HU stock, SLE, Stock Entry nor Credit Note | Not run |
| QR in Logistics | Opens exact live Case; native permissions and Company remain enforced | Not run |
| QR in QC page | Same Case/item lineage; case remains on QC worklist until normal follow-up | Not run |
| Reprint/replay | Same bundle label reprinted with reason; lost create/confirm response does not allocate/count twice | Not run |

## Printer and mobile acceptance

| Test | Required result | Evidence |
|---|---|---|
| Normal print | Configured ERPNext format/letterhead/80mm paper works using the installed system printer | Not run |
| Direct protocol | Installed companion accepts signed v1 UTF-8-key HMAC job; correct printer receives it | Not run |
| Short documents | DN, Draft/submitted SI, SI return/custom Credit Note and Temporary Return Note match native values | Not run |
| QR/expiry | e-Invoice QR and custody/Stock Tag QR scan on paper; Batch/expiry/UOM/serial text legible | Not run |
| Long documents | All rows/totals/terms/QR printed across segments; no missing tail or duplicate section | Not run |
| Multiple copies | Whole copies collated; each segment explicitly handed off and confirmed | Not run |
| Unknown output | App absent, Bluetooth off, paper out, device locked/backgrounded, app rejection: no automatic retry or false confirmation | Not run |
| Retry reason | Same uncertain segment needs reason; confirmed segment cannot be resent within job | Not run |
| Source/format changed | Cached preview cannot hand off changed document; close reason and new review required | Not run |
| Image/CSS limits | External image fails visibly, same-origin/private/data assets render; complex format uses native fallback | Not run |
| Saved settings | Browser/Company isolation, printer alias/DPI/width/formats retained, signing key not persisted | Not run |
| Tablet/scanner | Camera, touch, Enter/Tab, printable commands, required ERP tables, Cancel/error/success focus | Not run |
| Page/operator change | Keys/preview removed, late callbacks ignored, active native app handoff not replayed | Not run |
| Two tabs | Device lock blocks simultaneous direct handoff; original pending driver identity retained | Not run |

## Offline evidence

`test_mobile_printing.py`, `test_mobile_invoicing.py` and `test_mobile_print_bridge.cjs` exercise
actual application functions using explicit native/database doubles. Existing driver receipt,
delivery, return, naming and permission tests are regression checks. The browser fixture
`cfg_kanban/tests/fixtures/mobile_print_browser.html` runs the real raster/crypto/control modules
in isolated local Chrome with a lightweight native-control/backend adapter; it is not a Frappe site.
It never launches the real companion or sends a physical print.

The dependency is pinned html2canvas 1.4.1 (MIT), served locally. Distribution SHA256:
`e87e550794322e574a1fda0c1549a3c70dae5a93d9113417a429016838eab8cb`.
Native API references: [ERPNext v15 DN mapper](https://github.com/frappe/erpnext/blob/version-15/erpnext/stock/doctype/delivery_note/delivery_note.py),
[Frappe v15 print utility](https://github.com/frappe/frappe/blob/version-15/frappe/utils/print_utils.py),
[html2canvas limitations](https://html2canvas.hertzen.com/documentation).

Results and deployed SHA must be recorded here before acceptance. Existing L1 transfer acceptance
and other separately deferred logistics tests remain open; this phase does not close those gates.

### Recorded local verification — 23 November 2026

Baseline HEAD `0053bb5`, plus this uncommitted mobile-printing change set:

- Broader Python delivery/returns/route/identity/naming regression: **680 run; 675 passed; 5 native
  Frappe naming tests skipped** because Frappe/ERPNext is not installed in this local environment.
  This includes the seven shipped-template render checks using temporary Jinja2 3.1.6; no app
  dependency was added for this test runtime.
- JavaScript regression: **241 Node test-runner entries passed** (some existing entries wrap several
  assertions).
- Isolated Chrome fixture: **28 checks passed**, using the real rendering/crypto/action/scanner/
  required-field modules and explicit native-control/backend doubles. Includes native gutter/QR,
  long receipt and fractional-DPI tiling, explicit handoff, unknown output, memory key reuse/clear,
  frozen scanner retry identity, policy-change rejection, read-only financial fields, row bounds,
  custom mandatory input and lost custody-response reconciliation.
- Python/JavaScript syntax, JSON, intended-diff whitespace and vendored-distribution hash checked.
  Both protected untracked documents remain unchanged.

To rerun the standalone browser fixture, use Node 22+ with Chrome:
`node cfg_kanban/tests/run_mobile_print_browser.mjs` (set `CFG_CHROME` to another Chrome executable
when needed). It creates its own localhost server and temporary browser profile, and never opens
Label Bridge or an ERPNext site. Optional `CFG_PRINT_SCREENSHOT` saves a local test-only screenshot.

These results do **not** record a deployed revision or pass any native/database/device row above.

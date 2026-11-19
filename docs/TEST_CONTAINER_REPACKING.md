# Received-stock container repacking acceptance

Prepared 17 November 2026. Offline checks are not live-site or kiosk acceptance.

## Agreed behavior

- Existing Stock Tag → container and container A → B; full or partial quantity.
- Empty destination can take an optional unused preprinted Main Stock Tag.
- Loaded destination reuses its existing compatible tag and combines quantity.
- Same Item/Batch/UOM/company/warehouse/certificate evidence/expiry; no stock creation.
- Operation Hopper WIP remains in Recover Hopper, separate from posted stock.

## Site acceptance (not run)

Record deployed SHA, operator, source/destination tags, before/after balances,
immutable Event/ledger/membership IDs and ERP stock balance for each case:

1. Whole received tag into empty B, then A → B with same tag. Quantity unchanged.
2. Partial A → empty B with new preprinted tag. Source remainder + B equals original.
3. Quantity-bin/production fill → empty container; permanent QR and new Main tag modes.
4. Loaded same-Batch B: existing tag retained, combined quantity displayed and saved.
   Test multiple fills with numbered selection and paging; reject absent/stale choices.
5. Reject Item, UOM, Batch, expiry and certificate provenance/policy mismatch; source
   and destination remain unchanged. Expiry and original printed evidence persist.
6. Reject cross-warehouse/company, reservations, pending Material Run use, open
   Manifest/Delivery, ERP serialized stock and intermediate Hopper WIP.
7. Consume a repacked physical tag through Production Output Container QR. Full
   consumption closes membership; cancel native consumption restores that same fill.
8. Native receipt cancellation while physical tag loaded is blocked. Ordinary
   untouched manufactured internal-fill cancellation still follows native reversal.
9. Lose HTTP response after commit: retry, Cancel/reopen and refresh use the same
   event token; quantity changes once. Confirmed rollback permits correction.
10. Two concurrent sessions/tabs: no lost balance or duplicate move; another operator
    cannot overwrite the terminal's pending request. Race destination load/unload and
    source consumption; stale contents reject/reload. Test real MariaDB transactions,
    certificate-policy failure rollback and native cancellation races.
11. Fixed scanner in kiosk/full-screen: open globally, select 1–10, page, quantity,
    source, destination, optional new tag, reason, Confirm and Cancel. Verify focus
    after success/error/cancel. Also verify touch and entered-code workflow.

## Offline scope

`test_container_repacking.py` executes the real repack service and shared quantity
ledger control flow against an in-memory store, plus native production-container
resolution and receipt cancellation guards. The FEFO candidate query also runs against an in-memory SQLite fixture; it
does not establish MariaDB transaction behavior. Certificate inheritance/merge behavior
is exercised through the repack service and separately covered by `test_logistics_stock_identity.py`. These checks do not
establish MariaDB locks, rollback, Frappe hooks, ERP posting, layout or real scanner
behavior. `test_container_repack_ui.cjs` executes the shared touch/scanner controller
with storage/RPC/lock doubles and checks global/catalogue/help integration.


## Recorded offline result — 17 November 2026

Working changes based on `abd0d59` (not a deployed revision):

- 421 targeted Python tests passed: 24 new repacking cases plus 397 existing
  production, hopper, material-run, certificate, expiry, rotation and schema checks.
- 96 JavaScript checks passed: 21 new controller/dialog/integration cases plus
  75 existing scanner/receipt/hopper checks.
- Changed Python and JavaScript syntax checks passed; `git diff --check` passed.
- No site mutation, commit, push, pull or deployment was performed. All site
  scenarios above remain unrun, including real transaction rollback/concurrency,
  Frappe hook execution, ERP stock and kiosk/scanner acceptance.


## Hidden-button dialog regression — 19 November 2026

Base revision: `2b5b138`. Opening Move / Repack after scanning a production bin could
fail with `Cannot read properties of undefined (reading 'on')`. The dialog bound a DOM
click handler to its initially hidden optional new-tag Button before Frappe created
that Button's input. Bind the Button's native `df.click` callback instead; it remains
available when an empty destination reveals that control.

The UI harness now models hidden Data/Button controls without inputs until shown.
It reproduced the owner's exact exception before the fix. Coverage includes opening
from a preselected production bin, touch/scanner completion, optional new-tag use and
clearing after hide/show, source rejection/correction/cancel with focus restoration,
and restoring the original uncertain request instead of reading a fresh source.
Existing request identity, Web Locks, quantity, certificate, expiry, merge and stock
rules remain in place. Backend services and scanner command payloads are unchanged.

Site checks still pending: scan a reusable Production Output Container in Logistics,
open Move / Repack, verify the source loads and the optional new-tag control starts
hidden. Read an empty compatible destination, use the now-visible New Tag button,
then switch to a loaded compatible destination and verify it hides again. Complete
moves and Cancel using both touch and the existing scanner commands. Check focus,
source/destination balances, certificates/expiry and original-token retry after a
lost response. An intermediate operation Hopper fill must still route to Recover
Hopper rather than posted-stock repacking. Record the deployed SHA and results.


## Tab-suffix scanner regression — 19 November 2026

Base revision: `ec981af`. The Move/Repack popup and main Logistics scanner previously
accepted only Enter. A Tab-suffix scanner left the code unread and moved focus away.
Both scanner inputs now accept Tab/Enter, consume a nonempty value once, clear it before
queueing work, and suppress the suffix's default action/bubbling. Blank Tab, Shift-Tab,
modified keys and IME composition remain ordinary input/navigation. Empty Enter cannot
activate native dialog confirmation. The existing serial action queue and focus/error/
retry/cancel paths are preserved; stock services and command payloads are unchanged.

`test_container_repack_ui.cjs` exercises actual keydown handlers through a complete
Tab-terminated move, Enter compatibility and Tab-plus-Enter suffixes, rapid scans behind
an unresolved source lookup, validation failure/correction/Cancel, unknown-result retry,
and global Logistics open-command routing. This extends the real hidden-control adapter;
it does not replace the scanner with a direct controller call in these suffix cases.

Live acceptance pending: fixed scanner configured with Tab suffix, open using
CFG:CMD:MOVE_CONTAINER_STOCK, then source, quantity, destination, optional new tag,
reason and Confirm. Repeat numbered choices/paging, errors/retry/Cancel, Tab-plus-Enter
suffix, and existing Enter scanner. Confirm one recorded move and restored focus after
each action. Verify manual blank Tab and Shift-Tab can still navigate the dialog, touch
Read/Set still works, and no empty suffix submits stock. Record deployed SHA and results.


## Tablet camera and registered destination guidance — 19 November 2026

Base revision: `e6083aa`. The popup adds general, source, destination and optional
new-tag camera buttons using Frappe's existing Scanner. Their `df.click` bindings
work while the new-tag control is initially hidden. One camera session accepts one
nonempty result; success and cancellation return to the same move, and closing the
parent closes the camera and invalidates late callbacks. Results run through the same
serial queue and controller validation as hardware scans. Opening/decoding the camera
does not post stock; the existing explicit Confirm is required. Pending original-token
reconciliation remains enforced. Camera startup failures remain inline and scanner/
touch alternatives remain available. Actual permission/decoder/device behavior still
requires tablet acceptance.

Stable command CFG:CMD:REPACK_CAMERA is available in the command catalogue, Production
global routing, Logistics routing and Move/Repack. General camera follows the normal
scan sequence; the named source/destination/new-tag buttons target that exact role.
No new production dependency or camera library is installed by the app.

Registry-only destination scans now explain that an unused label is not an activated
reusable destination container. Select an empty reusable bin first, then put an unused
Main Stock Tag in Optional New Preprinted Main Tag. Source scans explain that registered
labels without stock cannot supply quantity. Used/Void/Replaced registry identities
without Handling Unit links get review guidance. Preview remains read-only; no implicit
stock, bin creation, activation or certificate assignment is performed. Valid registered
Main tags remain accepted by the explicit new-tag validation and activated only by the
controlled completed repack. Destination diagnostics are also enforced by final move
validation so direct calls receive the same guidance without changing quantities.

Offline tests cover the four camera controls, delayed new-tag visibility, whole camera
sequence including explicit Confirm, cancellation/focus, repeated/late callbacks,
parent closure, unavailable camera/startup failure, validation correction, pending retry,
loaded-destination rules and command routing/catalogue/help. Backend tests exercise both
registry identity kinds, unused-source/destination explanations, missing-link states,
final-move rejection without mutation and the real unused-Main-tag validator.

Site acceptance pending: on the real tablet, allow camera permission, read source,
quantity, destination bin, optional registered Main tag and reason, then Confirm by
touch. Verify actual QR/Code 128 decoding, cancel/reopen/error focus and one stock move.
Repeat with existing destination stock and original-token retry. Confirm an unused
range tag in the destination-bin field shows the explanatory message, then succeeds
through the explicit New Tag field on an empty bin. Review Item/quantity/certificates/
expiry/audit before and after. Record deployed SHA, tablet/browser, scanner format and
results. Do not infer tablet or live-site acceptance from mocked camera tests.

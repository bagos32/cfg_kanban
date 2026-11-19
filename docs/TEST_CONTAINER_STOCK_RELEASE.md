# Direct release of container stock to a standalone Stock Tag

Prepared 2026-11-19 from `0f91c50`. Local implementation/offline verification only;
no server stock or live scanner acceptance is claimed.

## Accepted scope

Both physical situations are supported: an existing printed Stock Tag inside a reusable
container, and an internal stock fill identified only by the container's permanent QR.
The action applies only to ERP-posted stock in Logistics Container, Logistics Quantity
Bin or Production Output Container roles. Intermediate operation Hopper WIP and reserved/
held/serialized/open-logistics stock remain blocked. No other warehouse is selected:
release stays in the current Company/warehouse; the subsequent Manifest does the transfer.

A complete physical tag can detach unchanged. An internal fill or partial quantity must
move into an unused registered Main Stock Tag. Full replacement is allowed explicitly.
A partial release retains the original membership/remainder; a complete release closes
that membership and makes an otherwise empty container reusable. Audit history remains.
No quantity ledger is created for unchanged whole-tag detachment; tag conversion uses
one conserving Split ledger and the shared certificate inheritance engine. New labels
retain Item/Batch/UOM/Company/warehouse/packed date/certificate and expiry provenance.

The action uses the existing Stock Retagging and Container Loading authorization. Source,
container, current SQL quantities and memberships are rechecked under locks. A source
membership changing during a lock wait must reject. Production containers with multiple
fills require reconciliation. Existing native receipt/Manufacture reversal guards remain.
No Stock Entry, ERP consumption or operation progress is created by release.

## Scanner, tablet and retry contract

Stable payload CFG:CMD:RELEASE_CONTAINER_STOCK opens from Production/Logistics, and is
included in the printable catalogue and Scanner Help. Source, numbered choices/paging,
Material Qty, new tag if needed, reason, Confirm and Cancel work using Tab/Enter labels.
The release dialog hides destination-bin fields and shares the camera scanner and native
button callbacks. Existing Source/New Tag/Reason arms remain usable for corrections.
Camera decoding alone cannot post stock.

Move and release share the pending-action slot and Web Lock. Each new pending action
stores an explicit whitelisted server method; legacy move slots without a method still
replay as moves. Wrong-mode reopen fails closed and tells the operator which original
action to reopen. Unknown network outcomes freeze the original payload and token; only
the original operator can reconcile. Explicit Frappe rejection permits correction.

## Offline tests

`test_container_stock_release` executes actual release/preview/ledger/dispatch/reversal
functions with in-memory Frappe doubles. It checks full physical detachment, internal and
partial conversion, conserved totals, preserved identity/evidence, remaining membership,
multiple-content selection, rejected WIP/reservations/holds/serials/location/quantity,
authorization, exact/changed-payload replay after membership closes, stale lock data,
standalone dispatch eligibility and native Manufacture cancellation protection.

`test_container_repack_ui.cjs` executes the actual shared controller/dialog, including
release through Tab scans and cameras, new-tag requirements, numbered selection, old
move compatibility, rejection/retry/cancel, cross-mode pending safeguards, and floor
routing/catalogue/help. These doubles do not prove real MariaDB transactions, rollback,
Frappe hooks, ERP stock ledgers, browser permissions or physical scanner behavior.

## Isolated-site acceptance pending

Record deployed SHA, site, operator/tablet/scanner, exact source/container/new tag and
before/after Item/Batch/quantity/certificate/expiry/audit/ledger evidence for each case:

1. Full physical tag in Production Output Container: Release with no new tag; same tag
   remains active, container empties, no quantity ledger/ERP Stock Entry is created.
2. Full internal fill: unused Main tag required. Release all, verify new standalone
   stock equals old fill, old fill is Empty, membership history closes, certs/expiry
   remain valid and container QR is reusable.
3. Partial physical and internal releases: release 3 from 10; source/container retain
   7 and new standalone tag has 3. No doubled ERP stock or certificate coverage.
4. Multiple ordinary logistics contents: numbered choice releases only selected stock.
   Conflicting Production Output Container fills must reject for reconciliation.
5. Reject bad/used/child new tags, insufficient/NaN/fractional-whole-UOM quantity,
   missing reason, held/inactive/serialized stock, unauthorized roles, pending Material
   Runs, Manifest/Delivery reservations and intermediate WIP; no committed side effects.
6. Preserve same Company/warehouse. Release then scan the standalone tag into an
   ordinary warehouse-transfer Manifest without the old container. ERP stock moves
   only on its normal submitted transfer.
7. Lost response after commit: retry/Cancellation/reopen/refresh uses one release;
   changed data/token ownership and wrong Move/Repack dialog cannot bypass the slot.
   Validate two-tab and real MariaDB races with membership/stock use and new-tag claims.
8. Certificate inheritance failure rolls back tag/quantity/membership/event together.
   Native Manufacture/receipt cancellation must not orphan released descendants.
9. Fixed scanner in kiosk with Tab and Enter, complete flow/choices/camera alternatives,
   focus after errors/Cancel/success, then repeat by tablet touch/camera. Verify selected
   source, standalone tag and remainder physically match the recorded balances.

All site cases remain pending until actual evidence is recorded. This feature is not
production acceptance of the separate Package L1 transfer gate.

## Recorded offline result

Final working changes based on `0f91c50`: 158 Python tests passed across direct release,
existing repacking, certificate/stock identity, operator authorization and schema
contracts. 95 JavaScript UI checks passed across the shared release/repack dialog,
isolation, output declarations, Hopper lookup and logistics metadata. Changed Python/
JavaScript syntax and Git whitespace checks passed. Protected owner documents were
unchanged. No commit, server deployment, stock mutation or live-site acceptance was run.

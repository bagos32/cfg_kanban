# Material Run readiness checklist and source routing

Base revision: `9734fd5`. Offline implementation/testing only. No live site was
queried, no production records were changed, and no kiosk acceptance is claimed.

## Accepted behavior

- Packing creates its own new output boundary when its released policy requires
  one. Input boundaries remain source history and do not fulfill this requirement.
- Ready to confirm is always visible with ordered rows: applicable output boundary,
  destination Hopper, intermediate Hopper input, then configured tracked materials.
- Pending/invalid rows are red with text; checked rows are green with quantities
  and physical sources. Hopper WIP appears separately from raw material draws.
- The normal scan order is retained. Known sources also route by identity/Item out
  of order. Source-first scans wait for quantity; multiple waiting sources stay
  visible. Explicit material selection and ten-choice paging are scanner/touch operable.
- Quantities selected for one Item are not stolen by a different tag. Unassigned
  quantities wait for a tag to identify its Item. Only one source per Item/run is
  supported; another tag cannot silently replace it.
- Confirm waits for queued source checks, requires complete readiness, and keeps
  the native backend identity/stock/FEFO/certificate checks. Preview does not reserve
  or consume stock. Green is readiness for final validation, not physical-work authority.
- Rejection/error/cancel restore focus. Late responses after cancellation/context
  changes are ignored. Unknown confirmation outcomes retain the original request;
  confirmed Frappe rejection permits corrections. Double Confirm is guarded.
- `CFG:CMD:MATERIAL_RUN_BOUNDARY` explicitly arms output-boundary capture and is
  globally dispatched, printable, documented in Scanner Help and User Manual.

## Offline evidence

Run the Material Run scan-routing, pre-use context and scanner suites, plus the
existing Hopper/recovery/carry-in, material actuals, expiry, certificates, receipt,
closure, rotation and DocType contracts. The scanner suite executes real dialog and
confirmation handlers with doubles; the real Card Context dictionary feeds its
API-to-UI regression. These checks do not prove MariaDB isolation, deployment,
asset layout, real scanner timing or live ERP behavior.

Recorded offline result: **397 Python checks and 75 JavaScript checks passed**,
including 13 scan-routing cases and 39 Material Run dialog/scanner cases. The other
checks cover existing stock/certificate/receipt/Hopper behavior. JavaScript syntax
and Git whitespace checks were also run. This is not live-site acceptance.

## Site acceptance pending

Record deployed revision, operation/Card/WO IDs, source tag IDs and resulting run
and audit evidence. Test without mouse in kiosk/full-screen, then repeat by touch.

| Scenario | Expected | Live result |
| --- | --- | --- |
| Open Packing with a loaded source Hopper and certified bag tag | Red rows initially show new output boundary, product/Hopper and BAG in order | Pending |
| Follow boundary, Hopper, quantity, bag tag | Each row turns green with checked numbers and physical source; Hopper stays visible before Confirm | Pending |
| Bag quantity/tag before Hopper and boundary | Bag maps to its Item; other rows stay red and Confirm stays blocked | Pending |
| Hopper carries a prior boundary | Display source boundary as history; Packing still requires its own new boundary | Pending |
| Source-first, then quantity | Source visible while quantity is red; positive checked quantity turns row green | Pending |
| Two sources first, then numbered item/quantity choices | Both remain visible; quantities stay with explicitly identified items | Pending |
| Second physical source for same Item | Reject replacement; original evidence retained; no silent merge/drop | Pending |
| Wrong Item/warehouse/Company/UOM, expired/held source, unavailable quantity | Validation rejection; no stock reservation/run; affected readiness stays incomplete | Pending |
| Fill Hopper | Destination identity turns green only after an empty configured Hopper is checked | Pending |
| Existing carry-forward | Existing reservation visible; no unnecessary rescan or duplicate consumption | Pending |
| More than ten material choices | NEXT/PREVIOUS pages; numbered choice identifies the exact row | Pending |
| Touch Apply Quantity / Read Scan | Same readiness, validation and final request as scanner path | Pending |
| Rapid scans and Confirm during preview | Ordered processing; no cross-item quantity swap or incomplete submission | Pending |
| Error/cancel/context change during preview | Scanner focus restored; late response does not repopulate cancelled/changed context | Pending |
| Lost confirmation response vs explicit rejection | Original retry stable; corrections only after confirmed rejection/reconciliation | Pending |
| Ordinary operation with boundary None | No invented/mandatory output boundary; tracking defaults unchanged | Pending |

Existing executions retain their release-time policy/rule snapshots. Master edits
are not retroactive. Deploy backend and rebuilt operator assets together.


## Repeated Hopper run and allocation regression

Offline coverage in `test_operation_hoppers` and `test_material_run_pre_use_ui.cjs`
checks a second run within an allocation, an exhausted Operation Card with 2 units
still physically available, and the main Card's larger remaining allocation. The
checklist must show target/processed/remaining and clear cycle-closure guidance;
confirmation cannot reserve beyond the selected execution's target. No live result
is implied by these checks.

Site acceptance pending: allocate a Process Card for 3 against a Work Order for 5,
load a Hopper with 5, then report 3 through that Process Card. Its next Hopper preview
must stay red at 0 with Loaded/Available=2 and explain closure/reallocation. The main
Card must offer 2. Cancel, close/reallocate the Process Card through normal gates,
and confirm the next allocation can use the remaining 2 without re-reporting prior
work. Also test two reports of 2 and 3 within one allocation of 5, by scanner and touch.
Record deployed SHA, Card/Cycle/WO IDs and resulting reservations/progress. Verify
Operator Complete still permits partial closure, not over-allocation.

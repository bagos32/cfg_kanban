# Consolidated Customer Orders acceptance

Prepared 27 November 2026. Native-site acceptance: **Not run**. Record deployed SHA, site, actors,
document links, expected/actual quantities and evidence below before accepting the extension.

## Migration and setup

Run the owner's normal CFG-only migrate, asset build, cache clear and restart after updating code.
New default-off fields are added to Delivery Trip/Dispatch Plan, the office Plan link, demand lines,
Route Stop and Delivery Session. No existing records are converted, and no ERP stock is posted by
migration. Existing confirmed follow-on/carry-in requests keep their current planning mode.

Use an isolated test Company/source Warehouse/lorry. Prepare two submitted Sales Orders for two
Customers/Sites, including the same SKU on both orders, different prices, an additional SKU and
tagged plus untagged stock. Grant native Company/document access and existing office, dispatch,
Customer Delivery, driver/team, Supervisor and Logistics Reconciliation permissions as appropriate.
Configure the Profile's approval, proof and customer-verification policy explicitly.

## Site procedure

1. Save a new Draft Office Delivery Trip, enable automatic dispatch generation and **Consolidated
   Customer Orders**, assign the exact SO rows/quantities to their stops, then generate/Mark Planned.
   Expect one Customer Order Plan linked to All Customer Stops, exact demand lines and separate saved
   customer scopes. Generation must not reserve or post stock. Repeat generation: same Plan/scopes.
2. Reserve tagged and untagged goods on the correct customer demand rows. Reject excess quantities,
   wrong Company/Warehouse/Batch/UOM, unavailable stock and a tag already reserved elsewhere. Race two
   planners/operators for the last source quantity: only the permitted quantity may be reserved.
3. Pack two SKUs in one customer Loose Tag; retry the same request without another split/reservation.
   Undo it before claim: restore only its source quantities/certificates/expiry. Repack, retain the
   exact customer and source allocation identities, then print its normal QR. Check ordinary Quantity
   Bins, mixed Logistics Containers and Loose WIP Bins still use their existing rules.
4. Confirm LIFO instructions for both customers. Claim the actual lorry once, scan its tags/box QR,
   confirm loose quantities and post the loading Manifest through the native ERP gateway. A saved
   Draft is pending; only submitted Stock Entry feedback makes loading complete. Expect one shared
   loading movement, with exact tags, certificates, batches, expiry and native stock balances.
5. Approve a Route Sheet containing every exact customer scope, including the Open Route pool if
   configured. Reorder as permitted; reject an omitted/replaced scope or outside Site. Verify strict
   order and mandatory Site QR policies through driver, scanner and direct API entry points.
6. Start Route. Customer A sees only A's tags/loose quantities. Scan B's Site/box or submit B's source
   under A: reject without stock/evidence changes. For a full acceptance, create the native DN and
   required proof. Verify its Customer/address, exact SO item, rate, stock/sales UOM and conversion.
7. Complete A, then deliver B with a partial refusal on one line and reason/condition. Verify B's DN
   includes only accepted stock; refused stock remains in custody with its hold/QC decision. A's
   completion must not consume/release B's goods. Existing unrelated old-return collection still
   creates its own Return Case. Print/invoice selection and assistant access must use the right DN.
8. Lose a Begin Delivery response, reopen, double-scan and replay the same action. Verify one Session,
   one DN, one consumption/hold and stable request identity. A second device cannot start another
   customer while one is active. Reject a changed payload under the same action identity.
9. On another Trip, Supervisor-cancel one unused customer: release only its reservations and keep
   its original demand audit. If an unused shared claim is released, confirm the remaining load again.
   Once ERP work exists, reject direct cancellation until its controlled recovery permits it.
10. After loading, cancel one unstarted customer. Test both return hold and same-trip release. Other
    stops remain executable and the shared Manifest stays posted. Held stock remains unavailable;
    released stock becomes eligible only through the existing explicit sale/transfer checks. An
    ambiguous cancellation retry must not add another hold or release.
11. Start the single consolidated E5 review. Confirm delivered/refused/released/remaining quantities
    per source, one D3 lorry count, any controlled recovery and final settlement. Incomplete Sessions,
    pending proof and open Manifests must still block closure. Also test overnight continuation and
    E5 follow-on takeover: native delivered SO rows determine the exact remaining demand.
12. Repeat default-off planning: retain the existing separate Plan behavior. Verify denied Company,
    responsibility, unassigned driver/team and missing Supervisor rights remain rejected. Repeat
    with two SOs at one customer stop, including UOM conversion/different row rates. Reject incompatible
    currency/conversion, Price List or Project before creating a Session/reserving delivery stock.

Perform the routine scanner path in kiosk mode without a mouse: existing Start Prepared Delivery,
numbered scope selection, Site QR, Confirm, camera alternative, Cancel and focus after errors.

## Offline verification

The feature suite executes real generation, prepared-delivery/DN builder/feedback, source scoping,
customer outcomes, cancellation, E5 balances, route-sheet approval and Loose Tag services with
explicit ERP/document/database doubles. A separate case executes the actual aggregate commitment
SQL in SQLite; this is not MariaDB or native ERP stock acceptance. Browser fixtures use demo RPC.

Run `python3 -B -m unittest cfg_kanban.tests.test_consolidated_dispatch` and the relevant dispatch,
route, recovery, packing, team, printing and continuation regressions. Run the existing E4A UI suite
and `node cfg_kanban/tests/run_consolidated_dispatch_browser.mjs`, then repeat with
`CFG_BROWSER=firefox`. No fixture connects to a site, posts ERP stock or sends paper to a printer.

Verified offline on 27 November 2026:

- 31 consolidated feature tests passed, including native-service doubles, multiple SO row prices/
  conversions, tagged/untagged isolation, refusal/cancellation, E5, route scopes, Loose Tags and actual
  aggregate commitment SQL in SQLite.
- Combined relevant Python regressions: **849 run; 828 passed; 21 native permission tests skipped**
  because this checkout has no connected Frappe site.
- Node regressions: **131 passed**, including the prepared-delivery suite's 22 internal checks.
  Its extracted Logistics scanner harness now declares the existing Loose Tag state variables,
  which previously caused a fixture-only ReferenceError before its remaining checks could run.
- Offline Chrome and Firefox fixtures: **10 checks passed in each** for exact customer selection,
  wrong-site rejection, camera input, uncertain retry identity, no quantity re-entry and Cancel.

Native migration, transactional rollback/unique indexes, MariaDB concurrency, actual DN/proof/media
and stock/accounting feedback, kiosk hardware and printer acceptance remain to be run on the site.

| Deployed SHA / site | Tester / date | Evidence / result |
| --- | --- | --- |
| Not run | | |

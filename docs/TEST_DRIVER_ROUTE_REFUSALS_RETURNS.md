# Driver Route — refusals and old customer returns

Prepared: 21 November 2026, above `bb22248 Add driver route execution`.
Status: **Implemented locally; native-site acceptance Not run.**

## Approved behavior

- Use the separate driver route page and existing native Delivery Note/proof engine.
- Refuse quantities from today's exact prepared load before starting its Delivery Session.
- Good order reductions may be sold on the same trip under captured Dispatch Profile policy,
  or held until Supervisor release. Expiry/identity/other stock validity gates remain.
- Damage/quality refusals create a QC case for monitoring. They remain company-owned stock:
  no duplicate Material Receipt or customer credit.
- Old customer goods use existing Return Case custody → physical QC receipt → QC → independent
  accounting/physical disposition. An existing unreceived Temporary Return Note is reused.
- Preserve stable requests, native Company/customer/Item/Batch/UOM identities, authority,
  strict stop sequence, required Site QR policy and private media ownership.

## Local verification record

Offline executable checks use actual services/controllers with in-memory documents, native
service doubles, quantity math and DOM/RPC doubles. They cover prepared tagged/untagged delivery,
partial/zero/full acceptance, exact sources, UOM/serialization boundaries, refusal holds, owned
QC, native credit/receipt rejection, expiry-safe releases, recovery hold adoption/restoration,
settlement budgets, ERP stock-shortage rejection during loose recovery, exact native Issue disposal,
old-intake/reused-note scope, request receipts,
changed-operator/tab/retry behavior and reviewed scanner/touch input.

Run the targeted Python suites for driver delivery outcomes, collections/return actions, driver
route/actions, direct customer returns, prepared fulfilment, route delivery/sheets, office trips,
dispatch E3/reconciliation/recovery and vehicle overview. Run the corresponding driver/native
fulfilment/return/recovery/proof JavaScript suites. Local regression passed: **361 Python tests** and **85 Node runner tests** across ten JavaScript
suites (including their internal contract checks). Python/JSON parsing, DocType field/Select consistency, changed JavaScript syntax
and `git diff --check` are also required.

These doubles do **not** establish MariaDB locks/rollback/uniqueness, real ERP stock/accounting,
native validation/custom fields, S3/device permissions, printing or Frappe migration acceptance.

## Native acceptance setup

Use test Company/customer data, one Planned assigned Delivery Trip and physically loaded Customer
Order Vehicle Delivery Plans, with a mix of tagged and untagged Items and submitted loading Stock
Entries. Keep one flexible route and one approved strict route; include two SO Plans at a stop,
a Visit Only stop and a multi-day trip. Record initial stock, tag reservations, SO delivered qty,
source certificates/expiry and native document revisions.

Enable Customer Returns. Configure the Site's Customer Return QC/Inspection Location, terminal
native read permissions, Driver Customer Delivery + Customer Return + native Dispatch responsibility
and Start/Complete flags, QC responsibility, and a Supervisor with View All/Override. Test both
captured Sound Refused Goods policies. Do not edit read-only audit fields manually.

## Acceptance checklist

All results below are **Not run**. Record actual references, observations, exceptions and deployed
Git revision before treating any row as passed.

| Case | Expected result | Result / evidence |
| --- | --- | --- |
| Full acceptance | Routine confirmation reuses exact loaded sources, native DN/proof; no refusal Outcome/Case | Not run |
| Tagged partial 10 → 8 | DN consumes 8 only; original tag retains 2 on lorry, reserved/unavailable; SO delivered 8 | Not run |
| Mixed tagged and untagged partial | Exact accepted source quantities reach DN; held loose balances unavailable to all other allocation paths | Not run |
| Full refusal | Closed audited Session/Completed-with-refusal visit; no DN, proof or stock posting; all source stock held | Not run |
| Quantity validity | Negative, excessive, nonfinite, wrong whole-number UOM, missing source/reason, duplicate/substitute source rejected atomically | Not run |
| Serialized stock | Whole-tag accept/refuse only; partial requires prior controlled split | Not run |
| Native identity | Item/Batch/UOM/Company, SO conversions/currency/pricing and expiry/certificates stay enforced | Not run |
| Required Site verification | QR policy still enforced; wrong/guessed Site rejected; selection policy works without extra QR | Not run |
| Required proof / Draft | Partial accepted delivery still waits for configured ERP submission and real proof before release/stop completion | Not run |
| Default sound hold | Driver cannot resell/release without Supervisor; reasoned release after native closure frees only refused qty | Not run |
| Automatic sound release | Captured allow-resale policy releases only after native Closed; expired/invalid stock stays held | Not run |
| Damage/quality refusal | One owned-stock QC case with original source/trip/stop; no customer credit or second receipt | Not run |
| Owned QC | Physical QC start/result visible; Release Own Stock is separate from old-return credit; source remains held until authorized release | Not run |
| E5 tag/loose recovery | Original held remainder transfers through exact recovery Manifest/ERP stock movement; hold follows custody | Not run |
| Recovery cancellation | Unused recovery unreserves its allocation and restores refusal hold once; unrelated reservations remain protected | Not run |
| E5 released/disposed budget | Resolved refusal deducted exactly once; no second movement required for the original Plan; actual lorry count remains ERP-based | Not run |
| Owned disposal | QC approves full physical case; exact submitted native Material Issue confirmed once; tag ledger mirrors disposal without new ERP command | Not run |
| Disposal rejection | Wrong Issue Company/type/status/Batch/UOM/qty, reused Issue or changed custody rejected; no partial changes | Not run |
| Disposal evidence | Case/Issue unique link, audit and empty-container state agree; cancelling finalized evidence blocked | Not run |
| New old-return claim | Review/confirm creates one native Temporary Return Note; saved customer/company/location/UOM; no QR required for intake, no stock/credit yet | Not run |
| Existing Return Note | Number/QR collects full original claim without duplication; other customer/company, received/owned/already-collected case rejected | Not run |
| Old-return continuation | Warehouse receipt/start QC, private evidence, QC result, accountant source/credit and stock disposition work unchanged | Not run |
| Trip/stop visibility | Driver sees refused qty, hold/custody and QC states/print links; QC open list includes stock-pending owned cases | Not run |
| Visit Only / final stop | Old collection creates no delivery or fake stop completion; collection still available after driving Completed until office closes | Not run |
| Return permission | Missing role, action flag, native Company/customer/source/case read or driver assignment rejects without leakage | Not run |
| Frozen custody | Existing accepted/refused allocation cannot be released/replaced/cancelled independently; DN cancellation requires supervised recovery | Not run |
| Retry / transactions | Lost response, double confirm, concurrent tabs/operators, stock competition, failure after hold/Case creation: exact replay or full rollback, no duplicate stock/QC/DN/Event | Not run |
| Tablet/scanner | Accepted/refused row edits, old-note QR, multiple old Items, review/edit/confirm/cancel, Enter/Tab, camera, focus and owner changes work on actual device | Not run |
| Notes/printing | Refusal QC note identifies already-owned stock; old note remains temporary custody; standard print result matches case/Batch/expiry/UOM | Not run |

## Remaining boundary

Refusals are entered **before Begin Delivery** for a new prepared Session. A recorded source
outcome is immutable. This phase provides no arbitrary outcome rewrite, automatic accepted-DN
cancellation, partial-case owned-stock disposal or live route resequence approval. Use audited
Supervisor recovery for those exceptions. Existing open Sessions continue their original
prepared flow. Office route planning and final E5 reconciliation remain separate.

A return's reported original reference is informational; it does not silently choose an accounting
invoice. Private evidence remains in the existing S3 workflow. No map/tracking, thermal printer
or independent return/accounting/stock engine is introduced.

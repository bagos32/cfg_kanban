# Package D2B — Post-QC Customer Return Accounting System Test

This procedure tests the accountant-controlled continuation of a **Customer Return for QC**. It
does not test wrong-Delivery-Note correction, which remains the separate Package D2A Return
Delivery Note flow.

## 1. Scope and safety boundary

D2B lets an authorized Desk user make one of three decisions after QC:

- use the exact submitted Sales Invoice selected by accounting;
- use an approved substitute historical Sales Invoice for the same Company, Customer and Items; or
- approve **No Credit** with a mandatory reason.

The positive credit path creates a **Draft, non-stock ERPNext Sales Invoice Return**. It does not
submit it. The accountant must review rates, taxes and all e-Invoice requirements in ERPNext. The
driver and QC operator cannot select an invoice or create the credit document.

D2B does not put accepted physical goods into available stock. Use Package D2C for the independent
controlled stock-disposition and ERPNext Material Receipt workflow.

## 2. Required setup and sample data

1. Deploy and migrate the D2B revision, build assets and clear cache.
2. Use an ERPNext user with **Accounts User**, **Accounts Manager**, **Sales Manager**, or **System
   Manager**. The positive credit path also requires Create permission for **Sales Invoice**.
3. Complete Package D2A until one `CFG Kanban Return Case` has:
   - Floor Workflow: `Customer Return for QC`;
   - Return State: `QC Completed - Accounting Pending`;
   - Accounting Status: `Pending Source Selection`;
   - Total QC Accepted Qty: `2`.
4. Keep one submitted, non-return Sales Invoice for the same Selling Company and Customer. Its
   remaining uncredited quantity must include at least `2` of the accepted Item.

Suggested example:

| Data | Value |
|---|---|
| Return Case | completed D2A case |
| Accepted Item | existing stock Item from that case |
| QC accepted quantity | `2` |
| Source invoice | submitted non-return Sales Invoice |
| Source basis | `Exact Sales Invoice` |
| Decision notes | `QC accepted two units; accounting source verified` |

## 3. Prepare an exact-source Draft credit return

1. Open the completed **CFG Kanban Return Case** in Desk.
2. Select **Accounting → Prepare Accounting Decision**.
3. Confirm the dialog shows the accepted Item, quantity and UOM.
4. Select `Exact Sales Invoice`.
5. Select the submitted source Sales Invoice.
6. Enter the decision notes and select **Apply Decision**.

Expected:

- only invoices for the Return Case Company and Customer are selectable;
- the candidate list indicates whether remaining invoice quantities cover all QC-accepted Items;
- one `CFG ERP Command` of type `Create Customer Credit Return` completes;
- one Draft Sales Invoice is opened with `Is Return = 1` and `Return Against` equal to the selected
  source invoice;
- `Update Stock = 0`;
- returned stock quantities are negative and exactly match the QC-accepted quantities;
- Customer Return Case and Kanban Accounting Event Identity are populated;
- Return Case Accounting Status is `Credit Pending` and Credit Document Status is `Draft`;
- no Stock Ledger Entry or GL Entry is posted by preparing the Draft.

Repeat **Prepare Accounting Decision** without cancelling the Draft. Expected: the same Draft is
returned; no duplicate credit document is created.

## 4. Accountant review and ERPNext feedback

1. In the Draft Sales Invoice Return, complete every mandatory tax, account, cost centre, e-Invoice
   and Company-specific field required by the installed ERPNext/custom apps.
2. Do not enable Update Stock.
3. Submit the Sales Invoice Return manually in ERPNext.
4. Return to the CFG Kanban Return Case and refresh.

Expected:

- submission is rejected if Company, Customer, Return Against, Update Stock, Items or quantities no
  longer match the controlled Return Case;
- a valid submission changes Return State to `Accounting Completed`, or `Closed` when Package D2C
  stock disposition already completed;
- Accounting Status becomes `Completed` and Credit Document Status becomes `Submitted`;
- a `Customer Credit Return Submitted` event records the ERP document;
- ERPNext owns GL/e-Invoice validation and posting;
- no ERP stock quantity is added by this accounting return.

## 5. Substitute historical invoice test

Use a separate D2A Return Case for the same customer and choose `Substitute Historical Sales
Invoice`. Select another submitted non-return invoice that has sufficient remaining quantity for
every QC-accepted Item, and explain the substitution in Decision Notes.

Expected: the Draft is created against that selected invoice and the source basis, deciding user,
decision time and notes are preserved on the Return Case. A draft/cancelled invoice, a return
invoice, a different Company or Customer, a missing Item, or insufficient uncredited quantity is
rejected.

## 6. No Credit test

Use a separate accounting-pending Return Case. Select `No Credit`, enter a reason such as `Customer
custody damage; claim not accepted`, and apply the decision.

Expected:

- a Sales Invoice must not be selected;
- no Sales Invoice Return is created;
- Return State becomes `Accounting Completed`, or `Closed` when stock disposition already completed;
- Accounting Status becomes `No Credit Approved`;
- deciding user, time and notes are retained in the audit record;
- physical goods still remain under the separate inspection/disposition boundary.

## 7. Cancellation and controlled replacement

Cancel a submitted D2B Sales Invoice Return in ERPNext.

Expected:

- Return State reopens to `QC Completed - Accounting Pending`;
- Accounting Status becomes `Source Selected`;
- Credit Document Status becomes `Cancelled`;
- Accounting Revision increments and a cancellation event is recorded;
- **Prepare Accounting Decision** can create one controlled replacement Draft;
- when the same source invoice is retained, ERPNext amendment lineage points to the cancelled
  document; choosing another valid source remains audit-visible through the old event and new link.

Attempt **No Credit** while an active Draft or submitted credit return exists. Expected: the action
is blocked; cancel the ERP document first.

## 8. Permission and negative tests

Verify all of the following:

- a floor-only Kanban operator cannot see or call the accounting action;
- a Desk user without one of the approved roles is rejected;
- an approved-role user without Sales Invoice Create permission is rejected when preparing a credit
  return (but can still record No Credit);
- changing the Draft to update stock is rejected on submit;
- changing Customer, Company, source invoice, Item or controlled quantity is rejected on submit;
- repeated requests do not create duplicate ERP Commands or Sales Invoice Returns.

## 9. Pass criterion

D2B passes when the accountant can close a case as No Credit or prepare exactly one controlled
Draft Sales Invoice Return from QC-accepted quantities, ERPNext retains tax/e-Invoice submission
control, submit/cancel feedback updates the Return Case, and neither the draft preparation nor the
accounting return changes ERP stock.


## 10. Native v15 credit-return numbering

Accepted owner clarification, 20 November 2026: CFG must use ERPNext/Frappe's configured document
series defaults and native Document Naming Rule precedence. Do not introduce an app-owned Credit
Note prefix, infer a return series from option text, copy an original invoice's series manually,
or generate a provisional document number before insertion.

Implementation above base commit `132b44a`:

- `_apply_native_naming_series_default` fills only a missing series from `frappe.new_doc`, then
  uses `get_default_naming_series` if that native default is still empty. This corrects the common
  ERP preflight's previous first-option-only choice and makes credit-return defaults explicit.
- `create_customer_credit_return` still uses native `make_return_doc` and ordinary `insert`.
  No early `set_new_name`, `make_autoname`, rule `apply`, counter update, or hardcoded return prefix
  is added. Mapped/hook-selected series, Draft-only non-stock accounting, quantity controls,
  idempotent existing credit reuse and amendment lineage remain in force.
- The ERP Command result records the generated `name` independently of its `naming_series`,
  together with `is_return` and `amended_from`. Native Naming Rules can assign an ID while leaving
  the Series field at its default; this alone is not evidence that the rule was ignored.

Verified upstream references for the reported versions:
[Frappe v15.69.2 naming flow](https://github.com/frappe/frappe/blob/v15.69.2/frappe/model/naming.py),
[native new-document defaults](https://github.com/frappe/frappe/blob/v15.69.2/frappe/model/create_new.py),
[native insertion](https://github.com/frappe/frappe/blob/v15.69.2/frappe/model/document.py),
[ERPNext v15.65.1 return mapper](https://github.com/frappe/erpnext/blob/v15.65.1/erpnext/controllers/sales_and_purchase_return.py).
Native amendment naming, when applicable, precedes a new rule-generated name; the implementation
preserves that order.

### Offline evidence

- The new gateway/default regression module has **12 passing application tests** with dependency
  doubles: configured default versus first option, native fallback, existing selected series,
  missing series fields, native-insert delegation, result evidence, no duplicate naming on retry,
  same/different-source amendment lineage, source Company and remaining-quantity rejection.
- **5 installed-Frappe naming-engine tests are skipped locally** because Frappe is not installed.
  They cover native rule priority/Company matching, return versus invoice conditions, fallback,
  Series field versus document ID, and amendment precedence with substituted counters. Even a
  future pass of these isolated functions is not a native transaction/site acceptance.
- The relevant schema/direct-return suite passed, as did the existing prepared/open-route/
  warehouse-delivery, recovery and stock-identity regressions. No development-server test was run.

The source audit found no explicit CFG bypass of native Naming Rules on this credit-return path.
The existing mapper normally supplies a native default already. Therefore this change must not be
reported as reproducing or fixing every site-specific rule mismatch: the reported development-site
case still needs its actual rule, Company, generated ID and deployed revision checked below.

### Native test-site checklist — all Not run

Use an isolated test site, approved test Company and fresh accepted Return Cases. Record exact rule
conditions/priorities, field default/series options, deployed Git revision, source invoices, created
Credit Notes and command result evidence. Do not edit production numbering counters to run tests.

| Case | Expected | Result |
| --- | --- | --- |
| Configured Series default differs from first option; no matching naming rule | Credit uses the same native default/fallback as a standard newly inserted Sales Invoice Return | Not run |
| Enabled Sales Invoice rule with Is Return = 1 and correct Company | Native rule controls generated document ID on Kanban Draft insertion | Not run |
| Two matching rules with differing priority | Native higher-priority rule controls ID; no CFG prefix override | Not run |
| Wrong-Company, disabled or nonmatching return rule | Native remaining matching rule or standard fallback controls ID | Not run |
| Inspect Series field versus document ID | Any difference caused by a rule is visible separately in ERP Command Result Payload; Series need not be rewritten by native rules | Not run |
| Normal Sales Invoice | Existing native non-return numbering remains unchanged | Not run |
| Repeated Prepare Accounting Decision / command replay | Existing Draft/submitted credit reopens with the original ID and no extra credit/number allocation | Not run |
| Cancelled credit; same approved source | Native amendment naming/lineage is honoured according to installed settings | Not run |
| Cancelled credit; different approved source | No amendment to the unrelated cancelled credit; native new-document naming applies | Not run |
| Native Company/accounting/e-Invoice hooks and failed validation | Native hooks execute at insertion in their usual order; transaction/numbering behaviour matches ERPNext | Not run |

Acceptance evidence / exceptions:

- Deployed Git revision:
- Site / date / accounting user:
- Company / field default / series options:
- Matching rules / conditions / priorities / amendment settings:
- Return Cases / source invoices / Credit Note document IDs / Series values:
- Command result / native audit evidence:
- Decision / unresolved discrepancy:


## 11. Optional custom Credit Note choice — development extension

Approved requirement and owner-provided schema/controller evidence, 20 November 2026, above
`7c503b8`: keep standard Sales Invoice Return as the default; checking **Create Custom Credit Note**
creates the separate custom Credit Note Draft. Read [the setup guide](USER_GUIDE_CUSTOM_CREDIT_NOTE_RETURNS.md).
The existing custom controller creates an additional native Sales Invoice Return Draft on submit;
accounting completes only on native posting. This is separate from the earlier native-series fix.

Offline verification exercises actual gateway, adapter, accounting feedback and Desk UI functions
with dependency substitutes. It covers both choices, native/custom identity separation, exact QC
stock quantity/UOM/source row, optional-app/schema/permission rejection, idempotent reuse/target
conflicts, generated native linkage, duplicate-return rejection, posting/cancellation/amendment and
explicit generated-Draft discard audit. Native custom-controller/tax, migration, database,
transaction, permission and live-site acceptance are not established by these checks.

Final local verification on 20 November 2026: **291 Python tests passed, 5 installed-Frappe
naming tests skipped**. This includes **25 new custom Credit Note tests**. **35 JavaScript UI
checks passed**, including 8 for the new Desk choice and 27 existing direct-return checks.
Source/schema and diff-whitespace checks passed for the scoped changes. No live-site/custom-app
submission or native migration/transaction acceptance was performed.

### Test-site acceptance — Not run

| Case | Expected | Result |
| --- | --- | --- |
| Optional DocType absent | Core migration and default Sales Invoice Return work; custom choice unavailable | Not run |
| Optional DocType installed, migration | Only CFG trace fields added to existing Credit Note; original custom app/schema/controller preserved | Not run |
| Default checkbox | One non-stock Draft Sales Invoice Return using native numbering; no custom Note | Not run |
| Checked custom choice | One Draft Credit Note with its own native CN/default/rule numbering, Credit Note Item rows, original invoice source and exact QC stock quantities | Not run |
| Amounts/taxes/currency | Existing custom controller correctly recalculates partial accepted quantities, taxes, currency and account defaults | Not run |
| Permissions and Company | Existing accountant role/Create gates plus custom Note Read/Create; wrong source Company/Customer rejected | Not run |
| Retry/target conflict | Original document reused; changed target cannot create another credit for the same accounting revision | Not run |
| No Credit | Custom choice cleared; no accounting document; active custom/default credit prevents conflicting No Credit | Not run |
| Submit custom Note | Exactly one native Draft with exact Return Against Credit Note link; Case keeps custom identity and records native link; accounting still pending | Not run |
| Missing native link/controller error | Entire failed submit rolls back; no orphan or silently guessed native invoice | Not run |
| Native posting | Accountant submits native return; Case accounting completes; stock disposition remains independent | Not run |
| Tampering/duplicate source rows | Wrong identity/source/UOM/conversion/quantity or second active return rejected; custom repeated Item/UOM ambiguity directs to standard path | Not run |
| Cancellation and amendment | Active native document blocks custom cancellation; native cancellation reopens accounting; permitted native amendment and later custom cancellation preserve both histories | Not run |
| Explicit generated-Draft deletion | Native Draft discard audit retained; Case native link cleared before normal reference checks; custom cancellation can proceed | Not run |
| Two sessions/partial failures | One credit per Case/revision; native rollback, hook ordering and locks verified under concurrency | Not run |
| Desk opening | Creation and existing-document buttons open the selected DocType; native accounting button opens its separate invoice | Not run |

Record deployed revision, Company, source invoice, Return Case, custom Note and linked native return,
actual permissions/GL/e-Invoice evidence, exceptions and the acceptance decision. Existing numbering
counters and historical transactional documents must not be edited to make the test pass.

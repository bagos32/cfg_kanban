# Optional custom Credit Note for post-QC returns

## Decision and existing custom workflow

Owner-approved choice, 20 November 2026: **Sales Invoice Return remains the default**. Checking
**Create Custom Credit Note** in **Return Case → Accounting → Prepare Accounting Decision** creates
the site's separate **Credit Note** Draft instead. No floor/operator accounting action is added.

The owner supplied development-site definitions and the complete `CreditNote` controller:

- Parent: `Credit Note`, module `ERPNext Changes`, submittable, `autoname = naming_series:`.
- Its Series options/default are currently `CN-`, and Is Return defaults to 1.
- Its Items table uses `Credit Note Item`, with native-style stock UOM, conversion, quantity, rate,
  accounts, source `sales_invoice_item` and certificate fields.
- Sales Invoice has `return_against_credit_note`, a Link to Credit Note.
- The existing custom controller calculates totals and, on Credit Note submission, creates a Draft
  Sales Invoice Return. It does not submit that accounting invoice.

The earlier naming-series investigation concerned a different document target. Selecting a default
Sales Invoice series cannot create this custom DocType. Both targets continue to use their own
native defaults, Naming Rules, counters and amendment settings; CFG hardcodes no `CN-` prefix.

## Setup

1. Deploy/migrate/build through the owner's manual development-site process. CFG adds two read-only
   trace fields to Credit Note only when that custom DocType is already installed. It never creates
   Credit Note or imports/modifies its owning app. Standard returns continue on sites without it.
2. The accounting user retains the existing Accounts/Sales Manager/System Manager role gate and
   Sales Invoice Create permission. The custom choice additionally requires Credit Note Read/Create.
   Normal ERPNext permissions govern later editing, submission, cancellation and Draft deletion.
3. Verify the custom Items fields and Sales Invoice's existing Return Against Credit Note link.
   Missing migration/schema requirements produce a rejection, with no substitute invoice created.
4. Keep Company, Customer, approved submitted source invoice and QC-accepted stock quantities valid.
   Accounting remains separate from physical quarantine/rework/return stock disposition.

## Default choice in Settings

Open **CFG Kanban Settings → Customer Return Workflows**, enable **Use Custom Credit Note by
Default** and Save. This makes **Create Custom Credit Note** checked when opening a new Accounting
Decision dialog, when the custom DocType and permissions are available. Accountants may uncheck it
for an individual decision. The new setting initially defaults to off, preserving the existing
standard Sales Invoice Return choice. No Credit clears the checkbox. Existing Drafts, recorded
commands and historical decisions are unchanged; the setting does not automatically create or
submit documents. API calls that omit the per-decision option retain their standard return default.

## Prepare the selected Draft

Open a fresh QC-completed Return Case, choose Exact Sales Invoice or Substitute Historical Sales
Invoice, select its source and enter decision notes.

- **Unchecked** creates the existing non-stock Draft Sales Invoice Return.
- **Checked** creates one custom Credit Note Draft. Its own Series/default and applicable Naming
  Rules control its document number. The source invoice number/series is not copied as its identity.
- **No Credit** hides/clears the custom choice and creates neither document.

The custom Draft uses the same native return mapper and QC-selected quantities before copying
compatible business fields into the custom parent/child schemas. The custom controller calculates
its amounts/taxes. Names, parent identity, status, workflow and amendment identity are not cloned.
Both document types stay Draft for accountant review. Retry reuses the recorded document; an active
credit or recorded command cannot silently change target DocType. Existing Drafts are not converted
or renamed by checking the new option.

## Submit and inspect accounting

1. Review and submit the custom Credit Note in ERPNext. Its existing controller creates its native
   Sales Invoice Return through `return_against_credit_note`.
2. **Final Credit Document** stays linked to the custom Note, with **Credit Document Status = Submitted**.
   **Accounting Sales Invoice Return / Status** records the generated native Draft separately.
3. **Accounting Status remains Credit Pending.** Open the native Draft using **Open Accounting Sales
   Invoice Return**, review the tax/e-Invoice/accounting fields and submit it in ERPNext.
4. Native submission completes accounting; the Case closes only when stock disposition is also
   completed. CFG performs no extra stock movement, GL entry, automatic invoice submission or
   e-Invoice submission merely because a Draft was prepared.

Missing/ambiguous generated-invoice links, a second active invoice, altered Company/Customer/source,
positive or inconsistent quantities, wrong stock UOM and a changed approved source row are rejected.
The integration relies on the custom controller's existing exact link; it never infers a link from
similar customer names, quantities or creation times.

## Cancellation and limits

- Cancel the submitted native accounting return first, or explicitly discard its unsubmitted Draft
  in ERPNext, before cancelling its custom Credit Note. Discarding the generated Draft records a
  snapshot audit and clears its Case link; it does not post accounting.
- Native invoice cancellation reopens accounting while retaining the submitted custom Note. Its
  controlled native amendment can replace the cancelled accounting invoice.
- Cancelling the custom Note increments the Case accounting revision so one controlled replacement
  may be prepared. Same-DocType/same-source replacement preserves native amendment lineage.
- The supplied custom controller finds the original row by Item and UOM and takes the first match.
  Until that owning controller supports exact repeated rows, custom creation/submission rejects
  ambiguous or missing Item/UOM rows. Use the unchecked standard return path for that source.
- Accountant review remains responsible for rates, taxes, custom mandatory fields and e-Invoice
  treatment. Native tax totals, custom-controller execution, permissions, migration, rollback and
  concurrency require actual test-site acceptance.

See [the D2B acceptance procedure](TEST_PACKAGE_D2B_CUSTOMER_RETURN_ACCOUNTING.md).

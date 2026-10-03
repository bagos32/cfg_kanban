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

# Package D2A — Customer Return and Delivery Correction System Test

This package has two deliberately separate floor workflows. Do not use the wrong-Delivery-Note
workflow for damaged, expired, disputed, or ambiguous customer returns.

## 1. Required setup

1. Enable **Customer Return Workflows** in **CFG Kanban Settings**.
2. On one Customer Scan Point enable **Customer Return for QC**, set **Default Inspection Custody
   Location**, enable **Wrong Delivery Note Correction**, set its selling-company **Delivery
   Correction Return Warehouse**, and leave auto-submit correction disabled for the first test.
3. Give the driver **Customer Return** Responsibility with Start and Complete permissions.
4. Give the QC employee **Customer Return QC** Responsibility with Start and Complete permissions.
5. Keep one completed Customer Delivery Session with a submitted Delivery Note for the correction
   test. Use a Delivery Note that is not yet invoiced for the positive auto-submit test.

Example:

| Data | Value |
|---|---|
| Customer Site Code | `CUS-SITE-RETURN-TEST` |
| Inspection Location | `QC Return Cage - TEST` |
| Return Warehouse | selling-company non-group Warehouse |
| Returned Item | existing stock Item |
| Batch | optional Batch belonging to the Item |
| Physical Qty | `3` |
| Condition | `Damaged` |

## 2. Driver issues a Temporary Return Note

1. Log into **Logistics Operator Panel** as the driver.
2. Scan `CUS-SITE-RETURN-TEST` and select **Customer Return for QC**.
3. Confirm the warning says this is not a tax Credit Note, e-Invoice, or ERP stock receipt.
4. Enter reason `Seal damaged at customer site`.
5. Optionally enter the customer representative who acknowledges physical handover.
6. Add the Item, optional Batch and expiry, physical quantity `3`, condition `Damaged`, optional
   preprinted Stock Tag/reference, and details.
7. Select **Issue Temporary Return Note**.
8. On the created Return Case, take one timestamped/geotagged photograph and upload one supporting
   file or PDF. Open each file, then remove and upload a replacement while the case remains open.

Expected:

- a `CFG Kanban Return Case` is created in `Awaiting QC Receipt`;
- Original Delivery Note is blank and is not required;
- Customer, address, site, Company, inspection Location, operator and time are snapshotted;
- optional customer acknowledgement name/time are snapshotted and appear on the print;
- no Delivery Note, Sales Invoice, Credit Note, GL Entry, or Stock Ledger Entry is created;
- multiple return photos/files are private S3 media records owned by this Return Case; camera photos
  carry the visible server timestamp, Return Case identity and GPS stamp;
- the Return Case can print **CFG Temporary Return Note** with a QR containing its case number;
- scanning the case number/QR retrieves the live Return Case.

Negative tests: invalid Item, Batch belonging to another Item, zero/negative quantity, fractional
quantity for a whole-number UOM, missing custody Location, or duplicate event token.

## 3. QC receipt and disposition

1. Log in as the QC operator and scan the Temporary Return Note QR.
2. Select **Receive and Start QC**. Expected state: `QC In Progress`.
3. Select **Complete QC Result**. For quantity `3`, enter Received `3`, Accepted `2`, Rejected `1`,
   choose a disposition for every row, enter reasons/notes, and complete.

Expected:

- Accepted + Rejected must equal Received, and Received cannot exceed intake quantity;
- state becomes `QC Completed - Accounting Pending` when any quantity is accepted;
- accounting status becomes `Pending Source Selection`;
- a fully rejected case becomes `QC Rejected` / `No Credit Approved`;
- QC operator and timestamps are immutable audit evidence;
- evidence becomes read-only after QC completion and remains available through temporary view URLs;
- QC completion still creates no available ERP stock or accounting credit.

The supervisor/accountant later selects the exact Sales Invoice, an approved substitute historical
Sales Invoice, or No Credit in the ERP/accounting workflow. Driver and QC screens never make that
choice and never create the custom `Credit Note` DocType.

## 4. Wrong Delivery Note correction

1. Open a completed Delivery Session with a submitted, non-return Delivery Note.
2. Select **Correct Wrong Delivery Note**.
3. Enter reason `Wrong quantity delivered`, select a reversal quantity no greater than the remaining
   delivered quantity, and create the Return Delivery Note.

Expected with site auto-submit disabled:

- Return Case workflow is `Delivery Note Correction`;
- original Delivery Session, submitted Delivery Note, exact row, Item, Batch, UOM and Stock Tag are
  snapshotted;
- ERPNext creates a Draft Return Delivery Note with `is_return=1` and `return_against` equal to the
  original Delivery Note;
- quantities are negative and limited to the original delivered quantities;
- destination Warehouse is the configured selling-company correction Warehouse;
- no Sales Invoice Return/Credit Note is created.

Enable auto-submit and repeat against an uninvoiced submitted Delivery Note. Expected: the Return
Delivery Note submits and ERPNext confirms the stock reversal.

## 5. Already-invoiced Delivery Note safety test

Repeat correction using a Delivery Note linked to a submitted Sales Invoice.

Expected:

- the panel clearly lists the submitted Sales Invoice and shows **Accounting attention required**;
- even when site auto-submit is enabled, the Return Delivery Note remains Draft;
- ERPNext may prevent later submission until the linked accounting/e-Invoice correction is handled;
- the system never silently creates, chooses, or posts an accounting credit.

## 6. Pass criterion

D2A passes when QC returns can start at the Customer Site without an old invoice/DN, remain non-stock
custody until QC, and hand only accepted results to accounting; while wrong-DN correction requires
the exact submitted Delivery Note, never exceeds it, and creates only the controlled Return Delivery
Note with explicit accounting-attention protection.

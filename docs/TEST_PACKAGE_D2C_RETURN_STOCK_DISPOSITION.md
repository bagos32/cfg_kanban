# Package D2C — Accepted Customer Return Stock Disposition System Test

This procedure tests the physical-stock continuation after Customer Return QC. Accounting credit
(Package D2B) and physical stock are deliberately independent: either may finish first, and the
Return Case closes only when both are complete.

## 1. Scope and ERP boundary

D2C allocates every QC-accepted quantity to one or more of these exact dispositions:

- `Receive to Quarantine`;
- `Receive for Rework`;
- `Return to Available Stock`; or
- `Dispose Without Stock Receipt`.

The first three create a **Draft ERPNext Material Receipt Stock Entry**. Stock changes only when a
Stock Manager submits that document. Disposal creates no Stock Entry and must not increase ERPNext
stock. D2C never creates or changes the accounting Sales Invoice Return.

## 2. Required setup and sample data

1. Deploy and migrate the D2C revision, build assets and clear cache.
2. Use a Return Case with completed QC and accepted quantity. Accounting may be pending or complete.
3. Give the decision user **Stock Manager**, **Quality Manager**, or **System Manager**. A Warehouse
   receipt also requires Stock Entry Create permission.
4. Prepare non-group Warehouses belonging to the Return Case Selling Company, for example:

| Warehouse purpose | Example |
|---|---|
| Quarantine | `Customer Return Quarantine - TEST` |
| Rework | `Customer Return Rework - TEST` |
| Available stock | existing sales-company stock Warehouse |

5. Obtain the approved inventory valuation rate from the Stock/Accounts team. Do not use the sales
   price unless that is the Company's approved stock-valuation policy.

Suggested first case: one Item with QC Accepted Qty `3`, split as `2` to quarantine and `1` to
controlled disposal.

## 3. Prepare a mixed disposition

1. Open the completed **CFG Kanban Return Case** in Desk.
2. Select **Stock → Prepare Stock Disposition**.
3. Keep the first row for quantity `2`, choose `Receive to Quarantine`, select the selling-company
   quarantine Warehouse, enter the approved Valuation Rate and a reason.
4. Add a second row for the same Return Row and Item, quantity `1`, choose `Dispose Without Stock
   Receipt`, leave Warehouse and Valuation Rate empty/zero, and enter a disposal reason.
5. Enter Overall Disposition Decision Notes and apply.

Expected:

- the sum of disposition rows must exactly equal the accepted quantity `3`;
- the selected Warehouse must be non-group and belong to the Return Case Selling Company;
- disposal cannot have a Warehouse;
- a positive Valuation Rate is required unless the Item explicitly permits zero valuation;
- one Draft Material Receipt is created for only the `2` quarantine units;
- the disposal unit is not included in the Stock Entry;
- Return Case Stock Disposition Status becomes `Stock Receipt Draft`;
- ERP stock remains unchanged while the Stock Entry is Draft.

## 4. Verify and submit the Material Receipt

1. Open the linked **Return Material Receipt**.
2. Confirm Stock Entry Type is `Material Receipt`, Company matches the Return Case, and the CFG
   Customer Return Case link is populated.
3. Confirm Item, quantity, target Warehouse and approved Valuation Rate match the decision.
4. For batch/serial-controlled Items, complete the ERPNext v15 Batch/Serial Bundle requirements while
   retaining the physical return identity.
5. Submit the Stock Entry.

Expected:

- changing Company, Stock Entry Type, Item, controlled quantity, target Warehouse or approved
  Valuation Rate is rejected;
- ERPNext posts exactly the received quantity to the selected Warehouse;
- receipt disposition rows become `Posted` and disposal rows become `Disposed`;
- Stock Disposition Status becomes `Completed` and Material Receipt Status becomes `Submitted`;
- a `Customer Return Stock Disposition Posted` event identifies the submitted Stock Entry;
- if accounting is still pending, Return State remains `QC Completed - Accounting Pending`;
- if accounting already completed, Return State becomes `Closed`.

## 5. Accounting finishes after stock

On a case where D2C completed first, follow Package D2B and submit the controlled Sales Invoice
Return or approve No Credit.

Expected: the Return Case becomes `Closed`. The Material Receipt remains the stock authority and the
Sales Invoice Return remains the accounting authority; neither document replaces the other.

## 6. Disposal-only test

Use a separate accepted Return Case. Allocate every accepted quantity to `Dispose Without Stock
Receipt`, enter a reason for every split and overall notes, then apply.

Expected:

- no Stock Entry or Stock Ledger Entry is created;
- every disposition row becomes `Disposed`;
- Stock Disposition Status becomes `Completed` and Material Receipt Status is `Not Required`;
- state is `Closed` only when accounting is also completed; otherwise accounting remains pending.

## 7. Draft discard, cancellation and replacement

### Discard before submission

On a Draft return Material Receipt, use **Stock → Discard Return Material Receipt Draft**, enter a
reason, then refresh the Return Case.

Expected: only the linked Draft is deleted, the reason is audited, Disposition Revision increments,
and **Prepare Stock Disposition** becomes available for a corrected decision.

### Cancel after submission

Cancel a submitted return Material Receipt using ERPNext's normal cancellation control.

Expected:

- ERPNext reverses its Stock Ledger effect;
- Stock Disposition Status returns to `Decision Recorded`;
- Material Receipt Status becomes `Cancelled`;
- receipt rows become `Cancelled`, Disposition Revision increments and an event is recorded;
- if accounting is complete, Return State returns to `Accounting Completed`; otherwise it returns
  to `QC Completed - Accounting Pending`;
- a controlled replacement Draft can be prepared.

## 8. Negative and permission tests

Verify rejection of:

- disposition before QC completion or with no accepted quantity;
- missing or excess quantity, including split totals that differ from accepted quantity;
- a Return Row from another case;
- invalid disposition value or missing reason;
- group Warehouse, wrong-Company Warehouse, or missing Warehouse for a receipt disposition;
- Warehouse entered for disposal;
- negative valuation or zero valuation when the Item does not permit it;
- floor-only users and unauthorized Desk roles;
- preparing a second Stock Entry while the controlled Draft/submitted entry is active;
- deleting or changing controlled Stock Entry rows to bypass the Return Case decision.

## 9. Pass criterion

D2C passes when every QC-accepted quantity is conserved across controlled receipt/disposal splits,
only submitted ERPNext Material Receipts change stock, disposal never invents stock, cancellation
reopens the physical track safely, and the Return Case closes only after both stock disposition and
accounting are complete.

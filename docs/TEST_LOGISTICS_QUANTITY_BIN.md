# Logistics Quantity Bin — Partial Load Without Child Tag

## Purpose

Verify that a permanent lorry/bin QR can temporarily identify a controlled partial quantity without
printing a detachable child tag, while ERPNext remains the stock system of record.

## Test data

- One active source Main Stock Tag with 20 units available.
- One empty reusable Handling Unit configured as **Logistics Quantity Bin** in the same Company and
  Warehouse.
- An operator with **Container Loading** and the applicable Logistics Route responsibility.
- One internal-transfer Logistics Route from the source Warehouse to a destination Warehouse.

## Test 1 — Partial load

1. Open **Kanban Logistics** and identify the operator.
2. Scan the Logistics Quantity Bin and select **Manage Contents**.
3. Scan the 20-unit source tag, enter quantity `6`, enter a reason, and select **Load Quantity**.

Expected:

- no child or unused destination tag is requested;
- source available quantity becomes 14;
- the permanent bin shows 6 units with the source Item, Batch and UOM;
- Container Content and Handling Unit Quantity Ledger preserve the source-to-bin relationship;
- rescanning the bin shows the same balance.

## Test 2 — Matching top-up and mismatch rejection

1. Load another quantity from a tag with the same Item, Batch and UOM.
2. Attempt to load another Item or Batch.

Expected: the matching quantity is added; the mismatched load is rejected without changing either
balance.

## Test 3 — Controlled return

1. Select **Return to Source** on one bin fill.
2. Return part of its available quantity with a reason.
3. Return its remaining quantity.

Expected: every return restores the exact original source tag; the internal fill decreases; the
membership closes when its balance reaches zero; and the bin becomes Empty when no fill remains.

## Test 4 — Manifest movement

1. Load the bin again and create a Draft Manifest for the configured route.
2. Start dispatch scanning and scan the permanent bin QR once.
3. Prepare, dispatch, receive and complete the ERP-controlled transfer.

Expected: the Manifest expands the bin into its controlled internal fill lines, moves the exact
quantity once, and ERP submission updates both bin and contents to the destination Warehouse.

## Negative controls

- Quantity above source availability is rejected.
- Zero or negative quantity is rejected.
- Decimal quantity for a whole-number UOM is rejected.
- Reserved, serialized, wrong-Company, wrong-Warehouse or already-containerized source tags are
  rejected.
- Item/Batch/UOM mixing is rejected.
- Loading or returning while the bin is on an open Manifest or Delivery Session is rejected.
- Repeating one request with the same event token does not duplicate quantity.

## Pass criteria

The package passes when the permanent bin QR replaces the disposable split tag in operator use,
both source and bin balances remain conserved, every movement is auditable and idempotent, and only
submitted ERPNext documents change Warehouse stock.

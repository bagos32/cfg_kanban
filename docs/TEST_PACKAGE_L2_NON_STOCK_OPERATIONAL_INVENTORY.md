# Package L2N — Non-stock Operational Inventory Test

## Purpose

Verify that an ERPNext Item with **Maintain Stock** disabled can be physically traced, transferred
between Warehouses, and withdrawn through CFG Kanban without creating ERPNext Bin balances or Stock
Ledger Entries.

## Test data

- One active non-stock Item with a valid Stock UOM.
- One Company and two Warehouses in that Company.
- One active preprinted Stock Tag Handling Unit for the Item, Company, source Warehouse, and a
  positive quantity such as `20 Nos`.
- One Internal Warehouse Transfer route between the two Warehouses.
- One Transfer Master/Card for `20 Nos` and one Withdrawal Master/Card for `5 Nos`.
- Operators authorized for the route and **Stock Withdrawal** responsibility.

## Transfer test

1. Confirm ERPNext Item **Maintain Stock** is disabled and no Bin quantity is expected.
2. Trigger and release the Transfer Card.
3. Open its Manifest. Verify **Inventory Control Mode Snapshot = Kanban Operational Inventory**,
   **Warehouse Transfer Tags = Required Physical Tag**, **Kanban operational inventory** is
   displayed, and **Use ERP Stock Without Tags** is unavailable.
4. Arm dispatch scanning and scan the exact active tag. Stop scanning and prepare the Manifest.
5. Confirm dispatch.

Expected for Direct Transfer:

- no Stock Entry or ERP Command is created;
- the Manifest is Received and its line is Received;
- the Handling Unit Current Warehouse is the destination Warehouse;
- its quantity is unchanged and reservation returns to zero;
- Cycle/Signal complete and the Card returns to Available; and
- Location Transfer and completion Events reference the Manifest.

For Goods in Transit, additionally verify dispatch moves the tag to the Transit Warehouse and makes
the Manifest Awaiting Receipt. The receiving operator must scan the listed tag and confirm receipt;
only then does it move to the destination and complete.

## Withdrawal test

1. Trigger and release the Withdrawal Card after the tag reaches the destination Warehouse.
2. Verify the Cycle's **Withdrawal Tag Policy Snapshot** is **Required Physical Tag - Kanban
   Operational Inventory** even when no material-trace policy exists.
3. Add the destination tag for `5 Nos`, prepare, and select **Confirm Tagged Withdrawal**.

Expected:

- no Material Issue Stock Entry or ERP Command is created;
- Handling Unit quantity decreases from `20` to `15 Nos` and reservation returns to zero;
- the Withdrawal allocation is Consumed;
- Cycle/Signal complete and the Card returns to Available; and
- ERPNext still has no Bin or Stock Ledger quantity for the Item.

## Negative checks

- Untagged transfer or withdrawal is rejected.
- A tag for the wrong Item, Company, Warehouse, UOM, or insufficient quantity is rejected.
- A tag already reserved by another open transaction is rejected.
- Cancelling an unused Draft/Prepared transaction releases reservations and preserves audit history.
- Changing the Item to Maintain Stock must restore the normal ERPNext Stock Entry boundary for new
  Cycles; never reinterpret historical non-stock movements.

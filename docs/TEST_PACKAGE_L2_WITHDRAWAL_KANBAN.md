# Package L2 — Withdrawal Kanban System Test

## Purpose

Verify a simple operational stock withdrawal that is not tied to a BOM or Work Order. CFG Kanban
controls the Card, approval, floor selection, and physical-tag audit. ERPNext remains the stock
system of record through a native Material Issue Stock Entry.

## Test data

Use a non-batch, non-serial consumable for the first positive test.

| Record | Example |
|---|---|
| Company | Wasilah FZD Trading Sdn Bhd |
| Item | TEST-RUBBER-BAND |
| Stock UOM | Nos |
| Source Warehouse | Raw Material Stores - FZD |
| ERPNext available stock | At least 100 Nos |
| Withdrawal Card quantity | 10 Nos |
| Standard reason | Daily packing consumables |
| Operator responsibility | Stock Withdrawal |

Do not use a production Item/BOM for this test.

## A. Prerequisites

1. Confirm ERPNext **Stock Ledger** / **Bin** has at least 100 Nos in the source Warehouse.
2. Open **CFG Kanban Responsibility** and confirm an active record named **Stock Withdrawal** exists.
3. Open the test worker's **CFG Kanban Operator Profile**:
   - enable Start and Complete permissions;
   - add **Stock Withdrawal** under Responsibilities;
   - ensure the operator QR/login works in Logistics Operator Panel.
4. Create **CFG Kanban Material Trace Policy** for the Item and Company:
   - Enabled = Yes;
   - Stock Withdrawal Tags (`stock_withdrawal_tag_policy`) = **No Physical Tag**.
5. Record the opening ERP quantity. This is the baseline for the final assertion.

Expected: no Work Order, Job Card, destination Warehouse, or Logistics Route is required.

## B. Create the Withdrawal Master and Card

Create **CFG Kanban Master** with:

| Screen label (`fieldname`) | Test value |
|---|---|
| Kanban Name (`kanban_name`) | Test Rubber Band Withdrawal 10 |
| Active (`active`) | Yes |
| Company (`company`) | Test Company |
| Item (`item_code`) | TEST-RUBBER-BAND |
| Control Type (`control_type`) | Withdrawal |
| Replenishment Qty (`replenishment_qty`) | 10 |
| Stock UOM (`stock_uom`) | Nos |
| Number of Cards (`number_of_cards`) | 1 |
| Source Warehouse (`source_warehouse`) | Test source Warehouse |
| Standard Withdrawal Reason (`withdrawal_reason`) | Daily packing consumables |
| Automation Level (`automation_level`) | Approval |
| Submit Material Issue on Operator Confirmation (`auto_submit_withdrawal_stock_entry`) | No |

Save, then create one **CFG Kanban Card** for this Master with **Card Type = Physical Batch Card**
and note its Card Number. Do not select Task Card or Task Schedule; Withdrawal is a stock-control
workflow, not a scheduled service task.

Expected:

- Destination Warehouse and Internal Logistics Route are blank.
- Master saves without BOM/operation profiles.
- Card is active and Available.
- Task Schedule is not requested or stored on the Card.

## C. Approval-mode positive flow, untagged ERP stock

1. Open **CFG Kanban → Logistics Operator Panel**.
2. Identify the authorized test operator.
3. Scan/enter the Withdrawal Card Number.
4. Select **Trigger Withdrawal Card**.

Expected: a Signal is created as **Waiting Approval**; no Work Order or Stock Entry exists.

5. As an authorized manager, open **Kanban Supervisor**.
6. Find the Signal whose Signal Type is **Stock Withdrawal** and choose **Release Stock Withdrawal**.
7. Return to Logistics Operator Panel and scan the same Card again.

Expected:

- a Withdrawal Cycle is displayed;
- Withdrawal Status = Requested;
- Tag Policy = No Physical Tag;
- one selection named ERP STOCK exists for exactly 10 Nos.

8. Select **Prepare Withdrawal**.

Expected: Withdrawal Status becomes **Prepared**. ERPNext available stock is checked, but stock has
not moved yet.

9. Select **Create Material Issue**. Complete any mandatory ERP fields displayed.

Expected:

- one Draft **Stock Entry** is created;
- Purpose / Stock Entry Type = Material Issue;
- Company, Item, source Warehouse and quantity exactly match the Cycle;
- `cfg_withdrawal_cycle` links the Stock Entry to the Cycle;
- Cycle/Withdrawal remains Document Pending;
- Card is not yet Available;
- ERP stock quantity is unchanged because the Stock Entry is Draft.

10. Open the linked Stock Entry, review it, and Submit it in ERPNext.
11. Refresh Logistics Operator Panel and rescan the Card.

Expected:

- ERP stock decreases by exactly 10 Nos;
- Cycle and Withdrawal Status are Completed;
- Signal is Completed and references the Stock Entry;
- Card returns to Available and Active Cycle is blank;
- no Work Order or Job Card was created.

## D. Idempotency checks

1. Before submission, press **Create Material Issue** again or retry after a simulated timeout.
2. Search Stock Entry by the Cycle.

Expected: only one non-cancelled Stock Entry exists for that Cycle.

3. Scan the Card twice rapidly while it already has an active Cycle.

Expected: the existing Cycle is shown; a second active Cycle/Signal is not created.

## E. Cancellation before ERP document

1. Trigger a new Approval-mode cycle and have the manager release it.
2. Do not select **Create Material Issue**.
3. From the Signal action, choose controlled Cancel/Rollback and enter a reason.

Expected:

- Signal and Cycle become Cancelled;
- Card returns to Available;
- no Stock Entry exists;
- audit Events retain the reason.

## F. Tagged-stock variant

Run this only after the untagged flow passes.

1. Create/choose an active released Stock Tag for the same Item, Company and source Warehouse with
   at least 10 Nos available and no reusable-container membership.
2. Change **Stock Withdrawal Tags** to **Required Physical Tag**.
3. Trigger and approve a new Card cycle, then scan the Card again in Logistics Operator Panel.
4. Select **Add Stock Tag**, scan the tag, and enter 10 Nos.
5. Select **Prepare Withdrawal**.

Expected: selected total is 10; allocation state is Reserved; Handling Unit current quantity is
unchanged but Reserved Qty increases by 10 and Available Qty reduces by 10.

6. Create the Draft Material Issue.

Expected: the reservation remains; current tagged quantity still has not been consumed.

7. Submit the Stock Entry.

Expected: Handling Unit current quantity reduces by 10, Reserved Qty releases by 10, a **Stock
Withdrawal** quantity-ledger event references the Stock Entry, and the Card/Cycle complete.

## G. Negative tests

Each test must reject without stock movement or duplicate documents:

1. Operator lacks **Stock Withdrawal** responsibility.
2. Scan a tag for a different Item, Company, or Warehouse.
3. Scan a quarantined, revoked, empty, or container-loaded tag.
4. Select less/more than the exact Card quantity, then try Prepare.
5. Request more than ERPNext available quantity.
6. Use untagged mode for a batch- or serial-controlled Item.
7. Try to edit the generated Stock Entry Item, quantity, source Warehouse, batch, or allocation link.
8. Try to cancel a submitted controlled Material Issue directly.
9. Try Signal rollback after a Draft Stock Entry already exists.

Expected: each action gives a clear blocking message and preserves the existing audit trail.

For the unused Draft in test 9, an operator with **Supervisor Override** may instead choose
**Discard Draft and Retry**, provide a reason, and then create a replacement Draft from the same
prepared selection. Verify the old Draft is removed, the ERP Command records the failed/discarded
attempt, reservations remain intact, and only one current Draft exists.

## Pass criteria

Package L2 passes only when:

- a floor operator completes the flow from one mobile-friendly panel without ERP manufacturing
  documents;
- ERPNext Material Issue submission is the only event that reduces ERP stock;
- tagged balances change only after ERP submission;
- Approval and Automatic release modes behave as configured;
- a Draft entry stays pending and does not recycle the Card;
- retry/cancellation safeguards prevent duplicate or unaudited stock use.

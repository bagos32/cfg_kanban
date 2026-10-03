# CFG Kanban Package C2B System Test

## Customer Delivery Note Posting and Cancellation Recovery

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Prerequisites:** Package C1 and C2A tests passed  
**Audience:** Independent system testers, logistics supervisors, drivers, Sales/Stock users, and
implementation personnel  
**Boundary:** This package creates and confirms the customer Delivery Note. It does not create the
Sales Invoice or capture proof of delivery.

## 1. Purpose and pass rule

C2B must prove one important control: a Kanban allocation alone does not reduce tagged stock. Only
a submitted ERPNext Delivery Note may confirm delivery and reduce Handling Unit Current Qty.

The test passes only when the Delivery Note, Delivery Session, Delivery Allocations, Handling Units,
quantity ledger, reusable-container history, ERP Command, Event, and Exception records agree.

## 2. Sample data

Reuse the C1/C2A Selling Company, Customer, site, lorry Warehouse, operator, and tags. Use separate
records for Draft-policy and auto-submit tests.

| Record | Suggested value | Required setup |
|---|---|---|
| Customer Site 1 | `CUS-SITE-C2B-DRAFT` | Auto-submit Customer Delivery Note unticked |
| Customer Site 2 | `CUS-SITE-C2B-AUTO` | Auto-submit Customer Delivery Note ticked |
| Selling Price List | `C2B Selling` | Enabled for selling |
| Ordinary Stock Tag | `STK-C2B-001` | 20 Nos, Released, in the selling-company lorry Warehouse |
| Auto-submit Stock Tag | `STK-C2B-002` | 10 Nos, Released, in the same lorry Warehouse |
| Reusable Container | `BOX-C2B-01` | Two complete active Stock Tags loaded into it |
| Operator | Existing test driver | Active profile with Customer Delivery responsibility |

Create a positive **Item Price** in `C2B Selling` for each test Item and stock UOM. If the Item is
batch controlled, the tag Batch must exist, must not be expired, and ERPNext Batch/Warehouse stock
must be sufficient. If the installation makes Sales Team or another field mandatory on Delivery
Note, keep that rule active; C2B must collect it in the panel.

Record before testing:

- ERPNext stock quantity in the lorry Warehouse;
- each Handling Unit Current Qty, Reserved Qty, Available Qty, movement state, and identity state;
- active reusable-container contents;
- the latest Delivery Session and Delivery Note number.

## 3. Draft-policy happy path

1. Open **Logistics Operator Panel** and identify the operator.
2. Scan `CUS-SITE-C2B-DRAFT`, select the correct selling-company lorry Warehouse, and start the
   Delivery Session.
3. Select **Start Allocation Scanning**. Scan `STK-C2B-001`, allocate 5 Nos, stop scanning, and
   select **Confirm Customer Allocation**.
4. Verify the session is **Awaiting Confirmation**, the allocation is **Delivery Pending**, Current
   Qty remains 20, Reserved Qty is 5, and ERPNext stock has not changed.
5. Select **Create Delivery Note**.
6. If a mandatory-details dialog appears, complete every field. For Sales Team, add one or more
   rows and make allocated percentages total exactly 100%.
7. Confirm creation.

Expected result before ERP submission:

- exactly one Draft Delivery Note exists and is linked in the panel and Delivery Session;
- the Delivery Note Company, Customer, shipping address, source Warehouse, price list, Item, Batch,
  UOM, quantity, rate, Stock Tag, and Delivery Allocation match the immutable session/allocation;
- the session is **ERP Document Pending**;
- the allocation remains **Delivery Pending**;
- Current Qty remains 20, Reserved Qty remains 5, and ERPNext stock remains unchanged;
- one completed **Create Customer Delivery Note** ERP Command exists;
- repeated clicking/reloading does not create a second Draft or command.

8. Open the linked Draft Delivery Note as an authorized ERPNext user. Do not change the controlled
   Company, Customer, address, Warehouse, allocation, tag, Item, Batch, or quantity.
9. Submit the Delivery Note and return to the Logistics panel. Refresh and reopen the session.

Expected result after ERP submission:

- Delivery Note is submitted;
- session is **Delivered** and has Completed On;
- allocation is **Delivered**, Delivered Qty is 5, and its active reservation key is cleared;
- Handling Unit Current Qty is 15, Reserved Qty is 0, Available Qty is 15, and the tag remains
  Active in the lorry Warehouse;
- ERPNext stock reduces by 5;
- one immutable **Deliver** quantity-ledger event references the Delivery Note;
- one **Customer Delivery Posted** Event references the session and Delivery Note.

## 4. Auto-submit happy path

1. Start a new session by scanning `CUS-SITE-C2B-AUTO`.
2. Allocate and confirm 10 Nos from `STK-C2B-002`.
3. Select **Create Delivery Note**, complete any mandatory ERP inputs, and confirm.

Expected result:

- the Delivery Note is created and submitted in the same controlled action;
- the session returns as **Delivered**, not ERP Document Pending;
- the allocation, ledger, tag balance, and ERPNext stock results match section 3;
- if the delivery empties the tag, Current/Reserved/Available Qty are zero, Identity State is
  **Empty**, Movement State is **Empty**, and Current Warehouse is blank.

## 5. Reusable-container delivery

1. Start a new session and scan `BOX-C2B-01` while allocation scanning is armed.
2. Confirm that every currently loaded Stock Tag appears and is allocated at its full available
   quantity. Confirm the allocation and create/submit the Delivery Note.

Expected result:

- Delivery Note has one Item row per physical contained Stock Tag, not one row for the container;
- each row retains its Handling Unit and Delivery Allocation reference;
- all included allocations become Delivered;
- every submitted quantity is posted once to its own Handling Unit ledger;
- the container membership episodes become **Unloaded** with Delivery Note reason/audit;
- reusable container Movement State becomes **Empty** and it is available for a later loading cycle.

## 6. Validation and failure tests

Run each test separately and confirm that no Delivery Note or quantity consumption occurs:

1. Remove/expire the applicable Item Price.
2. Make ERPNext lorry-Warehouse stock lower than the confirmed allocation.
3. Expire the Batch.
4. Disable the Customer.
5. Change the tag Company or Warehouse after allocation.
6. Put the tag on quality Hold or make it inactive.
7. Change reusable-container contents after allocation; normal UI should already block this.
8. Enter incomplete mandatory Delivery Note inputs.
9. Enter Sales Team rows whose percentages do not total 100%.
10. Attempt to edit controlled Item/Batch/quantity/Handling Unit references in the Draft before
    submission.

Expected result for every rejected case:

- submission is refused with a specific validation message;
- tagged Current Qty and Reserved Qty remain unchanged;
- no Deliver ledger entry is created;
- command failure creates or retains a linked critical Exception;
- after correcting the prerequisite, **Create Delivery Note** can be retried without duplicates.

## 7. Submitted Delivery Note cancellation and amendment

This test represents a genuine full physical rollback. Return the goods to the same lorry/tag and
empty reusable container before cancelling the ERP document. Do not use cancellation as a customer
return after the delivery was accepted; that belongs to a later returns package.

1. From a completed C2B test, ensure the affected remainder tag has no later active reservation and
   the reusable container has not been reused.
2. Cancel the submitted controlled Delivery Note in ERPNext.
3. Refresh/reopen the Delivery Session.

Expected result:

- cancellation is permitted only while reversal is safe;
- ERPNext restores stock;
- Kanban posts one **Customer Return** ledger event and one new **Reserve** event per allocation;
- Handling Unit Current Qty and Reserved Qty both increase by the delivered amount, leaving
  Available Qty unchanged;
- allocations return to **Delivery Pending**;
- session returns to **Awaiting Confirmation**, Delivery Revision increments, and a critical
  cancellation Exception is visible;
- reusable-container membership is restored when applicable;
- historical Delivery Note and allocation links remain intact.

4. Select **Create Amended Delivery Note**, complete required values, and submit it.

Expected result:

- only one amended Delivery Note is created for the new revision;
- its Amended From points to the cancelled Delivery Note;
- successful submission consumes the restored reservation once, resolves the current Exception,
  and returns the session to Delivered.

## 8. Unsafe cancellation tests

For a partially delivered tag, reserve its remaining quantity in a later Delivery Session and then
try to cancel the earlier Delivery Note. Separately, reuse an emptied container and load new stock
before trying to cancel the earlier container Delivery Note.

Expected result:

- ERPNext cancellation is blocked before any Kanban reversal;
- the message identifies the later tag reservation or reused container;
- no old quantity is mixed into the later transaction;
- supervisor must first resolve the later physical transaction or use the future controlled return
  workflow.

## 9. Audit evidence checklist

For each successful delivery, capture these names/screenshots:

- Customer Scan Point and auto-submit policy;
- Delivery Session;
- Delivery Allocation rows;
- ERP Command;
- submitted or Draft Delivery Note and Item rows;
- Handling Unit before/after balances;
- Handling Unit Quantity Ledger events;
- Event History;
- Container Content history when used;
- Exception and resolution evidence for failure/cancellation tests.

## 10. Acceptance decision

- [ ] Draft-policy delivery passed.
- [ ] Auto-submit delivery passed.
- [ ] Mandatory parent/child input collection passed.
- [ ] Partial and full-tag balance posting passed.
- [ ] Reusable-container delivery passed.
- [ ] Validation and idempotency passed.
- [ ] Safe cancellation and amendment passed.
- [ ] Unsafe cancellation guard passed.
- [ ] C2B accepted for the proof-of-delivery increment.
- [ ] C2B rejected; blocking defects and record names are attached.


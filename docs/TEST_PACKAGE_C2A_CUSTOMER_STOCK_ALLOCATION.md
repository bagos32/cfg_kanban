# CFG Kanban Package C2A System Test

## Customer Stock Allocation and Reservation

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Prerequisite:** Package C1 tests passed  
**Audience:** System testers, logistics supervisors, drivers, and implementation personnel  
**Boundary:** This package reserves tagged stock. It does not create a Delivery Note or move ERP stock.

## 1. Sample data

Use one Selling Company, Customer Site, and Company-specific lorry Warehouse already approved in
Package C1. Prepare these physical identities in that lorry Warehouse:

| Identity | Example | Stock | Purpose |
|---|---|---:|---|
| Ordinary Stock Tag | `STK-C2A-001` | 20 Nos | Full and partial allocation |
| Serialized Stock Tag | `STK-C2A-S01` | 2 Nos / 2 active serials | Full-only validation |
| Reusable Container | `BOX-C2A-01` | Contains two complete Stock Tags | One-scan expansion |
| Wrong-Company Tag | `STK-C2A-WC` | Any | Company isolation |
| Wrong-Warehouse Tag | `STK-C2A-WH` | Any | Warehouse isolation |
| Quality-Hold Tag | `STK-C2A-QH` | Any | Quality rejection |

The Handling Unit quantity and Batch must agree with submitted ERPNext stock. The operator needs the
**Customer Delivery** responsibility.

## 2. Happy path: partial Stock Tag allocation

1. Open **Logistics Operator Panel** and identify the operator.
2. Scan the Customer Site, select the correct Selling-Company lorry Warehouse, and start a Delivery
   Session.
3. Select **Start Allocation Scanning**. Confirm that the scanner banner states **CUSTOMER
   ALLOCATION SCANNING ARMED** and shows the Delivery Session.
4. Scan `STK-C2A-001`. Confirm Item, Batch, UOM, and available quantity. Enter `5` and select
   **Reserve for Customer**.
5. Expected results:
   - session state is **Allocating Stock**;
   - one Delivery Allocation is **Reserved** for 5;
   - the Handling Unit retains Current Qty 20, Reserved Qty becomes 5, and Available Qty becomes 15;
   - movement state is **Reserved**;
   - ERPNext Bin/Batch quantity is unchanged;
   - a Handling Unit Quantity Ledger **Reserve** event points to the allocation.
6. Stop allocation scanning and select **Confirm Customer Allocation**.
7. Expected: session becomes **Awaiting Confirmation** and allocation becomes **Delivery Pending**.

## 3. Correction and reconfirmation

1. Select **Release** on the 5-unit allocation, provide a reason, and confirm.
2. Expected: historical allocation becomes **Released**, Reserved Qty returns to 0, Available Qty
   returns to 20, an **Unreserve** ledger entry exists, and session returns to **Customer Identified**.
3. Allocate 10 units, stop scanning, and confirm again. Expected session is **Awaiting Confirmation**.

## 4. Complete reusable-container allocation

1. Start a separate Delivery Session after cancelling/releasing the previous test session as needed.
2. Arm allocation scanning and scan `BOX-C2A-01`.
3. The confirmation must list every currently loaded Stock Tag and its full quantity.
4. Confirm. Expected: one Delivery Allocation per contained Stock Tag, all sharing the container
   identity; every content tag is reserved in full.
5. Attempt to load or unload a content tag while reservations are active. Expected: rejected with the
   Delivery Session reference.
6. Attempt to allocate one contained Stock Tag independently. Expected: rejected and instructed to
   scan the container.

## 5. Mandatory negative tests

Each test must be rejected without creating an allocation or changing a ledger balance:

1. wrong-Company tag;
2. correct Company but wrong Warehouse;
3. Hold/Quarantined/Rejected quality state;
4. inactive, empty, void, or replaced tag;
5. quantity above Available Qty or zero/negative quantity;
6. fractional quantity where the UOM requires whole numbers;
7. partial allocation of a serialized tag;
8. tag already reserved by a Manifest or another Delivery Session;
9. ERPNext stock lower than the physical tagged quantity;
10. allocation scan after the session is **Awaiting Confirmation**;
11. container with no contents;
12. container whose contents changed or whose content fails any eligibility rule.

## 6. Audit and genealogy

1. Open **CFG Kanban Delivery Allocation**. Verify operator, operator session, timestamps, reservation
   and release ledgers, immutable customer session, Handling Unit, Item, Batch, UOM, and quantity.
2. Scan the allocated tag in **Material Genealogy Explorer**. Verify **Customer Delivery Allocation
   History** shows Delivery Session, Customer Site, Selling Company, physical tag/container,
   quantity, allocation state, and release reason where applicable.
3. Verify released allocations remain visible and cannot be deleted.

## 7. Acceptance rule

C2A passes only if Kanban reservation balances and audit evidence are exact while ERPNext stock
remains unchanged. Do not report the absence of a customer Delivery Note or proof-of-delivery as a
C2A defect; those belong to C2B and the proof package.

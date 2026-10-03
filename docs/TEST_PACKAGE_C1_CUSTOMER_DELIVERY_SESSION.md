# CFG Kanban Package C1 System Test

## Customer Site Scan and Delivery Session Foundation

**Test package:** C1  
**Application:** CFG Kanban for ERPNext/Frappe v15  
**Minimum application revision:** `e450dae` — `feat: add customer delivery session foundation`  
**Audience:** System testers, key users, logistics supervisors, and implementation personnel  
**Test type:** Functional acceptance, authorization, Company isolation, audit, and recovery  

## 1. Purpose

This test proves that a driver or logistics operator can scan a permanent Customer Site code and
start a controlled delivery context without selecting technical ERPNext documents.

The system must lock the following information into one **CFG Kanban Delivery Session**:

- exact Customer Site and printed site code;
- ERPNext Customer and Delivery Address;
- Selling Company;
- Company-specific lorry Warehouse;
- physical vehicle identity;
- Selling Price List;
- proof-of-delivery policy;
- operator identity and operator session;
- start time and idempotency evidence.

ERPNext remains the stock and accounting system of record. Package C1 does **not** move stock or
create a Delivery Note.

## 2. Test now or wait for the next package?

**Run this test now.** Do not wait for customer stock allocation or Delivery Note automation.

Testing C1 separately confirms the safety boundary before stock-changing functions are enabled. It
isolates errors in Customer, address, Company, lorry Warehouse, price list, operator responsibility,
and active-session locking. The same approved test records can be reused in the next package.

## 3. Functions included in this test

This package includes:

1. Customer Site code lookup in the **Logistics Operator Panel**.
2. Customer and Delivery Address display before the session starts.
3. Selling-Company filtering of Vehicle Warehouses.
4. Mandatory **Customer Delivery** operator responsibility.
5. Creation of one immutable Delivery Session.
6. One active Customer Delivery Session per operator.
7. Refresh and session-recovery visibility.
8. Empty-session cancellation with a mandatory reason.
9. Event history linked to the Delivery Session.
10. Read-only Delivery Session and Delivery Allocation audit lists in the CFG Kanban workspace.

## 4. Functions intentionally not included yet

The following are later increments and must not be reported as C1 defects:

- scanning Stock Tags or reusable containers into a Customer Delivery Session;
- reserving or allocating lorry stock to a Customer;
- entering partial quantities or loose-container quantities;
- creating or submitting a customer Delivery Note;
- creating or submitting a Sales Invoice;
- changing ERPNext Warehouse stock;
- proof-of-delivery photo, signature, GPS, or recipient-name capture;
- completing a Delivery Session as Delivered, Invoiced, or Closed;
- route-stop sequencing, returns, overnight reconciliation, or billing grouping.

The **CFG Kanban Delivery Allocation** list is expected to remain empty during this C1 test.

## 5. Roles needed for testing

Use separate identities where practical.

| Test identity | Required access | Purpose |
|---|---|---|
| Setup user | System Manager, Stock Manager, or Sales Manager as applicable | Creates the Warehouse and Customer Scan Point |
| Terminal ERP user | **Kanban Terminal**, Manufacturing Manager, Stock User, Stock Manager, or System Manager | Opens the Logistics Operator Panel |
| Kanban operator | Active Employee with an active **CFG Kanban Operator Profile** | Represents the driver or logistics worker |

The shared terminal’s ERPNext login and the scanned Kanban operator are different identities. The
Employee does not require their own ERPNext login.

## 6. Sample data

The names below are test examples. If equivalent ERPNext records already exist, use them and record
their exact saved names in the test result. Do not alter live Company or Customer records solely to
match these examples.

### 6.1 ERPNext master data

| Record | Example value | Required condition |
|---|---|---|
| Selling Company | `CFG SALES TEST SDN BHD` | Enabled Company used for customer sales |
| Company abbreviation | `CST` | Example only; ERPNext may append it to Warehouse names |
| Customer | `C1 TEST CUSTOMER` | Active Customer |
| Delivery Address | `C1 TEST CUSTOMER-WAREHOUSE 1` | Address must be linked to the test Customer |
| Selling Price List | `Standard Selling` | Price List must have **Selling** enabled |
| Physical vehicle | `LORRY-TEST-01` | Operational identity shared by Company-specific lorry Warehouses |
| Lorry Warehouse input name | `LORRY-TEST-01-SALES` | Active, non-group Warehouse belonging to the Selling Company |
| Normal Warehouse | `C1-NORMAL-WAREHOUSE` | Active, non-group Warehouse in the same Company; not a Vehicle Warehouse |

After saving the lorry Warehouse, copy its exact ERPNext document name. Depending on ERPNext naming,
it may appear as `LORRY-TEST-01-SALES - CST`.

### 6.2 Customer Scan Points

Create two records to test active-session isolation.

| Screen label | Site 1 value | Site 2 value |
|---|---|---|
| Printed Customer Site Code (`site_code`) | `CUSTSITE-TEST-001` | `CUSTSITE-TEST-002` |
| Site / Branch Name (`site_name`) | `Test Customer Main Gate` | `Test Customer Branch Gate` |
| Active (`active`) | Checked | Checked |
| Selling Company (`selling_company`) | `CFG SALES TEST SDN BHD` | Same Selling Company |
| Customer (`customer`) | `C1 TEST CUSTOMER` | Same Customer or another test Customer |
| Delivery Address (`customer_address`) | Customer-linked test Address | Customer-linked second Address |
| Territory (`territory`) | Existing test Territory | Existing test Territory |
| Route Reference (`route_reference`) | `TEST-ROUTE-A` | `TEST-ROUTE-B` |
| Default Selling Price List (`default_price_list`) | `Standard Selling` | `Standard Selling` |
| Proof Policy (`proof_policy`) | `Required` | `Unattended Delivery Allowed` |
| Require Recipient Name | Checked | Checked |
| Require Signature | Checked | Unchecked |
| Require Photograph | Checked | Checked |
| Require GPS | Checked | Checked |

The **Internal UUID Alias** is generated by the system and is not printed or entered by the tester.
The permanent physical QR or barcode should contain the visible value `CUSTSITE-TEST-001` or
`CUSTSITE-TEST-002`.

### 6.3 Lorry Warehouse

Open the saved ERPNext Warehouse and set:

| Screen label | Test value |
|---|---|
| Company | `CFG SALES TEST SDN BHD` |
| Is Group | Unchecked |
| Disabled | Unchecked |
| Vehicle Warehouse (`cfg_is_vehicle_warehouse`) | Checked |
| Physical Vehicle Reference (`cfg_vehicle_reference`) | `LORRY-TEST-01` |

If the same physical lorry carries stock belonging to another sister Company, create another
Warehouse belonging to that Company. Both Warehouse records may use `LORRY-TEST-01` as their
**Physical Vehicle Reference**, but they must never share one ERPNext Warehouse across Companies.

### 6.4 Kanban operator

Create or update one **CFG Kanban Operator Profile**:

| Screen label | Test value |
|---|---|
| Employee | Active test Employee |
| Active | Checked |
| Kanban Role | `Operator` |
| Start | Checked |
| Responsible Roles | Add `Customer Delivery` |

Save the profile. Select **Credentials → Issue New QR Credential**, then print or download the QR
immediately. Issuing a new credential invalidates that operator’s previous QR.

For the authorization-negative test, prepare a second active Operator Profile without the
**Customer Delivery** responsibility.

## 7. Pre-test checks

Before testing, confirm all of the following:

- the deployed CFG Kanban revision includes `e450dae` or a later revision;
- migration and asset build completed without an error;
- the lorry Warehouse shows **Vehicle Warehouse** and **Physical Vehicle Reference**;
- **Customer Delivery** exists in **CFG Kanban Responsibility** and is active;
- both Customer Scan Points save successfully;
- each Delivery Address is linked to its selected Customer;
- the selected Price List has **Selling** enabled;
- the terminal ERP user is authenticated and can open **CFG Kanban → Logistics Operator Panel**;
- no earlier active Customer Delivery Session belongs to the test operator. If one exists, open it
  from the panel and cancel it with a test reason before starting.

## 8. Main acceptance test

Record screenshots or screen recordings at the marked evidence points.

### Test C1-01 — Identify the operator

1. Open **CFG Kanban → Logistics Operator Panel** (`/app/kanban-logistics`).
2. Select **Scan / Enter Operator**.
3. Scan the test operator QR. On a phone or tablet, use the camera option. On a keyboard-wedge
   scanner, configure the scanner to append Enter.

Expected result:

- the panel displays the test Employee’s name as **Active operator**;
- no ERPNext User identity is changed;
- the panel shows no active Customer Delivery Session for this new test.

Evidence: screenshot the active-operator header.

### Test C1-02 — Scan Customer Site 1

1. Ensure the panel is in normal lookup mode and no Movement Manifest is being edited.
2. Scan or enter `CUSTSITE-TEST-001` in the Logistics Scanner.

Expected result:

- the panel shows **Customer Site identified**;
- Site / Branch Name is `Test Customer Main Gate`;
- the displayed Selling Company, Customer, Delivery Address, route, and proof policy match Site 1;
- **Available Vehicle Warehouses** is at least 1;
- **Start Customer Delivery** is visible;
- no stock movement or ERP document is created.

Evidence: screenshot the Customer Site result before starting.

### Test C1-03 — Start the Delivery Session

1. Select **Start Customer Delivery**.
2. In **Selling-company Lorry Warehouse**, select the exact saved lorry Warehouse carrying
   `LORRY-TEST-01`.
3. Select **Lock Customer and Vehicle**.

Expected result:

- one new name such as `KDS-2026-00001` is created;
- Delivery State is **Customer Identified**;
- the panel shows the Customer, Delivery Address, Selling Company, physical vehicle, lorry
  Warehouse, and Proof Policy;
- the new session appears under **Customer Delivery Sessions**;
- there is no Stock Entry, customer Delivery Note, or Sales Invoice created by this action;
- **CFG Kanban Delivery Allocation** remains empty for this session.

Evidence: screenshot the active session and record its `KDS-...` name.

### Test C1-04 — Verify the saved audit record

1. Open **CFG Kanban → Customer Delivery Sessions**.
2. Open the `KDS-...` record created above.
3. Compare it against the Customer Scan Point and lorry Warehouse.

Expected result:

- **Delivery State** is `Customer Identified`;
- **Customer Scan Point**, **Scanned Customer Site Code**, **Customer Site / Branch**,
  **Selling Company**, **Customer**, and **Delivery Address** are correct;
- **Selling-company Lorry Warehouse** and **Physical Vehicle Reference** are correct;
- **Locked Selling Price List** is correct;
- all proof-policy fields match the values present when the session was started;
- **Started by Operator**, **Operator Session**, and **Started On** are populated;
- Customer Delivery Note and Customer Sales Invoice are blank;
- operational snapshot fields are read-only.

4. Open **CFG Kanban → Event History** and filter Delivery Session by the `KDS-...` name.

Expected result:

- one **Customer Delivery Session Started** Event is linked to this session;
- its operator and operator-session audit fields are populated.

Evidence: screenshot the session record and its start Event.

### Test C1-05 — Refresh and recover the active session

1. Return to the Logistics Operator Panel.
2. Select **Refresh**.
3. If required, reopen the session from **Customer Delivery Sessions** in the panel.

Expected result:

- the active operator remains identified while the session is valid;
- the `KDS-...` session remains visible with the same immutable context;
- refresh does not create a duplicate session.

### Test C1-06 — Prevent a second active Customer Site

1. While Site 1’s session remains active, scan `CUSTSITE-TEST-002`.
2. Confirm the second site information and try **Start Customer Delivery**.

Expected result:

- the system refuses to create another active session for the same operator;
- the message identifies the existing `KDS-...`, its site, and its state;
- Site 1’s active session remains unchanged;
- no second Delivery Session is created.

Evidence: screenshot the refusal message.

### Test C1-07 — Cancel the empty session

1. Reopen Site 1’s `KDS-...` from **Customer Delivery Sessions**.
2. Select **Cancel Empty Session**.
3. First try to continue without a reason.
4. Enter `C1 system test cleanup — no stock allocated` and confirm cancellation.

Expected result:

- blank reason is rejected by the dialog;
- the saved Delivery State becomes **Cancelled**;
- **Cancelled by Operator**, **Cancelled On**, and **Cancellation Reason** are populated;
- the record is preserved and is no longer shown in the active-session list;
- one **Customer Delivery Session Cancelled** Event is linked to the session;
- no stock or ERP transaction is reversed because C1 never moved stock.

Evidence: screenshot the cancelled session and cancellation Event.

### Test C1-08 — Start after cleanup

1. Scan `CUSTSITE-TEST-002` again.
2. Start a new session using the same Company-specific lorry Warehouse.
3. Verify the Site 2 proof-policy snapshot.
4. Cancel this second empty session with reason `C1 second-site test cleanup`.

Expected result:

- a new Delivery Session is allowed because the first one is Cancelled;
- Site 2’s Customer/address/route/proof values are used, not Site 1’s values;
- cleanup cancellation succeeds and preserves both historical sessions.

## 9. Negative and boundary tests

### Test C1-N01 — Operator lacks Customer Delivery responsibility

1. Switch to the second operator prepared without **Customer Delivery**.
2. Scan `CUSTSITE-TEST-001`.

Expected result:

- the Customer Site may be displayed for identification;
- **Start Customer Delivery** is not available;
- the panel says the operator is not assigned to Customer Delivery;
- no Delivery Session is created.

### Test C1-N02 — Ordinary Warehouse is excluded

1. Confirm `C1-NORMAL-WAREHOUSE` is active in the Selling Company but **Vehicle Warehouse** is
   unchecked.
2. Scan Site 1 and open the start dialog using an authorized operator.

Expected result:

- the ordinary Warehouse is not offered in **Selling-company Lorry Warehouse**;
- only active, non-group Vehicle Warehouses for the Site’s Selling Company are offered.

### Test C1-N03 — Wrong-Company Vehicle Warehouse is excluded

1. Use or create a Vehicle Warehouse belonging to another Company.
2. Give it the same Physical Vehicle Reference `LORRY-TEST-01`.
3. Scan Site 1 and open the start dialog.

Expected result:

- the wrong-Company Warehouse is not offered;
- sharing the physical vehicle reference does not mix Company ownership.

### Test C1-N04 — No configured Vehicle Warehouse

1. Temporarily uncheck **Vehicle Warehouse** on all test Warehouses for the Site’s Selling Company,
   or use a separate test Company without a Vehicle Warehouse.
2. Scan the matching Customer Site.

Expected result:

- Customer Site lookup still identifies the Customer and address;
- the panel warns that no active Vehicle Warehouse is configured for the Selling Company;
- **Start Customer Delivery** is not available.

Restore the Warehouse configuration after recording the result.

### Test C1-N05 — Inactive Customer Site

1. Uncheck **Active** on Site 2.
2. Scan `CUSTSITE-TEST-002`.

Expected result:

- the system refuses to start or display it as an available delivery destination;
- no Delivery Session is created.

Restore Site 2 to Active after the test.

### Test C1-N06 — Address/Customer mismatch

1. Create a temporary Customer Scan Point.
2. Select one Customer and an Address that is not linked to that Customer.
3. Try to save.

Expected result:

- the form refuses to save and identifies the mismatched Address and Customer;
- no invalid Customer Scan Point is created.

### Test C1-N07 — Non-selling Price List

1. On a temporary Customer Scan Point, select a Price List that does not have **Selling** enabled.
2. Try to save.

Expected result:

- the form refuses to save because the Price List is not enabled for selling transactions.

### Test C1-N08 — Duplicate physical code

1. Try to create another Customer Scan Point using `CUSTSITE-TEST-001`.

Expected result:

- the duplicate visible code is rejected;
- the original Customer Scan Point remains unchanged.

## 10. Pass criteria

Package C1 passes only when all of the following are true:

- an authorized operator can scan a visible Customer Site code;
- the exact Customer and linked Delivery Address are shown before confirmation;
- only Selling-Company Vehicle Warehouses are selectable;
- the resulting Delivery Session contains the correct immutable snapshots;
- unauthorized operators cannot start a delivery;
- an operator cannot own two active Customer Delivery Sessions;
- refresh shows the existing session without duplication;
- an empty session can be cancelled only with a reason;
- started and cancelled Events are preserved and linked;
- no stock, Delivery Note, Sales Invoice, or allocation is created during C1.

Any failure of these conditions must be recorded before Package C2 stock allocation is enabled.

## 11. Test result form

Copy this table into the test report.

| Test ID | Result: Pass/Fail/Blocked | Actual result | Evidence filename | Defect/reference |
|---|---|---|---|---|
| C1-01 |  |  |  |  |
| C1-02 |  |  |  |  |
| C1-03 |  |  |  |  |
| C1-04 |  |  |  |  |
| C1-05 |  |  |  |  |
| C1-06 |  |  |  |  |
| C1-07 |  |  |  |  |
| C1-08 |  |  |  |  |
| C1-N01 |  |  |  |  |
| C1-N02 |  |  |  |  |
| C1-N03 |  |  |  |  |
| C1-N04 |  |  |  |  |
| C1-N05 |  |  |  |  |
| C1-N06 |  |  |  |  |
| C1-N07 |  |  |  |  |
| C1-N08 |  |  |  |  |

### Environment record

| Item | Recorded value |
|---|---|
| Test date/time |  |
| Tester |  |
| ERPNext site |  |
| CFG Kanban Git revision |  |
| ERPNext version |  |
| Frappe version |  |
| Browser/device |  |
| Terminal ERP user |  |
| Kanban operator Employee |  |
| Selling Company |  |
| Customer Scan Point codes |  |
| Lorry Warehouse |  |
| Physical Vehicle Reference |  |
| Created Delivery Session names |  |

### Final decision

- [ ] Package C1 accepted for the next development increment.
- [ ] Package C1 accepted with documented non-blocking observations.
- [ ] Package C1 rejected; blocking defects are attached.

## 12. Defect-report minimum information

For every failure, provide:

1. Test ID and exact step number.
2. Customer Site code.
3. Delivery Session name, if one was created.
4. Kanban operator Employee and terminal ERP user.
5. Selling Company and exact Warehouse document name.
6. Full visible error message and screenshot.
7. Whether retrying created a duplicate record.
8. Event History entry, if present.
9. Browser/device and time of failure.
10. Confirmation that the server is running revision `e450dae` or later.


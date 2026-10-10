# CFG Kanban — Purchase Signal through Package C1 System Test

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Minimum application revision:** Package D3 or later  
**Audience:** Independent system testers, implementation personnel, purchasing, production, stock,
logistics, and key users  
**Test type:** End-to-end functional acceptance, ERP authority, physical-tag genealogy,
multi-company isolation, authorization, idempotency, audit, and recovery

## 1. Purpose

This procedure begins with a buyer-owned purchase Kanban signal and ends when a driver scans a
Customer Site and creates a Package C1 Customer Delivery Session. It does not rely on prior chat
history.

The complete test chain is:

```text
Purchase Kanban Card
  -> Purchase Replenishment Signal and Cycle
  -> ERPNext Material Request
  -> submitted ERPNext Purchase Order
  -> ERPNext Purchase Receipt
  -> optional raw-material Stock Tag activation
  -> ERPNext manufacture / material genealogy
  -> finished-product Stock Tag activation
  -> intercompany Movement Manifest
  -> source-company Delivery Note
  -> destination-company Purchase Receipt
  -> sales-company lorry Warehouse
  -> Customer Site scan
  -> Package C1 Delivery Session
```

ERPNext remains authoritative for purchasing, manufacturing, stock, Batch, and intercompany stock
documents. CFG Kanban controls signals, physical identity, scans, authorization, handover, audit,
and operator visibility. A Kanban scan alone must never change ERP stock.

## 2. Scope boundary

This guide tests:

1. Purchase Replenishment Master and reusable Card.
2. Material Request creation and Purchase Order association.
3. Full or partial Purchase Receipt feedback.
4. Mixed tagged and untagged material policy.
5. Submitted Purchase Receipt tag activation.
6. ERPNext Stock Entry-confirmed production input/output genealogy.
7. Preprinted tag range lazy registration.
8. Package B intercompany dispatch and receipt.
9. Package C1 Customer Site identification and Delivery Session creation.
10. Negative controls, duplicate requests, permissions, Company isolation, and audit evidence.

This guide stops at C1. The following are tested by later packages and are not C1 defects:

- reserving finished stock for a customer (C2A);
- creating the customer Delivery Note (C2B);
- proof of delivery (D1);
- customer returns and credit control (D2);
- end-of-route reconciliation (D3).

## 3. Tester safety rules

- Use a development/test site and clearly marked test records.
- Do not delete Signals, Cycles, ERP Commands, Events, quantity ledgers, Material Traces, Manifests,
  or Delivery Sessions. Use controlled cancellation or recovery actions.
- Keep both intercompany auto-submit settings disabled for the first run. Submit the ERP documents
  manually so every authority boundary can be observed.
- Never force-edit CFG read-only trace fields on native ERPNext documents.
- Record exact saved ERPNext names because Company abbreviations may be appended to Warehouses.
- Use unique scan codes. Do not reuse a Stock Tag from an earlier test.

## 4. Test identities and access

Use separate users/operators where practical.

| Identity | Required access | Test responsibility |
|---|---|---|
| Setup user | System Manager, Manufacturing Manager, Stock Manager, Purchase Manager | Creates configuration and test masters |
| Purchase user | Purchase User/Manager | Creates and submits Purchase Order |
| Stock user | Stock User/Manager | Reviews/submits Purchase Receipts and Stock Entries |
| Production user | Manufacturing User/Manager | Creates Work Order and manufacturing Stock Entry |
| Dispatch terminal user | Kanban Terminal or permitted stock/manufacturing user | Opens Logistics Operator Panel |
| Dispatch operator | Active Employee + active Operator Profile | Scans source tags and confirms dispatch |
| Receipt operator | Active Employee + active Operator Profile | Rescans and confirms intercompany receipt |
| Driver | Active Employee + active Operator Profile | Starts Package C1 Customer Delivery Session |

The ERPNext terminal login and scanned Kanban Employee are different identities. A floor Employee
does not need a personal ERPNext login.

## 5. Sample data

Equivalent existing data may be used. Record the actual names in the execution sheet in section 17.

### 5.1 Companies, parties, and Warehouses

| Record | Example | Required condition |
|---|---|---|
| Manufacturing Company | `CFG MFG TEST SDN BHD` | Buyer/manufacturer and tag-number issuer |
| Sales Company | `CFG SALES TEST SDN BHD` | Destination owner and selling Company |
| External Supplier | `TEST FLAVOUR SUPPLIER` | Supplies the raw material |
| Internal Customer | `CFG SALES INTERCOMPANY` | Customer belonging to the source-company commercial setup |
| Internal Supplier | `CFG MFG INTERCOMPANY` | Supplier used by destination Company |
| Manufacturing Raw Warehouse | `TEST RAW - MFG` | Active, non-group, Manufacturing Company |
| Manufacturing FG Warehouse | `TEST FG - MFG` | Active, non-group, Manufacturing Company |
| Sales Lorry Warehouse | `LORRY-TEST-01-SALES - SLS` | Active, non-group, Sales Company, Vehicle Warehouse |
| Rejected Warehouse | `TEST REJECTED - MFG` | Optional, Manufacturing Company |

Open the Sales Lorry Warehouse and set:

| Screen label | Test value |
|---|---|
| **Vehicle Warehouse** (`cfg_is_vehicle_warehouse`) | Checked |
| **Physical Vehicle Reference** (`cfg_vehicle_reference`) | `LORRY-TEST-01` |

### 5.2 Items and production example

| Record | Example | Test quantity |
|---|---|---:|
| Purchased raw material | `RM-FLAVOUR-TEST` | 100 Kg purchased |
| Finished item | `FG-SAUCE-TEST` | 20 Nos manufactured |
| Submitted BOM | `BOM-FG-SAUCE-TEST-001` | Use its actual input quantities |
| Raw Batch | system/test Batch | Required only if Item has Batch enabled |
| Finished Batch | system/test Batch | Required only if Item has Batch enabled |

The BOM must be active and submitted. Adjust the raw input quantity to the actual BOM requirement;
do not alter a submitted Stock Entry merely to match the example.

### 5.3 Price Lists and Item Prices

Create or verify:

- one Selling Price List usable by the Manufacturing Company for the internal Customer;
- one Buying Price List usable by the Sales Company for the internal Supplier;
- a positive Item Price for `FG-SAUCE-TEST` in both lists and the applicable UOM.

### 5.4 Physical printed codes

Use unused codes from test-only labels:

| Purpose | Example |
|---|---|
| Raw material container 1 | `TST-STK1000` |
| Raw material container 2 | `TST-STK1001` |
| Finished goods container | `TST-STK1002` |
| Customer Site | `CUSTSITE-TEST-001` |

The visible printed code is the primary scan identity. The generated internal UUID/opaque token is
not printed and is not entered by the tester.

## 6. Configuration prerequisites

### 6.1 Register the preprinted tag range

Create **CFG Kanban Tag Range Registry**:

| Exact screen label | Example value |
|---|---|
| **Range Registry Code** (`registry_code`) | `TST-STK-1000-1099` |
| **Active** (`active`) | Checked |
| **Issuing Company / Number Namespace** (`issued_company`) | Manufacturing Company |
| **Printed Prefix** (`prefix`) | `TST-STK` |
| **Starting Number** (`start_number`) | `1000` |
| **Ending Number** (`end_number`) | `1099` |
| **Number Width** (`number_width`) | `4` |
| **Child Separator** (`child_separator`) | `-` |
| **Detachable Child Count** (`child_count`) | `5` |

Expected after Save:

- First Main Tag is `TST-STK1000`;
- Last Main Tag is `TST-STK1099`;
- no Tag Family or Handling Unit is created merely by saving or looking up the range;
- the exact family is lazily created only when a controlled activation uses a tag.

### 6.2 Configure material-trace policies

Create **CFG Kanban Material Trace Policy** for the raw material:

| Exact screen label | Value |
|---|---|
| **Enabled** (`enabled`) | Checked |
| **Company** (`company`) | Manufacturing Company |
| **Item** (`item_code`) | `RM-FLAVOUR-TEST` |
| **Trace Level** (`trace_level`) | `Exact Handling Unit` |
| **Purchase Receiving Tags** (`receiving_tag_policy`) | `Optional Physical Tag` |
| **Production Input Tags** (`production_input_tag_policy`) | `Optional Physical Tag` |
| **Production Output Tags** (`production_output_tag_policy`) | `No Physical Tag` |
| **Require Batch on Tagged Quantity** (`require_batch`) | Match Item control |
| **Allow Receipt Quantity Across Multiple Tags** (`allow_partial_tag_quantity`) | Checked |

Create a second policy for the finished item:

| Exact screen label | Value |
|---|---|
| **Company** | Manufacturing Company |
| **Item** | `FG-SAUCE-TEST` |
| **Trace Level** | `Exact Handling Unit` |
| **Purchase Receiving Tags** | `No Physical Tag` |
| **Production Input Tags** | `No Physical Tag` |
| **Production Output Tags** | `Required Physical Tag` |

Optional policy permits a mixture of tagged and ERP-only raw stock. Required production output
blocks the manufacturing Stock Entry until its finished row is fully covered by staged tags.

### 6.3 Configure the Purchase Replenishment Master

Create **CFG Kanban Master**:

| Exact screen label | Example value |
|---|---|
| **Kanban Name** (`kanban_name`) | `TEST RM FLAVOUR PURCHASE 100KG` |
| **Active** (`active`) | Checked |
| **Company** (`company`) | Manufacturing Company |
| **Item** (`item_code`) | `RM-FLAVOUR-TEST` |
| **Control Type** (`control_type`) | `Purchase Replenishment` |
| **Card Representation** (`card_representation`) | `Container` |
| **Replenishment Qty** (`replenishment_qty`) | `100` |
| **Item Stock UOM** (`stock_uom`) | `Kg` (read-only, fetched from Item) |
| **Number of Cards** (`number_of_cards`) | `1` |
| **Destination Warehouse** (`destination_warehouse`) | Manufacturing Raw Warehouse |
| **Automation Level** (`automation_level`) | `Approval` |
| **Default Supplier** (`default_supplier`) | External Supplier |
| **Purchase UOM** (`purchase_uom`) | `Bag` |
| **Stock Qty per Purchase UOM** (`purchase_uom_conversion_factor`) | `20` (read-only, from Item UOM conversion) |
| **Calculated Replenishment Qty (Purchase UOM)** (`purchase_replenishment_qty`) | `5` (read-only) |
| **Supplier Pack Multiple (Purchase UOM)** (`supplier_pack_size`) | `1` |
| **Minimum Order Qty (Purchase UOM)** (`minimum_order_qty`) | `5` |
| **Purchase Order Multiple (Purchase UOM)** (`purchase_order_multiple`) | `1` |
| **Submit Material Request on Approval** (`auto_submit_material_request`) | Checked |
| **Purchase Execution Mode** (`purchase_execution_mode`) | `Material Request Only` for the baseline; repeat later with both PO automation modes |
| **Receipt Posting Mode** (`receipt_posting_mode`) | `Create Draft Purchase Receipt` |
| **Allow Partial Receipt** (`allow_partial_receipt`) | Checked |
| **Kanban Over-receipt Tolerance %** (`over_receipt_tolerance_pct`) | `0` |
| **Rejected Warehouse** (`rejected_warehouse`) | Test Rejected Warehouse |

Create one **CFG Kanban Card** from that Master:

| Exact screen label | Example value |
|---|---|
| **Kanban Master** (`kanban_master`) | purchase Master above |
| **Card Number** (`card_number`) | `PUR-RM-FLAVOUR-001` |
| **Card Type** (`card_type`) | `Physical Batch Card` |
| **Kanban Qty** (`kanban_qty`) | `100` |
| **Active** (`active`) | Checked |

Expected after Save: Item, Company Snapshot, UOM, source/destination values, and QR identity are
derived; state is **Available** and Active Cycle is blank.

### 6.4 Configure production control

Create or use a Production **CFG Kanban Master** for `FG-SAUCE-TEST`, with the submitted BOM,
Manufacturing Company, correct raw/WIP/FG Warehouses, and **Use ERP BOM Operations** enabled. Create
one active production Card. Keep the production quantity at `20 Nos` for this test.

Production Card configuration is intentionally separate from the purchase Card. The purchase Card
requests raw material; the production Card controls the finished-item Work Order/Cycle.

### 6.5 Configure the intercompany route

Create **CFG Kanban Logistics Route**:

| Exact screen label | Value |
|---|---|
| **Route Name** (`route_name`) | `TEST MFG FG TO SALES LORRY` |
| **Active** (`active`) | Checked |
| **Source Company** (`source_company`) | Manufacturing Company |
| **Source Warehouse** (`source_warehouse`) | Manufacturing FG Warehouse |
| **Destination Company** (`destination_company`) | Sales Company |
| **Destination Warehouse** (`destination_warehouse`) | Sales Lorry Warehouse |
| **Internal Customer** (`internal_customer`) | internal Customer |
| **Selling Price List** (`selling_price_list`) | test selling list |
| **Internal Supplier** (`internal_supplier`) | internal Supplier |
| **Buying Price List** (`buying_price_list`) | test buying list |
| **Handover Mode** (`handover_mode`) | `Two Confirmation` |
| **Auto-submit Dispatch Delivery Note** (`auto_submit_dispatch_dn`) | Unchecked for first test |
| **Auto-submit Receipt Purchase Receipt** (`auto_submit_receipt_pr`) | Unchecked for first test |
| **Billing Frequency** (`billing_frequency`) | `Manual Batch` |
| **Dispatch Responsibility** | active dispatch responsibility |
| **Receipt Responsibility** | active receipt responsibility |
| **Supervisor Responsibility** | active supervisor responsibility |

Give the dispatch and receipt Employees active **CFG Kanban Operator Profile** records, add the
matching Responsibilities under **Responsible Roles**, and enable the required Start/Complete
permissions.

### 6.6 Configure the C1 Customer Site

Create a Customer and linked Delivery Address for the Sales Company, then create
**CFG Kanban Customer Scan Point**:

| Exact screen label | Example value |
|---|---|
| **Printed Customer Site Code** (`site_code`) | `CUSTSITE-TEST-001` |
| **Site / Branch Name** (`site_name`) | `Test Customer Main Gate` |
| **Active** (`active`) | Checked |
| **Selling Company** (`selling_company`) | Sales Company |
| **Customer** (`customer`) | active test Customer |
| **Delivery Address** (`customer_address`) | Address linked to that Customer |
| **Route Reference** (`route_reference`) | `TEST-ROUTE-A` |
| **Default Selling Price List** (`default_price_list`) | active Selling Price List |
| **Proof Policy** (`proof_policy`) | `Required` |

Give the driver **Customer Delivery** Responsibility in the Operator Profile. Issue a current QR
credential. Issuing a new credential invalidates the previous one.

## 7. Test Phase A — Trigger purchase replenishment

1. Open **CFG Kanban → Production Operator Panel**.
2. Identify the test operator using their QR credential.
3. Scan or enter `PUR-RM-FLAVOUR-001` and choose **Find Card** if necessary.
4. Confirm the displayed Item, quantity, Master, and Card type.
5. Select **Consume / Trigger** once.
6. Open **CFG Kanban → Kanban Signals** and locate the new Purchase Replenishment Signal.
7. Select **Approve Purchase Replenishment**.

Expected:

- exactly one Signal and one Cycle are created;
- Signal Type is **Purchase Replenishment**;
- the Card/Signal remains `100 Kg`, while the Material Request is `5 Bag` with conversion factor
  `20` and Stock Qty `100 Kg`;
- Signal moves through Executing to Completed when its ERP command succeeds;
- Card moves from Available to Replenishment Requested;
- one ERPNext Material Request is created, linked to the Signal/Cycle, and submitted because the
  test Master has **Submit Material Request on Approval** enabled;
- no Purchase Order, Purchase Receipt, or stock movement is silently created.

Idempotency check: do not deliberately trigger a second cycle from the same active Card. If the
browser retries the approval request, the existing ERP Command/Material Request must be returned;
no duplicate Material Request may appear.

## 8. Test Phase B — Purchase Order association

1. Open the linked Material Request.
2. Use the normal ERPNext buying action to create a Purchase Order.
3. Confirm Company, Supplier, Item, UOM, quantity, rate, taxes, schedule date, and target Warehouse.
4. Submit the Purchase Order.
5. Refresh the Kanban Cycle.
6. If it was not associated unambiguously, use **Purchase Replenishment → Select Purchase Order**.
7. Select the submitted PO and enter **Selection Reason**, for example `System test PO for cycle`.

Expected:

- Cycle shows Purchase Order, Purchase Order Item, Supplier, Ordered Qty, Received Qty, Outstanding
  Qty, and Purchase Status **Ordered**;
- Card state becomes **Purchase Ordered**;
- PO trace fields show Kanban Controlled, Kanban Cycle, and Kanban Signal;
- an Event records who selected the PO and the reason.

Negative check: attempt to select a submitted PO belonging to a different Supplier, Company, or
without the Item. The operation must be blocked and a visible Exception created.

## 9. Test Phase C — Receive purchased material

1. Open the Kanban Cycle.
2. Select **Purchase Replenishment → Receive Purchased Item**.
3. Enter:
   - Delivered Qty: `5 Bag`;
   - Accepted Qty: `5 Bag`;
   - Rejected Qty: `0`;
   - Accepted Warehouse: Manufacturing Raw Warehouse;
   - Supplier Delivery Note: `SUP-DN-TEST-001`.
4. Select **Create Purchase Receipt**.
5. Review the Draft Purchase Receipt. Add required Batch, serial, Quality Inspection, tax, or native
   ERPNext details when the Item requires them.
6. Submit the Purchase Receipt manually.
7. Refresh the Cycle and Card.

Expected before submission:

- the Purchase Receipt is Draft;
- ERP stock has not changed;
- the Cycle does not claim the quantity is received.

Expected after submission:

- ERPNext stock in the Raw Warehouse increases by the accepted quantity;
- Cycle becomes fully received/completed and Card returns to **Available**;
- submitted Purchase Receipt carries Kanban Cycle/Signal trace fields;
- supplier invoice/payment remains outside this Kanban workflow.

Partial-receipt variant: on a separate cycle receive `3 Bag` (`60 Kg`), submit it, verify state
**Partially Received**, outstanding `2 Bag / 40 Kg`, and Card remains tied to the active Cycle.
Receive the balance using a second Purchase Receipt; only then may the Card recycle.

Negative checks:

- Delivered Qty not equal to Accepted Qty plus Rejected Qty must fail.
- Rejected Qty without Rejected Warehouse must fail.
- Quantity above outstanding plus tolerance must fail and create an Exception.

### 9.1 Logistics Panel warehouse-card receiving variant

1. Create a **Location Card** named `RCV-RAW-TEST-001`, set **Location Purpose** to **Supplier
   Receiving**, and set **Current Warehouse** to Manufacturing Raw Warehouse.
2. Add **Supplier Receiving** Responsibility to the receiving operator profile, then migrate before
   assigning it if the Responsibility was not previously installed.
3. Print **CFG Supplier Receiving Location Card**.
4. Open **Kanban Logistics**, identify that operator, and scan `RCV-RAW-TEST-001`.
5. Confirm the page lists only submitted, outstanding PO items for Manufacturing Raw Warehouse.
6. Scan `PUR-RM-FLAVOUR-001`; verify it selects the exact active Cycle and PO item.
7. Choose **Receive This Order**, enter supplier Delivery Note and quantities, confirm the review
   checkbox, then create the controlled Purchase Receipt.
8. If the receipt submits immediately and physical tags are permitted, activate one unused
   preprinted main tag. If it remains Draft, complete the indicated ERP prerequisites first.

Expected: a location scan never posts stock; an original-card scan cannot select another warehouse,
Company or item; only the submitted Purchase Receipt updates ERP stock and releases Card lifecycle;
physical tags cannot exceed submitted accepted stock quantity.
- A fully received PO row cannot be selected again.

### 9.2 Rejected-warehouse and replacement chronology

Use a separate Cycle ordered for `5 Bag` and configure a valid **Rejected Warehouse**.

1. Receive Delivered `5`, Accepted `3`, Rejected `2`, then submit the Purchase Receipt.
2. Verify ERPNext added `3 Bag` to the accepted Raw Warehouse and `2 Bag` to the Rejected Warehouse.
3. Verify the Cycle shows Physically Received `5`, Accepted `3`, rejected/open `2`, usable
   fulfilment `3`, usable outstanding `2`, status **Receipt Exception**, and the Card remains active.
4. Open **Purchase Replenishment → Open Receipt Dispositions**. Select **Supplier Replacement** and
   enter a reason.
5. From the original submitted Purchase Receipt, create the native Purchase Return for the rejected
   `2 Bag`, explicitly returning it from the Rejected Warehouse, then submit it.
6. On the Cycle choose **Refresh Receipt Result**. Verify the disposition records the native return,
   rejected stock is no longer in the Rejected Warehouse, and replacement remains pending.
7. Receive the replacement `2 Bag` against the reopened PO/Cycle, accept all `2`, and submit.

Expected: ERPNext documents alone move stock; the first physical delivery does not recycle the Card;
the Purchase Return reopens replacement receiving; cumulative usable fulfilment reaches `5 Bag` only
after the replacement receipt; then the Cycle completes and the Card becomes **Available**.

Concession variant: select **Accept by Concession**, submit a Material Transfer Stock Entry moving
the rejected quantity from the exact Rejected Warehouse to the Cycle Destination Warehouse, then
use **Confirm Concession Transfer**. A Draft entry, wrong Item, wrong warehouses, or excessive
quantity must be rejected. The validated concession may satisfy usable fulfilment.

Short-close variant: use **Short-close Usable Shortage** with a manager and mandatory reason. Verify
the Card is released only for the authorised shortage and that short close neither moves rejected
stock nor creates a supplier Debit Note. The physical disposition remains auditable.

## 10. Test Phase D — Activate received raw-material tags

1. Open the submitted Purchase Receipt.
2. Select **CFG Kanban → Tag Received Material**.
3. Select the `RM-FLAVOUR-TEST` receipt row.
4. Scan `TST-STK1000`, enter `60 Kg`, and select the appropriate Handling Unit Type.
5. Activate it.
6. Repeat with `TST-STK1001` for `40 Kg`.

Expected:

- exactly two active Handling Units are created;
- Item, Company, Warehouse, UOM, Batch, Supplier, expiry, and ERP origin come from the submitted
  Purchase Receipt and cannot be freely substituted;
- range lookup lazily creates only families `TST-STK1000` and `TST-STK1001`;
- total activated quantity is `100 Kg` and cannot exceed the receipt row;
- each tag has an immutable activation/quantity ledger reference to the Purchase Receipt;
- rescanning the same receipt-row/tag returns the existing result rather than duplicating quantity.

Mixed-trace check: use another received Item with no enabled Material Trace Policy. It must remain
valid ERP stock, show **No Physical Tag**, and require no tag activation.

## 11. Test Phase E — Manufacture and create finished-product genealogy

1. Trigger the `FG-SAUCE-TEST` production Card and create/release its Work Order through the normal
   approved production workflow.
2. Ensure the submitted Work Order has the correct BOM operations/Job Cards.
3. Create and save the appropriate Draft ERPNext Stock Entry for the Work Order. Use the site's
   actual flow:
   - `Material Transfer for Manufacture`, followed later by `Manufacture`; or
   - direct `Manufacture` / `Material Consumption for Manufacture` when transfer is skipped.
4. On the Draft Stock Entry select **CFG Kanban → Production Material Trace**.
5. Under **Allocate Tagged Material Input**, choose the raw input row and scan the appropriate raw
   Stock Tag. Enter the actual Stock UOM quantity required by the ERP row.
6. Under **Stage Preprinted Production Output Tag**, choose the finished row, scan `TST-STK1002`,
   enter `20 Nos`, and select the Handling Unit Type.
7. Confirm that the output identity remains pending while the Stock Entry is Draft.
8. Submit the Stock Entry through ERPNext.

Expected:

- Draft tracing reserves physical input quantity but does not move ERP stock;
- required finished output coverage blocks submission if the output tag is missing/short;
- submitted ERPNext Stock Entry confirms the trace;
- consumed quantity is deducted from the raw Handling Unit;
- finished tag `TST-STK1002` is activated for `FG-SAUCE-TEST`, `20 Nos`, the finished Batch,
  Manufacturing Company, and Manufacturing FG Warehouse;
- upstream genealogy connects finished tag to exact raw tag(s) and the Stock Entry;
- ERP-only BOM items remain visible through ERP documents but are not falsely represented as exact
  physical tags.

For a transfer-to-WIP flow, the same raw tag must first move through the submitted Material Transfer
for Manufacture and then be scanned again from the WIP Warehouse on consumption/manufacture.

Open **CFG Kanban → Material Genealogy Explorer**, scan `TST-STK1002`, and verify:

- focus details match live Item, Batch, quantity, Company, and Warehouse;
- Upstream Materials shows the input tag(s);
- Confirmed Lineage Relationships identifies the ERP Stock Entry;
- Chronological Quantity and Movement Evidence shows receipt, consumption, and output evidence.

## 12. Test Phase F — Intercompany dispatch (Package B)

1. Open **CFG Kanban → Logistics Operator Panel**.
2. Identify the dispatch operator.
3. Select **New Dispatch Manifest** and choose `TEST MFG FG TO SALES LORRY`.
4. Select **Start Dispatch Scanning**.
5. Confirm the scanner status names the intended Manifest.
6. Scan `TST-STK1002` once.
7. Select **Stop Dispatch Scanning**.
8. Select **Prepare and Reserve**.
9. Verify the Handling Unit Available Qty is reserved but ERP stock remains in the Manufacturing FG
   Warehouse.
10. Select **Confirm Dispatch**.
11. Complete any displayed **Required Delivery Note Details**. If Sales Team is mandatory, add every
    salesperson row and make the percentage total exactly 100%.
12. Open the created source-company Delivery Note, review it, and submit it manually.
13. Refresh the Logistics panel.

Expected before Delivery Note submission:

- Manifest has one exact line for `TST-STK1002`;
- Delivery Note is Draft;
- ERP stock and tag ownership/location have not moved;
- tag is reserved and cannot enter another open transaction.

Expected after Delivery Note submission:

- Manifest becomes **Awaiting Receipt**;
- tag movement state is **Intercompany Transit**;
- source-company stock changes only because ERPNext submitted the Delivery Note;
- the printed tag identity and issuing Company namespace remain unchanged.

Negative checks:

- a wrong-Warehouse, wrong-Company, inactive, empty, unreleased, already reserved, or unknown tag
  must be rejected;
- rescanning in safe lookup mode may display status but must not add or change the Manifest;
- Package B requires a complete Stock Tag. Use an activated child tag first if only a physical
  portion will move.

## 13. Test Phase G — Intercompany receipt (Package B)

1. Switch to the receipt operator.
2. Open or scan the Manifest number, for example `KMF-2026-00001`.
3. Select **Start Receipt Scanning**.
4. Rescan `TST-STK1002`.
5. Verify **Receipt scans: 1 of 1**.
6. Select **Stop Receipt Scanning** and then **Confirm Receipt**.
7. Open the destination-company Draft Purchase Receipt.
8. Complete required native ERPNext values and submit it manually.
9. Refresh the Logistics panel.

Expected before Purchase Receipt submission:

- Manifest remains awaiting ERP receipt confirmation;
- tag does not falsely claim destination ownership or Warehouse;
- destination stock has not increased.

Expected after Purchase Receipt submission:

- Manifest becomes **Received**;
- Purchase Receipt **Inter Company Reference** points to the source Delivery Note;
- every Purchase Receipt Item points to its exact source Delivery Note Item, and each document's
  ERPNext **Connections** tab shows the other document;
- destination Company stock is available in the Sales Lorry Warehouse;
- Handling Unit **Inventory Company** becomes Sales Company;
- Handling Unit **Current Warehouse** becomes the Sales Lorry Warehouse;
- issuing Company/printed identity remains the original Manufacturing Company namespace;
- genealogy shows both Manifest, Delivery Note, and Purchase Receipt evidence.

Negative check: receipt confirmation before the source Delivery Note is submitted, or with a
missing/unlisted tag, must be blocked.

## 14. Test Phase H — Package C1 Customer Site and Delivery Session

1. Keep or identify the driver in **Logistics Operator Panel**.
2. Ensure the page is in safe **Tag lookup ready** mode and no Manifest edit/scanning mode is armed.
3. Scan `CUSTSITE-TEST-001` using the fixed scanner, or use **Scan with Camera** on mobile.
4. Confirm the panel displays the exact Customer, Delivery Address, Selling Company, route,
   Price List, and proof policy.
5. Select the Sales Company-specific `LORRY-TEST-01-SALES` Warehouse.
6. Select **Lock Customer and Vehicle**.

Expected:

- exactly one **CFG Kanban Delivery Session** is created;
- state is **Customer Identified**;
- session snapshots Customer Scan Point, scanned code, site/branch, Customer, Delivery Address,
  Selling Company, lorry Warehouse, physical vehicle reference, Price List, proof policy, operator,
  operator session, and start time;
- no stock reservation, Delivery Note, Sales Invoice, or ERP stock movement occurs in C1;
- the current Delivery Allocation list remains empty;
- one **Customer Delivery Session Started** Event is linked to the session;
- browser refresh restores the operator/session context and the active Delivery Session.

### C1 isolation and recovery checks

1. Scan the same Customer Site again with the same event/request retry. No duplicate active session
   may be created.
2. While the first session is active, scan a different Customer Site. The operator must be prevented
   from owning two active sessions.
3. Try a normal Warehouse that is not marked **Vehicle Warehouse**. It must not be selectable or
   must be rejected.
4. Try a Vehicle Warehouse belonging to the wrong Company. It must be rejected.
5. Switch to an operator without **Customer Delivery** Responsibility. Starting the session must be
   denied.
6. On an empty session still in Customer Identified state, select Cancel and enter a reason. The
   session must become Cancelled, remain in audit history, and release the operator to start another
   session.
7. Use an inactive Customer Scan Point, a Delivery Address linked to a different Customer, or a
   non-selling Price List in separate setup-negative tests. Configuration must be rejected before a
   valid session is created.

## 15. Cross-stage authority checks

The end-to-end test fails if any of these occur:

- Material Request approval directly changes stock.
- Draft Purchase Receipt is treated as received stock.
- tag quantity exceeds a submitted ERP receipt/output row.
- a Draft manufacturing Stock Entry consumes or creates physical tag quantity.
- a Manifest scan independently moves ERP stock.
- Draft intercompany Delivery Note claims the tag reached transit.
- Draft intercompany Purchase Receipt claims destination ownership/stock.
- a C1 Customer Site scan reserves or delivers stock.
- one Handling Unit simultaneously claims two Companies or two Warehouses.
- an ERP-only Item is incorrectly blocked because it has no tag.
- a duplicate scan/retry creates a duplicate Material Request, Purchase Receipt, Handling Unit,
  Manifest line, or Delivery Session.

## 16. Audit evidence to retain

Record or export the following:

1. Purchase Kanban Master, Card, Signal, Cycle, and Event timeline.
2. Material Request, Purchase Order, and Purchase Receipt numbers/statuses.
3. Raw Handling Unit records and quantity ledger entries.
4. Production Cycle, Work Order, Stock Entry, Material Trace, and finished Handling Unit.
5. Genealogy Explorer screenshot/report for `TST-STK1002`.
6. Movement Manifest, source Delivery Note, destination Purchase Receipt, and ERP Commands.
7. Handling Unit Company/Warehouse before dispatch, in transit, and after receipt.
8. Customer Scan Point, Vehicle Warehouse, Delivery Session, and C1 Event.
9. Every negative-test error and any CFG Kanban Exception created.

## 17. Test execution record

| Evidence | Actual value |
|---|---|
| CFG Kanban deployed commit |  |
| Manufacturing Company |  |
| Sales Company |  |
| Purchase Master / Card |  |
| Purchase Signal / Cycle |  |
| Material Request |  |
| Purchase Order |  |
| Purchase Receipt(s) |  |
| Raw tag(s) |  |
| Production Master / Card / Cycle |  |
| Work Order |  |
| Manufacture Stock Entry |  |
| Finished tag |  |
| Movement Manifest |  |
| Intercompany Delivery Note |  |
| Intercompany Purchase Receipt |  |
| Customer Scan Point |  |
| C1 Delivery Session |  |
| Exceptions observed |  |
| Tester and date |  |

## 18. Acceptance decision

Mark the package **Pass** only when:

- every stock-changing result comes from the applicable submitted ERPNext document;
- purchase Card state follows Material Request/PO/receipt feedback and recycles only after full
  receipt;
- tagged and untagged policies both operate as configured;
- production genealogy connects confirmed input and output identities without inventing ERP stock;
- intercompany Company/Warehouse ownership changes only after submitted Delivery Note and Purchase
  Receipt feedback;
- the same preprinted finished tag remains traceable after Company handover;
- Package C1 locks the correct Customer/site/Company/vehicle context but does not move or reserve
  stock;
- authorization, duplicate, wrong-Company, wrong-Warehouse, and cancellation tests behave safely;
- all records and exceptions remain auditable.

Result:

- [ ] Pass — purchase signal through C1 accepted.
- [ ] Conditional pass — non-blocking observations are attached.
- [ ] Fail — blocking defects and exact reproduction steps are attached.

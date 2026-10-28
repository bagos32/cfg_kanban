# Dispatch E1 Profile Launcher Acceptance Test

**Package:** CFG-DISPATCH-E1  
**Purpose:** Verify dispatch policy selection before Dispatch Plans and stock reservation exist  
**Expected stock effect:** None

## 1. What this test proves

This test proves that a warehouse can use one permanent Dispatch Operations card to show the
correct manager-approved workflows in business language. It also proves operator-responsibility
isolation, manager priority, single-choice recommendation, permanent-card printing, and the strict
E1 no-transaction boundary.

E1 does not create a Dispatch Plan, reserve stock, assign a vehicle, create a Movement Manifest,
move a Handling Unit, or post ERPNext documents. Stop the test if any of those changes occur from
scanning or reviewing the Profile.

## 2. Sample records

Replace the sample Company and Warehouse with real development-site records.

| Record | Sample value |
|---|---|
| Company | Wasilah FZD Trading Sdn Bhd |
| Source Warehouse | Finished Goods - FZD |
| Location Reference | FG Dispatch Bay 1 |
| Responsibility A | Dispatch Preparation |
| Responsibility B | Route Stock Dispatch |
| Profile 1 | Known Customer Delivery |
| Profile 2 | Open Route Stock |

Use a test operator who initially has Responsibility A but not Responsibility B. Use only a
development site with current migrations and assets.

## 3. Create and print the permanent card

1. Open **CFG Kanban Card** and create a new record.
2. Set **Card Type** to **Location Card**.
3. Set **Location Purpose** to **Dispatch Operations**.
4. Set **Location Reference** to `FG Dispatch Bay 1`.
5. Set **Current Warehouse** to the sample source Warehouse. Save.
6. Confirm Company is derived from that Warehouse and the card is active and unblocked.
7. Select **Print Kanban → Print Dispatch Operations Card**.

Expected result:

- an A6 landscape card is available;
- its QR contains the permanent card identity;
- the printed Warehouse, Company and location are correct;
- the label states that Profile selection does not move stock.

## 4. Create two Dispatch Profiles

Create Profile 1:

| Exact field | Value |
|---|---|
| Profile Code | DSP-KNOWN-CUSTOMER |
| Operator Label | Known Customer Delivery |
| Launcher Priority | 10 |
| Dispatch Operations Card | the card from section 3 |
| Company / Source Warehouse | exact card Company and Warehouse |
| Plan Type | Customer Order |
| Fulfilment Mode | Vehicle Delivery |
| Destination Assignment | Select Before Dispatch |
| Physical Tag Policy | Mixed |
| Stock Rotation Suggestion | FIFO |
| Supervisor Approval Required | enabled |
| Dispatch Responsibility | Responsibility A |

Create Profile 2 with code `DSP-OPEN-ROUTE`, label `Open Route Stock`, priority `20`, Plan Type
**Open Route Stock**, Fulfilment Mode **Existing Ad-hoc Lorry Delivery**, and Responsibility B.

Expected validation:

- selecting a Dispatch Operations card from another Warehouse is rejected;
- Source Warehouse must match the card Warehouse;
- a Warehouse from another Company is rejected;
- **Select at Receipt** is rejected unless Fulfilment Mode is **Goods in Transit**;
- a Goods-in-Transit profile requires an ERPNext Transit Warehouse;
- Auto-submit Stock Transfer is rejected for a mode that does not use a controlled transfer;
- saving a controlled policy change increases Profile Revision.

## 5. Verify operator authorization and priority

1. Give the test operator Responsibility A only.
2. Open **Logistics Operator Panel** and identify that operator.
3. Scan the Dispatch Operations card with the fixed scanner, or use the existing camera scanner.

Expected result:

- only **Known Customer Delivery** appears;
- the panel states that one other active workflow is hidden by responsibility;
- the only eligible workflow is marked **Recommended workflow** and its read-only review opens
  automatically;
- selecting **Review Workflow** shows source, Plan Type, Fulfilment Mode, destination policy,
  tag/FIFO policy, approval, proof, responsibility and Profile Revision;
- closing the review returns to the same launcher safely.

Now add Responsibility B to the same Operator Profile, refresh the operator session, and scan the
card again.

Expected result:

- both Profiles appear;
- Known Customer Delivery is first because priority 10 precedes priority 20;
- neither is automatically selected because the choice is ambiguous;
- deactivating one Profile makes the remaining Profile the recommendation.

## 6. Prove the E1 no-transaction boundary

Before scanning, note current counts or latest names for:

- CFG Kanban Movement Manifest;
- CFG Kanban Handling Unit quantity ledger/events;
- CFG Kanban Delivery Session;
- ERPNext Stock Entry;
- ERPNext Delivery Note.

Scan the Dispatch Operations card repeatedly and review each Profile. Do not open an unrelated
existing workflow.

Expected result:

- no record above is created or modified;
- no Kanban Cycle or Signal is created;
- no stock quantity, reservation, Warehouse, custodian or vehicle assignment changes;
- the permanent card remains reusable and has no active Cycle.

## 7. Permission and invalid-card negatives

1. Scan with an operator having neither Responsibility. No Profile should be disclosed; the panel
   explains that no active workflow is assigned.
2. Block the Dispatch Operations card and scan it. The server must reject it as blocked.
3. Try assigning a Warehouse Operations or General Service Location Card to a Dispatch Profile.
   Save must fail.
4. Change the permanent card Warehouse while Profiles reference it. Profile validation must prevent
   an inconsistent policy from being saved.

## 8. Acceptance decision

Pass E1 only when:

- the printed permanent card scans reliably on the intended tablet/phone/scanner;
- operator authorization and priority behave exactly as configured;
- the single-choice recommendation is truthful;
- manager policy validation prevents Company/Warehouse/mode mismatch;
- scanning and reviewing cause zero Kanban, logistics, stock, delivery, or ERP mutation.

After E1 passes, E2 may introduce Dispatch Plans, approval/cancellation, and tagged/untagged/mixed
reservation. Do not interpret the E1 **Review Workflow** button as an activation button.

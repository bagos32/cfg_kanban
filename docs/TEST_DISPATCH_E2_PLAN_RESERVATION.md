# Dispatch E2 Plan and Reservation Acceptance Test

**Package:** CFG-DISPATCH-E2  
**Purpose:** Verify business Dispatch Plans, approval, tagged/untagged reservation, release and
cancellation without vehicle assignment or ERP stock movement.

## 1. Pass boundary

E2 passes only when:

- a permanent Dispatch Operations card opens the correct authorized Profiles and open Plans;
- Customer Order and Open Route Stock Plans preserve the selected Profile revision snapshot;
- approval-required Plans cannot reserve stock before Supervisor approval;
- tagged, untagged and Mixed policies enforce their exact reservation mode;
- wrong Company, Warehouse, Item, UOM, Batch, quality state or already-reserved tags are rejected;
- Plan state becomes `Picking` after a partial reservation and `Ready for Vehicle` only when every
  requested line is fully reserved;
- release and cancellation restore active reservation availability without deleting audit records;
- no Movement Manifest, Stock Entry, Delivery Note or vehicle assignment is created.

## 2. Prerequisites and sample data

Reuse the accepted E1 setup or create:

| Record | Example |
|---|---|
| Dispatch Operations card | `DSP-POINT-FZD-MAIN` |
| Company / source Warehouse | `Wasilah FZD Trading Sdn Bhd` / `Finished Goods - FZD` |
| Customer Site | one active site belonging to the same selling Company |
| Customer Order Profile | `DSP-FZD-CUSTOMER`, Tag Policy `Mixed`, approval enabled |
| Open Route Profile | `DSP-FZD-ROUTE`, Tag Policy `Mixed`, route or territory fixed, approval enabled |
| Operator | active, Start permission, Profile responsibility |
| Supervisor | same responsibility plus Override permission |
| Tagged test stock | active Released Stock Tag in the exact source Warehouse |
| Untagged test stock | ERP stock balance not already represented by active tags |

Record the initial ERPNext stock balance and the tagged Handling Unit's `current_qty`,
`reserved_qty`, `available_qty`, Warehouse and movement state.

## 3. Customer Order Plan

1. Open **CFG Kanban → Logistics Operator Panel** and identify the operator.
2. Scan the Dispatch Operations card.
3. Select the Customer Order Profile and **Create Dispatch Plan**.
4. Select the Customer Site, optional submitted Sales Order, required date and priority.
5. Add at least two lines: one for tagged stock and one for untagged ERP stock. Save the Draft.

Expected:

- one `CFG Kanban Dispatch Plan` exists in `Draft`;
- Company, source Warehouse, Plan Type, fulfilment, tag/rotation policy and responsibility match the
  Profile;
- Profile revision, snapshot JSON and hash are populated;
- changing the Profile afterwards does not rewrite this Plan;
- no stock or Manifest document is created.

## 4. Approval gate

1. Select **Submit Plan** as the operator.
2. Confirm it becomes `Awaiting Approval`.
3. Attempt a reservation before approval.
4. Identify the Supervisor and select **Approve Plan**.

Expected:

- reservation is unavailable/rejected before approval;
- an operator without Override cannot approve;
- the authorized Supervisor changes the Plan to `Approved` with Employee, session and time audit.

For a separate Profile with approval disabled, repeat creation and submission. It should enter
`Approved` directly and record the submitting operator as approver.

## 5. Tagged reservation

1. On an Approved Plan line select **Scan Tagged Stock**.
2. Confirm FIFO/FEFO Profiles show eligible suggested tag codes in the intended order, then scan
   the correct Stock Tag.
3. Repeat negative scans with a wrong Warehouse/Company/Item/Batch tag and an already-reserved tag.

Expected:

- the correct tag creates one Reserved `CFG Kanban Dispatch Allocation`;
- one Handling Unit quantity-ledger `Reserve` event increases `reserved_qty` without changing
  `current_qty`, ERP stock, Warehouse or Company;
- only the Plan quantity still required is reserved;
- negative scans show an exact reason and create no Allocation;
- retrying the same event does not duplicate the Allocation or ledger event.

## 6. Untagged reservation

1. Select **Reserve Untagged** for a remaining line.
2. Enter an optional Batch and a quantity within verified availability.
3. Attempt a quantity above available untagged stock.
4. Attempt untagged reservation for a non-stock ERP Item.
5. Attempt untagged reservation for a serialized Item and a batch-controlled Item without Batch.

Expected:

- availability equals ERP balance minus active tagged physical quantity minus active untagged E2
  reservations for the same Company/Warehouse/Item/Batch;
- a valid action creates a Reserved untagged Allocation only;
- no Handling Unit ledger or ERP stock movement is invented for untagged stock;
- over-allocation and non-stock untagged allocation are rejected.
- serialized stock requires exact tagged identity, and batch-controlled untagged stock requires the
  exact Batch.

## 7. State and quantity check

Expected:

- at least one but not all requested quantities reserved: `Picking`;
- every line fully reserved: `Ready for Vehicle` and `Ready for Vehicle On` populated;
- `total_reserved_qty` equals the sum of active Reserved Allocations;
- every child line shows its own requested, reserved and line state.

Different Item UOMs may make the header total informational only. Quantity control remains line/UOM
specific; do not treat the header total as a convertible cross-UOM stock value.

## 8. Release and cancellation

1. Select **Release** on one active Allocation and enter a reason.
2. Verify the Plan returns from Ready to `Picking` or `Approved` according to remaining reservations.
3. Select **Cancel Plan**, enter a reason, and confirm.

Expected:

- tagged release posts one `Unreserve` ledger event and restores Handling Unit availability;
- untagged release changes only the Allocation audit state;
- released/cancelled Allocation records remain visible with operator/session/time/reason;
- cancellation releases all remaining active reservations, sets every Plan line to `Cancelled`, and
  leaves the Plan in `Cancelled`;
- no transaction history is deleted.

## 9. Open Route Stock Plan

1. Re-scan the Dispatch Operations card and select the Open Route Profile.
2. Create a Plan with route or territory, trip date, priority and total Item quantities; do not
   select a Customer or vehicle.
3. Submit, approve and reserve stock using the same tagged/untagged tests.

Expected:

- Customer is not required;
- route/territory and Trip Date are required;
- Plan may reach `Ready for Vehicle` without a vehicle;
- no customer Delivery Note is created.

## 10. Audit and no-mutation proof

Compare against the values recorded before testing:

- ERPNext stock balance: unchanged;
- no new Movement Manifest: unchanged;
- no new Stock Entry or Delivery Note: unchanged;
- tagged Handling Unit `current_qty` and location: unchanged;
- only reserved/available balances changed while active, then returned after release/cancellation;
- Event, Plan, Allocation and quantity-ledger audit records identify the exact Employee and session.

Stop here. E3 vehicle claim, loading, Manifest creation and ERP Material Transfer are deliberately
not part of this test.

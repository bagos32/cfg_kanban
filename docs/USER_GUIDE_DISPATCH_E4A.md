# Prepared customer delivery — E4A operator guide

Development increment: known-customer **Vehicle Delivery**, with tagged, untagged or Mixed stock.
The goods must already be loaded into the lorry through E3. ERPNext remains the stock system of
record. This guide does not establish live acceptance.

## Manager settings

1. Use a **Customer Order** Dispatch Profile with **Vehicle Delivery**, the correct Company,
   dispatch point, source Warehouse and same-Company Direct Transfer route.
2. Assign its **Dispatch Responsibility** and **Customer Delivery** responsibility to the driver’s
   Operator Profile. Enable **Start** and **Complete** for the required actions. Company selection
   is not an operator setting; the Plan and lorry Warehouse determine it.
3. Configure the exact active Customer Scan Point: Customer, selling Company, delivery address,
   price list, proof requirements, photo/signature/GPS settings and optional return policies.
4. Set **Auto Submit Delivery Note** on the Dispatch Profile. E4A uses that Profile’s captured
   policy; later Profile changes do not alter a prepared Plan. Off means an ERP Draft for review.
5. Set Profile **Proof Policy** to **Inherit Customer Site**, or select the explicit permitted
   policy. Recipient/signature/photo/GPS flags are copied from the Customer Site when the Session
   starts. For an inherited policy, the current Site policy is copied at that time.
6. If using a Sales Order, select an open submitted order for the same Customer/Company during
   preparation. Native Delivery Note rows retain their Sales Order row, UOM, conversion factor,
   rate, currency and project. Operator quantities remain stock quantities.

A migration and asset build are required before using this increment. Migration classifies legacy
Delivery Allocations as Tagged Stock; it does not create or consume stock.

## Driver steps

1. Identify yourself in **Logistics Operator Panel**.
2. Scan the Customer Site QR. Under **Prepared Customer Loads**, choose the exact Plan/lorry and
   select **Start Prepared Delivery**. A previously started Session opens through **Resume**.
3. Alternatively open a Loaded Dispatch Plan, select **Start Prepared Customer Delivery**, then
   scan the physical Customer Site QR in the dialog. Both entry paths use the same checks.
4. Review the Plan and quantities, then select **Start / Resume Prepared Delivery**. The system
   stages the exact loaded Stock Tags and untagged Item/Batch quantities. Do not type quantities
   again or create a second ad-hoc Session for this prepared load.
5. Review the allocations and select **Confirm Customer Allocation**. Reservations alone do not
   deliver stock.
6. Select **Create Delivery Note**, supply only missing operational ERP details, and confirm.
   A Draft remains **ERP Document Pending**; stock is delivered only on ERP submission.
7. After submission, select **Capture / Close Delivery** and complete the configured proof.
   A required-proof delivery stays **Delivered** until proof is submitted. **No Proof Required**
   closes automatically after ERP submission.
8. Reopen the Plan to see Customer Fulfilment, Delivery Session, Delivery Note and proof references.
   The E3 state remains **Loaded**; Customer Fulfilment progresses independently to **Completed**.

## Scanner and tablet use

Print these from **Kanban Operator → Scanner Command Labels**:

| Command | Purpose |
|---|---|
| `CFG:CMD:START_PREPARED_DELIVERY` | Open prepared-load selection from Logistics or Production |
| `CFG:SELECT:1` … `CFG:SELECT:10` | Select the exact displayed Plan when several are eligible |
| `CFG:CMD:NEXT_MATERIALS` / `CFG:CMD:PREVIOUS_MATERIALS` | Page Plan choices |
| `CFG:CMD:PREPARED_DELIVERY_SOURCE` | Clear the selection and scan another Plan/Site |
| `CFG:CMD:PREPARED_DELIVERY_CAMERA` | Open camera scanning |
| `CFG:CMD:CONFIRM` | Start/resume the reviewed prepared delivery |
| `CFG:CMD:CANCEL` | Close the selection safely |
| `CFG:CMD:HELP` | Show selection help |

The dialog accepts both Enter- and Tab-suffixed scans. Empty Tab and Shift-Tab retain ordinary focus
navigation. Tablets have **Scan with Camera**. Customer Site and Plan identities remain their
normal physical QR/document identities. Continue with the existing Delivery Session controls for
ERP details, signature/photo/GPS and proof. Scanner-only/kiosk acceptance of the complete existing
workflow still requires a live floor test; offline dialog tests do not establish that acceptance.

## Stock controls and recovery boundary

- Known-customer loaded Stock Tags cannot be allocated through an unrelated ad-hoc delivery.
  Loaded untagged quantities remain committed to their prepared customer until converted into
  Delivery Allocations. Active customer reservations and Dispatch reservations share availability
  checks, so they are not counted as free unassigned lorry stock. Automatic prepared commitments
  apply to loads completed after this update. Historical Loaded Plans are not retroactively held:
  explicitly starting E4A revalidates their current stock before activating this commitment. Review
  old Plans already fulfilled through the former ad-hoc workflow; no historical delivery is inferred.
- Untagged delivery requires a non-serialized stock Item, stock UOM and exact Batch when required.
  It never invents a physical Stock Tag or a certificate. Batch expiry is checked. Tagged stock
  retains its existing certificate/serial/expiry identity; effective printed expiry is checked.
- A contained tag is associated with its current physical container. Every current content tag
  of that container must be included; mixed unrelated contents are not silently delivered.
- Retrying or reopening a prepared Plan returns its existing authorized Session. A pending request
  retains its original identity in the open dialog; selecting different work is blocked until the
  outcome is known. Closing/reopening still reconciles through the Plan’s persisted Session link.
- Before an ERP document exists, release **all** allocations and cancel the now-empty Session if
  a restart is needed. Its records remain for audit. Released untagged rows do not create tag
  ledger entries. Restarting needs a fresh action and rechecks the original loaded stock.
- Submitted Delivery Note cancellation follows the existing guarded reversal/amendment workflow.
  Only physical tags receive tag-ledger reversals; ERPNext reverses untagged stock. Submitted proof
  still blocks direct DN cancellation. Existing controlled wrong-DN returns support untagged rows.
- E4A confirms the **whole prepared load**. Missing, substituted or partially released quantities
  cannot be quietly confirmed. Partial/refused delivery, reassignment, abandoned prepared loads,
  returned/overnight quantity reconciliation and wider recovery belong to E5.
- Each prepared allocation must fit one remaining native Sales Order item row. If one tag spans
  multiple repeated order rows, split preparation by order row before loading. E4A fails closed
  rather than attach excessive quantity to the first Sales Order row.

Open Route multi-customer delivery/Route Stops are implemented in the separate E4B development
increment; see [its guide](USER_GUIDE_DISPATCH_E4B.md). Direct Warehouse Delivery/Customer Pickup
are implemented in the E4C development increment; see [its guide](USER_GUIDE_DISPATCH_E4C.md).
E5 recovery/reconciliation and optional E6 remain separate increments. User-managed commit
and deployment remain required before site verification.

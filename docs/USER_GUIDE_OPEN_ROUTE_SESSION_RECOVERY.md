# Resume a stuck “Sell from Lorry” session

The driver page previously treated the normal **Customer Identified** state as blocked and
showed “Use controlled recovery for this Open Route Session”. Native Open Route start creates
this state after recognising the customer/site, before the first goods allocation. It is not
proof of an ERP posting failure. The correction offers **Add Product / Scan Stock** for both
Customer Identified and Allocating Stock, using the existing Session and reservations.

Native-site diagnosis/acceptance: **Not run**. Read the actual Session state and linked documents
on the affected site. Do not infer it solely from the old generic message.

## 1. Immediate workaround using the existing Logistics page

This path is already present in the reviewed checkout and does not require resetting the Trip.

1. Close the current driver action with **Close**. If it does not respond, navigate directly to
   **Kanban Logistics** (`/app/kanban-logistics`) in the same browser. Keep browser storage:
   it may contain an original request awaiting readback.
2. Identify the **same driver/assistant who opened the sale**. An authorised Supervisor may
   inspect another operator's Session only with the existing role, responsibility and native
   document permissions. Do not start another Trip or another sale for the same goods.
3. Scroll to **Customer Delivery Sessions** and select the existing row matching the customer
   and lorry. Its Session number and State are shown on the row and at the top of the opened
   Session. Compare the customer/address and **Source Warehouse** before continuing.
4. If State is **Customer Identified** or **Allocating Stock**, and no Delivery Note is linked,
   select **Add Route Stock**. This is the Open Route action; ordinary allocation scanning
   for an unrelated ad-hoc Session does not replace it.
5. For tagged goods, scan the source Stock Tag or supported reusable quantity bin. For untagged
   goods, select **Untagged ERP Item** and **Exact Batch** where required. Choose the displayed
   prepared/unassigned source, enter **Stock Quantity** in its stock UOM, and confirm. Repeat
   **Add Route Stock** for the other Items. Mixed containers retain their full-tag rules.
6. Review every allocated Item/Batch/quantity, then **Confirm Customer Allocation**. Select
   **Create Delivery Note** and provide any required ERP details. If the configured result is
   a Draft, an authorised ERPNext user must review and submit it. Only submission feedback
   records stock delivery; opening/confirming the Session alone does not.
7. Complete **Capture / Close Delivery**, including required signature/photo/GPS or other proof.
   Return to **Driver Route**, select the same Trip and **Refresh**. Continue/complete that stop
   from its recorded Delivery Note/proof, then proceed to the next customer.

For a bound multi-SKU Loose Tag, use its driver stop's scanned-pack acceptance workflow. Do not
replace the frozen pack quantities with separate internal-tag allocations through this workaround.
The native pack/source gates remain mandatory.

## 2. Resume from Driver Route after deploying this correction

1. Close the old action, reload **Driver Route**, and identify the original operator if needed.
2. Select the existing Trip and current customer stop, then **Sell from Lorry**.
3. The existing Customer Identified Session now opens **Add Product / Scan Stock**. It does not
   create another Session. Select and allocate the goods, repeat as needed, then use
   **Finish Selection / Create DN** and the existing Delivery Note/proof steps.
4. On a wedge scanner, `CFG:CMD:ALLOCATE_ROUTE_STOCK` opens the same product-selection action.
   The older driver alias `CFG:CMD:ROUTE_ALLOCATE_STOCK` remains supported. Source, numbered
   origin choice, `CFG:QTY:MATERIAL:n`, Confirm, camera and safe Cancel use the existing Open
   Route dialog. Focus returns to the driver scanner after the child dialog closes.
5. If an earlier request has an unknown result, use **Check saved outcome / Refresh** or the
   product dialog's **Re-read Pending Action** before changing its payload. Do not clear storage
   or issue a new action identity to work around an uncertain result.

## 3. When a real ERP problem is present

The corrected driver action displays the Session number/state and links to the Session, linked
Delivery Note and exception. Opening a link does not change stock or the Session lifecycle.

| Actual state / document | Recovery path |
| --- | --- |
| Customer Identified / Allocating Stock, no DN | Resume the existing goods selection using the steps above. This is not an exception reset. |
| Awaiting Confirmation, no DN | Allocations are confirmed. Continue Create Delivery Note; do not allocate them again. |
| ERP Document Pending or Exception, existing **Draft** DN | Open that same DN from the Session; correct/review its actual validation issue and submit through normal ERPNext controls. Refresh the Session and complete proof after posting feedback. |
| Delivered, submitted DN | Stock has posted. Complete the required proof / Capture Close Delivery; do not make another DN for the same goods. |
| Exception, **submitted** DN | Have a Supervisor inspect the linked exception and existing ERP/Kanban posting evidence. A second DN or manual status reset is not a recovery. Record the Session/DN/exception numbers and exact error before any further stock action. |
| Exception, no DN | Open the exception from the Session and resolve its actual cause. Where confirmed allocations remain valid, retry the existing **Create Delivery Note** action on that Session; its native command/revision controls apply. If it rejects, retain the exact validation message for investigation. Do not edit status to force it through. |
| Cancelled Session or cancelled DN | Preserve the cancelled attempt and use the existing Supervisor visit/ERP cancellation-amendment reconciliation. An office Trip's frozen route must not be relinked to another visit by editing records manually. |

If you intentionally want to abandon an **unused** attempt, the existing **Release** controls
require a reason and the normal completion permission. **Cancel Empty Session** is offered only
when it is empty and Customer Identified; frozen accepted/refused outcomes cannot be abandoned
this way. Cancellation is not required for this missing-goods-button bug. It ends the attempt
and may require Supervisor reconciliation of the office visit/route before a new attempt.

No database edits, balance resets, reservation deletion or new loading movement are needed to
resume a normal identified Session. This fix changes no schema or ERPNext version. If deployed
together with the pending Loose Tag package, that package's migration requirements still apply.

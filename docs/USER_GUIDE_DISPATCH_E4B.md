# Open Route delivery and Customer Stops — E4B

This increment extends a **Loaded Open Route Stock / Vehicle Delivery Plan**. One lorry load can
serve several existing Customer Sites. Every visit uses the existing Customer Delivery Session,
Delivery Note and proof workflow; it does not create a second delivery engine.

## 1. Setup

In **CFG Kanban Dispatch Profile**:

| Setting | Value/purpose |
|---|---|
| Plan Type | Open Route Stock |
| Fulfilment Mode | Vehicle Delivery |
| Company / source Warehouse / Dispatch Operations Card | Correct company-specific dispatch context |
| Logistics Route | The existing same-Company Direct Transfer route used to load the lorry |
| Customer Stop Sequence | **Flexible Order** or **Planned Order**, as required |
| Customer Delivery Route Reference | Optional exact match to Customer Scan Point **Route Reference** |
| Territory | Optional Territory scope; its child Territories are eligible |
| Allow Controlled Supervisor Override | Enable if a Supervisor may approve an out-of-order visit |
| Dispatch Responsibility | Assign to the driver and relevant Supervisor |
| Auto Submit Delivery Note / Proof Policy | Existing captured delivery/posting policy |

**The two sequence modes are configurable during setup.**

- **Flexible Order:** planned stops may be visited in any order. An eligible unplanned Customer
  Site can also become a visit. The original planned position and actual visit sequence are both
  retained.
- **Planned Order:** the driver must choose the next unstarted planned Stop. A different planned
  Stop requires a recorded Supervisor sequence approval and the Plan’s captured override policy
  must permit it. An unplanned Site must first be planned by a Supervisor.

Changing the Profile creates a new policy revision for future Plans. It does not rewrite an
existing Plan. Existing Profiles/Plans receive the compatibility default **Flexible Order** during
migration; their historical snapshot JSON is not rewritten.

The **Customer Delivery Route Reference** is a business/customer route identifier. It is separate
from the warehouse-loading **Logistics Route**. If configured, set the same reference on eligible
Customer Scan Points. Company, optional Customer Site restriction, Territory and delivery-route
reference are checked together. No geographic optimization is performed.

Operator Profiles need the Plan’s **Dispatch Responsibility**, **Customer Delivery** responsibility,
and **Start / Complete** permissions. A Supervisor planning/skipping/approving Stops also needs the
Supervisor Kanban role and Override permission. Operators do not switch a global Company setting;
Company is taken from the scanned Plan, Customer Site and lorry Warehouse.

Migrate and build assets before using this increment. Native database and tablet acceptance still
need to be recorded in [the E4B test guide](TEST_DISPATCH_E4B_OPEN_ROUTE.md).

## 2. Prepare, load and optionally plan Stops

1. Create the Open Route Plan with trip date and total Item/stock quantities. A Customer is not
   required at preparation. Submit/approve and reserve tagged/untagged stock as before.
2. Use E3 to select the lorry at the last minute, confirm physical loading and submit its controlled
   Stock Entry. The Plan must be **Loaded** before a customer visit can start.
3. A Supervisor may plan Stops before or after loading: open the Plan, select **Plan Customer
   Stop**, scan the Customer Site, then Confirm. Repeat for subsequent planned positions. A repeated
   visit to the same Site is permitted; the driver must select the exact Stop if several match.
4. **Approve Stop Order** records a reasoned approval for one selected planned Stop. It does not
   change stock rules or become a route-wide bypass. **Skip Planned Stop** is a Supervisor planning
   action with a reason; it retains the original record rather than deleting it.

## 3. Deliver to each customer

1. Identify the driver in **Logistics Operator Panel**.
2. Scan the Customer Site and select an eligible **Open Route Load**, or open the Loaded Plan and
   select **Start / Resume Route Visit**, then scan the physical Customer Site.
3. Select the exact numbered Plan/Stop when several are eligible. Review and Confirm.
4. The new **CFG Kanban Route Stop** records both planned position (if any) and actual sequence.
   Its Delivery Session locks the Customer, Company, address, lorry, prices and proof policy.
5. Select **Add Route Stock**. Scan the physical Stock Tag/container, or select/scan the exact ERP
   Item and Batch for untagged stock.
6. Choose the stock origin explicitly if several are shown:
   - **Prepared Route Stock** consumes the remaining allocation budget from this loaded Plan.
   - **Unassigned Lorry Stock** uses verified free stock in the same company-specific lorry.
7. Enter/scan the quantity in **stock UOM**, review the source and Confirm. Repeat for further
   inputs. Tagged and untagged allocations may share one customer Session without inventing tags.
8. Use the existing **Confirm Customer Allocation**, **Create Delivery Note**, and proof controls.
   A Draft does not consume stock. A required-proof delivery remains active until proof closes it.
9. Repeat for the next customer. One active visit is allowed per Plan, and the existing one-active-
   Session-per-operator rule still applies. Another operator cannot adopt the driver’s Session.

The Plan shows visits started/completed and the Stop history. **A completed visit is not a settled
route.** Existing D3 stock counting remains available; E5 will connect final route reconciliation,
returns, overnight balances, reassignment and release/carry-forward of remaining commitments.

## 4. Reusable containers and stock identity

- A **Production Output Container** or **Logistics Quantity Bin** with one real ERP-posted fill may
  supply a partial quantity. Its current content identity, Batch, certificates and expiry remain.
  The bin stays loaded while quantity remains, so another customer can use the remainder.
- An ordinary **Logistics Container** groups complete physical Stock Tags. Scanning it confirms
  all current contents, including separate compatible route/unassigned origins. It does not merge
  different products or batches into one tag, and it does not permit a partial mixed-container pick.
- Serialized tags remain whole physical units. Whole-number UOMs, mandatory Batch, quality, stock
  location, certificate identity and effective expiry checks remain enforced.
- Intermediate operation Hopper WIP is not posted lorry stock and does not become delivery stock
  through this flow.
- Prepared stock cannot quietly be sold through an unrelated ad-hoc Session. Remaining prepared
  quantities and active reservations are excluded from free unassigned stock. Historical Open Route
  loads are not automatically held retroactively; explicit entry validates their stock first.

## 5. Scanner and tablet controls

Print from **Kanban Operator → Scanner Command Labels**:

| Payload | Action |
|---|---|
| `CFG:CMD:START_ROUTE_DELIVERY` | Start/resume visit selection; also reopens a pending route action |
| `CFG:CMD:PLAN_ROUTE_STOP` | Supervisor: add one planned Customer Stop |
| `CFG:CMD:APPROVE_ROUTE_ORDER` | Supervisor: approve one Stop out of planned order |
| `CFG:CMD:SKIP_ROUTE_STOP` | Supervisor: skip an unstarted planned Stop with a reason |
| `CFG:CMD:ALLOCATE_ROUTE_STOCK` | Add stock in the currently displayed Route Delivery Session |
| `CFG:CMD:ROUTE_CAMERA` | Open the tablet camera |
| `CFG:CMD:ROUTE_SOURCE` | Clear selection and scan another source |
| `CFG:CMD:ROUTE_ITEM` / `CFG:CMD:ROUTE_BATCH` | Arm exact ERP Item/Batch input |
| `CFG:CMD:ROUTE_REASON` | Arm a Supervisor or pending-cancellation reason |
| `CFG:SELECT:1` … `CFG:SELECT:10` | Select a displayed Plan, Stop or stock origin |
| `CFG:CMD:NEXT_MATERIALS` / `CFG:CMD:PREVIOUS_MATERIALS` | Page numbered choices |
| `CFG:QTY:MATERIAL:n` | Set stock quantity; signed steps adjust it |
| `CFG:CMD:CONFIRM` / `CFG:CMD:CANCEL` | Confirm the reviewed action / close safely |
| `CFG:CMD:ROUTE_RECONCILE` | Re-read an uncertain action’s recorded result |
| `CFG:CMD:ROUTE_VOID_PENDING` | Reasoned cancellation only if the pending action is unrecorded |

Enter and Tab scanner suffixes are supported. Blank Tab, Shift-Tab and composition preserve normal
navigation. Camera, touch Item/Batch/quantity fields and scanner input share the same controller.
A failed source/Site/quantity scan clears readiness. Continue through the existing ERP detail and
photo/signature/GPS proof controls; full floor/kiosk acceptance still requires live testing.

## 6. Retry and controlled correction

An uncertain result stays locked to its original operator, action, source, quantity and event token
across closing/reopening or refresh. Web Locks serialize tabs. Another action cannot overwrite that
pending intent. Re-identify the original operator if required; authentication can be renewed without
changing the original business action identity.

Use **Re-read Pending Action** first. A recorded result reopens the existing Session/Stop without
allocating again. No recorded result alone does not permit replacement of an uncertain request:
retry its original Confirm, or choose **Cancel If Unrecorded**, enter a reason and Confirm.

The cancellation uses the same server scope lock, records a no-stock audit event and blocks a late
copy of that old request. If the original action was already recorded, its result is reopened and
no stock is undone. To change a recorded reservation, use the ordinary reasoned release controls.
Corrupt pending data fails closed for Supervisor investigation; it is never silently discarded.

An empty cancelled planned visit retains its actual sequence/history and creates a new Planned
retry position. Submitted Delivery Note cancellation/amendment and proof protections remain the
existing controlled workflow. A partial quantity-bin reversal preserves its existing membership;
reuse with different contents remains protected. Invoice creation and route optimization are outside
this increment.

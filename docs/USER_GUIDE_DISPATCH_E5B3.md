# E5B3 — Follow-on Delivery Trip

Prepared 25 November 2026 on top of `3c9cc99`. Implementation and offline verification do not
establish native ERPNext or physical warehouse acceptance. At the owner's explicit request,
live E5B2 testing is deferred until the complete E5 section can be tested together.

## Where to work

Open the **original CFG Kanban Delivery Trip → Plan Follow-on Trip** button / **Follow-on Trip**
tab. This is an embedded editor on the normal office DocType form, not a planning popup.
**Trip Handover → Plan Follow-on Trip** opens the same form for an exact selected Trip.
The Driver Route retains links to the original/follow-on Trip and shows carried customer returns.

The ERPNext user needs the existing Trip editor role and native Create/Write/Read permissions.
Sign in with an authorized Supervisor operator with Start, Complete, Override and Logistics
Reconciliation responsibility. Membership of a driving team alone does not authorize this decision.
The active dispatch profiles, their stock/tag/proof/route policies, Company restrictions and native
source-record permissions still apply. Use a supported HTTPS browser with Web Locks and storage.

## Before takeover

1. Complete or cancel the original Delivery Sessions and finish required proof. Posted Delivery
   Notes, customer signatures and completed deliveries remain on the original Trip.
2. Through E5B2, physically return/transfer selected leftovers or keep sound stock on the lorry.
   Post any required existing recovery Stock Entry, close a fresh balanced D3 count and settle
   every original Customer Order and Open Route Plan. An overnight choice that continues the
   same Plan still owns its commitments: settle it before creating a follow-on Trip.
3. For a replacement lorry, first complete the controlled physical stock transfer into that lorry.
   E5B3 confirms stock **already present there**. It does not withdraw from the original warehouse
   or create another loading Stock Entry. Available unassigned stock on that receiving lorry may
   also be explicitly selected and confirmed for the remaining order.
4. Receive old customer returns through QC, or include their entire unreceived Cases in takeover.
   A Case is indivisible here: check every line and all physical bundles before confirming it.
   Stock/QC holds on company-owned refusals continue through their existing hold/release workflow;
   these goods cannot be made saleable by creating a follow-on Trip.

## Office setup and confirmation

1. Save/reload the original Trip; click **Plan Follow-on Trip** and sign in if necessary.
2. Under **Setup Inputs**, select the receiving lorry Warehouse, scan that exact physical
   **Warehouse Operations** card, select an active receiving lead driver and optional assistant
   Employee IDs (one per line or comma separated), and enter dates and a Supervisor reason.
   Assistants require their normal active Customer Delivery Operator Profiles.
3. **Select Orders** lists the smaller of the original still-required quantity and the current
   unassigned SO balance. Pick exact rows and quantities. Nothing is selected automatically.
   Already completed/refused stops require an explicit decision that the outstanding order is
   still wanted; cancelled stops are excluded. This recovery covers physical stock Items.
4. **Select Visits** chooses unfinished optional-sale/information visits. They share one new
   Open Route pool. Extra stock is optional; an empty shared pool uses eligible unassigned
   lorry stock through the existing controlled route-sales flow.
5. **Choose Physical Sources** selects an exact order row or the shared optional-sale pool.
   Scan the Stock Tag, preview its Item/Batch/available quantity, then **Add Source**. Keep each
   physical tag whole and on one Plan; split/repack first if its quantity must be divided.
   For loose stock, choose **Untagged ERP Stock**, exact Item/Batch, preview and enter the quantity.
   Serial-controlled or ambiguous certified stock requires exact tags. Expiry, certificate,
   source-warehouse and reservation checks remain active. Every order's sources must total its
   selected quantity exactly. **Review / Remove Sources** removes an unsaved source by number.
6. **Select / Confirm Returns** selects Cases and confirms their original Return Note / custody
   label identities. Confirm the complete Case, including all its listed lines and bundles.
   All still-unreceived customer-return Cases must either be carried or physically received by
   QC before the original Trip can end. Selecting some Cases is supported after receiving the others.
7. **Review Handover** shows the exact request. **Confirm Create** closes the original Trip,
   records return custody, closes its settled operational sheets through their existing workflow,
   and creates one linked **Draft** Trip with confirmed normal Dispatch allocations.
8. Open the new Trip, review it, **Mark Planned**, and approve its operational Route Sheet when
   required by the unchanged dispatch/route policy. Use **Driver Route → Start Route / Complete Stop**
   and the existing Delivery Note/proof workflow. Do not Generate Dispatch again: stock has
   already been confirmed. The new Trip's actual source is its receiving lorry; its Dispatch
   Profile policy snapshot retains the original office policy.

A return-only takeover is supported with no invented customer stop or stock Plan. Mark the new
Trip Planned, Start Route to transport the listed return custody to QC, then have the office close
it after physical receipt. Inspection, credit decisions and disposition may continue separately.

## What remains traceable

- The original Trip, its loaded allocations, Delivery Notes, proof, counts and recovery entries.
- The linked follow-on Trip and immutable physical-source/request receipt.
- Each original Return Case's collection Trip, collection lorry, customer, quantities and QC state.
- A separate **Current Custody Trip / Lorry** and append-only handover history on that same Case.
  QC Monitor can filter **Original Driver Trip** and **Current Custody Trip** independently.
- Driver Route lists incoming Cases even if their original customer stop is not on the new route.
  Trip-level Documents / Print offers their original Return Notes and custody labels for reprint.
- An outgoing middle Trip retains its confirmed incoming Case history after a further takeover.

One source Trip can create only one follow-on. For another takeover, work from the latest child.
Changing confirmed stock/custody or the child Trip's business snapshot through ordinary fields is
blocked. Use normal E5 settlement and another controlled follow-on action.

## Unknown response or correction

The browser retains the original operator/user, payload and action identity before Create. It does
not post automatically on opening, refresh or Read Back. After a lost response, **Read Back** first.
If already recorded, open that child. If not recorded, keep/retry the exact original request, or enter
a reason and **Void Unrecorded Request**. Server-side voiding serializes with creation and blocks
a late execution. Then refresh and correct the setup. A first explicit validation rejection allows
correction; an uncertain attempt followed by rejection stays frozen until reconciled. Back/Cancel
preserves an unknown request; it does not reverse recorded stock, custody or documents.

## Scanner commands

Print from the existing command-label catalogue. Commands use `CFG:CMD:`; identities retain their
normal physical labels. Enter and Tab suffixes and the **Camera** button use the same controller.

| Command | Action |
| --- | --- |
| `PLAN_FOLLOW_ON_TRIP` | Open the exact selected Trip's normal office follow-on section; from Operator/Logistics first select an exact Trip in Trip Handover |
| `FOLLOW_ON_INPUTS` | Numbered receiving lorry/card, driver, assistants, dates and reason inputs |
| `FOLLOW_ON_ORDERS` | Numbered SO rows toggle selection; `CFG:QTY:MATERIAL:n` changes the last selected row |
| `FOLLOW_ON_VISITS` | Numbered optional-sale visits toggle selection |
| `FOLLOW_ON_RETURNS` | Numbered Cases toggle selection; scan each selected Case or original custody label after checking the entire Case |
| `FOLLOW_ON_SOURCES` | Numbered selected order / shared pool, then physical source tag |
| `FOLLOW_ON_LOOSE`, `FOLLOW_ON_ITEM`, `FOLLOW_ON_BATCH` | Choose loose stock and arm exact Item/Batch inputs |
| `FOLLOW_ON_PREVIEW`, `FOLLOW_ON_ADD` | Review current physical identity/availability, then add its stock-UOM quantity |
| `FOLLOW_ON_STOCK` | Numbered unsaved physical sources; select to remove |
| `FOLLOW_ON_REVIEW`, `FOLLOW_ON_CREATE` | Review, then explicit Create (also `CONFIRM`); pending Create retries the original request |
| `FOLLOW_ON_READBACK` | Resolve an original unknown submission without posting |
| `FOLLOW_ON_VOID_REASON`, `FOLLOW_ON_VOID` | Reason, then serialize/void an unrecorded original request |
| `FOLLOW_ON_CAMERA`, `HELP`, `CHANGE_OPERATOR`, `CANCEL` | Camera, help, sign-in change and safe Back |

`CFG:SELECT:1`–`CFG:SELECT:10`, `NEXT_MATERIALS` and `PREVIOUS_MATERIALS` operate numbered pages.
Scanner Ready focus returns after success, rejection, camera and Cancel. Verify real kiosk/tablet
scanner use in the combined acceptance test; the offline browser fixture simulates those inputs.


## Recovery before the follow-on driver departs

A confirmed child is already carrying stock/custody even while it is Draft or Planned. To abandon
it, first settle every linked Plan through the normal E5 count/stock-stays or recovery workflow.
The office can then enter the closure/cancellation reason and use the normal Cancel Planning /
Close Planning action. Unreceived old returns still require physical QC receipt before a standalone
cancellation; cancelling office planning does not discard physical custody.

If the load and returns need another lorry/team immediately, open **Plan Follow-on Trip** on that
settled child instead. Its valid recorded carry-in receipt permits reviewed replacement without
pretending the route started. Select the still-required orders/visits, confirm current physical
stock and all pending Cases, then Review/Confirm. The transaction transfers custody, closes the
unused child and creates its next child together; original source/collection facts remain intact.
A normal unstarted Trip without a confirmed carry-in receipt still uses ordinary office planning.

Changed quantities on a reservation retry are rejected; release the original reservation through
its existing action before changing it. Native reservation endpoints now require POST; the CFG
UI already uses that method. Current stock/Plan-line/metadata checks may require a refreshed
physical review after another action changes the source. An expired operator session returns to
sign-in while preserving unknown requests. Late responses from the previous operator are hidden.

See [combined E5 acceptance and native test prerequisites](TEST_DISPATCH_E5_COMBINED.md).

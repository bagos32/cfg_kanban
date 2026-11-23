# Driver documents and 80mm printing

Development implementation, 23 November 2026. Native ERPNext/site, companion-app and physical
printer acceptance remain pending. This guide does not declare production readiness.

## Office setup on a normal DocType page

1. Open **CFG Dispatch Control → Mobile Print Setup → New** (or search **CFG Kanban Mobile Print
   Profile**). An Accounts Manager or System Manager creates one profile for each Company.
2. Enable the profile. Set paper width, printer DPI and **printable width in dots** from the
   printer specification. Defaults are **80mm paper / 203 DPI / 576 printable dots**, not a claim
   that every 80mm printer uses these values. Printable width must be divisible by eight.
3. Select the native **ERPNext Print Format** for Delivery Note, Sales Invoice, custom Credit Note,
   Temporary Return Note, Trip stock list, existing Stock Tag and Return Custody Label.
4. Keep **Invoice creation = Draft** initially. **Disabled** prevents new driver invoices.
   **Automatic Submission** requires a named Employee authorization list and the terminal user's
   native Sales Invoice **Create / Submit** permissions. The assigned operator must also have
   Kanban **Complete** authority and Customer Delivery responsibility. Being an assistant alone
   does not confer accounting permissions. Normal native Company/User Permissions still apply.
5. In the already installed **Label Bridge companion app**, pair/select the physical Bluetooth
   printer. CFG does not select a Bluetooth MAC address or install a Bluetooth driver.

**Print Format is the layout source for BOTH print paths.** The app ships `CFG Delivery Note 80mm`,
`CFG Sales Invoice 80mm`, `CFG Return Note 80mm`, `CFG Trip Stock 80mm`, `CFG Stock Tag 80mm` and
`CFG Return Custody 80mm`. Duplicate a preset as a custom ERPNext Print Format, edit the copy and
select it in the profile. Keep your custom format under its own name so app updates preserve it.
Several enabled formats of the same DocType can be selected on the driver page. The driver’s
last format choice is saved for that browser and Company.

A custom **Credit Note** remains optional. No mandatory custom-app dependency or custom DocType
is installed. If it exists, select an existing format with **DocType = Credit Note**, or duplicate
and adapt the Sales Invoice receipt format for that DocType. An empty format setting uses the native DocType default Print Format, falling back to
`Standard`. For credit returns recorded as Sales Invoice, use a Sales Invoice format.

Native ERPNext Print Settings control whether a Draft may be printed. CFG does not enable draft
printing or override cancelled-document restrictions. If allowed, the supplied financial presets
show **DRAFT — NOT POSTED** on drafts.

## Driver workflow

1. Open the assigned Trip on **Driver Route**. On the current customer stop choose
   **Documents / Print / Invoice**. Completed stops retain this button, so a driver can print an
   invoice after delivery. The page-level button also opens Trip documents.
2. Select the exact document. Available documents are linked to this Trip and selected stop:
   Delivery Notes, their native Invoices, the stop’s Return Cases and linked Return/Credit documents,
   existing allocated Stock Tags, created custody labels, and the current lorry stock list.
   This is not a search of every invoice for that Customer.
3. Choose an **ERPNext Print Format**, letterhead choice and complete copy count.
4. **Normal ERPNext Print** opens the native print view with that format. Use the browser/system
   printer dialog as usual. Opening it does not certify that paper was printed.
5. For direct printing, use **Printer Setup** to save this device’s printer alias, paper width,
   printable dots and DPI. Enter the companion app’s 32-character lowercase signing key and
   **Pair Key for This Tab**. The alias is a reference name; Bluetooth printer selection stays
   inside the companion app. The signing key is held in memory, never saved in browser storage,
   the ERP database or the print URI. The key can be reused for the same operator and Company while Driver Route stays open; pair again after leaving the route, changing operator/Company, refreshing the browser or choosing Forget Key.
6. Choose **Prepare Direct Print**. Inspect the raster preview generated from the selected native
   format. Choose **Prepare This Segment for Handoff**, then **Open Label Bridge for This Segment**.
   A fresh click/scan is required; CFG does not silently launch or resend a prepared print.
7. Check the physical receipt, then **Confirm This Segment Printed**. If uncertain, select
   **Outcome Unknown**. An explicit retry needs a reason. Confirmed segments cannot be resent
   within the same job. A deliberate complete reprint is a new reviewed job.

Long receipts are split to the existing bridge’s **4096-row / 48,000-character URI limits**.
Every segment needs a separate handoff and paper confirmation. Multiple copies are collated as
all segments of copy 1, then all segments of copy 2. No receipt tail is silently truncated.
The companion protocol has no physical-print acknowledgement or automatic cut/receipt commands.

## Create an Invoice

**Create Invoice** is a separate, explicit action. Select a submitted non-return Delivery Note
from this exact stop, enter any native mandatory fields and confirm **Create Invoice Draft** or
**Create and Submit Invoice**, according to office policy. It uses ERPNext’s Delivery Note → Sales
Invoice mapper: native remaining billing quantity, tax calculation, commercial values, naming
series and Document Naming Rules apply. It never sets `update_stock` or creates a second issue
of the delivered goods. It does not take payment or produce a POS receipt/payment transaction. Missing accounting,
pricing or currency defaults must be configured by the office. Drivers cannot edit rates,
quantities, accounts or currency through the mandatory-field editor; mapped Item columns remain
read-only while any permitted custom mandatory values are entered.

An existing office Invoice draft for that DN is reused and is **never automatically submitted**.
Multiple existing drafts require Accounts reconciliation. Partially submitted billing and returned
quantities are handled by the native mapper. An all-billed DN has no new billable quantity.
Native validations, workflows and required custom fields can still reject creation/submission.
A changed office Invoice policy invalidates the reviewed request; refresh and review it again.
The server locks and rechecks the policy version before creating/submitting, so a Draft review
cannot silently become an automatic submission.
The print action itself never creates an Invoice or Credit Note. Customer credit remains in the
existing Return Case accounting-decision workflow.

## Create an at-site return custody label

First collect old customer goods through **Collect Old Customer Return**, which creates or links
the Temporary Return Note. Then choose **Create Return Custody Label**, select its exact Item row
and enter the quantity on this physical bundle. Several labels may divide the same row, but their
combined quantity cannot exceed its collected/claimed quantity. New labels are available only
before QC receipt begins. Company-owned goods refused before delivery use their existing stock
identity and refusal QC Case, not this old-return label.

The label is marked **Pending QC — not available stock** and identifies the Return Case, Item row,
quantity, UOM, Batch and expiry. Its QR uses a separate `CFG:RETURN-CUSTODY:` namespace. Scan it in
Kanban Logistics or the Customer Return QC page to open the live Case. It is neither a Stock Tag,
stock receipt nor Credit Note. QC and the existing controlled stock/accounting workflows remain
necessary. Never place this label over an active Stock Tag in a way that loses the original trace.
Reprint an existing label rather than creating another allocation for the same bundle. A reprint
of an already confirmed label requires a reason.

Existing Stock Tag presets show effective expiry (earliest tag/Batch/certified printed date),
certificate set, active ERP serials and captured source printed serial boundaries when available.
Source printed ranges are provenance, not invented individual-unit assignments for a split tag.

## Recovery and format limits

- New invoices, labels, print jobs and print confirmations use the existing durable driver action
  identity. After a lost response, use **Retry original request** or **Read back result**. Do not
  create a new request to bypass uncertainty. Another operator cannot retry your retained request.
- **Unfinished print jobs** can be resumed. If the source document or format changes, close the
  unfinished job with a reason and prepare a new reviewed print. Closing a job preserves audit
  history and does not cancel or change the source document. A changed raster manifest also
  cannot silently replace previously prepared segments. Printer dimensions are frozen per job; changed device defaults apply to new jobs.
- Direct print requires HTTPS, Web Crypto, browser storage and Web Locks. One printer panel owns
  the device handoff lock at a time. Pairing stays in memory across this operator’s stop panels; it is forgotten when leaving Driver Route, changing operator/Company or explicitly forgetting the key.
- Native format HTML and raster remain transient. The database retains source/version hashes and
  operator confirmation metadata, not images, signing keys, print URIs or durable presigned URLs.
- Direct rendering supports static HTML/CSS and same-origin/private/data image assets. An external
  QR/letterhead image is rejected rather than silently omitted. Use normal ERPNext print or adapt
  the format asset. Complex CSS, script-rendered widgets and very large documents may need normal
  print. Always inspect the raster, especially an e-Invoice QR. A signed bridge handoff is not proof
  that the companion app version, Bluetooth model, cutter, fonts or printed QR are accepted.
- Keep format values stable during a job. For an optional prepared timestamp in your format use
  `doc.flags.cfg_mobile_print_on or frappe.utils.now_datetime()`; source posting dates/times are
  preferable to a fresh current timestamp. Dynamic content can invalidate a resumed render.
- The Trip stock list shows **current whole-lorry custody**, including other commitments and QC
  holds. ERP and tag quantities describe the same material; do not add them. It does not authorize
  selling every printed quantity. Existing delivery allocation/FEFO/QC controls still decide usage. Collected old customer goods
are documented by their custody labels/Return Notes; they remain outside ERP stock until QC disposition.

At departure, **Start Route** fills the Trip's **Lorry Warehouse** from the verified loading
lorry. For older started Trips with a blank header, the stock-list rows and supplied format
heading use the frozen departure lorry. Custom formats may use `trip_vehicle_warehouse(doc)`
for the same heading. An office planner can reload the Trip and press **Sync Lorry Assignment**
to restore its stored header, including for custom formats that still read
`doc.vehicle_warehouse`. This does not change stock or the frozen route. Conflicting lorries,
changed source scope and missing permissions require reconciliation; no substitute lorry is guessed.

## Assigned Trip driver name and Employee ID

The supplied 80mm Trip stock format shows the assigned **Name (Employee ID)**. Trip forms,
driver/assistant labels, route views and Supervisor/GPS views retain the Employee IDs beside
names. Delivery Note, Invoice, Credit Note, Return Note and custody-label formats keep their
existing content. For a cloned Trip stock format use `{{ trip_driver_display(doc) | e }}`.

## Scanner and tablet controls

The panel has an Enter/Tab scanner input and a camera button. Scan an existing document/tag code
or use numbered fields (`CFG:SELECT:1`–`10`) and exact values. Document and return-row choices have
visible numbers. For required ERP tables the existing `DELIVERY_ADD_ROW`, `DELIVERY_NEXT_ROW`,
`DELIVERY_PREVIOUS_ROW` and `DELIVERY_INPUTS` commands remain supported.

Printable labels are in **Kanban Operator → Scanner Command Labels → Driver Mobile Printing**:

| Command | Action |
|---|---|
| `CFG:CMD:MOBILE_PRINT` | Open the selected stop’s document panel |
| `CFG:CMD:PRINT_SETUP` | Device printer setup |
| `CFG:CMD:PRINT_NATIVE` | Open native ERPNext print |
| `CFG:CMD:PRINT_SEND` | Prepare the direct job / current segment (never automatically resend) |
| `CFG:CMD:PRINT_OPEN` | Explicitly hand the freshly prepared segment to Label Bridge |
| `CFG:CMD:PRINT_CONFIRM` | Operator confirms physical output of the current segment |
| `CFG:CMD:PRINT_UNKNOWN` | Record an uncertain physical result |
| `CFG:CMD:PRINT_PAIR` / `PRINT_FORGET` | Pair the entered key / erase it from memory |
| `CFG:CMD:CREATE_DRIVER_INVOICE` | Open the separate Invoice action |
| `CFG:CMD:CREATE_RETURN_LABEL` | Open the custody-label action |
| `CFG:CMD:MOBILE_PRINT_BACK` | Return to document choices |
| `CFG:CMD:CONFIRM` / `CANCEL` / `REFRESH` | Confirm current action / close safely / read back pending result |

See [native/device acceptance](TEST_DRIVER_MOBILE_PRINTING.md) before accepting this phase.

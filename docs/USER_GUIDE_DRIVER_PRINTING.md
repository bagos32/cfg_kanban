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
   Both key fields are non-login text controls, visually masked in Chrome, with autocomplete,
   capitalization and spelling suggestions disabled and fresh non-credential input names.
   Paste/type the current app Browser key or select the key field with the numbered scanner
   command and scan it, then choose **Pair Key**. Values filled without observed deliberate
   entry, or replaced after entry, are rejected and cleared before import. Browser/password-manager
   hints are best effort; this check also protects against unnoticed fills. Keys are excluded
   from generic form/scanner snapshots and cleared after each pairing attempt, Forget Key and
   panel redraw/closure. A syntactically valid key still must match the app's actual Browser key.
6. Choose **Prepare Print**. It saves and previews the job, then prepares the first part when the
   key is paired. On first use, **Pair Key** also prepares that part. There is no separate normal
   "prepare segment" click. Inspect the image and click **Print Recipient copy · Open Label Bridge**
   (or the displayed copy/part button). It opens the companion only on this fresh click/scan.
7. Check the paper and choose **Recipient copy printed** / **Confirm This Part Printed**. CFG
   prepares the next part or office copy, but waits for its own Print button. Tear off the complete
   recipient copy before clicking **Print Office copy · Open Label Bridge**. Confirm the office
   copy after checking it. **Complete copies** is the total number for this job; every Bridge
   payload requests one physical copy. Select 1 for a single copy. No second copy prints by itself.
8. If uncertain, select **Outcome Unknown**. An explicit retry needs a reason. Confirmed parts
   cannot be resent within the same job. Lost responses keep the original request; after readback
   or reopening, the recovery path may require explicit preparation instead of the normal shortcut.
   A deliberate complete reprint is a new reviewed job.

Long receipts are split to the existing bridge’s **4096-row / 48,000-character URI limits**.
Every segment needs a separate handoff and paper confirmation. Multiple copies are collated as
all segments of copy 1, then all segments of copy 2. No receipt tail is silently truncated.
The companion protocol has no physical-print acknowledgement or automatic cut/receipt commands.

Label Bridge **0.3.0** supports the signed links used here. The supplied 0.3.0 APK and its source
were inspected; the owner reported successful basic handoff after updating from 0.2.1. This does
not establish signature, multi-copy or device acceptance. Version 0.3.0 opens a visible Android
Activity. It has no silent background-print path or automatic return after sending; those require
a separate companion-app change. Kanban never interprets a Bluetooth write as paper confirmation.

## Signed Delivery Note copies

For future deliveries, set the site's **CFG Kanban Customer Scan Point → Proof Policy** to
**Required** and enable **Require Signature**. Complete the existing proof-capture/submission
workflow before printing. Existing Delivery Sessions retain their saved proof policy; printing
does not add a retrospective acknowledgement to an old session that recorded no proof.

In **CFG Kanban Mobile Print Profile**, **Delivery Note copies** defaults to 2. It supplies the
initial total; the driver can choose 1–5 for an individual job. **Require signature for direct DN
printing** defaults to enabled. Capture and submit the customer proof before preparing either
copy. The signature requirement is checked again on preview/resume and segment recording.
Both copies use the same frozen render; changing a proof or format requires closing the old job
with a reason and reviewing a new one.

Select **CFG Delivery Note 80mm** as the profile's DN Print Format. Its acknowledgement footer
prints recipient name, capture time, proof number and available submitted signature images below
the document terms. Missing recorded evidence fails visibly. A draft, return DN or document without
submitted proof does not invent an acknowledgement. Native ERPNext print remains available under
its own permissions/settings; turning off the direct-signature policy permits unsigned direct prints.

Custom DN formats stay editable in ERPNext. Include the footer when duplicating the preset. The
Jinja helper below supplies only authorized metadata and stable image references; an enabled
signature policy rejects a direct format that omits its images:

```jinja
{% set acknowledgement = delivery_note_acknowledgement(doc) %}
{% if acknowledgement %}
<p>{{ acknowledgement.recipient_name | e }} · {{ acknowledgement.captured_on | e }}</p>
{% for image in acknowledgement.signatures %}
<img src="{{ image.src | e }}" alt="Recipient signature" style="max-width:100%;max-height:35mm">
{% endfor %}
{% endif %}
```

Signature references are scoped to the submitted DN, Company, Customer, exact closed Delivery
Session/proof and available signature media version, with native read/print permissions rechecked
at image access. The image endpoint redirects to an ephemeral private S3 view; it does not proxy
or store bytes. The browser downloads PNG/JPEG/WebP images up to 512 KB into transient data images
for rasterization. No presigned URL is stored in jobs or embedded as a durable format value.
The existing S3 CORS policy must permit GET from the exact ERPNext origin. Other external format
images remain rejected. Native ERPNext HTML/PDF printing follows the same authorized image reference;
verify cookies, S3 access and PDF output on the actual site.

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

- **Prepare Print** first saves the print job and renders its 80mm preview. It does not
  open Label Bridge. The panel shows checking, preparation, rendering and preview-ready messages.
  If preview generation fails, it shows the job number and actual error, retains the recorded
  preparation and permits reasoned closure. Rendering has a 60-second elapsed-time limit while
  the browser is running; a failed preview never automatically creates another job or sends it.
  Use **Documents** for native printing or to resume/review the original job. Button actions are
  captured before entering the asynchronous queue, so later changes to the browser click event
  cannot silently discard the selected action.

- New invoices, labels, print jobs and print confirmations use the existing durable driver action
  identity. After a lost response, use **Retry original request** or **Read back result**. Do not
  create a new request to bypass uncertainty. Another operator cannot retry your retained request.
- **Unfinished print jobs** can be resumed. If the source document or format changes, close the
  unfinished job with a reason and prepare a new reviewed print. Closing a job preserves audit
  history and does not cancel or change the source document. A changed raster manifest also
  cannot silently replace previously prepared segments. Printer dimensions are frozen per job; changed device defaults apply to new jobs.
- If preparing a print reports an unfinished job, return to **Documents / Print / Invoice**.
  **Unfinished print jobs** also lists jobs for the displayed documents that were prepared by
  another operator, at another stop, or on another Trip. It shows the original job, operator,
  Trip and stop. **Documents** refreshes this list after office recovery.
- For your own job on the current Trip (including another stop), choose **Resume / Review**. Check the physical paper
  before confirming any segment. If the preview cannot open because the source or format changed,
  enter a reason and choose **Close Unfinished Job**; this remains available without a preview.
- For another operator or Trip, use **Open Print Job for Office Recovery**. An office user
  with a Trip-editing role (Stock Manager, Sales Manager, System Manager or CFG Kanban System
  Maintenance), read access to the job/Company and read/write access to the original Trip can
  open **CFG Kanban Mobile Print Job**, review it and choose **Close Unfinished Job** with a reason.
  This works after Trip reassignment or closure. An ordinary driver cannot resume another
  operator's job. If native permissions hide the job, the error identifies its job number for
  the authorized office user to find.
- Closing records **Closed By**, **Closed On**, the reason and an audit event. Original operator,
  source/version hashes and segment confirmations remain intact. It does not confirm printing,
  cancel the DN/Invoice, change stock, or automatically send another print. A changed job must
  be reloaded and reviewed before office closure; retrying an already closed office request
  preserves the first closure. Prepare a new print only after reviewing any physical output.
- Direct print requires HTTPS, Web Crypto, browser storage and Web Locks. One printer panel owns
  the device handoff lock at a time. Pairing stays in memory across this operator’s stop panels; it is forgotten when leaving Driver Route, changing operator/Company or explicitly forgetting the key.
- Native format HTML and raster remain transient. The database retains source/version hashes and
  operator confirmation metadata, not images, signing keys, print URIs or durable presigned URLs.
- Direct rendering supports static HTML/CSS and same-origin/private/data image assets, plus the
  exact authorized delivery-signature endpoint described above. An arbitrary external
  QR/letterhead image is rejected rather than silently omitted. Use normal ERPNext print or adapt
  the format asset. Complex CSS, script-rendered widgets and very large documents may need normal
  print. Always inspect the raster, especially an e-Invoice QR. A signed bridge handoff is not proof
  that the companion app version, Bluetooth model, cutter, fonts or printed QR are accepted.
- The sandbox CSP explicitly permits the current ERP site origin for stylesheets, images and
  fonts, as well as the existing inline/data assets. This avoids Firefox's blocked same-site
  resources in `srcdoc`/renderer clones, including native print CSS and BMP letterheads. Scripts,
  nested frames, connections and unrelated external origins remain blocked. No global Firefox
  privacy setting or server CSP is disabled. After deployment, reload Firefox without cache and
  resume the existing unfinished job; if a prepared raster manifest changes, use reasoned closure
  and a reviewed new job rather than bypassing the duplicate-print safeguards.
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

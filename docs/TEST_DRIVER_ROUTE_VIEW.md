# Driver Route view — native acceptance

Prepared 21 November 2026. Base commit `91ab7da`; local development is uncommitted.
Every native case below is **Not run**. Offline results do not establish site acceptance.

## Setup

Use an isolated development site with two Companies, native restricted Stock Users, two driver
Employees/operator profiles, one Supervisor, Company lorry Warehouses, saved office Delivery Trips,
known-customer Vehicle Dispatch Plans, tagged and untagged allocations, E3 loading records,
Delivery Sessions/Notes and approved/Draft Route Sheets. Include a multi-day trip, repeated Sites,
multiple SOs at one stop, Visit Only and non-stock rows. Preserve all accounting and stock evidence.

## Cases

| Case | Expected result | Native result |
|---|---|---|
| Migration/build/Page launch | Workspace, Logistics button and saved Trip button open the separate Driver Route page; normal office planner remains intact. Refresh/deep link works after navigation away/back. | Not run |
| Terminal and native access | Kanban Terminal alone does not expose protected records. Proper Trip/source read and Company permissions are required, including direct API access. Wrong Company/source permissions fail without partial quantities. | Not run |
| Driver assignment | Valid Customer Delivery operator sees only its Employee-assigned trips; unassigned/other-driver trips and guessed URLs are denied. Reassignment removes old-driver details on refresh. | Not run |
| Supervisor | Both Supervisor/Development Proxy authority and View All are required to browse others; native Company/document restrictions still apply. | Not run |
| List and dates | Draft/Planned trips, Company, departure/return dates, explicit selection, paging and optional closed history are correct. Multi-day trips remain visible across midnight; inactive template does not erase trip history. | Not run |
| Entry | Existing login reused. Credential/PIN and camera login work. Enter/Tab scanner suffixes work; blank Tab and modified keys retain navigation. A Trip ID before login is not submitted as an operator credential. | Not run |
| Camera and lifecycle | Camera decode accepted once, cancel/error restores focus, unavailable camera explains fallback, late scans/results after cancel/hide/operator change are ignored. Page timers/camera stop off-page. | Not run |
| Planned versus actual | Planned SO/customer PO/Item/UOM shown even before preparation. No source allocation means no loaded tag. Partial preparation stays Partially loaded/awaiting loading, with unprepared balance shown. | Not run |
| Posted loading | Tagged and untagged allocation amounts appear loaded only with submitted same-Company loading Stock Entry and matching lorry Manifest. Draft/cancelled/missing entry does not count as loaded. Conflicting source references require review. | Not run |
| Posted delivery | Partial submitted non-return DN reduces the exact allocation remainder. Draft/cancelled/return DN does not count. No mixed-UOM grand total or unrelated tag deduction. | Not run |
| Proof and completion | Delivered/Invoiced Session awaiting proof remains current. Closed completed full delivery advances next stop; short closure is Closed Incomplete. Pending ERP/review feedback does not falsely complete. | Not run |
| Approved order | One complete approved mapped Sheet overrides office display order while retaining office numbers. Group adjacent source Plans for one stop only when unambiguous. Original records remain unchanged. | Not run |
| Missing/conflicting mapping | Draft/unapproved/multiple Sheets, outside stops, partial Plan coverage, interleaved/repeated ambiguous rows and visit-only gaps show Office plan + review warning. No unrelated customer data or authorization change. | Not run |
| Current work | Active delivery/proof task remains current even after approved reorder. Multiple active Sessions or conflicting lorries give no guessed next stop. | Not run |
| Visit Only/history | Customer/address/instructions visible. No check-in, fake stock or completion created. Closed/Cancelled planning shows history without next-stop instruction or implied full delivery. | Not run |
| Existing delivery handoff | Exact active accessible Session opens in established Logistics view without another scan, Session creation, allocation or posting. Other-operator ownership still enforced. Test initial and already-loaded Logistics pages. | Not run |
| Session activity | Manual interaction renews native activity; 15-second background refresh does not indefinitely prevent timeout. Expiry clears details and allows login again. | Not run |
| Races/offline | Two tabs, rapid trip changes, operator changes during login/read, repeated scanner login, late responses, network loss and blocked storage never show old operator/stop data as fresh or duplicate a stock mutation. | Not run |
| Escaping/tablet | Customer names/instructions/PO/tag text escaped. Desktop and tablet layouts retain quantities, large buttons and camera access without using a planning popup. | Not run |
| Regression | E3 loads, E4A/B/C fulfilment, Route Sheet order/QR approvals, native proof and E5 settlement remain under existing controls. Reading trip changes no office/stock/delivery record. | Not run |

## Local verification

New tests exercise actual service/controller/rendering code with document, DB, RPC and DOM doubles.
The suite covers assigned-driver/native-source permissions, posted quantities, order mapping,
proof, history, operator/session races, exact Logistics handoff, camera/scanner focus and stale data.
Final local results:

- 269 Python tests passed: new driver visibility (24), office planning, Route Sheets, lorry
  overview, schema and existing E4A/B/C fulfilment regressions.
- 26 new driver controller/rendering/scanner/camera-adapter checks passed under Node.
- Existing office form (14), Route Sheet (16), lorry/floor (9), E4A (18), E4B (35) and E4C (20)
  UI checks passed.
- Changed Python/JSON sources parsed; JavaScript syntax and `git diff --check` passed.

Native Frappe Desk, migrations, MariaDB, hardware and live posting have not been exercised by these
tests. All native cases above remain **Not run**.

## Acceptance record

- Deployed commit: **Not recorded**
- Site/owner/date: **Not recorded**
- Native outcomes/evidence: **Not run**
- Accepted exceptions: **Not recorded**

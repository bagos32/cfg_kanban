# General Service Point Location Card scan acceptance

The Service Panel previously recognized Task Schedule Service Point QRs and reusable Action
Cards but did not route General Service Point Location Cards. Those Cards fell through to
operator credential identification. This correction opens existing task status for the
Card's Location Reference and Company, without generating or starting tasks. Matching responsibilities
form the default queue; explicit scans can additionally show outside-role references.

## Setup

1. Create or select a CFG Kanban Card with Card Type **Location Card** and Location Purpose
   **General Service Point**. Enable **Active**, leave **Blocked** off and set **Location Reference**.
2. Give the relevant CFG Kanban Task Schedules/Tasks that exact **Location**. Tasks must already
   have been generated; a Location Card does not generate an occurrence.
3. Check the Card Company matches the task Company when the Card has a Company.
4. Check the operator's Responsible Roles, Allowed Workstations, assignment and task action permissions.
5. Print **Print Kanban → Print General Service Location Card** and use **Kanban Service Tasks**.

## Live acceptance (not run)

| Check | Expected result | Recorded result |
| --- | --- | --- |
| Scan existing printed Location QR after operator identification | Location shown; only eligible open matching tasks; no operator credential error | Not run |
| Scan with keyboard-wedge and tablet camera | Both enter the same location view | Not run |
| Scan before operator identification | Ask for operator identification and rescan; no Task/Card data disclosed | Not run |
| No matching tasks | Clear empty-location message; no task creation, Start or Action Run | Not run |
| Several tasks/schedules share the location | Eligible tasks listed independently; no automatic task chosen or started | Not run |
| Restricted responsibility, Workstation or another operator's assignment | Default queue hides unassigned non-matching roles; scanned references are separate and cannot execute | Not run |
| Scoped Supervisor assistance | Started eligible operator tasks visible; assist and action gates retained | Not run |
| Another Company uses the same location text | Excluded when the Card Company is set | Not run |
| Refresh and 15-second live update | Location filter remains; live refresh preserves input focus | Not run |
| Edit operator responsibilities while panel is open | Live queue refreshes without waiting for a Task modification; access restrictions take effect | Not run |
| Show All | Return to full eligible task list; location banner removed | Not run |
| Exact Task, Task Card, Asset Card or Task Schedule QR | Open exact occurrence/schedule/asset scope; outside-role results are view only | Not run |
| Empty Responsible Roles; Job Codes populated | Shared/directly assigned work only in default queue; Job Codes do not bypass responsibility | Not run |
| Supervisor assistance / View All Service Tasks | Existing scoped assistance and explicit broader authority retained | Not run |
| Direct API action/evidence attempt on a scanned outside-role reference | Rejected; no task mutation, evidence or Action Run | Not run |
| Operator switch | Previous scan context cleared; new identity uses its own responsibility queue | Not run |
| Inactive/blocked Card, missing reference, logistics Location Purpose | Specific server rejection; no credential fallback | Not run |
| Ordinary credential and reusable Action Card scans | Existing switch and Action Card paths continue to work | Not run |
| Unstarted Due/Assigned/Overdue task in location view | Start visible; no Progress/Complete; direct premature completion rejected | Not run |

## Evidence

Offline tests use actual scan normalization, API/access/filtering and Service Panel functions
with DB/DOM/RPC substitutes. Native Frappe permission/transaction behavior, camera usability and
kiosk keyboard-scanner focus must be checked on the deployed development site.

- Deployed revision: pending
- Operator/device/browser: pending
- Native result and evidence: pending

Offline checkpoint, 20 November 2026 (uncommitted changes above `20c2abc`):
142 Python lifecycle/access/scan/DocType Action/schema checks and 45 executable Service Panel UI
checks passed. These include strict empty-role discovery, view-only scan references, direct action
and evidence rejection, scope retention, camera routing and Start-before-Complete regressions.
All native site/device/scanner acceptance rows above remain **Not run**.

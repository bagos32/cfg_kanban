# Delivery Trip runtime order and approval — acceptance

Prepared 22 November 2026 above `dba2794`. Native-site result: **Not run**. No deployment or
production acceptance is asserted by the offline tests. Record deployed Git revision and results
below after the owner's manual migration/build.

Use a Company-specific loaded Trip with at least four customer stops, known-customer SO Plans
(including tagged and untagged stock), a shared optional-sale Plan, and an information-only visit.
Preset a lead plus an assistant. Configure one Flexible Order route and one Planned Order route.
Prepare a separate approved strict native Route Sheet with required Site QR. Permit Supervisor
override on captured Dispatch Profiles for the allowed case; retain a disallowed Profile case.

| Check | Expected result | Native result |
| --- | --- | --- |
| Flexible driver drag/drop, tablet Up/Down and scanner moves | Same pending order; main next-customer display agrees | Not run |
| More than ten remaining customers | Numbered pages select the correct customer after movement | Not run |
| Completed/customer-in-progress edits | Completed stops stay fixed; active DN/proof prevents changes/approval | Not run |
| Enforced request | Reason required; pending proposal does not change authorized order | Not run |
| One-next approval | Requested customer next, then remaining prior order | Not run |
| Full-order approval | Complete proposed remaining order becomes authoritative | Not run |
| Supervisor review page | Both scopes visible during approval; timer pauses; native identity/access enforced | Not run |
| Profile disallows override | Target/full affected scope is blocked, with no order mutation | Not run |
| Known-customer native delivery | Exact saved tags/untagged sources; one DN; correct SO; proof before completion | Not run |
| Optional-sale native delivery | Approved out-of-order customer can buy eligible stock; next resumes correctly | Not run |
| Mandatory Site QR | Missing/wrong QR rejected despite sequence approval | Not run |
| Direct native/API entry | Another customer, driver, Company, completed stop or stale source cannot bypass order | Not run |
| Source/Sheet change | No approval or delivery using a changed frozen source or Sheet revision | Not run |
| Request cancellation/rejection | Only requester/lead cancels; Supervisor rejects; old order remains; history retained | Not run |
| Progress during pending request | Old proposal cannot approve; reject or supersede with a current proposal | Not run |
| Trip closed with pending request | Supervisor can reject without requiring reopened/loaded stock | Not run |
| Lost request/decision response, reload, two tabs and duplicate Confirm | Original identity retained/reconciled; one request/decision; no duplicate order/DN | Not run |
| Actual concurrent native start vs approval | Trip lock serializes; stale revision rejected; no deadlock or partial decision | Not run |
| Native rollback/error | Request/order/audit/receipt roll back together; no partial approval or stock mutation | Not run |
| Credential/session change, expiry, page hide and camera callback | Old screen cannot submit; safe scanner focus; no credential stored in action payload | Not run |
| E5 and loading records | Office itinerary, LIFO/load records and Sheet revision preserved; normal settlement required | Not run |
| Historical request and unknown outcome | Request list → Review in Supervisor Centre recovers original result | Not run |
| Pending navigation corrections | Dispatch Control displays its stock icon; Card breadcrumb reads CFG Kanban → CFG Kanban Card after direct open/refresh | Not run |

Offline checks exercise the actual services/controller paths with in-memory/native-service doubles.
They do not prove Frappe schema migration/indexes, MariaDB locking/rollback, native User Permissions,
real ERP posting or camera/tablet behavior. Browser tests here simulate DOM/RPC, not a deployed Desk.

Deployed revision: _pending_

Tester/date/evidence: _pending_

Accepted exceptions and deferred risks: _pending_

Offline development checkpoint: **595 Python tests passed** across the relevant route, dispatch,
return, stock-identity, schema and navigation suites; **107 JavaScript test entries passed**
across 11 UI suites. These results use dependency/DOM doubles and do not change any native result
in the table above. Post-apply focused checks also passed in the existing worktree.

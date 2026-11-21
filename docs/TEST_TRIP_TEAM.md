# Delivery Trip assistant-driver acceptance

Development prepared 21 November 2026 above the pending Trip-generation/shared-pool changes.
Native-site acceptance is **Not run**. Record the deployed revision, roles, Trip/Session/DN/proof
and audit evidence after owner-managed migration and asset build.

## Setup

- Normal Delivery Trip with a lead Employee, at least two optional assistant Employees, two
  customer stops, Customer Order Plans, shared Open Route pool and one real lorry.
- Each person has an active Operator Profile and own login. Give Customer Delivery, the relevant
  Dispatch responsibility, action flags and native Company/Trip/source reads as appropriate.
  Collections still require Customer Return, and QC/release still need their existing authority.
- Test both office presets and an initially single-driver Trip. Include a native delivery
  Session started by the lead so an assistant can continue it.

| Native case | Expected | Result |
| --- | --- | --- |
| First Trip save with assistants | Parent/children save successfully; office assignment audit is written after the parent exists in the same transaction | Not run |
| Office presets | One lead plus multiple distinct active/qualified assistants on normal DocType form; assignment time/user/source retained | Not run |
| Invalid preset | Duplicate/blank/lead-as-assistant, inactive Employee/Profile or missing Customer Delivery rejects without partial rows or audit | Not run |
| Office edits | Before departure edits are authorized and audited; started table is read only and server rejects forged membership/audit/revision changes | Not run |
| My Trips | Lead and each assistant find the same assigned Trip; native User Permissions and pagination filter results; outsiders cannot open it | Not run |
| Add before loading | Lead can add an assistant to a Planned Trip before loading readiness; no departure, Session, stock or DN created | Not run |
| Add during route | Lead adds while In Progress; exact one child/audit and team/action revisions; itinerary/loading/route approval snapshot unchanged | Not run |
| Add authority | Assistant/outsider cannot add others; missing Start, wrong Trip/Company, inactive candidate and completed/closed Trip rejected | Not run |
| Independent login | Each signs in with own credential; assistant may Start Route, recording actual departure actor while retaining the lead assignment | Not run |
| Delivery continuation | Assistant continues the lead's exact active Session and submitted DN/proof flow; original creator preserved and current action/stop actor correct | Not run |
| Optional sale | Assistant allocates eligible shared/free tagged/untagged stock and completes native DN/proof on the same visit; one stock deduction and one DN | Not run |
| Customer return | Authorized assistant collects old goods through existing Return/QC pipeline; actual collector retained; no duplicate receipt or credit | Not run |
| No authority expansion | Membership does not grant Dispatch scope, Complete, Supervisor release/override, QC or ERP submit permissions | Not run |
| Exact source | Wrong Company/Site/address/lorry/Plan or unrelated Session cannot be accessed via membership | Not run |
| Concurrent operators | Real Trip/Session locks and current revision prevent duplicate begin/completion, stock/DN overconsumption and lost team assignments | Not run |
| Retry/lost response | Same assignment token/payload/actor returns original receipt; different details conflict; another assistant cannot replace an uncertain actor's action | Not run |
| Tablet/scanner | Employee Link, Employee-ID scan, camera, Confirm/Cancel, close/reopen and operator switching restore focus and ignore late callbacks | Not run |
| History/legacy | Single-driver Trips still work; finished Trip team and original action actors preserved; office/E5 closure remains separate | Not run |

## Offline evidence

The team suite exercises actual office validation, driver revision/receipt control, native Session
access and route stock/DN/ledger functions using in-memory Frappe/ERP/storage/DOM doubles. Existing
logistics regression suites remain separate from native migration, database, stock posting,
private media and tablet acceptance.

## Offline results

**442 Python tests passed**, including 21 assistant-team cases and the existing office,
Trip generation/shared pool, driver/refusal/collection, delivery, route, warehouse/pickup,
E3 and E5 suites. **98 Node test-runner cases passed**, including assistant selection/retry,
team visibility and office read-only controls. Changed source syntax/schema checks and
`git diff --check` passed. Tests use Frappe/ERP/database/browser doubles; all native-site
results above remain Not run. No migration, commit, push or deployment was performed.

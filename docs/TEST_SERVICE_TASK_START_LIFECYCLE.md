# Service Task Start-before-completion acceptance

Every normal Service Task must be started before progress or completion can be reported.
Supervisor Cancel / Bypass remains available for invalid or holiday occurrences, with authority
and a reason. Existing DocType Action and independent verification gates remain mandatory.

Use an eligible Operator, a scoped Supervisor and a Supervisor with View All Service Tasks.
Prepare separate Planned, Due, Assigned, unstarted Overdue, started In Progress, started Overdue,
and previously rejected Correction Required occurrences. Preserve Task IDs and the tested Git
revision with the results. Do not fabricate a start timestamp on a historical record.

| Check | Expected outcome | Site result |
| --- | --- | --- |
| Due without started_on | Start shown; Complete and Report Progress absent | Not run |
| Assigned without started_on | Start shown; Complete and Report Progress absent | Not run |
| Overdue without started_on | Start shown; Complete and Report Progress absent | Not run |
| Planned without started_on | Start shown; Complete and Report Progress absent | Not run |
| In Progress with started_on | Complete and Report Progress shown; Start absent | Not run |
| Overdue with started_on | Complete and Report Progress shown; Start absent | Not run |
| Correction Required with started_on | Correct and Resubmit shown; prior answers/notes retained | Not run |
| Correction Required without started_on | No Progress or correction completion; direct completion rejected | Not run |
| Direct API Complete, unstarted Due | Start the Service Task before completing it | Not run |
| Direct API Complete, unstarted Assigned | Same rejection | Not run |
| Direct API Complete, unstarted Overdue | Same rejection | Not run |
| Start, then report/complete | Immediate refresh moves task to Active Work; normal completion succeeds | Not run |
| Supervisor completion on behalf | Allowed after Start only; original assignment and acting Employee preserved | Not run |
| Premature completion with a bound Action Profile | No Task mutation, execution/checklist evidence, Action Run, or completion audit event | Not run |
| Stale completion dialog receives premature-completion rejection | Dialog closes safely; rejection shown; scanner focus returns after any server message closes | Not run |
| Scanner-driven attempted Complete before Start | Same rejection; Service Panel remains ready for next Task/credential scan | Not run |
| Authorized Cancel / Bypass before Start | Allowed with reason; original occurrence/audit retained | Not run |
| Missing On Task Start Action / required unposted document | Existing completion/document gate remains closed | Not run |
| Completion requiring verification | Awaiting Verification; independent review and correction/resubmission preserved | Not run |

Offline checks execute the real service, access, Action binding, rendering and dialog functions
with document, permission, RPC and DOM substitutes. They do not establish native transaction
rollback, live browser focus or full-screen keyboard-scanner acceptance. Service scanning uses
its existing Task/Service Point identity flow; this correction adds no new command labels.

- Tested site/revision: pending
- Browser/device/scanner: pending
- Evidence references and accepted exceptions: pending

Offline checkpoint, 20 November 2026 (uncommitted working changes above `a44c0b0`):
69 Python lifecycle/access/DocType Action/live-refresh checks passed, including 17 new lifecycle
tests with pre-start status/trigger subcases; 23 executable Service Panel UI checks passed.
All native site/device/scanner acceptance rows above remain **Not run**.

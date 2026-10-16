# Gate 2B — Reusable DocType Action Card Acceptance Test

**Purpose:** prove that one reusable QR can create separate controlled occurrences only after an
explicit operator choice, while a re-scan resumes an existing occurrence without duplication.

**Safety boundary:** use only the app-owned Gate 1 pilot targets on a development site. Do not
allowlist an operational, stock, manufacturing, accounting, HR, permission, or system DocType for
this test.

## 1. Prerequisites

Confirm all of the following before testing:

- the site has been migrated and CFG Kanban assets rebuilt after deploying Gate 2B;
- the Gate 1 pilot configuration is installed and both pilot profiles are enabled and `Valid`;
- the terminal ERPNext User has the **Kanban Terminal** role and the pilot target permissions;
- the test Employee has an active **CFG Kanban Operator Profile** with **Can Start** enabled;
- for the Supervisor-history check, a second Operator Profile has **Kanban Role = Supervisor** and
  **Can Override = Yes**.

The supplied pilot profiles use **No Additional Verification**, Operator Input mappings and safe
Server Context. They are suitable for this non-production direct-card test. A direct Card must not
use a profile containing a **Service Task Field** mapping or **Require Service Task Verification**.

## 2. Create and print the reusable Card

Open **CFG Kanban Card → New** and enter:

| Field | Test value |
|---|---|
| Card Number | `ACTION-PILOT-DRAFT-01` |
| Card Type | `DocType Action Card` |
| DocType Action Profile | `CFG Gate 1 Pilot - Draft` |
| Active | Yes |

Save. Confirm:

- **Company Snapshot** follows the profile;
- **Kanban Qty** is `0`;
- **Current State** is `Available`;
- Kanban Master and Active Cycle are empty;
- **Print Kanban → Print DocType Action Card** produces the CR80 QR card.

## 3. Prove that scanning does not create anything

1. Open **CFG Kanban → Kanban Service Tasks**.
2. Identify the normal test operator.
3. Scan the Card QR, or enter `ACTION-PILOT-DRAFT-01` and select **Find Task / Card**.

Expected:

- a **DocType Action Card** dialog shows Card, profile, destination and posting policy;
- **Authorized in-progress actions** is empty on first use;
- **Start New Action** is available;
- no Action Run or pilot target has been created merely by scanning.

Close the dialog. Confirm the Action Run list is still unchanged.

## 4. Start, abandon and resume the same occurrence

1. Scan the Card again.
2. Select **Start New Action** once.
3. When the mapped form opens, note the **Action Run** number, but close the form without saving.
4. Scan the same Card again.

Expected:

- exactly one in-progress Run is listed as `Form In Progress`;
- it shows the initiating Employee;
- selecting **Resume** opens that exact same Action Run number;
- no second Run and no destination document is created.

Enter this sample data:

| Field | Value |
|---|---|
| Summary | `Gate 2 reusable card draft occurrence 1` |
| Outcome | `Accepted` |
| Notes | `Created only after explicit Start New Action` |
| Observation / Check Item | `Reusable card selection` |
| Observation / Measured Value | `1` |
| Observation / Accepted | Yes |
| Observation / Remarks | `Resume reused the original Run` |

Select **Save Document**.

Expected:

- Action Run becomes `Draft Created`;
- exactly one **CFG Action Pilot Draft** is linked;
- target `docstatus` is `0`;
- the target contains the entered parent and child values;
- the Card remains `Available`, quantity `0`, with no Signal or Cycle.

## 5. Prove one Card can create a second independent occurrence

1. Scan the same Card again as the same operator.
2. The completed Save-Draft occurrence must not appear as in-progress.
3. Select **Start New Action**.
4. Confirm the new mapped form has a different Action Run number.
5. Save with Summary `Gate 2 reusable card draft occurrence 2` and one observation.

Expected: two Action Runs and two different pilot Draft targets exist. Neither replaces or edits
the other.

## 6. Prove Employee isolation and Supervisor history

1. Start a third occurrence as Operator A, then close its form before saving.
2. Switch to Operator B, who is not a Supervisor, and scan the Card.

Expected: Operator B cannot see or resume Operator A's in-progress Run. Knowing the Run name does
not authorize it.

3. Switch to the Supervisor profile and scan the Card.

Expected:

- the Supervisor can see Operator A's in-progress Run and select **Resume**;
- **Supervisor history** lists recent completed occurrences;
- a linked target button opens the exact pilot target when the terminal User has Desk read access.

## 7. Submit-policy variant

Create a second Card using:

| Field | Test value |
|---|---|
| Card Number | `ACTION-PILOT-SUBMIT-01` |
| Card Type | `DocType Action Card` |
| DocType Action Profile | `CFG Gate 1 Pilot - Submit` |

Scan it, explicitly select **Start New Action**, enter sample data and select **Submit Document**.

Expected:

- one **CFG Action Pilot Submission** is linked and submitted;
- Action Run is `Submitted` and target `docstatus` is `1`;
- re-scanning does not offer the submitted Run as resumable;
- a new occurrence is created only after selecting **Start New Action** again.

## 8. Negative controls

Verify each case fails without a target write:

- inactive Card;
- blocked Card;
- disabled or no-longer-Valid profile;
- profile with **Require Service Task Verification**;
- profile containing a **Service Task Field** mapping;
- operator without **Can Start**;
- terminal User without normal Create/Write/Submit permission on the pilot target;
- attempting to resume another Employee's Run without Supervisor Override.

## 9. Acceptance record

Record the following for handover:

- deployed Git commit;
- Card names and printed QR test result;
- Run and target names for occurrences 1 and 2;
- proof that the abandoned form resumed the same Run;
- proof that scan alone created nothing;
- Employee-isolation and Supervisor-history results;
- any browser/device used for USB and camera scanning.

Gate 2B passes only when the reusable Card remains outside production state, explicit new intent
creates separate occurrences, and every resume/retry preserves one Run and one target.

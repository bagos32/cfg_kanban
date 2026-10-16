# Gate 2C System Test — Direct DocType Action Run Media

## Purpose

Prove that a reusable **DocType Action Card** can capture private evidence for one business
occurrence without attaching those files to the reusable Card or exposing them to the next
occurrence. This test starts only after the Gate 2B direct-card form test has passed.

## Preconditions

- The deployment containing Gate 2C is migrated, assets are built, and cache is cleared.
- **CFG Kanban Settings → Private Media Storage** is enabled and the S3 connection already works.
- A working direct **DocType Action Card** and Valid Action Profile from Gate 2B exist.
- The shared terminal User has the required target DocType permission.
- An active Operator Profile can identify in **Kanban Service Tasks**.
- A Manufacturing Manager or System Manager is available for the Desk gallery check.

Use small test files only:

- one new camera photo;
- two existing files selected together, for example one JPG and one PDF;
- one harmless file that will be removed before posting.

## Test 1 — Start a clean occurrence

1. Open **CFG Kanban → Kanban Service Tasks** and identify the test Operator.
2. Scan the direct DocType Action Card.
3. Select **Start New Action**.
4. Record the displayed **Action Run** number.
5. Confirm the section **Action Run Private Evidence** is present and initially says no evidence is
   attached.

Expected result: scanning identifies the reusable Card, but evidence is created only after the new
Action Run exists. The reusable Card remains `Available` and has no Cycle.

## Test 2 — Timestamped camera capture

1. Select **Take Timestamped Photo**.
2. Permit camera and location access.
3. Take one photograph and wait for the green upload confirmation.
4. Open the photograph from **Open Evidence**.

Expected result:

- the image visibly contains server date/time, the Action ID, GPS coordinates and accuracy;
- the original opens through a short-lived private link;
- the evidence row identifies the file, capture time and Employee;
- the browser does not expose or save a permanent S3 URL in the Action Run.

## Test 3 — Multiple unchanged files

1. Select **Upload Photo / PDF / File**.
2. Select two files in the same picker action.
3. Wait until both complete and the verified list refreshes.
4. Open each file.

Expected result: both files appear as separate evidence records. Existing uploaded files are not
visibly stamped or altered. Camera stamping applies only to a new controlled camera photo.

## Test 4 — Correct an accidental attachment

1. Upload the harmless file intended for removal.
2. Select **Remove** on that row and confirm.
3. Close the mapped form without posting.
4. Scan the same Card, select **Resume** for the same Action Run, and reopen the form.

Expected result: the removed file does not return, while the remaining files are still visible.
The removed registry entry is archived for audit rather than physically erased by the operator.

## Test 5 — Post and freeze evidence

1. Complete all required mapped form fields.
2. Select **Save Document** or **Submit Document**, according to the Action Profile.
3. Open the resulting **CFG Kanban DocType Action Run** in Desk.
4. Check:
   - **Evidence Reference Count** equals the remaining verified files;
   - **Evidence Snapshot On** is populated;
   - **Stable CFG Kanban Media References** contains media IDs and safe metadata, but no S3 object
     key and no signed URL;
   - the **Direct Action Run Media Gallery** shows the same files and opens their originals.

Expected result: the target is posted once, evidence is frozen on that exact Run, and the upload and
remove controls are no longer offered when the completed Run is viewed/resumed.

## Test 6 — No cross-occurrence leakage

1. Scan the same reusable Card again.
2. Select **Start New Action**, not Resume.
3. Record the second Action Run number.
4. Inspect **Action Run Private Evidence**.

Expected result: the second Run starts with an empty evidence area. No file from the first Run is
shown or inherited. The two Runs may link to separate destination documents, while the physical
Card identity remains unchanged.

## Test 7 — Authorization and source boundary

1. Identify as a different ordinary Operator and try to resume the first Operator's open Run.
2. Verify an authorized Supervisor can review the Run according to normal Action Run scope.
3. Open a Service Task-driven Action and confirm its evidence continues to come from the exact
   **CFG Kanban Task**, not from the direct Action Run upload area.

Expected result: an unrelated Operator is rejected; authorized Supervisor access works; Task-owned
and direct-Run-owned evidence remain separate.

## Test 8 — Pending-upload posting guard

This is a controlled negative test. Start an upload and interrupt the browser/network before its
confirmation call completes, leaving the media registry entry `pending`. Then try to post the mapped
document.

Expected result: posting is refused with an explanation that an Action Run evidence upload is still
pending. After supervised cleanup/retry, posting may continue. The system must never freeze a
partially uploaded object as valid evidence.

## Acceptance checklist

- [ ] One Run accepts multiple evidence files.
- [ ] Controlled camera photo has visible server time and GPS.
- [ ] Existing uploaded files remain unchanged.
- [ ] Accidental evidence can be archived before posting.
- [ ] Closing and resuming the same Run retains its evidence.
- [ ] Posting freezes only verified `Available` evidence.
- [ ] Pending evidence blocks posting.
- [ ] Completed Run evidence cannot be added to or removed.
- [ ] A new Run from the same Card starts empty.
- [ ] Supervisor Desk gallery opens authorized originals.
- [ ] No S3 binary or presigned URL is persisted in the Action Run.


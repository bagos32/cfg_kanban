# Package D1 — Customer Delivery Proof System Test

This procedure tests only the implemented D1 proof and closure package. Complete the C2B customer
Delivery Note test first. The tester does not need development history.

## 1. Test prerequisites

- Private media storage is enabled and a Service Task photo upload has already passed.
- The test operator has Customer Delivery responsibility and Complete permission.
- A Customer Scan Point, Company-specific lorry Warehouse, active Stock Tag, Item Price, and customer
  delivery setup from C1-C2B exist.
- Use a mobile phone/tablet for camera, GPS, and signature tests.
- Prepare four Customer Scan Points, or repeat with one point after changing its policy before each
  new Delivery Session. A session preserves the policy snapshot taken when it starts.

| Case | Proof Policy | Flags |
|---|---|---|
| D1-A | Required | Recipient, Signature, Photo, GPS enabled |
| D1-B | Unattended Delivery Allowed | Photo, GPS, Unattended Reason enabled |
| D1-C | Optional | Any flags may remain enabled |
| D1-D | No Proof Required | Flags ignored |

## 2. Create the delivered starting condition

For each case:

1. Open **CFG Kanban → Logistics Operator Panel** and identify the operator.
2. Scan the exact Customer Site code, choose the correct Company lorry Warehouse, and start a session.
3. Start allocation scanning, scan an eligible Stock Tag, stop scanning, and confirm the allocation.
4. Create the Delivery Note and submit it in ERPNext when the site is configured to keep it Draft.
5. Refresh the Logistics panel.

Expected for D1-A, D1-B, and D1-C: the Delivery Session is **Delivered**, remains visible as active,
and shows **Capture / Close Delivery**. Expected for D1-D: it becomes **Closed** automatically with
Proof Disposition **No Proof Recorded** and no proof form is required.

## 3. Required attended proof

1. In D1-A select **Capture / Close Delivery**.
2. Try submitting without any input. Expected: recipient/signature/photo/GPS validation blocks it.
3. Enter the recipient name.
4. Select **Take Delivery Photo**, allow camera and location, and take one picture.
5. Expected: upload succeeds; the evidence list identifies it as `photo`.
6. Draw in the signature pad and select **Save Signature**.
7. Expected: a separate `signature` PNG appears.
8. Select **Submit Proof and Close** and allow location again if requested.

Expected: the session becomes **Closed**. Open **Customer Delivery Proofs** from the workspace. The
record is Submitted and shows recipient, attended disposition, operator, date/time, GPS, counts, and
image thumbnails. **Open Original** creates a working temporary link.

## 4. Unattended proof

1. In D1-B select **Capture / Close Delivery**, then disposition **Unattended**.
2. Submit without a reason/photo. Expected: the server rejects it.
3. Enter the unattended reason and take a timestamped delivery photo.
4. Submit and allow GPS.

Expected: recipient and signature are not required; the session closes with disposition Unattended.
The photograph visibly includes server capture time, proof number, GPS coordinates, and accuracy.

## 5. Optional no-proof closure

1. In D1-C select **Capture / Close Delivery**.
2. Choose **No Proof Recorded** and submit without media.

Expected: the server permits this only because the immutable policy is Optional. The proof record is
Submitted with zero evidence counts and the session closes as No Proof Recorded.

## 6. Evidence recovery and security tests

1. Start another Delivered session and open its Draft proof.
2. Upload an ordinary PDF using **Upload File**. Expected: it is `attachment`; it does not satisfy a
   required photo or signature.
3. Select **Remove** before submitting. Expected: it disappears, while the media registry keeps an
   archived audit record.
4. After proof submission, try removing evidence through the API/UI. Expected: removal is blocked.
5. Confirm the proof form stores no S3 URL. Expected: only media identifiers/metadata are persistent;
   view URLs are short-lived and generated on demand.
6. Try cancelling the submitted Delivery Note after proof submission. Expected: cancellation is
   blocked and instructs the user to use the controlled return workflow.

## 7. Idempotency and isolation

1. Repeat the final submit request with the same event token. Expected: the existing proof is returned
   and no second proof/Event is created.
2. Sign in as another ordinary delivery operator and attempt to open this session/proof. Expected:
   access is rejected unless supervisor/view-all authority applies.
3. Confirm only one Delivery Proof exists for the Delivery Session.

## 8. Pass criteria

D1 passes only when ERPNext submission remains the stock-delivery event, required proof cannot be
bypassed, allowed no-proof/unattended cases follow the policy snapshot, private media is securely
reviewable, the Delivery Session closes only after valid proof, and accepted proof cannot be erased
through Delivery Note cancellation.

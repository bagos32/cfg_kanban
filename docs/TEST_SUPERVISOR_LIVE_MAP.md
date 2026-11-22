# Supervisor Live Map and Trip GPS — native acceptance

Prepared 22 November 2026 above `02bd4b5`. Native result: **Not run**.
The owner must migrate/build manually, then record deployed SHA, tester/date and evidence.
Offline document/device/RPC doubles do not verify database concurrency, native ACL, browser/OS,
real GPS accuracy, third-party tiles, or foreground/background behavior.

Use two Company-scoped lorries, one active multi-day Trip, a finished Trip, assigned lead/assistant,
an unassigned driver, and a Kanban Supervisor with View All/Customer Delivery/Override plus native
Stock Manager. Configure Customer Site pins inside and outside KL, a repeated coordinate and a
missing pin. Use Flexible and enforced Trips with native DN/proof and both approval modes.
Use two supported HTTPS phone/tablet browsers with location enabled, and the Supervisor browser.

| Check | Expected | Native result |
| --- | --- | --- |
| Migration/build/launch | Controlled GPS DocType, native Page, workspace/Trip/Supervisor links load | Not run |
| Native maps KL defaults | New/empty Site Geolocation, Driver and Supervisor maps use 3.139,101.6869 zoom 13; configured tiles/attribution remain | Not run |
| Saved/selected focus | Existing non-KL saved pin and selected real Trip locations focus their actual coordinates; no fake KL lorry marker | Not run |
| No implicit tracking | Opening/refreshing pages does not request GPS before explicit Share | Not run |
| Driver/assistant source | Active assigned Employee with Start/Customer Delivery starts GPS for actual In Progress lorry; unassigned driver/Supervisor rejected | Not run |
| Native ACL | Wrong Company/Trip/lorry permissions reject/clear data; manager role alone or missing Supervisor/View All/Customer Delivery cannot view fleet | Not run |
| First fix / real movement | Correct lorry and source Employee; actual coordinates, receipt time, fix age and reported accuracy displayed; stationary devices still refresh | Not run |
| Freshness | Live only within 90 seconds; accuracy >100 m labelled Low Accuracy; paused/stale/expired/revoked/stopped/ended are distinct; last known grey | Not run |
| Pause/lock/background | Hiding attempts Paused; browser/OS freeze can prevent messages; retained last fix becomes stale. No promise of background tracking | Not run |
| Foreground resume | Validate original source, get fresh position; late prior callback/pause cannot overwrite newer source/fix | Not run |
| Source exclusivity | Simultaneous different-device Starts serialize; one source accepted; other source gets actionable rejection | Not run |
| Stop while Start uncertain | Stops local intent immediately; original Start retry/readback followed by Stop; no later location sampling | Not run |
| Lost Start reply / reload | Original payload/token retained; retry returns same source receipt; confirmed first rejection permits correction; ambiguous retry remains fenced | Not run |
| Stop retry | Stop prevents later fixes and records once; lost reply safely retried; old secret never stops replacement | Not run |
| Supervisor release/replacement | Override/reason/exact source required; original release replay remains same after replacement; old device fixes rejected | Not run |
| Release unknown-result recovery | Reload review retains exact original lease/reason; readback or authorized reasoned void; refresh never discards typed review | Not run |
| Delivery login timeout | GPS-only lease may continue; no activity renewal or delivery privileges; reidentify before posting actions | Not run |
| Explicit switch/logout/revocation | Different operator/station switch scope, profile/Employee/assignment/Customer Delivery removal, native permissions, Trip end revoke source | Not run |
| Lorry/snapshot changes | Reconciliation required; old source cannot report against changed/disabled/cross-Company lorry | Not run |
| 12-hour sharing expiry | Position stops being live; publisher reidentifies and explicitly stop/starts as needed; multi-day Trip stays listed | Not run |
| Timestamp/sequence defenses | Future >30s/old >120s/nonfinite/out-of-range/forged fields rejected; duplicate/old sequence/capture cannot refresh age or rewind fix | Not run |
| Pause request ordering | Pre-hide fix fenced by pause sequence; late pause cannot suppress a newer resumed fix | Not run |
| Supervisor current order/status | Next/current pins/list follow actual server route order, approvals, DN/proof/refusal/visit state and actual loaded/delivered/remaining quantities | Not run |
| Native lifecycle gates | Map clicks/directions never deliver, approve a route change, satisfy Site QR or proof, post stock or create returns | Not run |
| Multi-day/history | Active Trip stays visible across dates; closed history opt-in, GPS Trip Ended/last known; no stale source shown live | Not run |
| Viewport | GPS motion preserves manual viewport; Follow only one fresh lorry; Fit Locations/KL work; missing/repeated pins clear/exact-choice behavior preserved | Not run |
| Polling/identity/late results | Passive map reads do not renew operator inactivity; changed token/hide/denial clears old customer/GPS view; late responses ignored | Not run |
| Network/assets/permission denied | Stale/read failures and GPS errors visible; location denial stops local sharing; tiles failure does not break delivery controls | Not run |
| Tablet/scanner | Touch buttons, credential camera, Enter/Tab and GPS SHARE/STOP/REFRESH commands work; stop not queued behind uncertain Start; scanner focus usable | Not run |
| Data/audit review | Latest GPS row only, no point trail; control events/receipts retained without raw secret/coordinates; raw token only source-tab storage, never URL/local device registry | Not run |
| No unrelated ERP effects | Existing stock, DN, proof/QC, returns, route approvals and manufacturing flows retain owners and quantities; GPS does not change delivery revision | Not run |

Deployed SHA: _pending_

Tester/date/devices/network/provider/evidence: _pending_

Relevant platform behavior: [Geolocation getCurrentPosition](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition)
and [Chrome page lifecycle](https://developer.chrome.com/docs/web-platform/page-lifecycle-api).
Browser/OS suspension limits are real acceptance conditions, not implementation guarantees.

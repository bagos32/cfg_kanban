# Customer pins and driver directions — acceptance

Prepared 22 November 2026 above `eb4d977`. Native-site result: **Not run**. Record deployed Git
revision, tester/date and evidence after the owner's manual migration/build. Offline tests do not
establish native schema, Leaflet/tiles, permissions or phone/tablet app handoff.

Use a Company-specific Trip assigned to a lead and assistant, several Customer Sites with distinct
pins, a repeated Site/coordinate, a Site without a pin and a Visit Only stop without a Site. Include
known-customer SOs with customer PO references, tagged/untagged stock and the shared optional-sale
pool. Use a Flexible Order Trip and an enforced Trip with both Supervisor approval scopes.

| Check | Expected result | Native result |
| --- | --- | --- |
| Normal Site form and Save | Latitude/Longitude → Set Pin replaces one marker; save publishes; map tool works without a popup | Not run |
| Clear Pin | Save clears the marker; legacy delivery remains usable | Not run |
| Validation | Extra markers/shapes, invalid JSON, NaN/Infinity, out-of-range and nonnumeric coordinates reject; 0 coordinates remain valid | Not run |
| Site permissions | Existing native create/write/Company scope governs editing; unauthorized driver sees no editing action | Not run |
| Driver authorization | Only assigned/team or authorized Supervisor sources appear; wrong Company/Site/address/native access rejects | Not run |
| KL defaults and saved pin | Empty/new native Site and Driver maps start at KL 3.139,101.6869 zoom 13; saved pins focus actual coordinates; no invented lorry point | Not run |
| Map startup | Native local Leaflet assets and configured tile provider render pins; no automatic driver GPS prompt | Not run |
| Map details | Numbers match effective sequence; pin shows customer/status/products/SO/PO; View Stop only views the exact stop | Not run |
| Repeated coordinate | Combined pin offers each separate visit; no silent first-match selection | Not run |
| Next/current directions | Google Maps/Waze target server next/current point, even while another stop's details are selected | Not run |
| Flexible/reasoned order changes | Flexible edit and each approval scope update next target/numbering after refresh; Pending request does not | Not run |
| Unfinished proof/DN | Current stop remains current; maps cannot complete/bypass its required actions | Not run |
| Missing/invalid pin | No fake marker; counted missing pin; clearly labelled address directions/search, invalid imported pin handled safely | Not run |
| Missing/very long address | No guessed or truncated destination; office setup message | Not run |
| Google Maps on tablet/phone/desktop | Exact destination and driving directions; app/web behavior and origin reviewed on device | Not run |
| Waze installed/not installed | Universal link opens app or website appropriately; exact point or explicit address search | Not run |
| No automatic information transfer | Navigation URLs omit credentials, Trip, SO/PO; no automatic CFG GPS capture before explicit Share GPS; ordinary tile/provider requests only | Not run |
| Native browser new-tab policy | User tap opens provider successfully in kiosk/tablet browser; return refreshes route | Not run |
| Return refresh/session expiry | Passive refresh uses current saved order/pins; does not extend inactivity or post a DN/proof | Not run |
| Ordinary refresh | Existing viewport/map retained; status updates; changed coordinates recenter appropriately | Not run |
| Office correction during multi-day Trip | Pin updates on refresh; frozen stock/customer/address/itinerary/history remain; normal delivery still succeeds | Not run |
| Network/stale read | Directions disabled until refreshed; stale marker status visible | Not run |
| Map asset/tile failure | Directions and delivery controls remain usable; Retry Map/refresh recovers where provider permits | Not run |
| Operator replacement, hide, late load | Old customer's map cleared; delayed loads cannot render or navigate old identity | Not run |
| Completed/closed/incomplete Trip | History pins may be viewed; no next-stop navigation offered | Not run |
| ERP/proof/QC regression | Native allocations, route approval, Company, QR, DN submission, proof and returns retain gates/history | Not run |

Implementation references: [Google Maps URLs](https://developers.google.com/maps/documentation/urls/guide),
[Waze Deep Links](https://developers.google.com/waze/deeplinks), and Frappe `v15.69.2` native map
control/default assets. Google/Waze do the road navigation; the CFG map shows stop locations.

Deployed revision: _pending_

Tester/date/evidence: _pending_

Accepted exceptions/deferred risks: _pending_

Offline development checkpoint: **613 Python tests passed** across the related pin, route,
dispatch, returns, stock identity, schema and navigation suites. **134 JavaScript test entries
passed** across 13 related UI suites. These use dependency/DOM/Leaflet doubles and do not change
the native acceptance results above. Syntax/schema checks also passed.

The subsequent explicit Trip GPS feature has its own [Supervisor/GPS checklist](TEST_SUPERVISOR_LIVE_MAP.md); it does not change map/delivery/proof acceptance results above.

# Plan · Pilot modules 20–21: Incident Replay and Site Twin camera coverage

For the product owner and the coding agent. It maps RPL-01..07 and TWN-08..11 (D-51; `docs/requirements-pilot.md` §99–108) onto the code after pilot module 19, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner.

Neither module is 🔒 (D-29). Incident Replay only reads. Camera coverage adds five seeded columns (PC-53) and changes no RLS or grant.

## 1. Requirements against existing code

| Req. | Exists today | New work | Prompt |
|---|---|---|---|
| RPL-01 Replay from the record | `aar.service.incident()` (with `first_signal_at`) and `timeline()` (roles and references, no names, AAR-02); `intel.queries` exposure listing (`incident_exposure` with places from `person_location_current`); `intel.exposure.exposure_counts`; `checkin_response` history; `notification_delivery` per person | `app/modules/replay/{service,schemas,router}`; `GET /api/incidents/{id}/replay` (§2) | 122 |
| RPL-02 The map at *t* | `map/base.ts` (self-hosted PMTiles), `map/geo.ts` `circlePolygon`, `SEVERITY_COLOUR` | `map/ReplayMap.tsx`: state at *t* worked out in the browser from the one payload (§3) | 123 |
| RPL-03 Play and scrub | — | `screens/replay/ReplayScreen.tsx`: the bar, marks, speeds, keys (§3) | 123 |
| RPL-04 Figures at *t* | the Safety Check-in personnel tally (`checkin.service`) | the same figures computed at *t*; at the end they equal the API's (§2) | 122, 123 |
| RPL-05 No names | AAR-02's timeline has none | the payload has no name field at all (§2) | 122 |
| RPL-06 Where it opens | Incident detail, AAR screen, Exercise & Training runs | three "Replay" links; route `/incidents/replay` outside the sidebar | 123 |
| RPL-07 Link to a moment | `useSearchParams` (as Operations) | `?id=…&t=<seconds from start>` | 123 |
| TWN-08 Camera mounts | `site_sensor` (PC-42), 16 seeded cameras `CAM-01..16` in `TWIN_CAMERA_ZONES` | migration 0018 (PC-53), the seeded mounts (§4), the fields on the twin API's sensor | 124 |
| TWN-09 Coverage on the plan | the plan SVG (`TwinScreen.tsx`, viewBox 790 × 455) | `screens/twin/coverage.ts` (cones, clipping, area) and a "Camera coverage" toggle (§5) | 125 |
| TWN-10 Place → camera | the CCTV wall's enlarged view (`CctvWall` dialog); SITE timeline events carry `data.sensor` | open a camera by code; `/twin?site=…&camera=…`; links from the plan, "Sensors & systems" and the incident's SITE entries | 125 |
| TWN-11 Coverage KPI | the twin KPI row | "Camera coverage" KPI from `coverage.ts` | 125 |

## 2. The replay payload (RPL-01, RPL-04, RPL-05)

`GET /api/incidents/{id}/replay`, for the roles that read Incidents (the intel router's `Reader`), tenant-wide as the Incidents screen. One response, nothing stored:

- `window`: `start` = the first linked signal's `received_at` (as AAR's `first_signal_at`); `end` per G-2.
- `incident`: reference, title, severity, centre, `impact_radius_m`, `opened_at`, `status`, `exercise` label (EXR).
- `signals`: each linked signal's received time, place and severity; no body text.
- `people`: one row per exposed PERSON: an opaque index (not the person id), place (current), `exposed_at` (`computed_at`), `asked_at` (first CHECKIN delivery to them, if any) and `answers` [{`at`, `status`}]. No name, no id.
- `sites`: exposed sites: name, place, `exposed_at` (sites are named on every screen already).
- `trips`: a count only (G-4).
- `tally_end`: the personnel tally at `end`, from the Safety Check-in's own function, so the screen can check itself against it in the tests.
- `timeline`: AAR-02's `timeline(session, incident, end)`, with each entry's `at`, `source` and `text`, plus `sensor` and `site_id` for SITE entries (TWN-10).

The state at *t* is a pure function in the browser (`screens/replay/state.ts`): signals with `received ≤ t`; the zone if `opened_at ≤ t`; each person shown if `exposed_at ≤ t`, coloured *not asked* / *waiting* (`asked_at ≤ t`) / *safe* or *needs help* (latest answer ≤ t). Tested against the API's `tally_end` at `t = end`.

## 3. The screen (RPL-02, RPL-03, RPL-06, RPL-07)

Full width, Blueprint dark, as the Operations map:
- **Header:** the incident reference and title, the exercise banner when it is one, "Positions as now; the platform keeps no location history".
- **Map** (MapLibre, self-hosted tiles): signals as severity dots that appear when they arrive; the impact circle; people as small dots by state; sites as squares. Fits the impact zone on open.
- **Figures** beside it: time since the first signal (`+12:34`), signals, people exposed, the tally safe / needs help / waiting.
- **Timeline** beside the figures: AAR-02's entries; the current one highlighted and scrolled into view; a click jumps there.
- **Bar** under the map: play/pause, a scrubber with a mark per entry (coloured by source), speeds 0.5× · 1× · 2× · 4×; ←/→ step to the previous or next entry, space plays and pauses. At 1×, `end − start` plays in 60 s.
- **Reduced motion or Calm mode:** play steps from entry to entry every 2 s, with no animated movement.
- **Address:** `t` is written (replacing, not pushing history) when paused or scrubbed.

## 4. Camera mounts (TWN-08, PC-53)

Migration 0018: the five columns and the CHECK (all set for CCTV, all null otherwise), with existing rows filled in the same migration before the CHECK is added. Heading 0 = up the plan, clockwise. The seed (`simulator/nexira_sim/seed/data.py`) gets the same values for a fresh reset:

| Camera | Zone | Mount | Heading | FOV | Range |
|---|---|---|---|---|---|
| CAM-01 | Gate 1 | 22, 322 | 135 | 90 | 120 |
| CAM-02 | Gate 1 | 113, 383 | 315 | 90 | 120 |
| CAM-03 | Gate 2 | 682, 342 | 120 | 80 | 110 |
| CAM-04 | Gate 2 | 768, 383 | 290 | 80 | 110 |
| CAM-05 | Lobby | 132, 267 | 135 | 90 | 200 |
| CAM-06 | Lobby | 298, 383 | 315 | 90 | 200 |
| CAM-07 | Consular hall | 317, 267 | 120 | 90 | 280 |
| CAM-08 | Consular hall | 573, 383 | 300 | 90 | 280 |
| CAM-09 | Chancery | 132, 32 | 135 | 90 | 220 |
| CAM-10 | Chancery | 132, 248 | 70 | 70 | 280 |
| CAM-11 | Conference | 417, 157 | 130 | 110 | 190 |
| CAM-12 | Comms / IT | 768, 32 | 225 | 110 | 205 |
| CAM-13 | Safe room | 592, 147 | 130 | 110 | 210 |
| CAM-14 | Muster | 592, 267 | 105 | 90 | 190 |
| CAM-15 | Muster | 768, 323 | 285 | 90 | 190 |
| CAM-16 | Ambassador suite | 417, 32 | 130 | 110 | 200 |

The seeded gap (§108 Q2): the chancery's north-east corner, which neither CAM-09 nor CAM-10 reaches. Prompt 124 tunes these numbers if the measured coverage differs, and the test states the result.

**Tuned in Prompt 124:** as first planned (heading 60, range 200), CAM-10 left the chancery's whole east strip uncovered, not just its north-east corner. At heading 70 and range 280 the gap is the corner (about 7% of the chancery). Measured on the §5 grid: the site 96% covered, 95% with CAM-07 offline, the consular hall still covered by CAM-08.

**Re-aimed in Prompt 125 (migration 0019, data only):** CAM-11, CAM-12, CAM-13 and CAM-16 covered 50° either side of a heading that left the wall below their mount unseen, so four rooms showed a thin uncovered strip (4–5% each) and would have been listed beside the real blind corner. With 110° and the headings above, every zone but the chancery is fully covered: the site 97%, 96% with CAM-07 offline.

## 5. Coverage (TWN-09, TWN-11)

`screens/twin/coverage.ts`, pure and tested:
- `cone(camera)`: the sector as an SVG path, clipped to its zone's rectangle (Sutherland–Hodgman on the sector polygon, 24 arc steps).
- `covered(zones, cameras)`: each zone's covered share, sampled on a 5-unit grid of the zone: a point is covered if it is inside an online camera's clipped cone. Deterministic, a few thousand points, fast enough on each read.
- KPI = covered points / all zone points, rounded down to a whole percentage; "Not covered now" lists zones with no covered point. A zone partly covered is not listed; its uncovered part is hatched.

On the plan: online cones translucent blue; OFFLINE, FAULT or DEGRADED cones red and dashed; uncovered cells hatched. The toggle is kept in `sessionStorage` (`nexira.twin.coverage`), in a try/catch.

**As built in Prompt 125** (each a deviation for approval in its PR):
- A DEGRADED camera counts as covering and its cone stays blue, as the twin counts it online (plan-pilot-twn G-2); only OFFLINE and FAULT cones are red and dashed. Otherwise the KPI would count a camera the plan draws as down.
- Under the plan, "Not covered now" names the zones with no covered point (TWN-09), and a second line, "Blind spots", names partly covered zones with the share no camera sees ("Chancery offices (7%)"), so the seeded corner is named as §107 expects.
- The handoff also takes `?zone=` (a zone clicked on the plan), beside `?camera=` (TWN-10); a `camera` that is not a camera, such as a gate from a SITE entry, opens the camera watching its zone.

## 6. Acceptance (§102, §107)

- **Replay:** `frontend/e2e/rpl-acceptance.spec.ts`, run after the After-Action Review spec in `make acceptance` (it opens the replay from AAR-<year>-1042). It reads only.
- **Coverage:** added to `twn-acceptance.spec.ts`, which already plays NBO-SITE scenes 1 and 3: the cones, the KPI below 100% before, falling with CAM-07 offline (the consular hall stays covered by CAM-08, so it is not listed), recovering at scene 3; the handoff from Gate 2 and from the SITE entry.

**As built in Prompt 126** (each a deviation for approval in its PR):
- **Start of the window (§102):** "before the incident opened, no impact zone" cannot be shown. The window starts at the first signal's `received_at` (G-1), and the incident's `opened_at` is that signal's `occurred_at`, a few milliseconds earlier, so the zone is drawn from t = 0. The spec checks what holds at t = 0: one signal, no one exposed, no check-in yet. No code change.
- **End of the window:** the spec checks the replay's 229 and 15 / 1 / 1 against the Incidents screen's exposure card and the Safety Check-in screen's personnel figures for the same check-in.
- **Scrub:** to the first "a person needs help" entry; the expected tally is worked out from the payload's answers at that moment, and differs from the end's.
- **Found and fixed:** a zone opened from the plan kept keyboard focus, so the camera dialog never took it and Escape did not close it (the Close button did). The zone now lets go of focus on click and on Enter or Space (`TwinScreen.tsx`), with a unit test for each.

## 7. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | A signal has `occurred_at` (from the provider) and `received_at` (by the platform) | `received_at`: the replay shows what the platform knew and when, as AAR-02 and AAR-03 do |
| G-2 | **Decided: A** (PR #159). RPL-01 ends the window at "now" while not closed. INC-<year>-1042 stays at MONITORING after the Phase 1 run, so its replay would end hours later in silence | **A (chosen):** ACTIVE → now; MONITORING or CLOSED → the last thing the record holds (the latest timeline entry or check-in answer), or `closed_at` if later. **B:** as written, now until closed |
| G-3 | Which check-in figures: the check-in has personnel and other groups | Personnel, as the Safety Check-in summary and the Copilot (15 / 1 / 1) |
| G-4 | A trip has no current position of its own on the map, and restricted trips must never show (D-33) | Trips are a count in the figures, excluding restricted ones as the travel API does; not drawn |
| G-5 | An ACTIVE incident keeps changing while it is replayed | The payload is a snapshot when opened; a "Refresh" button reloads it and keeps *t* |
| G-6 | AAR-02's `timeline()` takes the AAR `Incident` dataclass | Reused as it is through `aar.service.incident()`; no copy of the query. The replay module imports from aar, not the other way round |
| G-7 | Coverage area as an exact polygon union is heavy in the browser | The 5-unit grid (§5): exact enough to show the gap, and testable |
| G-8 | TWN-10's SITE entries exist on the Incidents timeline (with `data.sensor`), but AAR-02's text-only timeline drops the data | Links from the Incidents timeline and the replay's timeline (which carries `sensor`, §2); the AAR screen's timeline stays text |
| G-9 | **Found while building (Prompt 123); deviation, for the product owner's approval.** After the Phase 1 run, two agent escalations arrive an hour after INC-<year>-1042 went to MONITORING. Under G-2 (A) they end the window, so at 60 s for the whole window the two minutes of response play in two seconds | The play axis shortens every quiet stretch longer than 30 s of record to 30 s; the bar shows each as a hatched break ("Quiet for 57:00; shortened"), and the elapsed time stays the record's. With no quiet stretch, 60 s at 1× is unchanged |

## 8. Prompts

As `docs/prompts-pilot.md` Prompts 122–126. None is 🔒.

## 9. Decisions by the product owner (2026-11-10, PR #159: "A")

- G-2: option A. An ACTIVE incident replays to now; a MONITORING or CLOSED one ends at the last thing the record holds, or `closed_at` if later.
- G-1, G-3..G-8: as proposed.

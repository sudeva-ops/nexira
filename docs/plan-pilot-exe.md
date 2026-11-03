# Plan · Pilot module 15: Executive Overview (Prompt 95)

For the product owner and the coding agent. It maps EXE-01..06 (`docs/requirements-pilot.md` §74–78) and D-45 onto the code after pilot module 14, and lists the gaps found, each with a proposed answer. Everything is worked out on read from existing data (D-45): no table, no seeded history, no invented baseline, no person's name.

## 1. Requirements against existing code

| EXE | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Headline figures | `people.queries._MISSIONS` (`display_risk`: the higher of the stored risk and the worst ACTIVE incident at the mission); `incident`, `incident_signal`, `raw_signal.received_at`; `notification_campaign.sent_at`; `checkin.service.tally()`; `site.readiness_score` | `executive.service.overview()` (§2) | 96 |
| 02 Trends and attention | the same, plus `evacuation`, `health_intel._levels()`, `hazards.list_hazards()`, `supply.service.summary()`, `fleet.service.list_assets()`, Site Twin's shelter query, `incident_event` | the trend, regions, drivers and timeline (§3–§5) | 96 |
| 03 Export | `app/core/audit.py` | `POST /api/executive/export` (audit) and a print-ready page (§6) | 96, 97 |
| 04 Who sees what | `require_roles(*ROLES)` | every role; aggregates and references only | 96 |
| 05 Screen | Blueprint dark; `Kpi`, `Card`; realtime | the screen, last under PLAN & INSIGHT (§7) | 97 |
| 06 Demo | NBO-CIVIL-UNREST | no new scenario (§8) | 98 |

New backend module: `app/modules/executive/{schemas,service,router}` (no models: no tables).

## 2. Headline figures (EXE-01)

- **Global posture** from each mission's `display_risk`: **SEVERE** if any is CRITICAL; **ELEVATED** if any is HIGH or any incident is ACTIVE; else **GUARDED**. The detail is "N critical · N elevated missions", where elevated means MODERATE or HIGH.
  - Seeded calm state: GUARDED, "0 critical · 4 elevated missions" (Baghdad, Islamabad, Abuja, Jakarta), as the design.
- **Active incidents:** the count of ACTIVE incidents and the most recently opened one's reference and title.
- **Detection to notification**, per incident opened in the last 30 days:
  - the time from `min(raw_signal.received_at)` over its signals to `min(notification_campaign.sent_at)` over its campaigns (any type);
  - incidents with no campaign sent are left out;
  - shown: the median and how many incidents it covers, and, for the most severe ACTIVE incident, its own time ("2m 41s"). No baseline.
- **Personnel accounted:**
  - over the latest CHECKIN campaign of each ACTIVE incident, the personnel part of `checkin.tally()`: (safe + need help) / recipients, rounded;
  - the detail names the incident, or "No active check-in", with the value shown as "—";
  - after the Nairobi scene 4: (15 + 1) / 17 gives **94%**.
- **Mission readiness:** the mean `site.readiness_score` of the EMBASSY sites, rounded, "/100", labelled "illustrative until Exercises".

## 3. The trend and regions (EXE-02)

- **Alerts, last 30 days:** two series by UTC day, the 30 days ending today:
  - raw signals by `received_at`;
  - fused incidents by `opened_at`.

  Days with nothing are 0. They come from the database only (§78 Q4), so in the demo most days are 0 until scenarios are played. The card says "Simulated feeds".
- **Regions (G-2):** a fixed country-to-region map in `executive/service.py`:

| Region | Mission countries |
|---|---|
| Africa | EG, MA, NG, KE, ET, ZA |
| Middle East | JO, IQ, SA, OM |
| Asia-Pacific | PK, IN, BD, CN, KR, JP, PH, MY, SG, ID, AU |
| Europe | GB, FR, DE, BE, CH, IT, ES, RU, TR |
| Americas | US, CA, MX, BR, AR |

  A mission whose country is not in the map is counted under "Other" and logged. A test checks that every seeded mission is mapped.
- **Exposure by region:** the mean of the region's missions' `display_risk` points (LOW 20, MODERATE 50, HIGH 75, CRITICAL 95), rounded, shown with the rule.
  - Africa before the unrest: (5 × 20 + 50) / 6 = 25 (Abuja MODERATE).
  - After it, with Nairobi CRITICAL: (4 × 20 + 50 + 95) / 6 = 38.

## 4. Missions requiring attention (EXE-02)

- **Which missions:** every mission whose `display_risk` is MODERATE or above, or that has an ACTIVE incident. They are ordered by risk, then by number of drivers, then by code.
- **Each row:** mission, risk, personnel (as `_MISSIONS`), embassy readiness, and the drivers.
- **Drivers**, each a short label with a reference where there is one. All are worked out by calling the modules' own read functions, so the rules stay in one place:

| Driver | Source |
|---|---|
| "INC-… · Civil unrest" | ACTIVE incidents with `mission_id` |
| "Evacuation EVN-… active" | `evacuation.status = 'ACTIVE'` |
| "Health advisory · LEVEL" | `health_intel._levels()` (OPEN advisories in the mission's country) |
| "Natural hazard · <title>" | `hazards.list_hazards()`: ACTIVE events `within_range` of the mission (G-5) |
| "N suppliers impacted" | `supply.service.summary()`, the impacted suppliers per mission |
| "N vehicles unavailable" | `fleet.service.list_assets()`: vehicles tagged BLOCKED or IN_ZONE (not maintenance; G-6) |
| "Shelter-in-place" | Site Twin's `_SHELTER` rule, exposed as `twin.service.sheltering(session, mission_id)` (G-7) |

- **Order:** a mission with an ACTIVE incident and no other risk still appears, its risk being the incident's severity through `display_risk`.
- **Names:** none. Drivers carry references and counts only.

## 5. The response timeline (EXE-02)

- **For the most severe ACTIVE incident** (by severity, then the latest opened): its `incident_event` rows of types FUSED, EXPOSURE, PLAYBOOK_STEP, NOTIFICATION, CHECKIN, DECISION and STATUS, oldest first, at most 12, as time, type and summary. Summaries are the timeline's own text, except a CHECKIN entry, which names the person and is shown as "Check-in: a person needs help." (G-11; checked in the tests).
- **With no ACTIVE incident:** "Recent activity", meaning incidents opened or closed in the last 7 days, newest first, at most 8.

## 6. The export (EXE-03, §78 Q6)

- **`POST /api/executive/export`:** returns the same overview with `generated_at`, and writes `EXECUTIVE.EXPORT` through `app/core/audit.py`. The details are the figures' headline values, never names. Any role may export (EXE-04).
- **The screen:** "Export briefing" calls it, then opens `/executive/briefing`, an in-app route with no nav entry. It shows:
  - a print-styled, one-page layout (white, A4) of the five figures;
  - regions;
  - the top five missions requiring attention, with their drivers;
  - the timeline's last six events;
  - "Simulated data · produced <time> by NEXIRA";
  - a Print button (`window.print()`).

  The browser saves it as PDF; nothing is stored on the server.

## 7. The screen (EXE-05, §78 Q7)

- **"Executive Overview"** (`/executive`, icon `chart`), last under PLAN & INSIGHT. The subtitle is "Dashboard · Leadership view".
- **Layout:**
  - **five KPIs:** posture (green for GUARDED, amber for ELEVATED, red for SEVERE), active incidents, detection → notification, personnel accounted, mission readiness;
  - **row 2:**
    - "Alerts · last 30 days": an inline SVG area chart of incidents over a faint bar series of signals, with the totals;
    - "Risk exposure by region": bars with the value and the rule as a tooltip;
  - **row 3:**
    - "Missions requiring attention": a table of mission, risk, drivers, personnel and readiness;
    - "<INC-…> · response timeline" or "Recent activity".
- **Export briefing** sits in the page header.
- **Realtime:** INCIDENT_*, EXPOSURE_COMPUTED, CHECKIN_*, CAMPAIGN_*, EVACUATION_UPDATED, HEALTH_ADVISORY_UPDATED, SUPPLY_UPDATED and FLEET_UPDATED invalidate `["executive"]`.

## 8. The demo and the acceptance (EXE-06, §77)

- **No new scenario.** NBO-CIVIL-UNREST scene 6 still opens Incidents (§78 Q8).
- **The calm state and the incident's figures need the Phase 1 run in progress,** but `make acceptance` runs the Phase 1 spec first and every later spec sees a world after it (G-1). So:
  - the **Phase 1 spec** (`acceptance.spec.ts`) gets two API checks of `/api/executive/overview`:
    - at scene 0: GUARDED, 0 active, 4 elevated missions, Africa 25;
    - after scene 4: SEVERE, INC-<year>-1042 active with a detection-to-notification time, personnel accounted 94%, Nairobi first with "INC-…" among its drivers, Africa 38.

    This is a small change to an existing spec, as Fleet and Site Twin made (FLT G-3, TWN G-3).
  - **`exe-acceptance.spec.ts`** (after `ev-`, before `flt-`) checks, in the browser:
    - the screen's KPIs against the API;
    - the attention list containing Nairobi with its drivers;
    - the timeline;
    - **the export:** the briefing page, no names (none of the seeded staff names appear), and `EXECUTIVE.EXPORT` audited with an intact chain;
    - the Viewer seeing the same page.
- `make acceptance` runs all specs.

## 9. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | The calm state cannot be seen after the Phase 1 run | Check it (and the incident's figures) in the Phase 1 spec, by API, at scene 0 and after scene 4; the module's own spec checks the screen and the export afterwards (§8). |
| G-2 | Türkiye and Egypt sit between regions | Türkiye under Europe, Egypt under Africa (the design counts Nairobi's unrest under Africa); the map is a constant, easy to change. |
| G-3 | "Accounted" for citizens | Personnel only, as the design's "Personnel accounted" and Phase 1's 94%; citizens stay on Safety Check-in. |
| G-4 | Which incident's own timing and timeline when several are ACTIVE | The most severe, then the latest opened, as `_MISSIONS`' "worst". |
| G-5 | When a natural hazard is a driver | An ACTIVE hazard event `within_range` (300 km, HZ-03) of the mission, as the hazards screen shows it. |
| G-6 | "Unavailable vehicles" | Vehicles tagged BLOCKED or IN_ZONE by Fleet; routine maintenance is not an attention driver. |
| G-7 | Site Twin's shelter rule is private | Expose it as `twin.service.sheltering(session, mission_id) -> str | None` (the incident reference), reusing `_SHELTER`; no behaviour change. |
| G-8 | The trend's days | UTC days, today included, 30 in all. |
| G-9 | The export route | An in-app route `/executive/briefing` with a print stylesheet; Playwright checks its content, not a PDF file. |
| G-10 | 🔒 scope | None: no schema, RLS, `approvals.py` or `audit.py` change (D-45, §78 Q9). |
| G-11 | Found while building Prompt 96: a CHECKIN timeline entry names the person who needs help ("<name> needs help (NTF-…)") | The overview shows it as "Check-in: a person needs help."; free-text NOTE and ESCALATION entries (which can name people) are left out. A test checks that no seeded person's name appears in the overview or the export. |

None of these needs a decision beyond the approved defaults; reply "approved" to take them as proposed.

## 10. Prompts

As `docs/prompts-pilot.md` Prompts 96–98: the service; the screen and the briefing; the acceptance. Each ships with its tests, and `make acceptance` passes at the end.

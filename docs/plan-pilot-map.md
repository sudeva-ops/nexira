# Plan · Pilot modules 22–24: map annotations, Nearby and map search

For the product owner and the coding agent. It maps ANN-01..06, NBY-01..06 and SRC-01..04 (D-52; `docs/requirements-pilot.md` §109–115) onto the code after pilot module 21, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner.

Only the annotations migration is 🔒 (D-29: a new table with RLS and grants). Nearby only reads, and search runs in the browser.

## 1. Requirements against existing code

| Req. | Exists today | New work | Prompt |
|---|---|---|---|
| ANN-01 Draw | Global Operations map (`map/OperationsMap.tsx`) | migration 0020 (PC-54); `app/modules/annotations`; drawing on the map (§2) | 127–129 |
| ANN-02 Live | Redis Streams → WebSocket (`core/events.py`, `core/realtime.py`); the browser refetches by event (`api/realtimeClient.ts` `staleKeys`) | event `annotation.changed` → query key `["annotations"]` | 128, 129 |
| ANN-03 Edit, withdraw | guards and column grants (as AAR, PC-50) | the PC-54 guard: ACTIVE → WITHDRAWN once; no DELETE | 127, 128 |
| ANN-04 Roles, not names | AAR shows roles (D-47) | the API returns the author's role, never the person | 128 |
| ANN-05 Audited | `core/audit.py` | `ANNOTATION.ADD`, `ANNOTATION.EDIT`, `ANNOTATION.WITHDRAW` | 128 |
| ANN-06 With its incident | `incident_event` (free `event_type`); AAR-02 `timeline()` maps event types; Replay reuses it | `ANNOTATION` incident events; mapped in `aar.timeline()` (G-4); annotations on the replay map at *t* | 128, 129 |
| NBY-01..06 | PostGIS on every located table; exposure groups (`intel/exposure.py`); `evacuations.name_scope()`; D-33 filters in travel | `GET /api/nearby` (§3); the panel on Global Operations | 130, 131 |
| SRC-01..04 | missions, sites, incidents and flights already loaded by the maps | the gazetteer build script and file; `map/search.ts`; the search box (§4) | 132 |

## 2. Annotations (ANN-01..06, PC-54)

**Migration 0020 (🔒)**: `map_annotation` as PC-54, with the shape's geometry type checked against the kind (`ST_GeometryType`). The guard does the following:
- it keeps the kind, author, incident and mission fixed;
- it allows ACTIVE → WITHDRAWN once, with a reason;
- it writes `updated_at` and `withdrawn_at`.

The table has FORCE RLS with `tenant_isolation`; there is no DELETE.

**API** (`app/modules/annotations/{models,schemas,service,router,tests}`):
- `GET /api/annotations?incident_id=`: the ACTIVE ones whose `ends_at` has not passed, for every role that reads Global Operations. Each carries the shape as GeoJSON, its role and its times.
- `POST /api/annotations`: add one.
- `PATCH /api/annotations/{id}`: change the label, note, shape or end time.
- `POST /api/annotations/{id}/withdraw`: withdraw it, with a reason.

Role and mission checks go through `approvals.py` (`user_has_role` with the annotation's mission, §115 Q2). Each change does three things:
- it writes `audit.write`;
- for a linked incident, it adds an `incident_event` (`ANNOTATION`), with a summary of the kind and the label;
- it publishes `annotation.changed`.

The author's role is the highest of the roles that allowed the action, in the order HQ Crisis Director, Security Officer, Duty Officer, Head of Mission.

**On the map** (`map/annotations.ts`, pure; the layers in `OperationsMap.tsx`):
- **Layers:** marks are symbols drawn as inline SVG icons (no sprite fetch). Lines are dashed. Areas are a translucent fill with an outline. The label shows from zoom 5.
- **Drawing:** a small toolbar ("Mark", "Line", "Area") for roles that may annotate:
  - click to place a mark;
  - click for each vertex of a line or area, then double-click or Enter to finish, or Escape to cancel;
  - a form for the symbol, the label, the note, the incident and the end time.
- **Editing:** dragging vertices is left out. A shape is redrawn instead (G-3).
- **Popups:** clicking an annotation shows its label, note, "Duty Officer · 14:02", and Edit and Withdraw where allowed.
- **Visibility:** a layer switch "Annotations" in the legend.

**Incident Replay:** the replay payload gains `annotations` (kind, symbol, shape, `created_at`, `withdrawn_at`). The map shows each one while `created_at ≤ t < withdrawn_at`.

**As built in Prompt 128** (each a deviation for approval in its PR):
- The event is `ANNOTATION_UPDATED`, as every other module's (`AAR_UPDATED`, `SITE_UPDATED`), not `annotation.changed`; `core/realtime.py` forwards it.
- The author's role is worked out on read from their grants (the table stores the person, not the role): the highest annotating role covering the annotation's mission, or "A user" if it was taken away since.
- Who may edit or withdraw is any annotating role in the annotation's mission (ANN-03); the author alone, without such a role, may not.
- AAR-02 and the replay's timeline read "Map annotation added: Checkpoint." (G-4); the incident's own timeline has "Annotation added: Checkpoint · <label>."; the replay's `annotations` carry the kind, symbol, shape and times, and no label or note.
- An end time must be in the future; ending one now is a withdrawal.

**As built in Prompt 129** (each a deviation for approval in its PR):
- The picked annotation opens a card in the map's corner (React, with Edit and Withdraw), not a MapLibre popup, so its buttons are ordinary, testable controls.
- Edit on screen changes the label, note and end time; a shape is changed by withdrawing and drawing again (G-3). The API's shape edit stays for later.
- Annotations have their own colours, apart from the severities and the people: checkpoint gold, closed road and lines rose, rally point green, hazard lilac, note grey, areas violet.
- A mark is placed with its one click; a line or an area finishes on double-click, Enter or "Finish", and Escape cancels.

## 3. Nearby (NBY-01..06)

`GET /api/nearby?lon=&lat=&radius_m=` (1,000 to 50,000) runs as the person asking, under RLS and mission scope. It returns one list per kind, nearest first:
- **people:** from `person_location_current`, grouped as the exposure groups them (staff, delegates, citizens), with counts and mean confidence. Names come only within `name_scope()` (G-5).
- **sites;**
- **vehicles:** `fleet_asset`;
- **travellers in transit:** people on an APPROVED or PENDING trip active today, never one on a restricted trip (D-33). The trips are counted.
- **partners:** those covering the country of the nearest mission (G-1);
- **active incidents and hazards:** both are incidents;
- **annotations.**

Each row carries its distance (`ST_Distance`) and the link to its screen. The endpoint reads only and is not audited (§115 Q5).

**The panel** (`screens/operations/NearbyPanel.tsx`):
- It opens from a right-click or long press on the map, and from a mission, site or incident popup.
- It shows the radius chips, the circle on the map and the lists.
- Each row opens its screen or flies the map to it.
- `?near=lat,lon&r=10` goes in the address (replace, as the replay's `t`).

**As built in Prompt 130** (each a deviation for approval in its PR):
- A restricted trip's traveller is counted in the people figures, as the incident exposure counts them, but is never named and never counted as a traveller (D-33).
- Each list holds at most the 50 nearest; the people counts cover everyone in range, and `unnamed` says how many in range the caller may not see by name.
- Partners are those covering the country of the mission nearest the point, wherever it is (G-1); the response names that mission and country.
- On the live stack, from the Nairobi embassy at 10 km: 14 staff, 3 delegates, 212 citizens (as INC-<year>-1042's exposure) and 1 other.

**As built in Prompt 131** (each a deviation for approval in its PR):
- Each row of Nearby flies the map to it (an incident opens its impact panel), so the API's rows now carry `lon` and `lat`; partners link to Assistance Partners and travellers to Journey Management. The other screens take no deep link to one record yet.
- Nearby opens from a right-click without a drag, a long press, and the incident's impact panel ("What's nearby"). Missions and sites have only hover popups on the map today, so they are reached by right-clicking on them.
- When Nearby opens or its radius changes, the map fits the circle.
- It refreshes on exposure, fleet and annotation events.

## 4. Search (SRC-01..04)

**Gazetteer:** `infra/scripts/build-places.py`, built as the star field is:
- the source is Natural Earth's 1:10m populated places (public domain), checked against its SHA-256;
- the file is `frontend/src/map/places.json`, holding the name, ASCII name, ISO country, longitude, latitude and rank of about 7,300 places;
- it is loaded with a dynamic import the first time the box gets focus, so the map does not pay for it (G-11).

**`map/search.ts`** (pure, tested) parses the following:
- decimal pairs (`lat, lon`, with N/S/E/W letters or signs);
- degrees, minutes and seconds;
- `geo:` URIs (RFC 5870, coordinates only; parameters ignored).

It matches platform records first:
- mission code or city;
- site name;
- incident reference;
- on Air, a flight number.

It then matches places, by prefix and rank, accent-insensitively.

**The box** sits in the map's top-left, under the legend:
- `/` focuses it; arrow keys and Enter choose a result.
- A result flies the map there and marks the point for 10 s.
- Each result offers "What's nearby".
- Nothing is sent anywhere (D-24); the acceptance spec checks that no request leaves the stack.

**As built in Prompt 132** (each a deviation for approval in its PR):
- The gazetteer is Natural Earth 5.1.1's populated places (simple): 7,342 places, 368 KB, built by `infra/scripts/build-places.py` from the official zip (checked by SHA-256) with the standard library, and committed. It loads as its own chunk the first time the box gets focus.
- A result flies to zoom 7 (a place) or 8 (anything else), not closer: the self-hosted world tiles carry detail to zoom 6 and only the Nairobi extract to 15 (D-24), so closer views elsewhere would be blank. An incident opens its impact panel instead, which fits its zone.
- The found point is marked for 10 s; "What's nearby" is a button on each result and Shift+Enter.
- The box sits under the legend; the annotation toolbar and card move down to make room.

## 5. Acceptance (§114)

`frontend/e2e/map-acceptance.spec.ts`, run in `make acceptance` before the Copilot spec, while INC-<year>-1042 is ACTIVE:
- annotations, with a second browser as the Viewer;
- Nearby from the Nairobi embassy at 10 km, its people counts checked against the API's exposure inside that radius;
- the four searches;
- audit actions and the chain.

Annotations added here appear in the After-Action Review spec's timeline. That spec's checks are by pattern, so they still hold. A check that the replay draws an annotation goes into `rpl-acceptance.spec.ts`.

## 6. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | A partner has no location, only the countries it covers (`partner.coverage`) | Nearby lists the partners covering the country of the mission nearest the point (within the radius, else the nearest), marked "covers KE", with no distance |
| G-2 | **Decided: A** (PR #168). Which mission an annotation belongs to, for the Head of Mission's scope | **A (chosen):** the linked incident's mission; else the mission nearest the shape, if within 300 km; else none (tenant-wide). A Head of Mission may only add or change annotations whose mission is theirs. **B:** the author picks a mission from a list every time |
| G-3 | Editing a shape vertex by vertex needs a drawing library; the stack has none, and AGENTS.md fixes the stack | Our own small drawing (click, double-click, Escape). Edit changes the label, note and end time; a shape is changed by redrawing it |
| G-4 | Annotation labels are free text, which may contain a name; AAR-02 leaves out free text (NOTE, AAR G-1) | The Incidents timeline shows the label (as it shows notes); AAR-02 and the replay's timeline show only the kind and symbol ("Checkpoint added", "Area added") |
| G-5 | Who counts as "staff" in Nearby; the exposure groups only staff (`STAFF_TYPES`: DIPLOMAT, LOCAL_STAFF), delegates and citizens | The same three groups, so Nearby agrees with the exposure, plus an "others" count for DEPENDANT and CONTRACTOR, so no one near the point is left out silently |
| G-6 | Drawing on a globe at world zoom is imprecise | The drawing tools are on from zoom 5; below it, the toolbar says "Zoom in to draw" |
| G-7 | Ended annotations | Filtered on read (`ends_at > now()`); no job. They stay on record with their end time and are shown in the replay until then |
| G-8 | The Viewer and Nearby | Counts only, as on Incidents. The Viewer holds no name scope |
| G-9 | Search on Air Travel Tracking finds flights | From the flights the Air map already loaded: only our travellers' flights (AT-01), never a restricted trip's (D-33) |
| G-10 | Right-click is already the map's rotate gesture in MapLibre | Right-click opens Nearby only without a drag (a click, not a drag). Rotation stays on right-drag |
| G-11 | The gazetteer's size (about 300 KB) | Loaded on first focus of the box, as its own chunk; never on sign-in |

## 7. Prompts

As `docs/prompts-pilot.md` Prompts 127–133. Prompt 127 is 🔒.

## 8. Decisions by the product owner (2026-11-11, PR #168: "A and Approved")

- G-2: option A. An annotation belongs to its incident's mission, else the mission nearest the shape within 300 km, else none (tenant-wide); a Head of Mission adds or changes only those of their mission.
- G-1, G-3..G-11: as proposed.

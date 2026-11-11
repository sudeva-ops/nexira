# Plan · Pilot module 25: Site Twin live activity

For the product owner and the coding agent. It maps TWN-12..TWN-16 (D-53; `docs/requirements-pilot.md` §116–120) onto the code after pilot module 24, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner.

No schema change (§120 Q2: no capacity for every room), so nothing here is 🔒 under D-29. The normal day writes presence through the existing service, audited as every presence move is.

## 1. Requirements against existing code

| Req. | Exists today | New work | Prompt |
|---|---|---|---|
| TWN-13 A normal day | `twin.service.presence()` moves, adds and removes an occupant and audits `SITE.PRESENCE` with kind, from and to; the consumer takes `SITE_PRESENCE` only from the scenario player (review of Prompt 84, L5) | `app/modules/twin/ambient.py`: a worker task that plays a working day through `presence()` (G-1); the switch (G-2) | 134 |
| TWN-14 Recent movements | the `SITE.PRESENCE` audit entries hold kind, from and to, plus a person id or label | `GET /api/sites/{id}/twin/movements`: the last 20 and today's figures, kind and zones only (G-5) | 135 |
| TWN-12 People who move | the plan SVG draws dots in rows per zone (`TwinScreen.tsx`) | `screens/twin/motion.ts` (pure): a place per occupant, drift, a walk between zones (G-6, G-7) | 136 |
| TWN-16 Furniture | — | `screens/twin/furniture.ts`: outlines per zone kind, scaled to the rectangle (G-9) | 136 |
| TWN-15 Camera wall | `CctvWall.tsx` draws walkers in generated views from occupancy; clips are empty | the count on each tile; the walkers over the clips too (G-8) | 137 |
| Acceptance | `twn-acceptance.spec.ts` (exact counts) | `twa-acceptance.spec.ts`, with the normal day on; the other specs with it off (G-2) | 138 |

## 2. The normal day (TWN-13)

`app/modules/twin/ambient.py`, started by the worker beside the consumers. Every 60 s (±15 s), for each site with a plan whose switch is on, it takes the next move of a fixed day script and applies it through `twin.service.presence()`, as the simulated access-control feed (`ACCESS`, as today). So each move is stored, audited as `SITE.PRESENCE` and published as `SITE_UPDATED`.

**The script.** A loop of about 40 moves, built from the seeded occupants only (11 staff, 3 guards, 11 visitors: `data.TWIN_STAFF`, `data.TWIN_LABELS`):
- visitors leave by Gate 1 and others arrive (as the same labels), queue in the lobby, are seen in the consular hall and leave;
- staff go between the chancery, the conference room and the IT room, and come back;
- a guard walks Gate 1 → Lobby → Muster point → Gate 2 → back.

The script is deterministic: a seeded order with fixed steps. So the site stays within a band (visitors 6–11, staff and guards all on site), and tests can predict it.

**Pausing (G-3).** A tick is skipped while any of these holds:
- shelter-in-place is active at the site (TWN-04);
- an evacuation is ACTIVE there;
- a run of `NBO-SITE` is PLAYING or paused mid-scenario.

Scene 1 of `NBO-SITE` already resets presence to the seed, so the scenario starts from the same place whatever the day did.

## 3. Recent movements (TWN-14)

`GET /api/sites/{id}/twin/movements`, for every role that reads the twin:
- the last 20 `SITE.PRESENCE` entries for the site, newest first, as `{at, kind, from, to}`. Zones are given as names; `from` is null for an arrival and `to` is null for a departure. No person id, label or name ever leaves the API.
- today's figures (since 00:00 Nairobi time): arrivals, departures, and visitors waiting now (in the lobby or the consular hall).

The strip refreshes on `SITE_UPDATED`.

## 4. The plan (TWN-12, TWN-16)

`screens/twin/motion.ts`, pure and tested:
- **A place per occupant:** a stable spot inside its zone, from a hash of the occupant's key, on a jittered grid. People don't overlap, and a dot keeps its place across refreshes.
- **Drift:** a few plan units of slow sine movement per dot, at its own phase.
- **A walk:** when an occupant's zone changes between two reads, the dot moves from its old place to its new one over 2 s, with ease-in-out (G-6).
- **Reduced motion or Calm mode:** no drift, and the dot jumps to its new place.

**The zone tint (§120 Q2):** each zone's fill gets a little stronger with its share of the people on site. The count stays in the corner, with "x / capacity" where a capacity exists.

`screens/twin/furniture.ts`: an outline set per zone kind, drawn as a faint SVG group under the dots and the coverage cones (G-9):
- OFFICE: desks;
- CONFERENCE: a table;
- CONSULAR: counters and seating;
- COMMS: racks;
- SAFE_ROOM: bunks and stores;
- LOBBY: a desk and seating;
- SUITE: a desk and sofa;
- GATE: a barrier;
- MUSTER: none.

## 5. The camera wall (TWN-15)

Each tile gets a corner label, "7 in zone · access control (simulated)", from presence. The generated views already draw walkers matching the zone's occupants (`cctv.ts` `walkers`, `people`). Over a clip, the same walkers are drawn on a transparent layer as stylised silhouettes (§120 Q3), never photographic. An offline camera still shows NO SIGNAL, with no figures.

## 6. Acceptance (§119)

`frontend/e2e/twa-acceptance.spec.ts` runs at the end of `make acceptance`, after the Exercise & Training run's reset, with the normal day switched on by the spec. It checks:
- within two minutes, a move appears in "Recent movements" and on the plan, for the Duty Officer and the Viewer, with no name;
- the matching `SITE.PRESENCE` audit row, and the chain verifies;
- `NBO-SITE` scene 2 pauses the day: no new movement while sheltering. Scene 3 resumes it.
- each key camera's tile count equals the plan's count for its zone.

Every other spec runs with the day off (G-2).

## 7. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | The presence consumer takes `SITE_PRESENCE` only from the scenario player (L5), so a separate simulator could not move people | The normal day is a worker task in the backend calling `twin.service.presence()` directly. The consumer's filter is unchanged, and no new event source is trusted |
| G-2 | **Needs a decision.** Where the "Normal day" switch lives, with no schema change | **A (proposed):** a Redis flag per tenant, `nexira:twin:normal-day:<tenant>`. Its initial value comes from the setting `TWIN_NORMAL_DAY` (`on` in `.env.example`); `make reset-demo` and `make acceptance` set it `off`. The presenter bar (demo mode) gets a "Normal day" switch, and changing it is audited (`SITE.NORMAL_DAY`). **B:** on whenever the demo is not running a scenario, with no switch, and the acceptance specs adapt to moving counts |
| G-3 | What pauses the day | Shelter-in-place at the site, an ACTIVE evacuation there, or an `NBO-SITE` run not yet complete, all worked out on each tick |
| G-4 | The day must not drift the site away from its seeded shape | A fixed script over the seeded occupants only, so totals stay in a band. `NBO-SITE` scene 1 resets to the seed |
| G-5 | Movements come from the audit log, which `audit.py` never reads | The twin service reads `audit_log` with SELECT (the app's grant), filtered to `SITE.PRESENCE` for the site. `audit.py` stays insert-only. The response holds kind and zones only |
| G-6 | The plan has no doors | A dot walks straight from its old place to its new one, over the shared wall where the zones touch |
| G-7 | Dots must not overlap or jump on each refresh | A stable spot per occupant from a hash of its key, on a jittered grid in the zone |
| G-8 | Figures over a real clip could read as people filmed | Flat, stylised silhouettes at reduced opacity, with "simulated" on the tile. Nothing is derived from the picture (§108 Q5) |
| G-9 | Furniture on small zones (Gate 2) gets cluttered | Outlines are scaled to the rectangle and left out below 60 × 40 plan units |
| G-10 | About 1,400 audit rows a day for the site (§120 Q4) | As decided. The chain verification stays well under a second at this volume, and the plan checks that in Prompt 138 |

## 8. Prompts

As `docs/prompts-pilot.md` Prompts 134–138. None is 🔒.

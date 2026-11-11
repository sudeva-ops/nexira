# Plan · Pilot module 26: UI polish pass

For the product owner and the coding agent. It maps UIP-01..UIP-08 (D-54; `docs/requirements-pilot.md` §121–125) onto the code after pilot module 25, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner.

Display only: no schema, API, role or permission change, so nothing here is 🔒 under D-29.

## 1. Requirements against existing code

| Req. | Exists today | New work | Prompt |
|---|---|---|---|
| UIP-01 Ticker | `app/Ticker.tsx` takes `useIncidents("ACTIVE")` and always doubles the items to loop; `tickerItems.ts` puts events first, then incidents in list order | Open incidents (ACTIVE and MONITORING) most severe first (G-1); scroll only when the items overflow (G-2); faded edges in CSS | 139 |
| UIP-06 Icons | `app/screens.ts`: `heart` twice (Health, Partners); `tick-circle` (Check-in) and `endorsed` (AAR) look alike | `symbol-cross` for Health, `helper-management` for Partners, `clipboard-file` for AAR (§125 Q4); a unit test that icons are unique | 139 |
| UIP-07 Audit in the sidebar | `AppShell.tsx` already leaves VIP out by `restricted: "vip"`; `AuditScreen` checks `hasRole(me, "ADMIN")` | `restricted: "admin"` on Audit, left out unless `hasRole(me, "ADMIN")` (G-5) | 139 |
| UIP-02 Header buttons | `IncidentDetail.tsx` `ReviewLink` reads "Open AAR-2026-1042" | "Open AAR" with the reference in its tooltip; header actions `nowrap` | 140 |
| UIP-03 Cut text | subtitles and source labels cut by CSS with no title | a small `Clip` component (ellipsis plus `title` with the full text) where text can be cut (G-3) | 140 |
| UIP-04 Camera row | `TwinScreen.tsx` renders the "All N cameras" button as a loose line | a small minimal button inside the CCTV row | 140 |
| UIP-05 Check-in | `CheckinScreen.tsx` names wrap; "Request partner" is a default-size button | names `Clip`ped; the button `size="small"` `variant="minimal"`; the phone header shortened to fit | 140 |
| UIP-08 Air globe | the air map box is short and wide | a taller map box, so the globe's outline is inside it at the starting zoom | 140 |
| Acceptance | — | `uip-acceptance.spec.ts`: every screen at two sizes (G-4) | 141 |

## 2. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | The ticker queries ACTIVE only; MONITORING needs a second status | Use the existing all-statuses list query and keep ACTIVE and MONITORING in the browser. No API change. Order: CRITICAL, HIGH, MODERATE, LOW, then newest |
| G-2 | Whether the items fit can only be measured in the browser | Measure the track against the viewport with a `ResizeObserver`; the choice itself is a pure function (`scrolls(track, view)`) with a Vitest test. Still when it fits, one copy of each item |
| G-3 | "Nothing cut without a way to read it" has no shared mechanism | `ui/Clip.tsx`: one line, ellipsis, and the full text as `title`. A native tooltip, so it works in every screen without Popover wiring. Used where the sweep found cut text and in panel subtitles |
| G-4 | A layout check on 25 screens could be slow or flaky | One signed-in page, each route at 1440 × 900 then 1920 × 1080, after the screen's first data loads. Checks: `scrollWidth <= clientWidth` on the document; panel header buttons no taller than one line; every element whose text overflows with an ellipsis has a `title` (or sits inside an element that has one). About two minutes; it runs in `make acceptance` before the Site Twin live activity spec, which stays last |
| G-5 | Hiding Audit must not look like a permission change | It is display only, as VIP-06 is: the API still refuses non-admins (D-04), and `/audit` opened directly still says "Administrators only". No change to `security.py` or `approvals.py` |
| G-6 | Unit tests and e2e may name the old button text | None found for "Open AAR-…" or the ticker. Tests that name "Request partner" keep their accessible name |

## 3. Prompts

As `docs/prompts-pilot.md` Prompts 139–141. None is 🔒.

## 4. After this module

The graphics module follows (resting states, charts, the incident mini-map, the globe's edge). For the globe, the product owner chose on 2026-11-11 to start with NASA Blue Marble and Black Marble imagery (public domain), self-hosted under D-24, and to look at paid options (MapTiler on-prem, EOX Sentinel-2 cloudless, Cesium self-hosted) only if that does not work.

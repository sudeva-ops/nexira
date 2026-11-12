# Plan · Pilot module 28: design consistency (panels, tiles, empty and loading states)

For the product owner and the coding agent. It maps DC-01 to DC-08 onto the code after pilot module 27 and lists the gaps found, each with a proposed answer. The requirements are D-56, in `docs/requirements-pilot.md` §131–135.

No schema or API change, and nothing here is 🔒 under D-29. Display code only. The Audit screen is restyled, but `audit.py`, the audit API and the chain are untouched.

## 1. Requirements against existing code

| Req. | Exists today | New work | Prompt |
|---|---|---|---|
| DC-08 Shared components | `ui/primitives.tsx`: `Card` (icon, title, sub, actions) and `Kpi` (with `trend`, GFX-07); `ui/Skeleton.tsx` `SkeletonRows` | `ui/Empty.tsx` (`Empty`), `Card` gains a `chip` prop (G-5), `ui/ContextLine.tsx` (`ContextLine`), `ui/TileRow.tsx` (`TileRow`, a 4- or 5-column grid replacing `nx-g4`, `nx-g5` and `nx-kpis`) | 147 |
| DC-03 Empty state | 70 `NonIdealState`s on 29 files; 29 dim sentences; whole-page empties on Safety Check-in and After-Action Review | `Empty` inside cards everywhere; `NonIdealState` kept only for errors, no access and not found (G-6) | 147 (cards); 148 (the two screens at rest) |
| DC-04 Loading | `SkeletonRows` in 53 places; `Spinner` in 15 places on 12 screens | `SkeletonRows` in panels; `Spinner` kept only in buttons and dialogs (G-7) | 147 |
| DC-05 Panels and header | `Card` everywhere but Audit and three raw `nx-card` sections (Operations map frame, proposal cards, Replay); header counts as a grey box, a chip or sub-text | `Card`'s `chip`; each header count moved to it, with plurals; Audit in cards (148). The map frame, proposal cards and Replay's stage stay raw: they are not panels | 147, 148 |
| DC-06 Context line | A line on Executive and Site Twin; informational banners on Decision Queue, AI Agents and Health; warning banners on 10 screens | `ContextLine` on Executive, Site Twin, Decision Queue, AI Agents and Health (G-8); warning banners unchanged | 147 |
| DC-07 Monospace | `.nx-log`, `.nx-mono` and a few lists set whole sentences in monospace | Sentences in the body font; monospace kept on times, references, codes and figures | 147 |
| DC-01 Tile rows | 17 screens have a row; Incidents, Playbooks, Predictive Risk and Audit have none; Safety Check-in and After-Action Review only once a check-in or review is open | A `TileRow` on each, from APIs the screen already calls (G-1 to G-4) | 148 |
| DC-02 Sparklines | 3 tiles (GFX-07) | The tiles in G-9 | 149 |
| DC-08 Check | `uip-acceptance` sweeps every screen as the Duty Officer | `dc-acceptance.spec.ts` sweeps every screen as the Administrator | 150 |

## 2. Gaps and proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Incidents' tiles.** | From `useIncidents()` (all, as the register loads): **Active** (with the highest severity), **Monitoring**, **Opened · 30 days** (sparkline per day, G-9) and **Signals fused** (the sum of `signal_count` over active incidents). Exercise incidents are counted apart, in the detail line, as the register marks them (EXR-03). |
| G-2 | **Response Playbooks' tiles.** | From `usePlaybooks()` and `useRuns()`: **Playbooks** (in the library), **Runs active**, **Waiting at a gate** (a run with a step `AWAITING_APPROVAL`) and **Runs · 30 days** (sparkline per day). Armed runs (HZ-05) count as active, with "armed" in the detail line. |
| G-3 | **Predictive Risk's tiles.** | From `usePredictiveOverview()`: **Missions rising** (`rising.length`), **Crossing the threshold** (`crosses`), **Highest peak** (with mission and day) and **Model** ("Illustrative", as the banner says). None counts over time, so no sparkline (G-9). |
| G-4 | **Audit, Safety Check-in and After-Action Review.** | **Audit**, from `useAuditVerify()` and `useAuditLog(200)`: **Entries** (`rows`), **Chain** (intact, or the first broken entry), **Entries · 24 h** (sparkline per hour) and **People acting · 24 h** (USER entries). The log loads 200 entries; if all 200 fall inside 24 hours, the figure shows "200+", not a wrong total. **Safety Check-in at rest**: its four tiles show "—" with "No check-in running"; the panels show their empty states. **After-Action Review**: **Reviews** (draft · final), **Ready for review**, **Findings** (`items`) and **Actions accepted** (`accepted`), all from `useReviews()`, at rest and with a review open. |
| G-5 | **One chip in a card header.** | `Card` gains `chip?: { text: string; tone?: "live" \| "ok" \| "warn" }`, drawn in today's `nx-chip` style on the right, before `actions`. A count says its noun with the right plural ("1 incident", "3 playbooks") through a shared `plural()` helper. |
| G-6 | **When a whole-page `NonIdealState` stays.** | Only for a screen that cannot work: a load error, no access (VIP Protection without the role) or a record not found. Everything else is `Empty` inside its card. `Empty` is a dim sentence in the body font, from one component, so its wording can say what appears and when. |
| G-7 | **Which spinners stay.** | The partners request dialog (an action running) and button loading states. The rest, in panels on 11 screens, become `SkeletonRows` sized to the panel. |
| G-8 | **The context line on each screen.** | `ContextLine` holds a sentence on the left and the screen's actions on the right. **Executive:** today's line and Export briefing. **Site Twin:** the site picker and "Illustrative floor plan (simulated)". **Decision Queue:** "N agents are watching…" and Agent console (the red kill-switch banner stays). **AI Agents:** the active sentence (the red paused banner stays). **Health:** its note. Predictive Risk's "Model output is advisory" stays a banner, as DC-06 names it. Other screens get no line: there is nothing to say there that the top bar's SIMULATED DATA does not. |
| G-9 | **Which tiles get sparklines (DC-02).** | A tile whose figure counts events over a period, where the screen already loads their times: **Mass Notification**'s three "· 24h" tiles (per hour, from campaigns' `sent_at`; failures from deliveries); **AI Agents**' Proposals (per hour over 24 hours); **Exercise & Training**'s "Exercises · year" (per month); and the new **Incidents** "Opened · 30 days", **Playbooks** "Runs · 30 days" and **Audit** "Entries · 24 h". Tiles that hold a state (counts now, percentages, scores) get none. The campaign list has delivery counts per campaign but no time for each delivery, so the delivered and failed sparklines put each campaign's counts in the hour it was sent; their labels say "by the hour sent". |

## 3. Prompts

As `docs/prompts-pilot.md` Prompts 147–150. None is 🔒.

## 4. After this module

The /usage fixes, then the parked items (the product name, a local Copilot model, the agent model choice, the captions).

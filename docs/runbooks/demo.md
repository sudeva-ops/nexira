# Running the NEXIRA demo

For whoever presents the demo on a laptop. Everything runs locally on simulated data (D-19): no real people, no real messages, no internet needed once set up. Steps marked **(once)** are done the first time only.

## 1. Set up (once)

1. Install Docker Desktop, `uv` (Python) and Node 20. Give Docker at least 6 GB of memory.
2. In the repository folder:
   ```sh
   make up        # creates .env from .env.example, builds and starts every container
   make tiles     # downloads the offline map (about 90 MB), once
   ```
3. Check `.env`: `APP_ENV=local` (or `demo`) and `VITE_DEMO_MODE=true`. The demo users' password is `DEMO_USER_PASSWORD` in `.env`.

## 2. Before every demo (5 minutes)

1. **Keep the Mac awake.** In a terminal, leave `caffeinate -dims` running (stop it with Ctrl-C afterwards). Plug in the charger.
2. **Start from a clean state:**
   ```sh
   make up
   make reset-demo   # wipes the local demo database and loads fresh data (D-21)
   ```
   Do this before every demo: scenarios move data forward (an incident stays, a landed flight is final).
3. **Check it works** (optional, about 4 minutes, then reset again):
   ```sh
   make acceptance   # plays every storyline automatically; expect "4 passed"
   make reset-demo
   ```
4. **Open browser windows** at http://localhost:3000, one per person in the story. Use a separate browser profile or a private window for each, so the sign-ins do not mix:

   | Window | User | Plays |
   |---|---|---|
   | A | `duty.officer` (Daniel Mercer) | Operations, drives the presenter bar |
   | B | `hom.nairobi` (Layla Haddad) | Head of Mission, Nairobi |
   | C | `hq.director` (Miriam Okafor) | HQ Crisis Director |
   | D | `consular.officer` (Anika Shah) | Second person for citizen messages |
   | E | `travel.desk` (Tomas Reyes) | Plans trips |
   | F | `security.officer` (Leila Nasser) | Approves risky trips |

   The **presenter bar** (bottom of window A) shows only for `duty.officer` or `admin` in demo mode. Its drop-down picks the scenario; **→ (Next scene)** moves on and opens the screen to watch.

## 3. Storyline 1 · Nairobi civil unrest (about 10 minutes)

Scenario **Nairobi civil unrest** (NBO-CIVIL-UNREST, decisions.md §7). In window A:

| Scene | Click | What to show |
|---|---|---|
| 0 Calm | — | Decision Queue: "No decisions waiting". Global Operations: all missions normal. |
| 1 Signals fused | → | Global Operations: three reports fuse into one incident, INC-…-1042, confidence 92, in about a second. A Paris transport strike stays separate. |
| 2 Impact | → | Click the incident marker: 229 people (14 staff, 3 delegates, 212 citizens), 3 sites, 1 trip; severity CRITICAL because the embassy is in the zone. Journey Management: TRP-8812 shows "Impacted · INC-…-1042". Decision Queue: the **Travel & Air** agent proposes a safety message to TRP-8812's travellers and a notice for TRP-8818 ("risk now CRITICAL"); window E (Travel Desk) can approve them. |
| 3 Playbook | → | Decision Queue: the Response Planner proposes PB-07. Approve as Duty Officer. The playbook runs to step 7 and waits. In **window B** (Head of Mission) open Response Playbooks and approve step 7. Back in A: the Communications agent proposes the citizen advisory; approve it. |
| 4 Check-in | → | Safety Check-in: answers arrive live: personnel 15 safe, 1 needs help, 1 pending; citizens 168 / 4 / 40. Hana Takeda, who did not answer, is escalated after 20 seconds. |
| 5 Decisions | → | Two-person rule. In a terminal: `cd simulator && APP_ENV=local uv run python -m nexira_sim.fixtures.evacuation` (adds an evacuation proposal). Window B approves step 1 of 2; she cannot approve step 2. **Window C** (HQ Crisis Director) approves step 2. |
| 6 Review | → | Incidents: set INC-…-1042 to MONITORING. Audit (admin): the chain verifies. |

## 4. Storyline 2 · Mass Notification and France (about 5 minutes)

1. In window A, pick **France protests** in the presenter bar and press → once. Global Operations: a Paris incident (CRITICAL, embassy exposed).
2. Window A, **Mass Notification**: Kind *Advisory*, add mission *PAR · Paris*, person type *Citizens*, template *Civil unrest: shelter in place*. The text names central Paris. **Save draft**, then **Send test to me** (a phone preview; nothing is sent).
3. **Submit for approval.** It waits: citizens need a second person (D-31). The Duty Officer cannot approve their own campaign.
4. **Window D** (Consular Officer): open the campaign and **Approve and send**. The delivery funnel fills live to "read" for every channel (simulated).

## 5. Storyline 3 · Journey Management (about 5 minutes)

Best right after storyline 2, while the Paris incident is active.

1. **Window E** (Travel Desk), Journey Management, **Plan a trip**: to Paris, country FR, dates next week, two travellers, one flight segment. **Save draft**.
2. The destination risk shows France raised to CRITICAL by the Paris incident. **Submit for approval**: it rates HIGH or above and waits. The Travel Desk sees no Approve button: it is the requester, and HIGH needs a Security Officer.
3. **Window F** (Security Officer): open the trip. Approve is missing until the four checklist boxes are ticked (the screen says why). Tick them, then **Approve trip**. Window E updates live to Approved.
4. Mention the restricted switch: a VIP or ministerial trip planned "restricted" is never tracked, and others see its flights only as "Flight (restricted)".
5. **Travel & Air agent.** The France scenario also raised the risk of TRP-8811 (Berlin staff to Paris next week, approved at LOW). Decision Queue: "Cancel TRP-8811 Paris · risk now CRITICAL", with "Notify the travellers instead" as an alternative. Only the Security Officer (window F) can approve it; the trip then shows Cancelled in Journey Management. The agent never proposes anything about restricted trips.

## 6. Storyline 4 · Air Travel Tracking (about 4 minutes)

1. Window A, **Air Travel Tracking**: the live air picture shows the tracked flights (two real-time background flights and XW 451, scheduled). Point out the Safeguards card.
2. Presenter bar: pick **Inbound flight diversion** and press →: XW 451 (Abu Dhabi → Nairobi, three London staff) is airborne.
3. → : **Holding** near Nairobi, amber banner.
4. → : **Diverted** to Mombasa, red banner, a new leg on the map; about a minute later it **lands**. Click XW 451: the event timeline. In People & Sites, its three travellers are now in Mombasa (source: flight).
5. **Travel & Air agent.** XW 451's detail lists the agent's proposals: notify its travellers (holding, then diverted) and "Arrange onward travel" in Mombasa, which is advice only (the platform books nothing). In the Decision Queue, window E (Travel Desk) approves a notification: a staff alert goes to the three travellers (simulated); Mass Notification shows it as "A trip's travellers (Travel & Air)". AI Agents lists Travel & Air with what it proposes and who decides.

XW 451 can land only once. To show it again, run `make reset-demo`.

## 7. If something goes wrong

| Symptom | Fix |
|---|---|
| A page shows "Base map not installed" | `make tiles`, then reload. |
| No presenter bar | Sign in as `duty.officer` or `admin`; check `VITE_DEMO_MODE=true` in `.env`, then `make up`. |
| "Live" indicator is grey | The page lost its connection; reload. If it persists, `make up`. |
| A scenario does nothing, or XW 451 stays landed | The scenario was already played: `make reset-demo` and sign in again. |
| Manila's weather stays stormy after the storm scenario | A scenario's conditions hold for 6 hours (plan-pilot-wx G-1); `make reset-demo` clears them. |
| No weather incidents for dust storms or heat, or the storm stays separate from Dataminr's report | The database was seeded before the Weather module, and new source categories are added only to a fresh seed (plan-pilot-wx G-2): `make reset-demo`. |
| Everything is slow or stuck after the laptop slept | `make up`, then `make reset-demo`; keep `caffeinate -dims` running. |
| Logs | `make logs` (the worker shows signals, exposure, flights and agents). |

## 8. Talking points

- **Agents propose, people decide.** Every agent action goes through the Decision Queue with the right role (D-12 to D-17); the kill switch on AI Agents stops all proposals.
- **Two people for what matters.** Citizen messages, risky trips and evacuation steps need a second person, enforced by the database as well as the screen.
- **Nothing real.** Channels, flights, risk scores and intelligence feeds are simulated and labelled so (D-19); no external service is called at runtime.
- **Everything is audited.** The audit chain is hash-linked by the database and verifies at any time (Audit screen, admin).

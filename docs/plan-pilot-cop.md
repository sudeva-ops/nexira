# Plan · Pilot module 19: AI Risk Copilot, simulated

For the product owner and the coding agent. It maps COP-01..08 and D-50 (`docs/requirements-pilot.md` §94–98) onto the code after pilot module 18, and lists the gaps found, each with a proposed answer. Items marked **needs a decision** wait for the product owner.

The Copilot has two halves. **Grounding** is real: facts come only from the platform's read functions, run as the asker. **Wording** is simulated: templates behind `app/core/llm.py`. Nothing is stored except audit rows, and nothing in it is 🔒 (D-29).

## 1. Requirements against existing code

| COP | Exists today | New work | Prompt |
|---|---|---|---|
| 01 Ask | Read functions: `intel.queries.list_incidents`, `get_incident` (exposure summary, timeline); `checkin.service.tally`; `playbooks.queries.list_runs`; the agents' `proposal_out` with `can_decide`; `people.queries.list_missions`; `predictive.service.overview`; `exercises.queries.readiness`; the travel API's trip list | `copilot/intents.py` (§2), `copilot/facts.py` (§3), `POST /api/copilot/ask` | 118 |
| 02 Cited | References on every record (INC-, NTF-, PB-, TRP-, proposal ids) and a screen for each | `Source` on every sentence, with its screen link (§3) | 118 |
| 03 Access | RLS (D-01, D-02), `approvals.user_has_role`, the travel API's restricted-trip rule (D-33) | the facts call the same functions as the asker; names per G-1 | 118 |
| 04 Report | The design's headings; print-ready exports (AAR, Executive briefing) | `copilot/report.py` (§4), `POST /api/copilot/report`, `/report/export` | 119 |
| 05 Simulated | `LLM` protocol and `StubLLM` in `app/core/llm.py`; no model is called | a `Writer` protocol beside `LLM`, and `TemplateWriter` (§5) | 118 |
| 06 Audited | `audit.py` | `COPILOT.ASK`, `COPILOT.REPORT_EXPORT` | 118, 119 |
| 07 Screen | Blueprint dark; `Card`; the design's chat layout | `/copilot` (§6) | 120 |
| 08 Demo | The Phase 1 run; `make acceptance` | `cop-acceptance.spec.ts` (§7) | 121 |

New backend module: `app/modules/copilot/{intents,facts,report,schemas,router}`, with no models and no migration.

## 2. Question types (COP-01, §98 Q2–Q3)

Matching is deterministic, in this order. The first type that matches wins.

| Type | Matches | Answers from |
|---|---|---|
| `HELP` | "help", "what can you", empty | the list and examples |
| `REPORT` | "situation report", "sitrep", "brief(ing)" + an incident | §4 |
| `PEOPLE` | "check-in", "responded", "accounted", "safe", "who has not" | the incident's latest CHECKIN campaign: `tally`, and the pending and need-help people (G-1) |
| `DECISIONS` | "decision", "approve", "waiting", "pending" | the asker's PENDING proposals, oldest deadline first, with `can_decide` |
| `TRAVEL` | "trip", "travel", "traveller", "flight" | unrestricted trips in the incident's exposure (D-33) |
| `READINESS` | "readiness", "exercise", "drill" + a mission | `exercises.queries.readiness` |
| `RISK` | "risk", "elevated", "forecast", "this week" | missions at MODERATE or above, and the forecast's rising missions |
| `INCIDENT` | an incident reference (`INC-\d{4}-\d+`), or a mission's code or city with an incident | `get_incident`: severity, place, confidence, exposure, the latest status |
| `SITUATION` | "situation", "summar", "what is happening", "overview" | ACTIVE incidents, worst first, each with exposure and its check-in |
| `UNKNOWN` | anything else | "I can't answer that yet", the list, no source |

- **Subjects:** an incident is found by reference first, then by a mission's code or city (`list_missions`) matched to the incident at that mission (worst ACTIVE, then the latest). "The Nairobi situation" resolves to INC-<year>-1042.
- **Exercise incidents** are included and labelled "(exercise)" in every sentence about them (D-48).

## 3. Facts and sources (COP-02, COP-03)

- **Facts as the asker.** `facts.py` returns typed facts (`IncidentFact`, `CheckinFact`, `DecisionFact`…), each carrying its `Source` (`kind`, `reference`, `href`, for example `{"INCIDENT", "INC-2026-1042", "/incidents?id=…"}`). Facts are built only by calling the read functions above in the asker's session, so RLS and the same role checks apply.
- **Sentences.** An answer is a list of sentences, and each sentence lists the sources of the facts it uses. A sentence without a source is a bug, and the tests fail on it.
- **Restricted trips** are filtered as the travel API does (D-33). They never become facts.

## 4. The situation report (COP-04, §98 Q6)

`report.py` builds the design's sections from the incident's record:

- **Summary:** category, place, severity, confidence and the number of sources (`get_incident`).
- **Our people:** exposure (staff, delegates, citizens) and the check-in tally. Names follow G-1.
- **Actions taken:** playbook steps DONE (`list_runs`), campaigns sent, proposals approved.
- **Related risks:** the mission's drivers as the Executive Overview reads them: health advisory, supply impacted, vehicles blocked, shelter-in-place.
- **Recommendations:** stated rules, labelled "Rule-based recommendations":

  | Condition in the record | Recommendation |
  |---|---|
  | people not yet accounted for | "Follow up the N people not yet accounted for." |
  | someone needs help | "Confirm assistance for the person who asked for help." |
  | a protected site in the zone | "Keep the mission closed to the public." |
  | always | "Reassess at the next check-in or on escalation." |

- **Sources:** every source cited above.

The export (`POST /api/copilot/report/export`) returns the same report for a print-ready page. It is audited `COPILOT.REPORT_EXPORT` with the incident reference, as the AAR export is.

## 5. The composer behind `llm.py` (COP-05)

- **Two protocols.** `app/core/llm.py` keeps `LLM`, and gains `Writer` with one method: `write(kind, facts) -> list[Sentence]`. `TemplateWriter` is the simulated one, with one template per question type and report section.
- **Swapping in a model later.** A `ModelWriter` would render the facts with their source ids into a prompt for the local model, and keep only sentences that cite ids it was given. The grounding and API do not change.
- **No external calls.** No HTTP client is added and the module makes no external call. A test asserts the module has no network import.
- **The label** is on every answer: "Simulated copilot · rule-based wording · simulated data".

## 6. The screen (COP-07, §98 Q8)

- **Route and nav:** `/copilot`, "AI Risk Copilot" (icon `chat`), subtitle "Grounded on live platform data", under RESPOND after Safety Check-in. The view is full height, as the design.
- **Left: the conversation.**
  - The empty state: "How can I help the operations centre?"
  - Three suggestions: "Summarise the Nairobi situation", "Which missions are at elevated risk this week?", "Who has not responded to the check-in?"
  - The composer: "Ask NEXIRA anything…"
  - Each answer shows its sentences, with source chips linking to the records, and the simulated label.
- **Right:**
  - **Grounding context:** active incidents, check-ins, playbook runs and missions, each lit when the platform holds one. It reads the existing queries.
  - **Guardrails:** the design's four lines.
  - **After a report:** "Export as PDF", which opens the print page. There is no "Send" (§98 Q6).
- **State:** the conversation is React state in the tab and is gone on reload (COP-06).

## 7. Acceptance (COP-08, §97, §98 Q9)

- **A new file, `frontend/e2e/cop-acceptance.spec.ts`.** It runs in `make acceptance`'s second command, before the After-Action Review spec (G-3).
- **It reads INC-<year>-1042 as the Phase 1 run left it.** It checks:
  - **Situation:** "Summarise the Nairobi situation" cites INC-<year>-1042, 229 exposed and 15 / 1 / 1, matching `/api/incidents/{id}` and the check-in summary.
  - **Names:** names for the Duty Officer and the count for the Viewer, as G-1 decides.
  - **Unknown question:** declined with no source.
  - **Report:** it has every heading and cites its sources; the export is audited.
  - **Audit:** `COPILOT.ASK` rows hold the type and references and never the text; the chain verifies.
  - **Network:** no request leaves the stack, checked with Playwright's request log.
- **It changes nothing.** The spec only reads, apart from audit rows, so the AAR spec that follows still finds the incident ACTIVE.

## 8. Gaps and conflicts, with proposed answers

| # | Gap | Proposed answer |
|---|---|---|
| G-1 | **Decided: A** (PR #152). Today every role, the Viewer included, sees names on the check-in list (`GET /api/checkin/{id}/people`). So COP-03 ("names only where that role sees them today") would show names to the Viewer, which contradicts COP-08 and §97 ("only counts for a role that does not see names") | **A (proposed):** the Copilot names people only to roles that may record answers (`RESPOND_ROLES`: Duty Officer, Security Officer, Consular Officer, Head of Mission, HQ Crisis Director). Everyone else gets counts. It is stricter than the screen and matches §97. **B:** as the screens, so the Viewer gets names, and §97's Viewer line is dropped |
| G-2 | "The Nairobi situation" has no reference in it | Mission code or city matched to the mission's incident (§2) |
| G-3 | §98 Q9 puts the Copilot inside the Phase 1 run, but `acceptance.spec.ts` is long and moves on to scenes 5–6 | A separate spec after the first batch, reading the record the Phase 1 run left (MONITORING, check-in 15 / 1 / 1). The figures are the same as after scene 4 |
| G-4 | "Related risks" in the design names cyber cases (CPX), which the pilot does not have | The mission's drivers that exist (§4). No cyber line |
| G-5 | `LLM.complete(prompt) -> str` cannot carry citations | The `Writer` protocol beside it (§5). `llm.py` is not 🔒 |
| G-6 | Exercise incidents | Included and labelled "(exercise)" (D-48). Unlike the Executive Overview, the Copilot answers operational questions |

## 9. Prompts

As `docs/prompts-pilot.md` Prompts 118–121. None is 🔒.

## 10. Decisions by the product owner (2026-11-10, PR #152: "approved a")

- G-1: option A. The Copilot names people only to the roles that may record check-in answers (`RESPOND_ROLES`); every other role gets counts.
- G-2..G-6: as proposed.

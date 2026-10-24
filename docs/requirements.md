> **Note (v0.2):** where this document conflicts with `docs/decisions.md`, the decisions file wins.
> In particular, the acceptance criteria for **INC-02** (see D-11) and **INC-05** (see D-23) are replaced.

NEXIRA

Global Resilience Platform

Product Requirements Document · Phase 1 (MVP)

| # | Item | Detail |
|---|---|---|
| 1 | Document | NEXIRA Product Requirements – Phase 1 |
| 2 | Version | 0.1 (draft for review) |
| 3 | Date | October 2026 |
| 4 | Status | Draft – for internal review |
| 5 | Classification | Internal |
| 6 | Companion files | nexira_schema.sql · NEXIRA_Phase1_Prompts.md · NEXIRA_Demo_Full.html |

# 1. Purpose and scope

NEXIRA is a sovereign, modular resilience platform for organisations with people, sites and travellers in many countries. The first target customer type is a ministry of foreign affairs with missions, diplomats and registered citizens abroad.

This document defines the requirements for Phase 1: a working MVP that runs on simulated data, reproduces the demo scenario end-to-end with a real backend, and is ready to connect the first real data feeds in Phase 2.

## 1.1 Phase 1 goals

- Prove the core loop: detect → assess exposure → recommend → human decides → act → account for people → audit.

- Replace the static demo with a real application (database, APIs, realtime updates, login and roles).

- Introduce AI agents that propose actions, with enforced human approval for consequential actions.

- Be deployable in-country (on-premise or sovereign cloud) from day one.

## 1.2 In scope

| # | Module | Phase 1 scope |
|---|---|---|
| 1 | Decision Queue | Agent proposals with approve / edit / reject, two-person approval, deadlines, undo |
| 2 | AI Agents | 4 agents, autonomy levels, policy floors, kill switch |
| 3 | Global Operations | Map, missions, incidents, impact zone, people in zone, live feed, KPIs |
| 4 | Incidents | Signal ingestion, normalisation, fusion, exposure, timeline |
| 5 | People & Sites | Missions, sites, people, location confidence |
| 6 | Response Playbooks | Playbook definitions, runs, approval gates, audit trail |
| 7 | Safety Check-in | Check-in campaigns, responses, accountability summary |
| 8 | Platform | Login, roles, tenancy, audit log, scenario engine, simulated channels |

## 1.3 Out of scope (later phases)

Journey Management, Air Travel Tracking, Local-Language OSINT, Cyber-Physical, Health Intelligence, Natural Hazards, Mass Notification composer, Evacuation Management, Consular Portal, VIP Protection, Fleet, Assistance Partners, Site Twin, Wellbeing, Continuity & Compliance, Predictive Risk, Supply Chain, Document Expiry, Exercises, After-Action Review, Executive Overview, AI Risk Copilot chat. Real SMS/email/WhatsApp delivery and real intelligence feeds are Phase 2.

# 2. Users and roles

| # | Role | Responsibilities in Phase 1 |
|---|---|---|
| 1 | Duty Officer | Monitors operations, approves standard proposals, starts playbooks and check-ins |
| 2 | Security Officer | Approves security-related proposals and playbook steps |
| 3 | Head of Mission | Approves mission-level gates (e.g. evacuation route), first approver for evacuation |
| 4 | HQ Crisis Director | Second approver for senior actions (evacuation, mission closure) |
| 5 | Travel Desk | Approves travel-related proposals (Phase 2 onwards) |
| 6 | Consular Officer | Citizen-related actions (Phase 2 onwards) |
| 7 | Administrator | Users, roles, agent autonomy, scenarios, audit access |
| 8 | Viewer | Read-only access |

Roles may be scoped to a mission (e.g. Head of Mission for Nairobi only). Role checks are enforced in the backend; the UI only hides actions the user cannot take.

# 3. Functional requirements

Priority: M = Must (Phase 1 acceptance), S = Should, C = Could.

## 3.1 Platform, identity and audit

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | PLT-01 | Users sign in through OIDC (Keycloak or Entra ID); sessions expire per policy | M | Login works for each demo role; expired token rejected |
| 2 | PLT-02 | Role-based access enforced on every API endpoint, optionally scoped to a mission | M | Forbidden actions return 403 and are not shown in the UI |
| 3 | PLT-03 | All data is tenant-scoped with database row-level security | M | Cross-tenant read test returns no rows |
| 4 | PLT-04 | Every state-changing action is written to an append-only, hash-chained audit log | M | Audit rows cannot be updated or deleted; chain verifies |
| 5 | PLT-05 | Realtime updates are pushed to open screens within 2 seconds | M | New incident appears on the map without refresh |
| 6 | PLT-06 | Scenario engine plays, pauses, steps and resets scripted scenarios | M | Nairobi scenario replays scenes 0–6 deterministically |

## 3.2 Incidents and intelligence

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | INC-01 | Ingest raw signals from connectors (simulated in Phase 1) into a common format | M | Signals stored with source, time, location, original severity |
| 2 | INC-02 | Normalise category and severity per source using configurable maps | M | 'High', 'Level 4', 'Moderate' map to HIGH for the Nairobi case |
| 3 | INC-03 | Fuse signals of the same category within 3 km and 60 min into one incident | M | Three Nairobi signals → one incident; Paris signal stays separate |
| 4 | INC-04 | Compute confidence from number and independence of sources | M | Formula documented; Nairobi incident ≥ 90% |
| 5 | INC-05 | Compute exposure of people, sites and trips within the impact radius | M | 14 staff + 3 delegates + 2 sites returned for Nairobi |
| 6 | INC-06 | Incident detail shows source normalisation table and timeline | M | Matches demo layout |
| 7 | INC-07 | Users can change status (Active / Monitoring / Closed) and add notes | S | Change audited and shown on timeline |

## 3.3 People and sites

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | PPL-01 | Maintain missions, sites and people (diplomats, local staff, dependants, delegates, citizens) | M | Seeded data browsable and searchable |
| 2 | PPL-02 | Store location observations from multiple sources | M | GPS, access control, booking, calendar, check-in supported |
| 3 | PPL-03 | Location Confidence Engine computes current location and confidence (0–100) | M | Hana Takeda shows 72% from calendar data, as in the demo |
| 4 | PPL-04 | Search and filter people and sites | M | Free-text filter across name, role, mission |

## 3.4 Global Operations

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | OPS-01 | Map shows missions coloured by risk, incidents with impact zone, people in zone | M | Matches demo; offline map style supported |
| 2 | OPS-02 | Live feed of normalised signals and fused incidents | M | Raw signals visibly merge into one incident |
| 3 | OPS-03 | KPI strip: missions, personnel, travellers, alerts, posture | M | Values computed from data, not hard-coded |
| 4 | OPS-04 | Impact panel lists linked people with confidence and source | M | Clicking incident opens panel |

## 3.5 Playbooks

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | PB-01 | Define playbooks with ordered steps, action types and trigger rules | M | PB-07 seeded with 8 steps |
| 2 | PB-02 | Run a playbook for an incident; execute steps in order | M | Steps progress with timestamps |
| 3 | PB-03 | Steps can require approval by a role; run pauses until approved | M | Step 7 waits for Head of Mission; Duty Officer cannot approve |
| 4 | PB-04 | Each step outcome written to incident timeline and audit log | M | Entries visible in the audit trail panel |

## 3.6 Safety check-in

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | CHK-01 | Create a check-in campaign for exposed people via selected channels | M | Campaign created by playbook step 5 |
| 2 | CHK-02 | Record responses (Safe / Need help) from app, simulator or API | M | Responses update live |
| 3 | CHK-03 | Show accounted %, safe, need help, no response; escalate non-responders | M | Scenario ends at 15 safe, 1 need help, 1 pending |
| 4 | CHK-04 | Channel adapters are pluggable; Phase 1 uses a simulated adapter | M | No real messages sent |

# 4. AI agents and human-in-the-loop

## 4.1 Phase 1 agents

| # | Agent | Trigger | Output | Default level |
|---|---|---|---|---|
| 1 | Watch Officer | Incident created | Informational proposal (logged) | Auto |
| 2 | Exposure | Exposure computed | Exposure summary (logged) | Auto |
| 3 | Response Planner | Incident matches playbook trigger | Propose START_PLAYBOOK | Approve |
| 4 | Communications | Shelter-in-place step done | Propose multilingual citizen advisory | Approve |

## 4.2 Autonomy levels

| # | Level | Behaviour |
|---|---|---|
| 1 | 0 · Auto | Executes immediately and is logged |
| 2 | 1 · Auto + notice | Executes; a human can undo within a set window |
| 3 | 2 · Approve | One named approver with the required role |
| 4 | 3 · Senior approval | Approvers in order (two-person rule) |
| 5 | 4 · Advise only | Never executable by the agent |

## 4.3 Requirements

| # | ID | Requirement | Pri. | Acceptance criteria |
|---|---|---|---|---|
| 1 | AGT-01 | Each proposal contains title, proposed action, machine payload, evidence with sources, alternatives, risk if no action, confidence, deadline | M | All fields shown on the card |
| 2 | AGT-02 | Effective level = max(agent level, action policy floor) | M | Agent set to Auto still needs approval to send external messages |
| 3 | AGT-03 | Approve, edit-and-approve, reject (with reason), use alternative, undo | M | Each action audited; reason stored |
| 4 | AGT-04 | Two-person rule for evacuation and mission closure | M | One approval does not execute |
| 5 | AGT-05 | Approved actions execute through the same services users call | M | No agent code calls channels or databases directly |
| 6 | AGT-06 | Overdue proposals expire and escalate | M | Escalation event raised at deadline |
| 7 | AGT-07 | Kill switch pauses all agents; platform falls back to manual playbooks | M | No new proposals while paused |
| 8 | AGT-08 | Administrators set autonomy per agent | M | Change audited |
| 9 | AGT-09 | LLM access only through an internal gateway supporting local models | S | Tests run with a stub; no external AI calls |

# 5. Non-functional requirements

| # | Area | Requirement |
|---|---|---|
| 1 | Sovereignty | Deployable on-premise, sovereign cloud or air-gapped; no dependency on public SaaS at runtime |
| 2 | Security | OIDC + MFA; TLS 1.3 in transit; AES-256 at rest; secrets in a vault; OWASP ASVS L2 as target |
| 3 | Privacy | Personal data minimised; welfare and medical data restricted by role (later phases) |
| 4 | Audit | Append-only, hash-chained audit log; retention configurable (default 7 years) |
| 5 | Performance | Signal to fused incident ≤ 5 s; incident to exposure ≤ 5 s; UI update ≤ 2 s |
| 6 | Scale (Phase 1) | 50 concurrent users; 10,000 people; 1,000 signals per hour |
| 7 | Availability | Target 99.9% for pilot; daily backups; documented restore |
| 8 | Usability | Dark operations theme, keyboard-friendly, works at 1440×900 and above; English first, Arabic-ready (RTL) |
| 9 | Quality | Automated tests for every feature; lint and type checks in CI |

# 6. Data model summary

Full definition: nexira_schema.sql (PostgreSQL 16 + PostGIS).

| # | Area | Main tables |
|---|---|---|
| 1 | Tenancy & access | tenant, app_user, role, user_role |
| 2 | People & places | mission, site, person, location_observation, person_location_current |
| 3 | Travel | trip, trip_traveller |
| 4 | Intelligence | intel_source, raw_signal, incident, incident_signal, incident_exposure, incident_event |
| 5 | Response | playbook, playbook_step, playbook_run, playbook_run_step |
| 6 | Communications | notification_campaign, notification_delivery, checkin_response |
| 7 | Agents | agent, action_policy, agent_proposal, proposal_approval |
| 8 | Audit & simulation | audit_log, scenario, scenario_event, scenario_run |

# 7. Technical architecture

| # | Layer | Phase 1 choice |
|---|---|---|
| 1 | Frontend | React 18 + TypeScript, Blueprint (dark), MapLibre GL, TanStack Query |
| 2 | Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| 3 | Database | PostgreSQL 16 + PostGIS 3, row-level security |
| 4 | Realtime | Redis Streams internally; WebSockets to browsers |
| 5 | Identity | Keycloak (OIDC); Entra ID supported |
| 6 | AI | Internal LLM gateway; local models via vLLM or Ollama; rule-based agents first |
| 7 | Deployment | Docker; docker-compose locally; Kubernetes / OpenShift for pilot |

# 8. Integrations

| # | Integration | Phase 1 | Phase 2 |
|---|---|---|---|
| 1 | Threat intelligence feeds | Simulated connector | First real feed (one provider) |
| 2 | HR / personnel | Seed data | HR system import |
| 3 | Access control / GPS | Simulated observations | Mobile app GPS + one access-control system |
| 4 | SMS / email / app push | Simulated adapter | One SMS gateway + email |
| 5 | Identity | Keycloak demo realm | Customer IdP |

# 9. Milestones and acceptance

| # | Milestone | Exit criteria | Indicative timing |
|---|---|---|---|
| 1 | M1 Foundation | Repo, CI, docker-compose, login, schema migrated | Weeks 1–2 |
| 2 | M2 Data & simulator | Seed data loaded; Nairobi scenario replays | Week 3 |
| 3 | M3 Incidents & map | Fusion, exposure, Global Ops, Incidents, People screens | Weeks 4–6 |
| 4 | M4 Response | Playbooks, check-in, audit trail | Weeks 7–8 |
| 5 | M5 Agents | Decision Queue, 4 agents, policy engine, kill switch | Weeks 9–10 |
| 6 | M6 Pilot-ready | Security review, deployment to test environment, end-to-end demo | Weeks 11–12 |

Phase 1 acceptance: the full Nairobi scenario runs end-to-end on the real application, with every decision approved by a logged-in user with the correct role, and every action visible in the audit log.

# 10. Assumptions, risks and open questions

## 10.1 Assumptions

- Phase 1 uses fictional data only; no customer data is processed.

- A pilot customer will provide access to one intelligence feed, an HR extract and an SMS gateway for Phase 2.

- 1–2 developers working with AI coding tools, plus part-time product, security and design input.

## 10.2 Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Third-party feed licensing restricts use | Confirm commercial terms before Phase 2 |
| 2 | AI-generated code quality or security gaps | Rules file, tests on every task, human review of auth, approvals and messaging |
| 3 | Agents act without proper approval | Policy floors enforced in backend; automated tests; kill switch |
| 4 | Sovereign hosting constraints | Container-only stack; no runtime SaaS dependencies |

## 10.3 Open questions

- Which identity provider will the pilot customer use?

- Which intelligence provider will be connected first?

- Required data residency and classification level for the pilot environment?

- Who owns approval roles at HQ (Crisis Director equivalent)?

- Arabic UI required in Phase 1 or Phase 2?

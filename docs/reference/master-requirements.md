> Reference only: all-phases specification. Phase 1 work follows `docs/requirements.md` and `docs/decisions.md`.

NEXIRA

Global Resilience Platform

Master Requirements Specification · All Phases

| # | Item | Detail |
|---|---|---|
| 1 | Document | NEXIRA Master Requirements Specification (all phases) |
| 2 | Version | 1.0 (consolidated baseline) |
| 3 | Date | October 2026 |
| 4 | Status | Baseline for internal record and review |
| 5 | Classification | Internal |
| 6 | Purpose | Single record of all requirements and their history, from concept through Phase 4 |
| 7 | Related files | NEXIRA_Requirements_Phase1.docx · nexira_schema.sql · NEXIRA_Phase1_Prompts.md · NEXIRA_Demo_Full.html · Resilience_Platform_Architecture.pdf |

# 1. Document control and requirements history

This section records how the requirements evolved, so later readers can see why each capability exists and when it was introduced.

## 1.1 Revision history

| # | Ver. | Stage | What changed |
|---|---|---|---|
| 1 | 0.1 | Market scan | Reviewed Restrata resilienceOS and its intelligence partners (Dragonfly, MAX Security, Factal, Samdesk, Signal, Dataminr, Healix, Riskline, xWeather) and competitors (Everbridge, Crisis24, International SOS, AlertMedia, Noggin, WorldAware, Global Guardian, Sicuro, iluminr). |
| 2 | 0.2 | Module concept | Defined 12 modules: 7 core (aggregation hub, people & asset visibility, location confidence, risk & journeys, incident management, GSOC dashboard, open APIs) and 5 gap-fillers (mass notification, check-in & SOS, assistance marketplace, local-language OSINT, BCM & compliance). |
| 3 | 0.3 | Competitive set | Added 8 differentiators (AI copilot, predictive analytics, automated playbooks, supply chain, cyber-physical, digital twin, sovereign deployment, executive reporting) → 20 modules; 3 packaging tiers. |
| 4 | 0.4 | Architecture | 7-layer modular architecture (experience, gateway & security, business modules, intelligence & AI, data platform, integration, infrastructure) with cross-cutting security, governance & audit. |
| 5 | 0.5 | Use case | Ministry of Foreign Affairs flagship case: missions, diplomats, delegations and citizens abroad; Nairobi civil-unrest scenario. |
| 6 | 0.6 | Demo v1 | Offline HTML demo 'HALO' with 7-scene scenario; 11 of 20 modules. |
| 7 | 0.7 | Demo v2 | Restyled to Palantir Gotham/Blueprint look; all 20 modules simulated. |
| 8 | 0.8 | Rename | Platform renamed HALO → NEXIRA. |
| 9 | 0.9 | Wave 3 | Added 10 modules: Health Intelligence (incl. WHO advisories), Natural Hazards & Climate, Evacuation Management, Consular Crisis Portal, VIP & Delegation Protection, Fleet & Assets, Wellbeing & Family Liaison, Document Expiry, Exercise & Training, After-Action Review. |
| 10 | 0.10 | Air travel | Added Air Travel Tracking (officials airborne, holding/diversion, evacuation charter tracking) linked to bookings. |
| 11 | 0.11 | Agents | Added 10 AI agents, Decision Queue and AI Agents console; 5 autonomy levels, policy floors, two-person rule, kill switch. |
| 12 | 0.12 | Build plan | AI-assisted build approach, target stack, Phase 1 PRD, Phase 1 database schema and coding-tool prompts. |
| 13 | 1.0 | Consolidation | This master specification: all phases, all modules, history and traceability. |

## 1.2 Key decisions log

| # | Decision | Rationale |
|---|---|---|
| 1 | Open, vendor-neutral intelligence hub | Customers choose feeds; avoids lock-in; matches Restrata's strongest differentiator while adding missing modules. |
| 2 | Sovereign / in-country deployment as standard | Decisive for GCC government and critical-infrastructure buyers; diplomatic location data is highly sensitive. |
| 3 | Foreign ministry as flagship customer | Global footprint, duty of care and evacuation needs exercise every module. |
| 4 | Palantir/Blueprint-style dense UI | Analyst-grade operations-centre look; Blueprint is open source (Apache 2.0). |
| 5 | Agents propose, humans decide | Proactive operation without loss of accountability; policy floors enforced in backend. |
| 6 | Air tracking only for linked travellers | Value comes from linking flights to bookings; VIP movements are never shown. |
| 7 | Phased delivery starting with 6 core modules | Earliest working pilot; remaining modules added once a customer commits. |

# 2. Product vision and scope

NEXIRA is a sovereign, AI-assisted, modular resilience platform that turns scattered threat information into clear, immediate and accountable action to protect an organisation's people, sites, travellers and operations.

## 2.1 Problems addressed

- Threat information arrives from many providers in different formats; teams lose time working out what matters.

- Knowing who is where, and whether they are safe, is slow and manual during a crisis.

- Existing products are fragmented: intelligence, notification, response and assistance are bought separately.

- Dashboards are reactive; operators must look for problems instead of being handed ready decisions.

- Government buyers need in-country hosting and full auditability.

## 2.2 Target customers

| # | Segment | Typical needs |
|---|---|---|
| 1 | Ministries of foreign affairs | Missions, diplomats, delegations, citizens abroad, evacuation, consular crisis |
| 2 | Other government entities | Staff abroad, critical sites, sovereign hosting |
| 3 | Energy & critical infrastructure | Remote sites, workforce safety, supply chain |
| 4 | Aviation & logistics | Crew and asset tracking, disruption management |
| 5 | Multinationals with mobile workforce | Duty of care, travel risk, ISO 31030 alignment |

## 2.3 Value proposition

- One picture: every intelligence source, person, site and flight in one place.

- Answers four questions instantly: What is happening? Who is affected? Are they safe? What do we do now?

- Proactive: agents raise risks hours or days ahead and prepare the response.

- Sovereign and auditable: in-country hosting, immutable audit, human approval for consequential actions.

## 2.4 Packaging tiers

| # | Tier | Included |
|---|---|---|
| 1 | Essentials | Intelligence Hub, People & Sites, Global Operations, Mass Notification, Safety Check-in |
| 2 | Professional | Essentials + Incidents, Journey Management, Playbooks, AI Copilot, Decision Queue & core agents |
| 3 | Enterprise / Sovereign | All modules, all agents, on-premise / air-gapped deployment |

# 3. Phased roadmap

| # | Phase | Theme | Modules | Indicative duration |
|---|---|---|---|---|
| 1 | Phase 1 · MVP | Core loop on simulated data | Platform & admin, Decision Queue, AI Agents (4), Global Operations, Incidents, People & Sites, Playbooks, Safety Check-in, Scenario engine | 12 weeks |
| 2 | Phase 2 · Pilot | Real data and travel | Real connectors (1 intel feed, HR, SMS/email, IdP), Journey Management, Air Travel Tracking, Mass Notification, Local-Language OSINT, Assistance Partners, AI Risk Copilot, Integrations console, agents: Travel & Air, Briefing | 10–12 weeks |
| 3 | Phase 3 · Response | Crisis operations depth | Evacuation, Consular Crisis Portal, VIP & Delegation, Fleet & Assets, Site Twin, Health Intelligence, Natural Hazards & Climate, Cyber-Physical, agents: Evacuation, Cyber-Physical | 12–16 weeks |
| 4 | Phase 4 · Insight | Prevention, compliance, learning | Predictive Risk, Supply Chain, Continuity & Compliance, Document Expiry, Exercise & Training, After-Action Review, Executive Overview, Deployment & Security console, agents: Forecast, Compliance & Readiness | 10–12 weeks |

Durations are planning estimates for 1–2 developers using AI coding tools, with part-time product, security and design support; not a commercial commitment.

# 4. Users, roles and permissions

| # | Role | Responsibilities | Phase |
|---|---|---|---|
| 1 | Duty Officer | Monitor, approve standard proposals, start playbooks, check-ins, notifications | 1 |
| 2 | Security Officer | Security proposals, playbook gates, cyber containment, trip approvals | 1 |
| 3 | Head of Mission | Mission-level gates; first approver for evacuation | 1 |
| 4 | HQ Crisis Director | Second approver for evacuation, mission closure | 1 |
| 5 | Administrator | Users, roles, agent autonomy, connectors, scenarios, audit | 1 |
| 6 | Viewer | Read-only | 1 |
| 7 | Travel Desk | Trip approvals, flight diversions, rebooking | 2 |
| 8 | Consular Officer | Citizen communications, crisis portal, family enquiries | 2 |
| 9 | Protocol Officer | VIP visit programmes | 3 |
| 10 | HR Officer | Documents | 3 |
| 11 | Fleet / Logistics Officer | Vehicles, fuel, suppliers | 3 |
| 12 | BCM Owner | Continuity plans, drills, compliance | 4 |
| 13 | Executive | Leadership dashboards and briefings | 4 |
| 14 | Traveller / Staff (mobile) | Receive alerts, respond to check-ins, SOS, share location | 1–2 |
| 15 | Citizen (public portal) | Register, report status, enquire about family | 3 |

All roles can be scoped to one or more missions. Permissions are enforced in the backend; the UI hides actions a user cannot take.

# 5. Functional requirements by module

Priority: M = Must, S = Should, C = Could. Requirement IDs follow <module code>-<number>. Phase shows when the module is first delivered.

## 5.1 Module index

| # | Code | Module | Phase | Purpose |
|---|---|---|---|---|
| 1 | PLT | Platform, identity, tenancy & audit | 1 | Secure multi-tenant foundation used by every module. |
| 2 | DQ | Decision Queue | 1 | Single place where agent proposals arrive for human decision. |
| 3 | AGT | AI Agents console | 1 | Manage agents, autonomy and guardrails. |
| 4 | OPS | Global Operations | 1 | Live map and situational awareness. |
| 5 | INC | Intelligence Hub & Incidents | 1 | Ingest, normalise, de-duplicate and fuse threat intelligence. |
| 6 | PPL | People, Sites & Location Confidence | 1 | Who and what the customer protects, and where they are. |
| 7 | PB | Response Playbooks | 1 | Pre-defined, automated response workflows. |
| 8 | CHK | Safety Check-in & SOS | 1 | Account for people quickly. |
| 9 | JRN | Journey Management | 2 | Travel risk and approvals. |
| 10 | AIR | Air Travel Tracking | 2 | Officials in the air, delays and diversions. |
| 11 | NTF | Mass Notification | 2 | Multi-channel communication at scale. |
| 12 | OSN | Local-Language OSINT | 2 | Earlier detection from local-language public sources. |
| 13 | AST | Assistance Partners | 2 | Medical, evacuation, security and welfare partners. |
| 14 | COP | AI Risk Copilot | 2 | Natural-language questions and briefings. |
| 15 | INT | Integrations console | 2 | Manage data connectors. |
| 16 | EVC | Evacuation Management | 3 | Plan and run evacuations. |
| 17 | CNS | Consular Crisis Portal | 3 | Public self-service for citizens and families. |
| 18 | VIP | VIP & Delegation Protection | 3 | Senior visits and delegations. |
| 19 | FLT | Fleet & Assets | 3 | Vehicles and critical equipment. |
| 20 | TWN | Site Twin | 3 | Floor plans, occupancy and sensors. |
| 21 | HLT | Health Intelligence | 3 | Medical risk including WHO advisories. |
| 22 | HAZ | Natural Hazards & Climate | 3 | Live hazards and long-term exposure. |
| 23 | CPX | Cyber-Physical Correlation | 3 | Link cyber and physical security events. |
| 24 | — | *Removed: Wellbeing & Family Liaison (D-49, 2026-11-10)* | — | — |
| 25 | PRD | Predictive Risk | 4 | Forecast risk before it materialises. |
| 26 | SUP | Supply Chain & Third-Party Risk | 4 | Suppliers and logistics routes. |
| 27 | BCM | Continuity & Compliance | 4 | Plans, drills and duty of care. |
| 28 | DOC | Document Expiry | 4 | Travel documents and clearances. |
| 29 | EXR | Exercise & Training | 4 | Readiness through drills. |
| 30 | AAR | After-Action Review | 4 | Learning loop. |
| 31 | EXE | Executive Overview | 4 | Leadership view. |
| 32 | DEP | Deployment & Security console | 4 | Platform health and sovereignty evidence. |

## 5.2 Platform, identity, tenancy & audit (PLT) · Phase 1

Secure multi-tenant foundation used by every module.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | PLT-01 | OIDC sign-in (Keycloak or customer IdP such as Entra ID) with MFA | M |
| 2 | PLT-02 | Role- and attribute-based access, optionally scoped to missions | M |
| 3 | PLT-03 | Tenant isolation with database row-level security | M |
| 4 | PLT-04 | Append-only, hash-chained audit log for every state change | M |
| 5 | PLT-05 | Realtime push of updates to open screens within 2 s | M |
| 6 | PLT-06 | Scenario engine: play, pause, step, reset scripted scenarios; demo and exercise modes | M |
| 7 | PLT-07 | Global search across people, missions, incidents, trips (Ctrl+K) | S |
| 8 | PLT-08 | Localisation framework; Arabic right-to-left support | S |
| 9 | PLT-09 | User preferences, notification settings, time-zone display (GST/UTC) | C |

Data: tenant, app_user, role, user_role, audit_log, scenario, scenario_event, scenario_run   ·   Integrations: IdP

## 5.3 Decision Queue (DQ) · Phase 1

Single place where agent proposals arrive for human decision.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | DQ-01 | Show pending proposals with title, proposed action, evidence, sources, confidence, risk if no action, alternatives, approver chain, deadline countdown | M |
| 2 | DQ-02 | Approve, edit-and-approve, reject with reason, use an alternative | M |
| 3 | DQ-03 | Multi-step approval (two-person rule) with ordered roles | M |
| 4 | DQ-04 | Undo for auto-with-notice actions within the undo window | M |
| 5 | DQ-05 | Escalate overdue proposals | M |
| 6 | DQ-06 | Pending / decided / all tabs; agent activity log; decision policy legend | M |
| 7 | DQ-07 | Header pill showing number of pending decisions | S |
| 8 | DQ-08 | Metrics: decisions pending, raised proactively, median time to decide, acceptance rate | S |

Data: agent_proposal, proposal_approval   ·   Integrations: —

## 5.4 AI Agents console (AGT) · Phase 1

Manage agents, autonomy and guardrails.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | AGT-01 | Roster of agents with what each watches, proposals and acceptance rate | M |
| 2 | AGT-02 | Set autonomy level per agent (admin only), audited | M |
| 3 | AGT-03 | Policy floors per action type that agents cannot go below | M |
| 4 | AGT-04 | Kill switch pausing all agents; fallback to manual playbooks | M |
| 5 | AGT-05 | Human override rate tracked for tuning | S |
| 6 | AGT-06 | Agents tested against exercise scenarios before go-live | S |

Data: agent, action_policy   ·   Integrations: LLM gateway

## 5.5 Global Operations (OPS) · Phase 1

Live map and situational awareness.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | OPS-01 | World map with missions coloured by risk, threats, incidents and impact zones | M |
| 2 | OPS-02 | Zoom to city level with sites, people in zone, routes | M |
| 3 | OPS-03 | Live intelligence feed showing raw signals merging into incidents | M |
| 4 | OPS-04 | KPI strip: missions, personnel, travellers, alerts, posture | M |
| 5 | OPS-05 | Impact panel listing linked people with confidence and source | M |
| 6 | OPS-06 | Officials airborne layer (Phase 2) | S |
| 7 | OPS-07 | Offline-capable map tiles for air-gapped sites | M |

Data: mission, site, incident, person_location_current   ·   Integrations: Map tiles

## 5.6 Intelligence Hub & Incidents (INC) · Phase 1

Ingest, normalise, de-duplicate and fuse threat intelligence.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | INC-01 | Ingest raw signals from connectors into a common format | M |
| 2 | INC-02 | Normalise category and severity per source via configurable maps | M |
| 3 | INC-03 | Translate non-English signals | S |
| 4 | INC-04 | Fuse same-category signals within distance/time windows into one incident | M |
| 5 | INC-05 | Confidence score from number and independence of sources | M |
| 6 | INC-06 | Compute exposure of people, sites, trips and flights within impact radius | M |
| 7 | INC-07 | Incident register and detail: source normalisation table, timeline, status changes, notes | M |
| 8 | INC-08 | Manual incident creation by users | S |

Data: intel_source, raw_signal, incident, incident_signal, incident_exposure, incident_event   ·   Integrations: Intel feeds

## 5.7 People, Sites & Location Confidence (PPL) · Phase 1

Who and what the customer protects, and where they are.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | PPL-01 | Missions, sites and people (diplomats, local staff, dependants, delegates, citizens, contractors) | M |
| 2 | PPL-02 | Location observations from GPS, access control, bookings, calendar/HR, check-ins, flights | M |
| 3 | PPL-03 | Location Confidence Engine computes current location and confidence 0–100 | M |
| 4 | PPL-04 | Search and filter people and sites; site readiness and last drill | M |
| 5 | PPL-05 | Registered citizens abroad count and linkage to consular module | S |

Data: mission, site, person, location_observation, person_location_current   ·   Integrations: HR, access control, mobile app

## 5.8 Response Playbooks (PB) · Phase 1

Pre-defined, automated response workflows.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | PB-01 | Playbook library with steps, action types and trigger rules | M |
| 2 | PB-02 | Run playbooks for incidents; steps execute in order with timestamps | M |
| 3 | PB-03 | Approval gates by role; run pauses until approved | M |
| 4 | PB-04 | Immutable audit trail panel per run | M |
| 5 | PB-05 | Playbook versioning and test mode | S |
| 6 | PB-06 | Initial library: civil unrest, evacuation, earthquake, severe weather, medical emergency, cyber-physical, kidnap/missing person | S |

Data: playbook, playbook_step, playbook_run, playbook_run_step   ·   Integrations: —

## 5.9 Safety Check-in & SOS (CHK) · Phase 1

Account for people quickly.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | CHK-01 | Check-in campaigns to exposed people and citizens | M |
| 2 | CHK-02 | Responses Safe / Need help from app, SMS, WhatsApp, API | M |
| 3 | CHK-03 | Accounted %, safe, need help, no response; auto-escalation of non-responders | M |
| 4 | CHK-04 | Mobile view: alert with one-tap response | M |
| 5 | CHK-05 | SOS / panic button and lone-worker timer | S (P2) |

Data: notification_campaign, checkin_response   ·   Integrations: Channels

## 5.10 Journey Management (JRN) · Phase 2

Travel risk and approvals.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | JRN-01 | Trips with travellers, itinerary, dates and destination risk | M |
| 2 | JRN-02 | Approval workflow for trips above a risk threshold | M |
| 3 | JRN-03 | Pre-travel checklist: briefing, insurance, contacts, check-in schedule | M |
| 4 | JRN-04 | Destination risk breakdown (security, unrest, health, transport) | M |
| 5 | JRN-05 | Trips flagged when impacted by an incident | M |

Data: trip, trip_traveller, trip_segment   ·   Integrations: Travel booking (GDS)

## 5.11 Air Travel Tracking (AIR) · Phase 2

Officials in the air, delays and diversions.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | AIR-01 | Match bookings to live flights; show only flights carrying the customer's travellers | M |
| 2 | AIR-02 | Live air picture and tracked-flight table with altitude, ETA, status | M |
| 3 | AIR-03 | Detect holding, delays, diversions, cancellations; raise proposals | M |
| 4 | AIR-04 | Landing/diversion updates traveller location automatically | M |
| 5 | AIR-05 | Track evacuation charter flights | M |
| 6 | AIR-06 | Never display VIP/ministerial movements | M |
| 7 | AIR-07 | Rebooking, hotel booking and traveller notification actions | S |

Data: flight, flight_position, flight_event   ·   Integrations: Flight data API (e.g. FlightAware, Flightradar24)

## 5.12 Mass Notification (NTF) · Phase 2

Multi-channel communication at scale.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | NTF-01 | Compose messages with audience, channels and templates | M |
| 2 | NTF-02 | Channels: app push, SMS, WhatsApp, voice, email with fallback | M |
| 3 | NTF-03 | Auto-translation (EN, AR, FR, SW, others) | S |
| 4 | NTF-04 | Delivery funnel per channel: sent, delivered, read, failed | M |
| 5 | NTF-05 | Campaign history; test send to self | M |

Data: notification_campaign, notification_delivery, template   ·   Integrations: SMS gateway, WhatsApp, email, voice

## 5.13 Local-Language OSINT (OSN) · Phase 2

Earlier detection from local-language public sources.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | OSN-01 | Collect public social, messaging-channel, local news and radio transcripts | M |
| 2 | OSN-02 | Show original text with translation, credibility and corroboration | M |
| 3 | OSN-03 | Language filters; multilingual watchlists per mission | M |
| 4 | OSN-04 | Link posts to incidents as supporting sources; promote to analyst | M |
| 5 | OSN-05 | Lead-time analytics vs global feeds | S |
| 6 | OSN-06 | Public sources only; analyst review before action | M |

Data: osint_post, watchlist   ·   Integrations: OSINT collectors, translation model

## 5.14 Assistance Partners (AST) · Phase 2

Medical, evacuation, security and welfare partners.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | AST-01 | Partner directory with services, coverage and SLAs | M |
| 2 | AST-02 | Request partner support; track accepted, en route, completed with ETA | M |
| 3 | AST-03 | Suggest nearest capable partner for an SOS | S |
| 4 | AST-04 | Coverage gaps by mission | S |

Data: partner, partner_request   ·   Integrations: Partner APIs / email

## 5.15 AI Risk Copilot (COP) · Phase 2

Natural-language questions and briefings.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | COP-01 | Chat grounded on incidents, people, playbooks, check-ins and intelligence | M |
| 2 | COP-02 | Situation reports with sources; export to PDF; send after approval | M |
| 3 | COP-03 | Cites sources for every answer; role-based data access | M |
| 4 | COP-04 | Runs on local/sovereign models | M |

Data: copilot_session, document   ·   Integrations: LLM gateway

## 5.16 Integrations console (INT) · Phase 2

Manage data connectors.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | INT-01 | Connector catalogue for intelligence, enterprise systems and channels | M |
| 2 | INT-02 | Enable/disable, health status, volume per 24 h | M |
| 3 | INT-03 | Configure severity/category maps per source | M |
| 4 | INT-04 | Add connectors by configuration, not code | S |

Data: intel_source, connector   ·   Integrations: All

## 5.17 Evacuation Management (EVC) · Phase 3

Plan and run evacuations.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | EVC-01 | Pre-built evacuation plans per mission | M |
| 2 | EVC-02 | Manifest of staff, dependants and citizens with document validity | M |
| 3 | EVC-03 | Seat allocation; charter, commercial and road options | M |
| 4 | EVC-04 | Assembly, convoy and flight sequence with check-in at muster point | M |
| 5 | EVC-05 | Activation requires senior two-person approval | M |
| 6 | EVC-06 | Link to Air Tracking, Fleet and Document Expiry | M |

Data: evac_plan, evac_manifest, evac_event   ·   Integrations: Charter / partner

## 5.18 Consular Crisis Portal (CNS) · Phase 3

Public self-service for citizens and families.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | CNS-01 | Public crisis page per country with advisory | M |
| 2 | CNS-02 | Citizen actions: I am safe, I need help, register trip, find family member | M |
| 3 | CNS-03 | Family and employer enquiries auto-matched to check-in data | M |
| 4 | CNS-04 | Hotline queue and enquiry metrics | S |
| 5 | CNS-05 | Multilingual, accessible, high-load hosting | M |

Data: citizen_registration, enquiry   ·   Integrations: Public web, SMS

## 5.19 VIP & Delegation Protection (VIP) · Phase 3

Senior visits and delegations.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | VIP-01 | Visit programme with segments, venues, routes and times | M |
| 2 | VIP-02 | Segment risk assessment and recommendations | M |
| 3 | VIP-03 | Protection detail, safe havens, pre-visit checklist | M |
| 4 | VIP-04 | Live tracking for authorised protection team only | S |

Data: visit, visit_segment   ·   Integrations: Protection team devices

## 5.20 Fleet & Assets (FLT) · Phase 3

Vehicles and critical equipment.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | FLT-01 | Vehicles and assets with GPS location, fuel/charge and status | M |
| 2 | FLT-02 | Availability for evacuation; seat capacity vs need | M |
| 3 | FLT-03 | Maintenance alerts and service due | M |
| 4 | FLT-04 | Geofence alerts when vehicles enter impact zones | S |

Data: asset, asset_telemetry   ·   Integrations: Telematics

## 5.21 Site Twin (TWN) · Phase 3

Floor plans, occupancy and sensors.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | TWN-01 | Floor plan per critical site with rooms, safe room, muster point, gates | M |
| 2 | TWN-02 | Live occupancy from access control and presence data | M |
| 3 | TWN-03 | Sensor and system status (gates, CCTV, generator, satellite comms) | M |
| 4 | TWN-04 | Shelter-in-place and evacuation route overlays | M |

Data: site_floor, site_zone, sensor   ·   Integrations: Access control, VMS, BMS

## 5.22 Health Intelligence (HLT) · Phase 3

Medical risk including WHO advisories.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | HLT-01 | Outbreak and health advisories (WHO Disease Outbreak News, ministries, partners) | M |
| 2 | HLT-02 | Entry and vaccination requirements by country | M |
| 3 | HLT-03 | Approved medical facilities near each mission; avoid flags in impact zones | M |
| 4 | HLT-04 | Staff health readiness; send health advisory | M |
| 5 | HLT-05 | Check WHO and provider terms of use before production | M |

Data: health_advisory, medical_facility   ·   Integrations: WHO, health intel providers

## 5.23 Natural Hazards & Climate (HAZ) · Phase 3

Live hazards and long-term exposure.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | HAZ-01 | Earthquakes, cyclones, floods, heat, air quality, wildfire within range of missions | M |
| 2 | HAZ-02 | Arm severe-weather playbooks ahead of landfall | M |
| 3 | HAZ-03 | Climate exposure per site today vs 2050 | S |

Data: hazard_event, climate_exposure   ·   Integrations: Weather, seismic, AQ, climate models

## 5.24 Cyber-Physical Correlation (CPX) · Phase 3

Link cyber and physical security events.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | CPX-01 | Ingest SIEM events (customer SIEM) and physical security events (access control, VMS, alarms, PSIM) | M |
| 2 | CPX-02 | Correlate by site, time and people into cases with a score | M |
| 3 | CPX-03 | Link analysis graph | M |
| 4 | CPX-04 | Containment action (block domain, warn staff, MFA step-up) through approval | M |

Data: security_event, cpx_case   ·   Integrations: SIEM, email gateway, access control, VMS

## 5.25 Removed

Wellbeing & Family Liaison (WEL-01..03) was removed by the product owner on 2026-11-10 (`docs/decisions.md` D-49). The section number is kept so later references stay valid.

## 5.26 Predictive Risk (PRD) · Phase 4

Forecast risk before it materialises.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | PRD-01 | 30-day history and 14-day forecast with uncertainty band per mission | M |
| 2 | PRD-02 | Key drivers explaining the forecast | M |
| 3 | PRD-03 | Missions with rising risk; recommended actions and tasks | M |
| 4 | PRD-04 | Model performance (precision, recall, warning time) | S |
| 5 | PRD-05 | Advisory only; never auto-acts | M |

Data: risk_index, forecast   ·   Integrations: Incident history, events calendars

## 5.27 Supply Chain & Third-Party Risk (SUP) · Phase 4

Suppliers and logistics routes.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | SUP-01 | Supplier register with tier, service and mission | M |
| 2 | SUP-02 | Route status and disruption from incidents | M |
| 3 | SUP-03 | Mitigation actions and backup suppliers | M |

Data: supplier, logistics_route   ·   Integrations: Procurement, logistics

## 5.28 Continuity & Compliance (BCM) · Phase 4

Plans, drills and duty of care.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | BCM-01 | Continuity plans per mission with critical functions and recovery time objectives | M |
| 2 | BCM-02 | Automatic plan activation by playbooks; function status during incidents | M |
| 3 | BCM-03 | Drill schedule; plan review status | M |
| 4 | BCM-04 | ISO 31030 alignment and duty-of-care checklists | M |

Data: bcp_plan, bcp_function, drill   ·   Integrations: —

## 5.29 Document Expiry (DOC) · Phase 4

Travel documents and clearances.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | DOC-01 | Track passports, visas, permits and clearances for staff and dependants | M |
| 2 | DOC-02 | Flag documents that would block evacuation | M |
| 3 | DOC-03 | Renewal reminders and progress | M |

Data: travel_document   ·   Integrations: HR

## 5.30 Exercise & Training (EXR) · Phase 4

Readiness through drills.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | EXR-01 | Scenario templates; launch exercises on the live scenario engine | M |
| 2 | EXR-02 | Score detection, accountability, decision speed, communication, plan adherence | M |
| 3 | EXR-03 | Exercise history and staff trained | M |

Data: exercise, exercise_score   ·   Integrations: —

## 5.31 After-Action Review (AAR) · Phase 4

Learning loop.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | AAR-01 | Reconstructed timeline and response metrics from the incident record | M |
| 2 | AAR-02 | AI-drafted lessons and actions; accept and assign owners | M |
| 3 | AAR-03 | Export review | M |

Data: aar, aar_action   ·   Integrations: —

## 5.32 Executive Overview (EXE) · Phase 4

Leadership view.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | EXE-01 | Global posture, active incidents, detection-to-notification time, accountability, readiness | M |
| 2 | EXE-02 | Alert trend, regional exposure, missions requiring attention, response timeline | M |
| 3 | EXE-03 | Board-level export | S |

Data: (views)   ·   Integrations: —

## 5.33 Deployment & Security console (DEP) · Phase 4

Platform health and sovereignty evidence.

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | DEP-01 | Hosting, availability, data residency, key management status | M |
| 2 | DEP-02 | Service health per microservice | M |
| 3 | DEP-03 | Security controls checklist and admin audit | M |

Data: (ops data)   ·   Integrations: Monitoring

# 6. AI agents and human-in-the-loop

## 6.1 Agent catalogue

| # | Agent | Watches | Proposes | Approver | Phase |
|---|---|---|---|---|---|
| 1 | Watch Officer | Intel feeds, OSINT, hazards | New risks and incidents | Auto / Duty officer | 1 |
| 2 | Exposure | People, trips, flights, sites | Who and what is affected | Auto | 1 |
| 3 | Response Planner | Incidents, playbooks, BCPs | Playbook runs | Duty / Security officer | 1 |
| 4 | Communications | Audiences, channels, languages | Multilingual alerts and advisories | Duty / Consular officer | 1 |
| 5 | Travel & Air | Bookings, flight status | Diversions, rebooking, trip conditions | Travel desk / Security | 2 |
| 6 | Briefing | All platform data | Situation reports, leadership summaries | Duty officer | 2 |
| 7 | Evacuation | Risk trend, seats, documents | Evacuation activation | Head of Mission + HQ Crisis Director | 3 |
| 8 | Cyber-Physical | SIEM, access control, CCTV | Containment actions | Security officer | 3 |
| 9 | Forecast | Predictive risk, events calendar | Pre-emptive changes (e.g. VIP programme) | Protocol / Security lead | 4 |
| 10 | Compliance & Readiness | Documents, drills, BCPs | Renewals, drills, plan reviews | HR / BCM owner | 4 |

## 6.2 Autonomy levels

| # | Level | Behaviour | Examples |
|---|---|---|---|
| 1 | 0 · Auto | Executes and logs | Enrichment, matching, map updates |
| 2 | 1 · Auto + notice | Executes; undo window | Internal heads-up, document reminders |
| 3 | 2 · Approve | One named approver | Staff alerts, partner requests, diversions |
| 4 | 3 · Senior approval | Ordered two-person approval | Evacuation, mission closure, public statements |
| 5 | 4 · Advise only | Never executable | Legal or diplomatic positions, use of force |

## 6.3 Agent requirements

| # | ID | Requirement | Pri. |
|---|---|---|---|
| 1 | AGR-01 | Every proposal includes action, machine payload, evidence with sources, alternatives, risk if no action, confidence and deadline | M |
| 2 | AGR-02 | Effective level = max(agent setting, action policy floor) | M |
| 3 | AGR-03 | Agents act only through the same service APIs and permissions as users | M |
| 4 | AGR-04 | No external message, spending or movement of people without human approval | M |
| 5 | AGR-05 | Kill switch; fallback to manual playbooks | M |
| 6 | AGR-06 | All proposals, decisions and executions audited; rejection reasons stored for tuning | M |
| 7 | AGR-07 | Proactive proposals raised before incidents (forecasts, documents, hazards, trips) | M |
| 8 | AGR-08 | LLM access only through an internal gateway with local/sovereign models; stub for tests | M |
| 9 | AGR-09 | Agents validated against exercise scenarios before activation | S |
| 10 | AGR-10 | Override rate and acceptance tracked per agent | S |

# 7. Non-functional requirements

| # | Area | Requirement |
|---|---|---|
| 1 | Sovereignty | Deployable on-premise, sovereign cloud, hybrid or air-gapped; no runtime dependency on public SaaS |
| 2 | Security | OIDC + MFA; TLS 1.3; AES-256 at rest; customer-managed keys (HSM); secrets vault; OWASP ASVS L2 target; annual penetration test |
| 3 | Privacy | Data minimisation; role-restricted medical data; retention policies |
| 4 | Audit | Append-only, hash-chained audit; default retention 7 years |
| 5 | Performance | Signal → fused incident ≤ 5 s; exposure ≤ 5 s; UI update ≤ 2 s; notification to handset median < 10 s |
| 6 | Scale | Phase 1: 50 users, 10k people, 1k signals/h. Production: 500 users, 100k people, 50k signals/h, 1M SIEM events/day |
| 7 | Availability | Pilot 99.9%; production 99.95% active-active across two data centres; documented RPO/RTO |
| 8 | Usability | Dense dark operations UI; keyboard support; 1440×900+; mobile app for staff; public portal accessible (WCAG 2.1 AA) |
| 9 | Localisation | English, Arabic (RTL), French; message translation for local languages |
| 10 | Observability | Metrics, logs, traces per service; service-health console |
| 11 | Quality | Automated tests per feature; lint and type checks in CI; human review for auth, approvals and messaging |

# 8. Architecture and technology

## 8.1 Layers

| # | Layer | Components |
|---|---|---|
| 1 | 1. Experience | GSOC web console, mobile app, executive dashboard, public consular portal, AI copilot |
| 2 | 2. API gateway & security | API gateway, identity (SSO/RBAC/MFA), multi-tenant manager, rate limiting |
| 3 | 3. Business modules | All modules in section 5 as separately licensable services |
| 4 | 4. Intelligence & AI | Normalisation & de-dup, location confidence, risk scoring & prediction, playbook/rules engine, LLM services, cyber-physical correlation, agent orchestration + policy engine |
| 5 | 5. Data platform | Event streaming bus, PostgreSQL/PostGIS, data lake, vector store |
| 6 | 6. Integration | Connector framework: intel feeds, enterprise systems, channels, SIEM, flight data |
| 7 | 7. Infrastructure | Kubernetes/OpenShift, observability, DevSecOps, backup & DR |
| 8 | Cross-cutting | Security, governance & audit; encryption; data residency |

## 8.2 Technology stack

| # | Area | Choice |
|---|---|---|
| 1 | Frontend | React 18, TypeScript, Vite, Blueprint (dark), MapLibre GL, TanStack Query |
| 2 | Mobile | React Native or native apps (Phase 2) |
| 3 | Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| 4 | Database | PostgreSQL 16 + PostGIS 3, row-level security |
| 5 | Streaming | Redis Streams (Phase 1), Kafka (production scale) |
| 6 | Identity | Keycloak or customer IdP (Entra ID) |
| 7 | AI | Internal LLM gateway; local models via vLLM/Ollama; agent framework (e.g. LangGraph or an approved enterprise platform) |
| 8 | Deployment | Docker, Kubernetes/OpenShift, Helm |

# 9. Data model (all phases)

Phase 1 tables are fully defined in nexira_schema.sql. Later-phase entities are listed for planning and will be added by migrations.

| # | Domain | Entities | Phase |
|---|---|---|---|
| 1 | Tenancy & access | tenant, app_user, role, user_role | 1 |
| 2 | People & places | mission, site, person, location_observation, person_location_current | 1 |
| 3 | Intelligence | intel_source, raw_signal, incident, incident_signal, incident_exposure, incident_event | 1 |
| 4 | Response | playbook, playbook_step, playbook_run, playbook_run_step | 1 |
| 5 | Communications | notification_campaign, notification_delivery, checkin_response, template | 1–2 |
| 6 | Agents | agent, action_policy, agent_proposal, proposal_approval | 1 |
| 7 | Audit & simulation | audit_log, scenario, scenario_event, scenario_run | 1 |
| 8 | Travel & air | trip, trip_traveller, trip_segment, flight, flight_position, flight_event | 2 |
| 9 | OSINT | osint_post, watchlist | 2 |
| 10 | Partners | partner, partner_request | 2 |
| 11 | Copilot | copilot_session, document | 2 |
| 12 | Evacuation | evac_plan, evac_manifest, evac_event | 3 |
| 13 | Consular | citizen_registration, enquiry | 3 |
| 14 | VIP | visit, visit_segment | 3 |
| 15 | Assets | asset, asset_telemetry | 3 |
| 16 | Sites | site_floor, site_zone, sensor | 3 |
| 17 | Health & hazards | health_advisory, medical_facility, hazard_event, climate_exposure | 3 |
| 18 | Cyber-physical | security_event, cpx_case | 3 |
| 19 | — | *Removed (D-49)* | — |
| 20 | Prediction | risk_index, forecast | 4 |
| 21 | Supply chain | supplier, logistics_route | 4 |
| 22 | Continuity | bcp_plan, bcp_function, drill | 4 |
| 23 | Documents | travel_document | 4 |
| 24 | Learning | exercise, exercise_score, aar, aar_action | 4 |

# 10. Integration catalogue

| # | Category | Examples (to confirm per customer) | Phase |
|---|---|---|---|
| 1 | Threat intelligence | Dataminr, MAX Security, Riskline, Dragonfly, Factal, Samdesk, Healix, xWeather | 2 |
| 2 | Flight data | FlightAware AeroAPI/Firehose, Flightradar24 API (commercial licence required; OpenSky needs written licence) | 2 |
| 3 | HR / identity | Customer HR system; Entra ID / Keycloak | 1–2 |
| 4 | Travel booking | GDS / travel management company feeds | 2 |
| 5 | Channels | SMS gateway, WhatsApp Business, email, voice, Teams | 2 |
| 6 | SIEM & email security | Microsoft Sentinel, Splunk, IBM QRadar, Elastic; Defender for Office 365, Proofpoint, Mimecast | 3 |
| 7 | Physical security | Genetec, LenelS2, Honeywell, Gallagher, Milestone, Axis, Bosch; PSIM platforms | 3 |
| 8 | Health | WHO Disease Outbreak News, ministries, health-intel providers (check terms of use) | 3 |
| 9 | Telematics | Vehicle GPS and fuel providers | 3 |

Vendor names are examples, not confirmed integrations or partnerships.

# 11. Reference scenario and acceptance

The Nairobi civil-unrest scenario (fictional) is the end-to-end acceptance test across phases.

| # | Scene | Expected behaviour | Modules |
|---|---|---|---|
| 1 | 0 Calm | Proactive proposals in Decision Queue (Addis forecast, document expiry, Dhaka cyclone, Baghdad trip, cholera advisory) | DQ, PRD, DOC, HAZ, JRN, HLT |
| 2 | 1 Signals fused | Swahili posts + 3 provider signals normalise and fuse into INC-2026-1042 (confidence ≥ 90%) | INC, OSN |
| 3 | 2 Impact | 2 sites, 14 staff, 3 delegates, 212 citizens, 1 inbound flight exposed | OPS, PPL, AIR |
| 4 | 3 Playbook | PB-07 approved and run; HoM approves route B; BCP-NBO activated; XW 451 diversion approved | PB, BCM, AIR, DQ |
| 5 | 4 Check-in | 15 safe, 1 need help (secure transport dispatched), 1 pending (escalated) | CHK, AST |
| 6 | 5 Briefing | Situation report incl. cyber (CPX-0042) and supply-chain risks released after approval | COP, CPX, SUP |
| 7 | 6 Leadership | Executive overview; optional evacuation with two approvals; charter tracked to Dubai; AAR generated | EXE, EVC, AIR, AAR |

# 12. Assumptions, risks and open questions

## 12.1 Assumptions

- Development and pilot use fictional data until a customer environment is approved.

- Pilot customer provides access to at least one intelligence feed, HR extract and a messaging gateway.

- Work is carried out on approved corporate tooling and repositories.

## 12.2 Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Third-party data licensing (intel, flight, WHO) | Confirm commercial terms before production use |
| 2 | AI-generated code defects or security gaps | Rules file, tests per task, human review of sensitive code |
| 3 | Agents acting without approval | Backend policy floors, tests, kill switch, audit |
| 4 | Sensitive location data exposure | Sovereign hosting, RBAC, VIP masking, encryption |
| 5 | Scope growth across 30+ modules | Phased delivery; modules licensed separately |
| 6 | Translation quality for local languages | Native-speaker review; show original text alongside translation |

## 12.3 Open questions

- Pilot customer identity provider, hosting environment and classification level?

- First intelligence feed and messaging gateway?

- Ownership of HQ approval roles?

- Arabic UI timing?

- Packaging and pricing model per tier?

# 13. Glossary

| # | Term | Meaning |
|---|---|---|
| 1 | AAR | After-action review |
| 2 | BCP / BCM | Business continuity plan / management |
| 3 | CPX | Cyber-physical correlation case |
| 4 | GSOC | Global security operations centre |
| 5 | HoM | Head of Mission |
| 6 | Human-in-the-loop | A named person approves consequential actions proposed by agents |
| 7 | ISO 31030 | International standard for travel risk management |
| 8 | OSINT | Open-source intelligence |
| 9 | PSIM | Physical security information management |
| 10 | RLS | Row-level security in the database |
| 11 | RTO | Recovery time objective |
| 12 | SIEM | Security information and event management |
| 13 | Sovereign hosting | Platform and data hosted in-country under customer control |

"""Seed data constants. All people and organisations are fictional.

Sources: docs/design/NEXIRA_Demo_Full.html (MISSIONS, AFFECTED, OTHERS, STEPS,
TRIPS, SRC) and docs/decisions.md (D-09, D-10, D-11, D-17, D-18, D-22, D-23, §7).
"""

from decimal import Decimal

# --- missions (demo MISSIONS array, in order; index = demo id) ----------------------------
# (code, city, country name, ISO country code, lat, lon, staff)
MISSIONS: list[tuple[str, str, str, str, float, float, int]] = [
    ("LON", "London", "United Kingdom", "GB", 51.51, -0.13, 42),
    ("PAR", "Paris", "France", "FR", 48.86, 2.35, 38),
    ("BER", "Berlin", "Germany", "DE", 52.52, 13.4, 31),
    ("BRU", "Brussels", "Belgium", "BE", 50.85, 4.35, 27),
    ("GVA", "Geneva", "Switzerland", "CH", 46.2, 6.14, 33),
    ("ROM", "Rome", "Italy", "IT", 41.9, 12.5, 24),
    ("MAD", "Madrid", "Spain", "ES", 40.42, -3.7, 19),
    ("MOW", "Moscow", "Russia", "RU", 55.75, 37.6, 29),
    ("ANK", "Ankara", "Türkiye", "TR", 39.93, 32.86, 22),
    ("CAI", "Cairo", "Egypt", "EG", 30.04, 31.24, 35),
    ("RBA", "Rabat", "Morocco", "MA", 34.02, -6.84, 17),
    ("ABV", "Abuja", "Nigeria", "NG", 9.07, 7.49, 16),
    ("NBO", "Nairobi", "Kenya", "KE", -1.286, 36.817, 14),
    ("ADD", "Addis Ababa", "Ethiopia", "ET", 9.03, 38.74, 18),
    ("PRY", "Pretoria", "South Africa", "ZA", -25.75, 28.19, 21),
    ("AMM", "Amman", "Jordan", "JO", 31.95, 35.93, 23),
    ("BGW", "Baghdad", "Iraq", "IQ", 33.31, 44.37, 19),
    ("RUH", "Riyadh", "Saudi Arabia", "SA", 24.71, 46.68, 41),
    ("MCT", "Muscat", "Oman", "OM", 23.59, 58.41, 20),
    ("ISB", "Islamabad", "Pakistan", "PK", 33.69, 73.05, 26),
    ("DEL", "New Delhi", "India", "IN", 28.61, 77.21, 44),
    ("DAC", "Dhaka", "Bangladesh", "BD", 23.81, 90.41, 15),
    ("BJS", "Beijing", "China", "CN", 39.9, 116.4, 39),
    ("SEL", "Seoul", "South Korea", "KR", 37.57, 126.98, 25),
    ("TYO", "Tokyo", "Japan", "JP", 35.68, 139.69, 34),
    ("MNL", "Manila", "Philippines", "PH", 14.6, 120.98, 18),
    ("KUL", "Kuala Lumpur", "Malaysia", "MY", 3.14, 101.69, 21),
    ("SIN", "Singapore", "Singapore", "SG", 1.35, 103.82, 24),
    ("JKT", "Jakarta", "Indonesia", "ID", -6.2, 106.85, 22),
    ("CBR", "Canberra", "Australia", "AU", -35.28, 149.13, 17),
    ("WAS", "Washington", "United States", "US", 38.9, -77.04, 48),
    ("NYC", "New York (UN)", "United States", "US", 40.75, -73.97, 36),
    ("YOW", "Ottawa", "Canada", "CA", 45.42, -75.7, 18),
    ("MEX", "Mexico City", "Mexico", "MX", 19.43, -99.13, 16),
    ("BSB", "Brasília", "Brazil", "BR", -15.79, -47.88, 19),
    ("BUE", "Buenos Aires", "Argentina", "AR", -34.6, -58.38, 15),
]
ELEVATED = {"Baghdad", "Islamabad", "Abuja", "Jakarta"}  # MODERATE; shown as "Elevated" (D-08)

# --- Nairobi (decisions.md §7) -----------------------------------------------------------------
EPICENTRE = (-1.2838, 36.8245)
EMBASSY = (-1.2950, 36.8080)
RESIDENCE = (-1.2745, 36.7935)
HOTEL = (-1.2975, 36.8240)
HANA = (-1.2676, 36.8108)
PETER = (-1.2985, 36.8195)
NAIROBI_CITIZENS = 212
CITIZEN_MAX_RADIUS_M = 4500  # inside the 5,000 m impact radius with margin

# AFFECTED array: (name, role title, place, source, confidence, person type)
# Location rule for "Embassy" rows: within 0.8 km of the Embassy (§7).
NAIROBI_PEOPLE: list[tuple[str, str, str, str, int, str]] = [
    ("Amb. Layla Haddad", "Head of Mission", "Residence", "MOBILE_GPS", 98, "DIPLOMAT"),
    ("Omar Siddiqui", "Deputy Head of Mission", "Embassy", "ACCESS_CONTROL", 99, "DIPLOMAT"),
    ("Martin Keller", "Security Attaché", "Embassy", "ACCESS_CONTROL", 99, "DIPLOMAT"),
    ("Aisha Rahman", "Political Officer", "Embassy", "ACCESS_CONTROL", 97, "DIPLOMAT"),
    ("Grace Wanjiru", "Consular Officer", "Embassy", "MOBILE_GPS", 95, "DIPLOMAT"),
    ("Sara Lindqvist", "Economic Officer", "Embassy", "ACCESS_CONTROL", 99, "DIPLOMAT"),
    ("Yusuf Al-Amin", "Communications Officer", "Embassy", "MOBILE_GPS", 94, "DIPLOMAT"),
    ("Nadia Petrova", "Administration Officer", "Embassy", "ACCESS_CONTROL", 99, "DIPLOMAT"),
    (
        "Peter Mwangi",
        "Driver (local staff)",
        "In transit · Haile Selassie Ave",
        "MOBILE_GPS",
        91,
        "LOCAL_STAFF",
    ),
    ("Hana Takeda", "Cultural Attaché", "Last seen · Westlands", "CALENDAR_HR", 72, "DIPLOMAT"),
    ("Karim Mansour", "Defence Attaché", "Embassy", "ACCESS_CONTROL", 99, "DIPLOMAT"),
    ("Ruth Achieng", "Consular Assistant", "Embassy", "ACCESS_CONTROL", 98, "DIPLOMAT"),
    ("David Okafor", "Logistics Officer", "Embassy", "MOBILE_GPS", 93, "DIPLOMAT"),
    ("James Otieno", "IT Support (local staff)", "Embassy", "ACCESS_CONTROL", 99, "LOCAL_STAFF"),
    ("Dr. Elena Costa", "Trade delegation", "Hotel · Upper Hill", "TRAVEL_BOOKING", 89, "DELEGATE"),
    ("Rami Khalil", "Trade delegation", "Hotel · Upper Hill", "TRAVEL_BOOKING", 89, "DELEGATE"),
    ("Mei Lin", "Trade delegation", "Hotel · Upper Hill", "TRAVEL_BOOKING", 89, "DELEGATE"),
]

# OTHERS array: named staff at other missions (name, role, city, place, source, confidence).
OTHER_NAMED: list[tuple[str, str, str, str, str, int]] = [
    ("Khalid Nasser", "Head of Mission", "London", "Embassy", "ACCESS_CONTROL", 99),
    ("Sophie Martin", "First Secretary", "Paris", "In transit · CDG", "TRAVEL_BOOKING", 92),
    ("Tariq Aziz", "Consul General", "New York (UN)", "UN HQ", "MOBILE_GPS", 96),
    ("Lena Fischer", "Political Officer", "Berlin", "Embassy", "ACCESS_CONTROL", 99),
    ("Arjun Mehta", "Economic Counsellor", "New Delhi", "Ministry of Commerce", "CALENDAR_HR", 81),
    ("Noor Hamdan", "Security Attaché", "Baghdad", "Embassy", "ACCESS_CONTROL", 99),
    ("Kenji Watanabe", "Cultural Attaché", "Tokyo", "Residence", "MOBILE_GPS", 97),
    ("Fatima Zahra", "Consular Officer", "Rabat", "Embassy", "ACCESS_CONTROL", 98),
    ("Lucas Silva", "Trade Attaché", "Brasília", "In transit · GRU→BSB", "TRAVEL_BOOKING", 90),
    ("Mariam Saleh", "Deputy Head of Mission", "Jakarta", "Embassy", "ACCESS_CONTROL", 99),
    ("Ahmed Farouk", "Head of Mission", "Cairo", "Residence", "MOBILE_GPS", 98),
    ("Olivia Brown", "Political Officer", "Washington", "State Dept. meeting", "CALENDAR_HR", 84),
    ("Hassan Qureshi", "Defence Attaché", "Islamabad", "Embassy", "ACCESS_CONTROL", 99),
]

# Plan G-10: personnel = 926 mission staff (array) + 412 others = 1,338 (demo KPI).
# The 3 Nairobi delegates count towards the 412.
OTHER_PERSONNEL = 412
OTHER_CITIZENS = 1000  # D-27: about 1,000 citizens across the other missions

# --- trip TRP-8812 (demo TRIPS) ------------------------------------------------------------------
TRIP_REFERENCE = "TRP-8812"
TRIP_PURPOSE = "Trade delegation (3)"

# --- intel sources (D-09, D-10, D-11) -----------------------------------------------------------
# (code, name, reliability, severity_map, category_map, enabled, fusion)
GENERIC_SEVERITY = {"Minor": "LOW", "Moderate": "MODERATE", "Major": "HIGH", "Severe": "CRITICAL"}
SOURCES: list[tuple[str, str, Decimal, dict[str, str], dict[str, str], bool, bool]] = [
    (
        "DATAMINR",
        "Dataminr",
        Decimal("0.60"),
        {"Low": "LOW", "Medium": "MODERATE", "High": "HIGH", "Critical": "CRITICAL"},
        {"Protest / Civil Unrest": "CIVIL_UNREST", "Transport Disruption": "TRANSPORT_STRIKE"},
        True,
        True,
    ),
    (
        "MAX",
        "MAX Security",
        Decimal("0.55"),
        {
            "Level 1": "LOW",
            "Level 2": "LOW",
            "Level 3": "MODERATE",
            "Level 4": "HIGH",
            "Level 5": "CRITICAL",
        },
        {"Civil Unrest": "CIVIL_UNREST", "Strike": "TRANSPORT_STRIKE"},
        True,
        True,
    ),
    (
        "RISKLINE",
        "Riskline",
        Decimal("0.55"),
        # D-11: a per-source map must never turn "Moderate" into HIGH.
        {"Low": "LOW", "Moderate": "MODERATE", "High": "HIGH", "Extreme": "CRITICAL"},
        {"Unrest": "CIVIL_UNREST", "Industrial Action": "TRANSPORT_STRIKE"},
        True,
        True,
    ),
    (
        "DRAGONFLY",
        "Dragonfly",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Civil unrest": "CIVIL_UNREST"},
        True,
        True,
    ),
    (
        "FACTAL",
        "Factal",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Unrest": "CIVIL_UNREST", "Strike": "TRANSPORT_STRIKE"},
        True,
        True,
    ),
    (
        "SAMDESK",
        "Samdesk",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Protest": "CIVIL_UNREST"},
        True,
        True,
    ),
    (
        "XWEATHER",
        "xWeather",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Flood": "FLOOD", "Storm": "STORM"},
        True,
        True,
    ),
    (
        "HEALIX",
        "Healix",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Outbreak": "HEALTH_OUTBREAK"},
        True,
        True,
    ),
    # D-09: no OSINT in Phase 1.
    (
        "OSINT",
        "NEXIRA OSINT",
        Decimal("0.50"),
        GENERIC_SEVERITY,
        {"Unrest": "CIVIL_UNREST"},
        False,
        False,
    ),
]

# --- playbook PB-07 (demo STEPS; plan G-14) ------------------------------------------------------
PB07_TRIGGER = {"category": "CIVIL_UNREST", "max_distance_m": 5000, "min_severity": "HIGH"}

# D-15: pre-written templates. AR, FR and SW must be reviewed by native speakers
# before any external demo; until then they carry the REVIEW REQUIRED marker.
REVIEW_REQUIRED = "[REVIEW REQUIRED] "
CITIZEN_ADVISORY = {
    "en": "Civil unrest in central Nairobi. Stay indoors, avoid the CBD and Upper Hill, and "
    "reply SAFE or HELP. Updates every 2 hours.",
    "ar": REVIEW_REQUIRED + "اضطرابات مدنية في وسط نيروبي. ابقوا في الداخل، وتجنبوا وسط المدينة "
    "ومنطقة أبر هيل، وردّوا بكلمة SAFE أو HELP. تحديثات كل ساعتين.",
    "fr": REVIEW_REQUIRED + "Troubles civils dans le centre de Nairobi. Restez à l'intérieur, "
    "évitez le CBD et Upper Hill, et répondez SAFE ou HELP. Mises à jour toutes les 2 heures.",
    "sw": REVIEW_REQUIRED + "Kuna ghasia katikati ya jiji la Nairobi. Kaeni ndani, epukeni CBD "
    "na Upper Hill, na jibuni SAFE au HELP. Taarifa mpya kila saa 2.",
}

# --- message templates (D-31, PC-07): per mission, with a generic fallback ---------------
# (code, kind, mission code or None for generic, name, texts). Every AR/FR/SW text keeps the
# REVIEW REQUIRED marker and is stored as not reviewed until a native speaker checks it (D-15).
# Nairobi reuses CITIZEN_ADVISORY unchanged, so the acceptance scenario sends the same words.
SHELTER = "CIVIL_UNREST_SHELTER"
MESSAGE_TEMPLATES: list[tuple[str, str, str | None, str, dict[str, str]]] = [
    (
        SHELTER,
        "ADVISORY",
        None,
        "Civil unrest: shelter in place",
        {
            "en": "Civil unrest in central {city}. Stay indoors, avoid demonstrations and "
            "large crowds, and reply SAFE or HELP. Updates every 2 hours.",
            "ar": REVIEW_REQUIRED + "اضطرابات مدنية في وسط {city}. ابقوا في الداخل، وتجنبوا "
            "المظاهرات والتجمعات الكبيرة، وردّوا بكلمة SAFE أو HELP. تحديثات كل ساعتين.",
            "fr": REVIEW_REQUIRED + "Troubles civils dans le centre de {city}. Restez à "
            "l'intérieur, évitez les manifestations et les rassemblements, et répondez SAFE ou "
            "HELP. Mises à jour toutes les 2 heures.",
            "sw": REVIEW_REQUIRED + "Kuna ghasia katikati ya {city}. Kaeni ndani, epukeni "
            "maandamano na mikusanyiko mikubwa, na jibuni SAFE au HELP. Taarifa mpya kila saa 2.",
        },
    ),
    (SHELTER, "ADVISORY", "NBO", "Civil unrest: shelter in place (Nairobi)", CITIZEN_ADVISORY),
    (
        SHELTER,
        "ADVISORY",
        "PAR",
        "Civil unrest: shelter in place (Paris)",
        {
            "en": "Protests and clashes in central Paris, around République, Bastille and "
            "Nation. Stay indoors, avoid the marches, expect transport disruption, and reply "
            "SAFE or HELP. Updates every 2 hours.",
            "ar": REVIEW_REQUIRED + "احتجاجات واشتباكات في وسط باريس، حول ساحات الجمهورية "
            "والباستيل والأمة. ابقوا في الداخل، وتجنبوا المسيرات، وتوقعوا اضطراب وسائل النقل، "
            "وردّوا بكلمة SAFE أو HELP. تحديثات كل ساعتين.",
            "fr": REVIEW_REQUIRED + "Manifestations et heurts dans le centre de Paris, autour "
            "de République, Bastille et Nation. Restez à l'intérieur, évitez les cortèges, "
            "prévoyez des perturbations dans les transports, et répondez SAFE ou HELP. Mises "
            "à jour toutes les 2 heures.",
            "sw": REVIEW_REQUIRED + "Maandamano na makabiliano katikati ya Paris, karibu na "
            "République, Bastille na Nation. Kaeni ndani, epukeni maandamano, tarajieni "
            "usumbufu wa usafiri, na jibuni SAFE au HELP. Taarifa mpya kila saa 2.",
        },
    ),
]

PERSONNEL_TYPES = ["DIPLOMAT", "LOCAL_STAFF", "DELEGATE"]

# (seq, name, action_type, action_config, requires_approval_role)
PB07_STEPS: list[tuple[int, str, str, dict[str, object], str | None]] = [
    (
        1,
        "Confirm incident & severity",
        "TASK",
        {"summary": "Fusion engine · sources and confidence confirmed"},
        None,
    ),
    (
        2,
        "Notify Head of Mission & Security Attaché",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {
                "mission": "incident",
                "role_titles": ["Head of Mission", "Security Attaché"],
            },
            "channels": ["APP", "SMS", "VOICE"],
            "message": "URGENT: Civil unrest near Embassy — security team alert",
        },
        None,
    ),
    (
        3,
        "Notify HQ Global Operations Centre",
        "TASK",
        {"notify_user_roles": ["DUTY_OFFICER"], "summary": "HQ GOC alerted"},
        None,
    ),
    (
        4,
        "Issue shelter-in-place advisory & activate BCP-NBO",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {"exposed": True, "person_types": PERSONNEL_TYPES},
            "channels": ["APP", "SMS", "WHATSAPP"],
            "message": "Shelter in place. Avoid CBD and Upper Hill.",
            "continuity_plan": "BCP-NBO",
            # Used by the Communications agent when this step is done (D-15).
            "citizen_advisory": {
                "translations": CITIZEN_ADVISORY,
                "channels": ["SMS", "WHATSAPP", "APP"],
            },
        },
        None,
    ),
    (
        5,
        "Send safety check-in",
        "CHECKIN",
        {
            "audience": {"exposed": True},
            "channels": ["APP", "SMS", "WHATSAPP"],
            "message": "Safety check-in: are you safe? Reply SAFE or HELP.",
            "escalate_after_s": 600,
        },
        None,
    ),
    (
        6,
        "Place assistance partner on standby",
        "PARTNER_REQUEST",
        {"partner": "Kestrel Medical Assistance", "service": "Medical & evacuation support"},
        None,
    ),
    (
        7,
        "Approve evacuation route B",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {"exposed": True, "person_types": PERSONNEL_TYPES},
            "channels": ["APP", "SMS"],
            "message": "Route B approved — await movement instruction",
        },
        "HEAD_OF_MISSION",
    ),
    (
        8,
        "Brief leadership",
        "BRIEFING",
        {"recipient": "Minister's office", "template": "situation_report"},
        None,
    ),
]

# --- agents and policies (D-17 seed table) --------------------------------------------------------
AGENTS: list[tuple[str, str, str, int]] = [
    ("WATCH_OFFICER", "Watch Officer", "Watches intel feeds and new incidents.", 0),
    ("EXPOSURE", "Exposure", "Watches people, trips and sites exposed to incidents.", 0),
    ("RESPONSE_PLANNER", "Response Planner", "Matches incidents to response playbooks.", 2),
    ("COMMUNICATIONS", "Communications", "Drafts multilingual advisories for audiences.", 2),
]
# (action_type, floor, approver_roles, undoable)
POLICIES: list[tuple[str, int, list[str], bool]] = [
    ("LOG_INFO", 0, [], True),
    ("POST_INTERNAL_NOTE", 0, [], True),
    ("START_PLAYBOOK", 2, ["DUTY_OFFICER|SECURITY_OFFICER"], False),
    ("SEND_EXTERNAL_MESSAGE", 2, ["DUTY_OFFICER|CONSULAR_OFFICER"], False),
    # Test only (scene 5): injected by a test, never proposed by a Phase 1 agent.
    ("START_EVACUATION", 3, ["HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"], False),
]

# --- reference counters (D-18) -------------------------------------------------------------------
INC_START = 1041  # next incident: INC-<year>-1042
NTF_START = 3100  # next campaign: NTF-3101

# --- fictional name pools (generated people) ------------------------------------------------------
FIRST_NAMES = [
    "Adel", "Ama", "Anders", "Ana", "Bilal", "Camila", "Chen", "Dalia", "Diego", "Elif", "Emeka",
    "Farah", "Farid", "Hanna", "Ibrahim", "Ines", "Jae", "Jonas", "Kofi", "Lara", "Leon", "Lina",
    "Malik", "Maya", "Mehmet", "Nadia", "Nikhil", "Noor", "Olga", "Omar", "Priya", "Rafael",
    "Rania", "Rosa", "Sami", "Sana", "Selin", "Tomas", "Wei", "Yara", "Yusuf", "Zainab", "Zara",
]  # fmt: skip
LAST_NAMES = [
    "Abiodun", "Alvarez", "Amari", "Bakr", "Bauer", "Castillo", "Chowdhury", "Dahl", "Demir",
    "Eriksen", "Farah", "Haddad", "Hassan", "Ibsen", "Iqbal", "Jansen", "Karimi", "Khoury",
    "Kowalski", "Lindgren", "Mansour", "Moreau", "Nakamura", "Nasser", "Ndlovu", "Novak",
    "Okafor", "Osei", "Park", "Petrov", "Qureshi", "Rahimi", "Rossi", "Saleh", "Santos", "Tan",
    "Usman", "Vasquez", "Wanjala", "Yilmaz", "Zhou",
]  # fmt: skip
DIPLOMAT_TITLES = [
    "First Secretary", "Second Secretary", "Third Secretary", "Political Officer",
    "Economic Officer", "Consular Officer", "Administration Officer", "Press Attaché",
]  # fmt: skip
LOCAL_TITLES = ["Driver", "Receptionist", "IT Support", "Interpreter", "Facilities", "Guard"]

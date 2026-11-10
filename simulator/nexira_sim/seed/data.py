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
TRP_START = 8834  # next user trip: TRP-8835, after the VIP visit's TRP-8834 (D-18, D-42)

# --- Journey Management (D-32, PC-16) ------------------------------------------------------------
# Simulated base risk per country: (security, unrest, health, transport), 0-100. Kenya and
# Iraq follow the demo's CRISK figures; France starts LOW, so the France scenario's
# incident is what raises it. Countries not listed get DEFAULT_COUNTRY_RISK.
COUNTRY_RISK_SOURCE = "Riskline (simulated)"
COUNTRY_RISK: dict[str, tuple[int, int, int, int]] = {
    "KE": (58, 46, 30, 40),
    "IQ": (78, 60, 35, 62),
    "ET": (55, 52, 38, 45),
    "BD": (44, 50, 52, 48),
    "PK": (62, 55, 40, 45),
    "NG": (60, 50, 45, 42),
    "ID": (35, 30, 40, 48),
    "FR": (25, 38, 8, 30),
    "BE": (22, 25, 12, 15),
    "BR": (40, 28, 22, 30),
    "SG": (8, 6, 10, 8),
    "KR": (12, 15, 10, 10),
    # Destinations of the tracked-flight trips without a mission (D-33): rated, so they are
    # not counted MODERATE as unrated countries are (review of Prompt 25, M1).
    "AE": (18, 10, 10, 12),
    "NL": (15, 20, 8, 12),
    "PT": (12, 18, 8, 10),
}
DEFAULT_COUNTRY_RISK = (20, 15, 10, 15)

# Trips for the Journey screen, all in the future so none is in today's exposure:
# (reference, purpose, traveller mission, travellers, destination, country, days from the
#  scenario date, length in days, status, risk). Seeded trips have no requester (plan G-4),
# except the draft, which belongs to the demo Travel Desk user so it can be edited and
# submitted. TRIP_SCOPE: the approval scope, the single mission in the country (plan G-2).
EXTRA_TRIPS: list[tuple[str, str, str, int, str, str, int, int, str, str]] = [
    # Approved at LOW: the France scenario makes France CRITICAL, so the Travel & Air agent
    # proposes cancelling it (D-34, plan-pilot-ta G-6). Berlin staff on no other trip.
    ("TRP-8811", "Cultural exchange · Paris", "BER", 2, "Paris", "FR", 5, 2, "APPROVED", "LOW"),
    ("TRP-8814", "Security assessment", "AMM", 2, "Baghdad", "IQ", 5, 3, "PENDING", "HIGH"),
    ("TRP-8815", "EU coordination meeting", "LON", 1, "Brussels", "BE", 2, 1, "APPROVED", "LOW"),
    ("TRP-8816", "Donor roundtable", "NBO", 2, "Addis Ababa", "ET", 4, 2, "DRAFT", "LOW"),
    (
        "TRP-8817",
        "Regional consular conference",
        "JKT",
        1,
        "Singapore",
        "SG",
        9,
        2,
        "APPROVED",
        "LOW",
    ),
]

TRIP_SCOPE = {"TRP-8814": "BGW"}

# Weather (D-35, WX-06): Kuala Lumpur staff at a Manila hotel, on a trip active on the
# scenario date, so MNL-TROPICAL-STORM's storm makes it "Impacted". They stay away from
# every Phase 1 scenario. (reference, purpose, traveller mission, travellers, destination,
# country, hotel (lat, lon), place)
MANILA_TRIP = (
    "TRP-8810",
    "Regional consular meeting · Manila",
    "KUL",
    2,
    "Manila",
    "PH",
    (14.5547, 121.0244),
    "Hotel · Makati (TRP-8810)",
)
TRIP_REQUESTER = {"TRP-8816": "travel.desk"}

# --- Air Travel Tracking (D-33, PC-17..19) -----------------------------------------------------
# Simulated airports (D-19): (IATA, name, city, ISO country, lat, lon). Fictional flight
# numbers ("XW"); no real schedules.
AIRPORTS: list[tuple[str, str, str, str, float, float]] = [
    ("LHR", "London Heathrow", "London", "GB", 51.47, -0.45),
    ("CDG", "Paris Charles de Gaulle", "Paris", "FR", 49.01, 2.55),
    ("BRU", "Brussels", "Brussels", "BE", 50.90, 4.48),
    ("AMS", "Amsterdam Schiphol", "Amsterdam", "NL", 52.31, 4.76),
    ("LIS", "Lisbon", "Lisbon", "PT", 38.77, -9.13),
    ("AUH", "Abu Dhabi", "Abu Dhabi", "AE", 24.43, 54.65),
    ("NBO", "Nairobi Jomo Kenyatta", "Nairobi", "KE", -1.32, 36.93),
    ("MBA", "Mombasa Moi", "Mombasa", "KE", -4.03, 39.59),
    ("ADD", "Addis Ababa Bole", "Addis Ababa", "ET", 8.98, 38.80),
    ("AMM", "Amman Queen Alia", "Amman", "JO", 31.72, 35.99),
    ("BGW", "Baghdad", "Baghdad", "IQ", 33.26, 44.23),
    ("CGK", "Jakarta Soekarno-Hatta", "Jakarta", "ID", -6.13, 106.66),
    ("SIN", "Singapore Changi", "Singapore", "SG", 1.36, 103.99),
    ("BSB", "Brasília", "Brasília", "BR", -15.87, -47.92),
]

# Tracked-flight trips, APPROVED with one FLIGHT segment: (reference, purpose, traveller
# mission, travellers to skip, travellers, destination, country, flight, from, to, hours
# from the anchor to departure, flight hours, restricted, scenario flight).
# - TRP-8818 carries XW 451 for the NBO-AIR-DIVERSION scenario (plan G-1, G-3): London
#   staff not on any other trip, so no Phase 1 figure changes; it departs on the scenario
#   date at 10:00 GST and moves only through the scenario's FLIGHT_FEED events.
# - TRP-8819 and TRP-8820 fly in real time around the seed time (plan G-4).
# - TRP-8813 is restricted (D-33): its flight must never be tracked or shown.
AIR_TRIPS: list[
    tuple[str, str, str, int, int, str, str, str, str, str, float, float, bool, bool]
] = [
    (
        "TRP-8818",
        "HQ consultations · Nairobi",
        "LON",
        1,
        3,
        "Nairobi",
        "KE",
        "XW 451",
        "AUH",
        "NBO",
        10,
        4.5,
        False,
        True,
    ),
    (
        "TRP-8819",
        "Trade fair · Amsterdam",
        "JKT",
        1,
        2,
        "Amsterdam",
        "NL",
        "XW 812",
        "CGK",
        "AMS",
        -3,
        14,
        False,
        False,
    ),
    (
        "TRP-8820",
        "Bilateral talks · Lisbon",
        "BSB",
        0,
        2,
        "Lisbon",
        "PT",
        "XW 260",
        "BSB",
        "LIS",
        -1,
        9.5,
        False,
        False,
    ),
    (
        "TRP-8813",
        "Ministerial visit",
        "AMM",
        2,
        2,
        "Abu Dhabi",
        "AE",
        "XW 777",
        "AMM",
        "AUH",
        1,
        3,
        True,
        False,
    ),
]

# --- intel sources (D-09, D-10, D-11) -----------------------------------------------------------
# (code, name, reliability, severity_map, category_map, enabled, fusion)
GENERIC_SEVERITY = {"Minor": "LOW", "Moderate": "MODERATE", "Major": "HIGH", "Severe": "CRITICAL"}
SOURCES: list[tuple[str, str, Decimal, dict[str, str], dict[str, str], bool, bool]] = [
    (
        "DATAMINR",
        "Dataminr",
        Decimal("0.60"),
        {"Low": "LOW", "Medium": "MODERATE", "High": "HIGH", "Critical": "CRITICAL"},
        {
            "Protest / Civil Unrest": "CIVIL_UNREST",
            "Transport Disruption": "TRANSPORT_STRIKE",
            "Tropical storm": "STORM",  # MNL-TROPICAL-STORM's second provider (plan-pilot-wx §5)
        },
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
        # WX §28 Q3: the two Phase 1 categories plus two (D-35); cyclone forecasts and
        # wildfire (D-38, §43 Q1).
        {
            "Flood": "FLOOD",
            "Storm": "STORM",
            "Dust storm": "DUST_STORM",
            "Extreme heat": "EXTREME_HEAT",
            "Tropical cyclone": "TROPICAL_CYCLONE",
            "Wildfire": "WILDFIRE",
        },
        True,
        True,
    ),
    # Natural hazards (D-38, §43 Q1): the measure in each signal decides its severity
    # (app/modules/intel/hazards.py), so these two have no severity map.
    (
        "SEISMIC",
        "Seismic network",
        Decimal("0.70"),
        {},
        {"Earthquake": "EARTHQUAKE"},
        True,
        True,
    ),
    (
        "AIRQ",
        "Air-quality network",
        Decimal("0.60"),
        {},
        {"Air quality": "AIR_QUALITY"},
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
STAFF_ALERT = "CIVIL_UNREST_STAFF_ALERT"  # PB-07 step 4's alert to personnel
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
        STAFF_ALERT,
        "ALERT",
        None,
        "Civil unrest: staff alert",
        {"en": "Shelter in place. Avoid demonstrations in central {city}."},
    ),
    (
        STAFF_ALERT,
        "ALERT",
        "NBO",
        "Civil unrest: staff alert (Nairobi)",
        {"en": "Shelter in place. Avoid CBD and Upper Hill."},  # PB-07 v1's words
    ),
    (
        STAFF_ALERT,
        "ALERT",
        "PAR",
        "Civil unrest: staff alert (Paris)",
        {"en": "Shelter in place. Avoid République, Bastille and Nation."},
    ),
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

# PB-06 (D-35, WX-05): English only until reviewed (D-15); generic with a Manila text, as
# the unrest templates have Nairobi and Paris ones.
WEATHER_SHELTER = "SEVERE_WEATHER_SHELTER"
WEATHER_STAFF_ALERT = "SEVERE_WEATHER_STAFF_ALERT"
MESSAGE_TEMPLATES += [
    (
        WEATHER_SHELTER,
        "ADVISORY",
        None,
        "Severe weather: shelter in place",
        {
            "en": "Severe weather warning for {city}. Stay indoors, away from windows and "
            "flood water, and reply SAFE or HELP. Updates every 2 hours."
        },
    ),
    (
        WEATHER_SHELTER,
        "ADVISORY",
        "MNL",
        "Severe weather: shelter in place (Manila)",
        {
            "en": "Tropical storm warning for Manila. Stay indoors, away from windows, Manila "
            "Bay and flooded streets, and reply SAFE or HELP. Updates every 2 hours."
        },
    ),
    (
        WEATHER_STAFF_ALERT,
        "ALERT",
        None,
        "Severe weather: staff alert",
        {"en": "Severe weather warning for {city}. Stay indoors and away from windows."},
    ),
    (
        WEATHER_STAFF_ALERT,
        "ALERT",
        "MNL",
        "Severe weather: staff alert (Manila)",
        {"en": "Tropical storm warning. Stay indoors; avoid Manila Bay and low-lying roads."},
    ),
]

# PB-01 (D-38, HZ-07): English only until reviewed (D-15).
QUAKE_ADVISORY = "EARTHQUAKE_CITIZEN_ADVISORY"
QUAKE_STAFF_ALERT = "EARTHQUAKE_STAFF_ALERT"
MESSAGE_TEMPLATES += [
    (
        QUAKE_ADVISORY,
        "ADVISORY",
        None,
        "Earthquake: aftershock advice",
        {
            "en": "A strong earthquake has affected the {city} area. Expect aftershocks: stay "
            "out of damaged buildings, follow local authorities, and reply SAFE or HELP. "
            "Updates every 2 hours."
        },
    ),
    (
        QUAKE_STAFF_ALERT,
        "ALERT",
        None,
        "Earthquake: staff alert",
        {"en": "Earthquake near {city}. Leave damaged buildings, expect aftershocks, report in."},
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

# PB-07 v2 (Prompt 19, D-31): step 4 names templates instead of carrying Nairobi text, so
# each mission gets its own words (MN-04). Everything else is v1 unchanged; v1 is retired.
PB07_VERSION = 2
PB07_STEP4_V2: dict[str, object] = {
    "campaign_type": "ALERT",
    "audience": {"exposed": True, "person_types": PERSONNEL_TYPES},
    "channels": ["APP", "SMS", "WHATSAPP"],
    "message_template": STAFF_ALERT,
    "continuity_plan": "BCP-NBO",
    # Used by the Communications agent when this step is done (D-15, D-31).
    "citizen_advisory_template": SHELTER,
    "citizen_advisory_channels": ["SMS", "WHATSAPP", "APP"],
}
PB07_STEPS_V2 = [
    (seq, name, kind, PB07_STEP4_V2 if seq == 4 else config, role)
    for seq, name, kind, config, role in PB07_STEPS
]

# PB-06 · Severe weather (WX-05, plan-pilot-wx.md §4; WX §28 Q6): HIGH or CRITICAL storm or
# flood with a mission site inside the incident's radius.
PB06_TRIGGER = {
    "categories": ["STORM", "FLOOD"],
    "min_severity": "HIGH",
    "mission_site_exposed": True,
}
PB06_STEPS: list[tuple[int, str, str, dict[str, object], str | None]] = [
    (
        1,
        "Confirm the warning & its reach",
        "TASK",
        {"summary": "Fusion engine · weather sources, severity and impact radius confirmed"},
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
            "message": "URGENT: Severe weather warning for the mission — security team alert",
        },
        None,
    ),
    (
        3,
        "Alert exposed staff to shelter",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {"exposed": True, "person_types": PERSONNEL_TYPES},
            "channels": ["APP", "SMS", "WHATSAPP"],
            "message_template": WEATHER_STAFF_ALERT,
            # Used by the Communications agent when this step is done (D-15, D-31).
            "citizen_advisory_template": WEATHER_SHELTER,
            "citizen_advisory_channels": ["SMS", "WHATSAPP", "APP"],
        },
        None,
    ),
    (
        4,
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
]

# PB-01 · Earthquake (D-38, HZ-07; plan-pilot-hz §7): HIGH or CRITICAL with a mission site
# inside its radius. Safety check-in first, then the staff alert (the Communications agent
# then proposes the citizen advisory: a second person approves it, D-31), then the mission's
# security team. No approval gate, as PB-06 (plan §7 named one; PB-06 has none, G-14).
PB01_TRIGGER = {
    "categories": ["EARTHQUAKE"],
    "min_severity": "HIGH",
    "mission_site_exposed": True,
}
PB01_STEPS: list[tuple[int, str, str, dict[str, object], str | None]] = [
    (
        1,
        "Send safety check-in",
        "CHECKIN",
        {
            "audience": {"exposed": True},
            "channels": ["APP", "SMS", "WHATSAPP"],
            "message": "Earthquake: are you safe? Reply SAFE or HELP.",
            "escalate_after_s": 600,
        },
        None,
    ),
    (
        2,
        "Alert exposed staff",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {"exposed": True, "person_types": PERSONNEL_TYPES},
            "channels": ["APP", "SMS", "WHATSAPP"],
            "message_template": QUAKE_STAFF_ALERT,
            "citizen_advisory_template": QUAKE_ADVISORY,
            "citizen_advisory_channels": ["SMS", "WHATSAPP", "APP"],
        },
        None,
    ),
    (
        3,
        "Notify Head of Mission & Security Attaché",
        "NOTIFY",
        {
            "campaign_type": "ALERT",
            "audience": {
                "mission": "incident",
                "role_titles": ["Head of Mission", "Security Attaché"],
            },
            "channels": ["APP", "SMS", "VOICE"],
            "message": "URGENT: Earthquake near the mission — security team alert",
        },
        None,
    ),
]

# --- Natural Hazards & Climate (D-38) -----------------------------------------------------------
# HZ-08, §43 Q7: illustrative, fictional scores for every mission (0-100, today and 2050),
# from the design for its seven cities and plausible for the rest. Jakarta is highest in 2050.
CLIMATE_SCENARIO = "Illustrative 2050 (simulated)"
CLIMATE: dict[str, tuple[list[str], int, int]] = {
    "JKT": (["Flood", "Sea-level rise"], 82, 88),
    "DAC": (["Cyclone", "Flood"], 79, 86),
    "DEL": (["Heat", "Air quality"], 74, 83),
    "MNL": (["Typhoon", "Flood"], 76, 81),
    "RUH": (["Heat", "Dust"], 70, 79),
    "BGW": (["Heat", "Water stress"], 66, 77),
    "MCT": (["Heat", "Cyclone"], 62, 72),
    "KUL": (["Flood", "Heat"], 58, 67),
    "SIN": (["Sea-level rise", "Heat"], 52, 64),
    "ISB": (["Heat", "Flash flood"], 55, 64),
    "CAI": (["Heat", "Water stress"], 54, 63),
    "TYO": (["Earthquake", "Typhoon"], 57, 62),
    "MEX": (["Earthquake", "Water stress"], 50, 58),
    "ABV": (["Flood", "Heat"], 45, 56),
    "ANK": (["Earthquake", "Drought"], 48, 54),
    "AMM": (["Water stress", "Heat"], 44, 54),
    "BJS": (["Heat", "Air quality"], 46, 53),
    "RBA": (["Drought", "Heat"], 40, 51),
    "NBO": (["Drought", "Flash flood"], 41, 49),
    "ADD": (["Drought", "Flash flood"], 38, 47),
    "PRY": (["Drought", "Heat"], 36, 45),
    "BSB": (["Drought", "Wildfire"], 34, 44),
    "CBR": (["Wildfire", "Heat"], 35, 44),
    "NYC": (["Coastal flood", "Storm"], 33, 42),
    "WAS": (["Heat", "Storm"], 30, 38),
    "SEL": (["Flood", "Heat"], 30, 37),
    "MAD": (["Heat", "Drought"], 29, 37),
    "ROM": (["Heat", "Wildfire"], 28, 36),
    "BUE": (["Flood", "Heat"], 27, 34),
    "MOW": (["Heat", "Wildfire smoke"], 22, 29),
    "PAR": (["Heat", "Flood"], 23, 29),
    "LON": (["Flood (pluvial)"], 22, 27),
    "BRU": (["Flood", "Heat"], 21, 26),
    "BER": (["Heat", "Drought"], 20, 26),
    "GVA": (["Flood", "Landslide"], 18, 23),
    "YOW": (["Flood", "Wildfire smoke"], 17, 22),
}
# HZ-11, §43 Q8: three Dhaka staff live in flood-prone wards and two Jakarta staff in North
# Jakarta, as the design ("Jakarta mission · 2 staff homes"). Fictional coordinates. The last
# generated staff of each mission are moved home; nobody is added and nothing is drawn from
# rng, so the seeded totals stay as they are.
HAZARD_HOMES: dict[str, list[tuple[str, float, float]]] = {
    "DAC": [
        ("Home · Mirpur (flood-prone ward)", 23.8223, 90.3654),
        ("Home · Jatrabari (flood-prone ward)", 23.7104, 90.4348),
        ("Home · Badda (flood-prone ward)", 23.7806, 90.4265),
    ],
    "JKT": [
        ("Home · Penjaringan, North Jakarta (flood-prone)", -6.1260, 106.7900),
        ("Home · Kampung Melayu, Ciliwung bank (flood-prone)", -6.2230, 106.8660),
    ],
}

# --- Health Intelligence (D-39, plan-pilot-hl §2-5, §48): simulated and illustrative ----------
# The design's six advisories, present after `make reset-demo` (§48 Q2). None is HIGH, so the
# Communications agent proposes nothing until NBO-CHOLERA raises cholera (HL-10). Mpox's
# countries have no mission. (feed id, topic, topic code, countries, region, level, guidance,
# source, days since published)
WHO = "WHO Disease Outbreak News (simulated)"
HEALTH_ADVISORIES: list[tuple[str, str, str, list[str], str, str, str, str, int]] = [
    (
        "who-don:cholera-ke",
        "Cholera",
        "CHOLERA",
        ["KE"],
        "Kenya · Coast & Nairobi counties",
        "MODERATE",
        "Case increase in informal settlements; water-safety advice for staff.",
        WHO,
        2,
    ),
    (
        "moh-bd:dengue-dhaka",
        "Dengue fever",
        "DENGUE",
        ["BD"],
        "Bangladesh · Dhaka division",
        "MODERATE",
        "Seasonal rise; mosquito-bite prevention recommended.",
        "Ministry of Health bulletin (simulated)",
        4,
    ),
    (
        "who-don:mpox-central-africa",
        "Mpox (clade I)",
        "MPOX",
        ["CD", "CF", "CG", "BI", "RW", "UG"],
        "Central Africa · regional",
        "MODERATE",
        "Ongoing transmission; no travel restrictions advised.",
        WHO,
        6,
    ),
    (
        "who-don:h5n1-sea",
        "Avian influenza A(H5N1)",
        "AVIAN_INFLUENZA",
        ["ID", "KH", "PH", "VN"],
        "Southeast Asia · poultry outbreaks",
        "LOW",
        "Low risk to travellers; avoid live-bird markets.",
        WHO,
        9,
    ),
    (
        "moh-pk:measles-punjab",
        "Measles",
        "MEASLES",
        ["PK"],
        "Pakistan · Punjab",
        "MODERATE",
        "Check MMR vaccination status before travel.",
        "Ministry of Health bulletin (simulated)",
        11,
    ),
    (
        "partner:heat-delhi",
        "Heat-health warning",
        "HEAT_HEALTH",
        ["IN"],
        "India · Delhi NCR",
        "MODERATE",
        "Temperatures above 44 °C; adjust working hours.",
        "Kestrel Medical Assistance intel (simulated)",
        1,
    ),
]

# Entry and vaccination requirements for every mission country (§48 Q3): illustrative, not
# for real travel. The design's five, then plausible ones. (mandatory, recommended)
NO_MANDATORY = "No mandatory vaccinations"
ROUTINE = "Routine vaccinations up to date"
YELLOW_FEVER_RISK = "Yellow fever certificate if arriving from risk country"
HEALTH_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "KE": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Cholera (optional)"),
    "ET": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Meningitis"),
    "NG": ("Yellow fever certificate required", "Hep A · Typhoid · Meningitis"),
    "SA": ("Meningococcal ACWY for pilgrims", "Hep A · Flu"),
    "BD": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Japanese encephalitis"),
    "ZA": (YELLOW_FEVER_RISK, "Hep A · Typhoid"),
    "EG": (YELLOW_FEVER_RISK, "Hep A · Typhoid"),
    "MA": (NO_MANDATORY, "Hep A · Typhoid"),
    "JO": (NO_MANDATORY, "Hep A · Typhoid"),
    "IQ": (NO_MANDATORY, "Hep A · Typhoid · Rabies"),
    "OM": (YELLOW_FEVER_RISK, "Hep A · Typhoid"),
    "PK": ("Polio vaccination certificate on departure for long stays", "Hep A · Typhoid · MMR"),
    "IN": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Japanese encephalitis"),
    "CN": (YELLOW_FEVER_RISK, "Hep A · Japanese encephalitis"),
    "PH": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Dengue precautions"),
    "MY": (YELLOW_FEVER_RISK, "Hep A · Typhoid"),
    "SG": (YELLOW_FEVER_RISK, ROUTINE),
    "ID": (YELLOW_FEVER_RISK, "Hep A · Typhoid · Japanese encephalitis"),
    "AU": (YELLOW_FEVER_RISK, ROUTINE),
    "MX": (NO_MANDATORY, "Hep A · Typhoid"),
    "BR": (NO_MANDATORY, "Yellow fever (some regions) · Hep A · Typhoid"),
    "AR": (NO_MANDATORY, "Yellow fever (northern provinces) · Hep A"),
    **{
        cc: (NO_MANDATORY, ROUTINE)
        for cc in ("GB", "FR", "DE", "BE", "CH", "IT", "ES", "RU", "TR", "KR", "JP", "US", "CA")
    },
}

# Sample facilities (§48 Q5, fictional, "(sample)"). Nairobi's four as the design; Nairobi
# Central sits inside INC-…-1042's 5 km zone, the other three more than 5 km from every
# Nairobi unrest signal (plan-pilot-hl §4). (name, lat, lon, capabilities, trauma level,
# open 24/7, vetted by Kestrel)
NAIROBI_FACILITIES: list[tuple[str, float, float, list[str], int | None, bool, bool]] = [
    ("Nairobi Central Medical Centre (sample)", -1.2830, 36.8125, ["EMERGENCY"], None, True, False),
    (
        "Highland Private Hospital (sample)",
        -1.2580,
        36.7680,
        ["EMERGENCY", "TRAUMA", "ICU"],
        1,
        True,
        True,
    ),
    ("Westlands Clinic (sample)", -1.2400, 36.7780, ["OUTPATIENT", "PHARMACY"], None, False, True),
    (
        "Karen Specialist Hospital (sample)",
        -1.3200,
        36.7200,
        ["SURGERY", "ICU", "HELIPAD"],
        None,
        True,
        True,
    ),
]
# Every other mission: three sample facilities north-east, west and south of the mission
# (offsets in degrees, about 3, 5 and 8 km), the first two vetted by Kestrel.
FACILITY_PATTERN: list[tuple[str, float, float, list[str], int | None, bool, bool]] = [
    (
        "{city} General Hospital (sample)",
        0.020,
        0.020,
        ["EMERGENCY", "TRAUMA", "ICU"],
        2,
        True,
        True,
    ),
    (
        "{city} International Clinic (sample)",
        0.0,
        -0.045,
        ["OUTPATIENT", "PHARMACY"],
        None,
        False,
        True,
    ),
    ("{city} Medical Centre (sample)", -0.072, 0.0, ["EMERGENCY", "MATERNITY"], None, True, False),
]

# Staff health readiness, counts only (D-39, §48 Q4): illustrative, per mission's seeded
# staff. Vaccines offered for the open advisories' topics; Nairobi as the design (9 of its 14
# staff offered the cholera vaccine, plan-pilot-hl G-4).
VACCINES_OFFERED: dict[str, dict[str, int]] = {
    "NBO": {"CHOLERA": 9},
    "DAC": {"DENGUE": 0},
    "ISB": {"MEASLES": 18},
    "JKT": {"AVIAN_INFLUENZA": 4},
    "MNL": {"AVIAN_INFLUENZA": 6},
}
READINESS_AS_OF_DAYS = 14  # counts as of two weeks before the scenario date

# HL-06, HL-07 (plan-pilot-hl G-1): health advisory templates, kind ADVISORY, one per topic
# with the generic HEALTH_GENERAL fallback. Nairobi's cholera text is the design's; AR/FR/SW
# keep the REVIEW REQUIRED marker until a native speaker checks them (D-15).
HEALTH_CHOLERA_NBO = {
    "en": "Health advisory: Cholera cases are rising in Nairobi. Drink bottled or boiled water "
    "only, avoid street food, and seek care quickly if symptoms appear.",
    "ar": REVIEW_REQUIRED + "تنبيه صحي: حالات الكوليرا في ازدياد في نيروبي. اشربوا المياه "
    "المعبأة أو المغلية فقط، وتجنبوا طعام الشارع، واطلبوا الرعاية سريعاً عند ظهور الأعراض.",
    "fr": REVIEW_REQUIRED + "Alerte santé : les cas de choléra augmentent à Nairobi. Ne buvez que "
    "de l'eau en bouteille ou bouillie, évitez la nourriture de rue et consultez rapidement en "
    "cas de symptômes.",
    "sw": REVIEW_REQUIRED
    + "Tahadhari ya afya: visa vya kipindupindu vinaongezeka Nairobi. Kunyweni "
    "maji ya chupa au yaliyochemshwa tu, epukeni chakula cha mitaani, na tafuteni matibabu "
    "haraka dalili zikitokea.",
}
HEALTH_TEMPLATES: list[tuple[str, str, str | None, str, dict[str, str]]] = [
    (
        "HEALTH_GENERAL",
        "ADVISORY",
        None,
        "Health advisory",
        {
            "en": "Health advisory for {city}: a disease outbreak or health warning is in force. "
            "Follow the mission's guidance and seek care quickly if you feel unwell.",
            "ar": REVIEW_REQUIRED + "تنبيه صحي في {city}: يوجد تفشٍ لمرض أو تحذير صحي. اتبعوا "
            "إرشادات البعثة واطلبوا الرعاية سريعاً إذا شعرتم بتوعك.",
            "fr": REVIEW_REQUIRED + "Alerte santé à {city} : une épidémie ou une alerte sanitaire "
            "est en cours. Suivez les consignes de la mission et consultez rapidement en cas de "
            "malaise.",
            "sw": REVIEW_REQUIRED + "Tahadhari ya afya {city}: kuna mlipuko wa ugonjwa au onyo la "
            "afya. Fuateni maelekezo ya ubalozi na tafuteni matibabu haraka mkijisikia vibaya.",
        },
    ),
    (
        "HEALTH_CHOLERA",
        "ADVISORY",
        None,
        "Cholera advisory",
        {
            "en": "Health advisory: Cholera cases are rising in {city}. Drink bottled or boiled "
            "water only, avoid street food, and seek care quickly if symptoms appear.",
        },
    ),
    ("HEALTH_CHOLERA", "ADVISORY", "NBO", "Cholera advisory (Nairobi)", HEALTH_CHOLERA_NBO),
]

# --- agents and policies (D-17 seed table) --------------------------------------------------------
AGENTS: list[tuple[str, str, str, int]] = [
    ("WATCH_OFFICER", "Watch Officer", "Watches intel feeds and new incidents.", 0),
    ("EXPOSURE", "Exposure", "Watches people, trips and sites exposed to incidents.", 0),
    ("RESPONSE_PLANNER", "Response Planner", "Matches incidents to response playbooks.", 2),
    ("COMMUNICATIONS", "Communications", "Drafts multilingual advisories for audiences.", 2),
    # Pilot module 4 (D-34): proposes only; a Travel Desk or Security Officer decides.
    (
        "TRAVEL_AIR",
        "Travel & Air",
        "Watches trips and flights; proposes messages and cancellations.",
        2,
    ),
    # Pilot module 7 (D-37): proposes only; a Consular or Duty Officer decides.
    (
        "COMPLIANCE",
        "Compliance",
        "Watches travel documents at missions at risk; proposes urgent renewals.",
        2,
    ),
    # Pilot module 16 (D-46; plan-pilot-prd G-1, option B): advice only, never a VIP visit.
    (
        "FORECAST",
        "Forecast",
        "Watches the risk forecast and events calendar; advises readiness checks.",
        4,
    ),
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
# Travel & Air agent (D-34, plan-pilot-ta §6): decided within 60 minutes or they expire.
# ADVISE_REBOOKING has no policy: advice only (level 4, D-12).
TRAVEL_POLICIES: list[tuple[str, int, list[str], bool, int]] = [
    ("NOTIFY_TRAVELLERS", 2, ["TRAVEL_DESK|SECURITY_OFFICER"], False, 3600),
    ("CANCEL_TRIP", 2, ["SECURITY_OFFICER"], False, 3600),
]
# Compliance agent (D-37, plan-pilot-dx §4): floor 2, so it can never be set to Auto (§38
# Q4). ADVISE_EMERGENCY_DOCUMENTS has no policy: advice only (level 4, D-12).
DOCUMENT_POLICIES: list[tuple[str, int, list[str], bool, int]] = [
    ("START_DOCUMENT_RENEWAL", 2, ["CONSULAR_OFFICER|DUTY_OFFICER"], False, 3600),
]
# Natural hazards (D-38, plan-pilot-hz §6): arming a playbook ahead of a cyclone landfall.
# Floor 2, so it can never be set to Auto (§43 Q5); decided within 12 h or it expires, so a
# stale forecast is not armed by accident.
HAZARD_POLICIES: list[tuple[str, int, list[str], bool, int]] = [
    ("ARM_PLAYBOOK", 2, ["SECURITY_OFFICER|DUTY_OFFICER"], False, 12 * 3600),
]
# Health (D-39, plan-pilot-hl §7): the Communications agent's health advisory. Floor 2, so
# it can never be set to Auto (§48 Q6); decided within 1 h, as the design. Approving creates
# the campaign; a second person approves it before it is sent (G-2).
HEALTH_POLICIES: list[tuple[str, int, list[str], bool, int]] = [
    ("PREPARE_HEALTH_ADVISORY", 2, ["DUTY_OFFICER|CONSULAR_OFFICER"], False, 3600),
]

# --- Document Expiry (D-37, plan-pilot-dx §8): simulated, never a document number ---------
# The fictional ministry's home state issues its staff's passports: the home time zone
# (plan Q2) and the AUH hub. Local staff hold the host country's.
HOME_COUNTRY = "AE"
# What each person holds: a passport-type document first (§38 Q1).
DOCUMENTS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "DIPLOMAT": ("DIPLOMATIC_PASSPORT", "ACCREDITATION"),
    "LOCAL_STAFF": ("PASSPORT",),
    "DEPENDANT": ("PASSPORT", "RESIDENCE_PERMIT"),
    "CONTRACTOR": ("PASSPORT", "VISA"),
}
# Plan G-2: Hana Takeda's child is the last generated dependant, moved to Nairobi and
# placed at home 9 km from the epicentre, outside the zone (D-23 does not move).
DEPENDANT_CHILD = "Aiko Takeda"
DEPENDANT_CHILD_HOME = (-1.3555, 36.7765)
DEPENDANT_CHILD_PLACE = "Home · Karen"
# Days left on the seed date. Nairobi's two (DX-02, DX-07); nobody else in Nairobi has a
# document under 180 days.
NAMED_DOCUMENTS: dict[tuple[str, str], int] = {
    ("Hana Takeda", "DIPLOMATIC_PASSPORT"): 21,
    (DEPENDANT_CHILD, "PASSPORT"): 12,
}
# Elsewhere, picked by digest: with Nairobi's two, exactly 6 within 30 days and 31 within
# 90 (the design's KPIs); about 19 of those already in renewal; a few passports under the
# six-month rule. Not at the missions of the demo scenarios, so the only documents the
# Compliance agent finds there are Nairobi's two.
DOCUMENT_CRITICAL_OTHERS = 4
DOCUMENT_HIGH_OTHERS = 25
DOCUMENT_MODERATE_PASSPORTS = 14
DOCUMENT_IN_PROGRESS = 19
DOCUMENT_QUIET_MISSIONS = ("NBO", "PAR", "MNL")
# DX-06: the Paris trip's first traveller's passport ends 150 days after the seed date,
# under 180 days after the trip ends.
DOCUMENT_TRIP_WARNING = ("TRP-8811", 150)

# --- Assistance Partners (D-36, plan-pilot-ast §8): fictional partners, simulated -----------
MISSION_COUNTRIES = sorted({cc for _code, _city, _name, cc, *_ in MISSIONS})
# Africa, the Middle East and Europe: Sentinel's secure-transport coverage.
EMEA = ["GB", "FR", "DE", "BE", "CH", "IT", "ES", "RU", "TR", "EG", "MA", "NG", "KE", "ET", "ZA",
        "JO", "IQ", "SA", "OM"]  # fmt: skip
# (code, name, services, coverage, SLA minutes, hours). Canberra and Buenos Aires have no
# evacuation partner: the two coverage gaps on the screen (AS-07).
PARTNERS: list[tuple[str, str, list[str], list[str], int, str]] = [
    ("KES", "Kestrel Medical Assistance", ["MEDICAL"], MISSION_COUNTRIES, 15, "24/7"),
    (
        "ATL",
        "Atlas Air Evacuation",
        ["EVACUATION"],
        [cc for cc in MISSION_COUNTRIES if cc not in ("AU", "AR")],
        240,
        "24/7",
    ),
    ("SEN", "Sentinel Secure Transport", ["SECURE_TRANSPORT"], EMEA, 30, "24/7"),
    (
        "HAR",
        "Harbor Crisis Support",
        ["WELFARE"],
        MISSION_COUNTRIES,
        120,
        "24/7 · remote / on-site",
    ),
    (
        "MER",
        "Meridian Relocation",
        ["RELOCATION", "SECURE_TRANSPORT"],
        MISSION_COUNTRIES,
        60,
        "24/7",
    ),
]
REQ_START = 550  # next request: REQ-0551

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


EVN_START = 1000  # EVN-1001 is the first evacuation

# --- Evacuation Management (D-40, plan-pilot-ev §2) --------------------------------------------
# Illustrative plans, one per mission (EV-01, §53 Q1). EVP-NBO as the design; every other
# mission: a charter to a regional safe haven (Atlas where it covers the country), held
# commercial seats, and an overland route (Sentinel in EMEA, else Meridian). Simulated.
SAFE_HAVEN = {  # mission country -> destination
    **dict.fromkeys(["GB", "FR", "DE", "BE", "IT", "ES", "RU", "TR"], "Geneva"),
    "CH": "Vienna",
    **dict.fromkeys(["EG", "MA", "NG", "KE", "ET", "ZA", "JO", "IQ", "SA", "OM"], "Dubai"),
    **dict.fromkeys(["PK", "IN", "BD", "CN", "KR", "JP", "PH", "MY", "ID", "AU"], "Singapore"),
    "SG": "Tokyo",
    **dict.fromkeys(["US", "CA", "MX", "BR", "AR"], "Panama City"),
}
NAIROBI_MUSTER, NAIROBI_ROUTE, NAIROBI_DESTINATION = "Embassy courtyard", "Route B", "Dubai"
EvacuationOption = tuple[str, str, str, int | None, str | None]  # role, kind, label, seats, partner
NAIROBI_OPTIONS: list[EvacuationOption] = [
    ("PRIMARY", "CHARTER", "Charter · Wilson Airport → Dubai", 72, "ATL"),
    ("BACKUP", "COMMERCIAL", "Commercial · JKIA (seats held: 30)", 30, None),
    ("CONTINGENCY", "ROAD", "Road · Namanga border → Arusha", None, "SEN"),
]
EVACUATION_MOVE = "EVACUATION_MOVE"
EVACUATION_TEMPLATES: list[tuple[str, str, str | None, str, dict[str, str]]] = [
    (
        EVACUATION_MOVE,
        "ALERT",
        None,
        "Evacuation · movement order",
        {
            "en": "Evacuation of {city} is under way. Go to the mission's muster point now with "
            "your passport and one bag, and follow the instructions of mission staff.",
            "ar": REVIEW_REQUIRED + "بدأ إجلاء {city}. توجهوا الآن إلى نقطة التجمع التابعة "
            "للبعثة ومعكم جواز السفر وحقيبة واحدة، واتبعوا تعليمات موظفي البعثة.",
            "fr": REVIEW_REQUIRED + "L'évacuation de {city} est en cours. Rendez-vous maintenant "
            "au point de rassemblement de la mission avec votre passeport et un sac, et suivez "
            "les consignes du personnel de la mission.",
            "sw": REVIEW_REQUIRED + "Uhamishaji wa {city} unaendelea. Nendeni sasa kwenye eneo "
            "la mkusanyiko la ubalozi mkiwa na pasipoti na begi moja, na fuateni maelekezo ya "
            "wafanyakazi.",
        },
    ),
    (
        EVACUATION_MOVE,
        "ALERT",
        "NBO",
        "Evacuation · movement order (Nairobi)",
        {
            "en": "Evacuation of Nairobi is under way. Go to the Embassy courtyard now with your "
            "passport and one bag. Convoy via Route B to Wilson Airport; follow mission staff.",
            "ar": REVIEW_REQUIRED + "بدأ إجلاء نيروبي. توجهوا الآن إلى فناء السفارة ومعكم جواز "
            "السفر وحقيبة واحدة. القافلة عبر الطريق B إلى مطار ويلسون.",
            "fr": REVIEW_REQUIRED + "L'évacuation de Nairobi est en cours. Rendez-vous maintenant "
            "dans la cour de l'ambassade avec votre passeport et un sac. Convoi par la route B "
            "vers l'aéroport Wilson.",
            "sw": REVIEW_REQUIRED + "Uhamishaji wa Nairobi unaendelea. Nendeni sasa uwanja wa "
            "ubalozi mkiwa na pasipoti na begi moja. Msafara kupitia Njia B hadi Uwanja wa Ndege "
            "wa Wilson.",
        },
    ),
]

# --- Fleet & Assets (D-41, plan-pilot-flt §2) -------------------------------------------------
# Illustrative and simulated. Passenger seats (the driver not counted, G-6).
SUV, SEDAN, MINIBUS, PICKUP = (
    ("Armoured SUV (B6)", 4),
    ("Sedan (official)", 3),
    ("Minibus 14-seat", 13),
    ("Pickup 4x4", 3),
)
NAIROBI_DRIVER = "Peter Mwangi"  # VH-02's driver; answers NEED HELP in scene 4 (G-2)
# (code, (type, seats), armoured, place, label, fuel %, status, reason, maintenance items)
NAIROBI_FLEET: list[
    tuple[str, tuple[str, int], bool, str, str, int, str, str | None, list[tuple[str, int]]]
] = [
    (
        "VH-01",
        SUV,
        True,
        "EMBASSY",
        "Embassy garage",
        82,
        "AVAILABLE",
        None,
        [("Routine service", 45)],
    ),
    (
        "VH-02",
        SUV,
        True,
        "PETER",
        "Haile Selassie Ave",
        46,
        "IN_USE",
        None,
        [("Routine service", 60)],
    ),
    (
        "VH-03",
        MINIBUS,
        False,
        "EMBASSY",
        "Embassy garage",
        90,
        "AVAILABLE",
        None,
        [("Routine service", 75)],
    ),
    (
        "VH-04",
        PICKUP,
        False,
        "RESIDENCE",
        "Residence",
        64,
        "AVAILABLE",
        None,
        [("Routine service", 50)],
    ),
    (
        "VH-05",
        SEDAN,
        False,
        "EMBASSY",
        "Workshop",
        30,
        "MAINTENANCE",
        "Brake service overdue",
        [("Brake service", -3)],
    ),
]
# A second vehicle, both armoured, at the eight higher-risk missions; one more armoured first
# vehicle at Ankara: 48 vehicles, 19 armoured, as the design's KPI (G-6).
FLEET_HIGH_RISK = ["ADD", "BGW", "ABV", "ISB", "CAI", "AMM", "PRY", "JKT"]
FLEET_ARMOURED_FIRST = ["ANK"]
FLEET_CODES = {"ADD": 11, "BGW": 21}  # as the design; the others from VH-31 in mission order
FLEET_NEXT_CODE = 31
# Maintenance items as the design (code: [(task, days from the seed date)]); routine items
# 30-90 days out elsewhere.
FLEET_ITEMS: dict[str, list[tuple[str, int]]] = {
    "VH-21": [("Tyre replacement (run-flat)", 5)],
    "GEN-ISB": [("Load test", 10)],
    "VH-11": [("Armour inspection", 30)],
}
GENERATOR = "Generator 250 kVA"
SATELLITE = "Satellite terminal"
GENERATOR_FUEL = {"NBO": 72}

# --- VIP & Delegation Protection (D-42, VIP-01; docs/plan-pilot-vip.md §2) ---------------------
# Illustrative: the principal by role only (§63 Q3), sample labels, no real names. Times are
# Addis Ababa local (UTC+3) on scenario days +4..+6. The industrial park sits about 11 km east
# of Bole airport and 16 km from the city venues, so only it is near the rally (G-4).
VIP_REFERENCE_NO = 31  # VV-<year>-031, as the design
VIP_TITLE = "Minister's visit to Addis Ababa"
VIP_PRINCIPAL = "Minister of Foreign Affairs"
VIP_MISSION = "ADD"
VIP_FIRST_DAY = 4  # days after the scenario date
VIP_DAYS = 3
# The restricted trip (D-33): two fictional travellers, the Amman diplomats of TRP-8813, the
# other ministerial trip, so no traveller count changes (G-6).
# The purpose names no visit: a trip's header is shown to every trip reader (review of
# Prompt 80, M3).
VIP_TRIP = ("TRP-8834", "Delegation travel (restricted)", "AMM", 2, 2, "Abu Dhabi", "ET")
AIRPORT_ADD = (8.9779, 38.7993)
INDUSTRIAL_PARK = (8.9779, 38.9000)
# (kind, title, venue, (lat, lon), day, local hh:mm, minutes or None, attendees or None)
VIP_SEGMENTS: list[
    tuple[str, str, str, tuple[float, float], int, str, int | None, int | None]
] = [
    ("ARRIVAL", "Arrival · Bole Intl. Airport (VIP terminal)", "Bole Intl. Airport",
     AIRPORT_ADD, 0, "09:30", None, None),
    ("MOTORCADE", "Motorcade · Airport → Hotel", "Hotel (sample)",
     (9.0190, 38.7530), 0, "09:50", 14, None),
    ("MEETING", "Bilateral meeting · Ministry of Foreign Affairs", "Ministry of Foreign Affairs",
     (9.0330, 38.7600), 0, "11:00", 90, None),
    ("EVENT", "Business forum · Conference centre", "Conference centre",
     (9.0150, 38.7680), 0, "14:00", 150, 600),
    ("SITE_VISIT", "Site visit · Industrial park", "Industrial park",
     INDUSTRIAL_PARK, 1, "10:00", 120, None),
    ("DEPARTURE", "Departure", "Bole Intl. Airport", AIRPORT_ADD, 2, "16:00", None, None),
]  # fmt: skip
VIP_DETAIL = {
    "team_lead": "Close-protection lead (sample)",
    "advance_team": "3 officers",
    "team_size": 8,
    "medic": True,
    "vehicles": ["VH-11", "VH-12"],
    "safe_havens": ["Embassy", "Hotel safe floor"],  # and the nearest hospital, at read time
}
# (label, days before the visit's first day, done by the seeded Security Officer: G-7)
VIP_CHECKLIST = [
    ("Threat assessment issued", 7, True),
    ("Host-nation security liaison confirmed", 5, True),
    ("Hospital & evacuation plan", 3, True),
    ("Industrial park venue survey", 1, False),
]

# --- Site Twin (D-43, TWN-01; docs/plan-pilot-twn.md §2-§6) -------------------------------------
# The Nairobi embassy's ground floor as the design, in plan units (viewBox 790 x 455).
# (code, name, kind, x, y, w, h, capacity)
TWIN_SITE = "NBO:EMBASSY"
TWIN_ZONES: list[tuple[str, str, str, int, int, int, int, int | None]] = [
    ("ch", "Chancery offices", "OFFICE", 130, 30, 270, 220, None),
    ("amb", "Ambassador suite", "SUITE", 415, 30, 160, 110, None),
    ("conf", "Conference room", "CONFERENCE", 415, 155, 160, 95, None),
    ("comms", "Comms / IT room", "COMMS", 590, 30, 180, 100, None),
    ("safe", "Safe room (hardened)", "SAFE_ROOM", 590, 145, 180, 105, 20),
    ("lob", "Lobby & reception", "LOBBY", 130, 265, 170, 120, None),
    ("cons", "Consular hall", "CONSULAR", 315, 265, 260, 120, None),
    ("must", "Muster point · courtyard", "MUSTER", 590, 265, 180, 60, 60),
    ("g1", "Gate 1", "GATE", 20, 320, 95, 65, None),
    ("g2", "Gate 2", "GATE", 680, 340, 90, 45, None),
]
# (code, label, path, exit gate)
TWIN_ROUTES: list[tuple[str, str, tuple[tuple[int, int], ...], str]] = [
    ("A", "Route A → main road via Gate 1", ((215, 250), (215, 300), (115, 350)), "g1"),
    ("B", "Route B → vehicles via Gate 2", ((680, 200), (680, 300), (725, 300), (725, 340)), "g2"),
]
# 43 sensors (G-2): the gates and safe room, 16 cameras, 16 doors and 8 panic alarms.
TWIN_CAMERA_ZONES = ["g1", "g1", "g2", "g2", "lob", "lob", "cons", "cons",
                     "ch", "ch", "conf", "comms", "safe", "must", "must", "amb"]  # fmt: skip
TWIN_DOOR_ZONES = ["ch", "ch", "ch", "amb", "conf", "comms", "comms", "safe",
                   "safe", "lob", "lob", "cons", "cons", "must", "g1", "g2"]  # fmt: skip
TWIN_ALARM_ZONES = ["ch", "amb", "conf", "comms", "safe", "lob", "cons", "must"]
# Where each camera is mounted and points (PC-53, TWN-08; docs/plan-pilot-rpl.md §4), in the
# order of TWIN_CAMERA_ZONES: (x, y, heading, field of view, range) in plan units, heading 0 up
# the plan and clockwise. Migrations 0018 and 0019 fill the same values into a database seeded
# before them.
# The chancery's north-east corner is the one blind spot (§108 Q2).
TWIN_CAMERA_MOUNTS: list[tuple[int, int, int, int, int]] = [
    (22, 322, 135, 90, 120), (113, 383, 315, 90, 120),    # Gate 1
    (682, 342, 120, 80, 110), (768, 383, 290, 80, 110),   # Gate 2
    (132, 267, 135, 90, 200), (298, 383, 315, 90, 200),   # Lobby
    (317, 267, 120, 90, 280), (573, 383, 300, 90, 280),   # Consular hall
    (132, 32, 135, 90, 220), (132, 248, 70, 70, 280),     # Chancery
    (417, 157, 130, 110, 190),                            # Conference
    (768, 32, 225, 110, 205),                             # Comms / IT
    (592, 147, 130, 110, 210),                            # Safe room
    (592, 267, 105, 90, 190), (768, 323, 285, 90, 190),   # Muster
    (417, 32, 130, 110, 200),                             # Ambassador suite
]  # fmt: skip
# (code, kind, label, zone, detail, camera mount)
TWIN_SENSORS: list[
    tuple[str, str, str, str | None, str | None, tuple[int, int, int, int, int] | None]
] = [
    ("G1-MAIN", "GATE", "Gate 1 · main", "g1", "Open · screening", None),
    ("G2-READER", "BADGE_READER", "Gate 2 · badge reader", "g2", "Online", None),
    ("SAFE-ROOM", "SAFE_ROOM", "Safe room", "safe", "Ready", None),
    *[(f"CAM-{n:02d}", "CCTV", f"Camera {n}", z, None, m)
      for n, (z, m) in enumerate(zip(TWIN_CAMERA_ZONES, TWIN_CAMERA_MOUNTS, strict=True), 1)],
    *[(f"DOOR-{n:02d}", "ACCESS", f"Door {n}", z, None, None)
      for n, z in enumerate(TWIN_DOOR_ZONES, 1)],
    *[(f"PANIC-{n:02d}", "ALARM", f"Panic alarm {n}", z, None, None)
      for n, z in enumerate(TWIN_ALARM_ZONES, 1)],
]  # fmt: skip
# (label, seeded done by the seeded Security Officer: G-7). The fourth stays open (G-6).
TWIN_READINESS = [
    ("Floor wardens assigned (3)", True),
    ("Safe room supplies checked · 14 d", True),
    ("Evacuation routes A & B surveyed", True),
    ("Generator load test witnessed", False),
]
# The 11 staff at "Embassy" (NAIROBI_PEOPLE), as the design: (name, normal zone, shelter zone).
TWIN_STAFF = [
    ("Omar Siddiqui", "ch", "safe"),
    ("Aisha Rahman", "ch", "safe"),
    ("Sara Lindqvist", "ch", "safe"),
    ("Nadia Petrova", "ch", "safe"),
    ("Karim Mansour", "ch", "safe"),
    ("Martin Keller", "conf", "safe"),
    ("David Okafor", "conf", "safe"),
    ("Grace Wanjiru", "cons", "safe"),
    ("Ruth Achieng", "cons", "safe"),
    ("Yusuf Al-Amin", "comms", "comms"),
    ("James Otieno", "comms", "comms"),
]
# Guards and visitors are labels, never names (§68 Q3): (label, normal zone, shelter zone).
TWIN_LABELS = [
    ("Guard 1", "g1", "g1"),
    ("Guard 2", "g2", "g2"),
    ("Guard 3", "lob", "lob"),
    *[(f"Visitor {n}", "cons" if n <= 9 else "lob", "conf") for n in range(1, 12)],
]

# --- Supply Chain & Third-Party Risk (D-44, SUP-01; docs/plan-pilot-sup.md §2, §3) -------------
# Illustrative and fictional: no real company is meant. 52 suppliers across the 36 missions, 14
# in Tier 1 (the design's KPIs). (code, name, service, mission code or None for Global, tier,
# backup code, status, detail). Backups come first: they are frozen once referenced (PC-43).
POUCH = "Diplomatic pouch courier"
SUPPLY_GLOBAL_BACKUPS = [
    ("SUP-301", "Polaris Global Couriers", POUCH),
    ("SUP-302", "Bastion Secure Mobility", "Armoured vehicle leasing"),
    ("SUP-303", "Continental Freight Partners", "Freight & relocation"),
    ("SUP-304", "Crestline Facilities Group", "Facilities management"),
]
WATCH = "Monitoring local disruption"
SUPPLY_NAIROBI = [
    ("SUP-105", "Falcon Express Couriers", POUCH, 2, None),
    ("SUP-118", "Highland Guard Services", "Guard force contractor", 2, None),
    ("SUP-122", "Mara Energy Supplies", "Generator fuel supply", 2, None),
    ("SUP-127", "Upesi Networks", "Local ISP & IT support", 2, None),
    ("SUP-104", "Swiftline Couriers", POUCH, 1, "SUP-105"),
    ("SUP-117", "Equator Guard Services", "Guard force contractor", 1, "SUP-118"),
    ("SUP-121", "Rift Valley Fuels", "Generator fuel supply", 2, "SUP-122"),
    ("SUP-126", "Savanna IT Networks", "Local ISP & IT support", 1, "SUP-127"),
    ("SUP-130", "Kilima Catering", "Catering services", 3, None),
]
# The design's other named suppliers: (code, name, service, mission, tier, backup, status).
SUPPLY_NAMED = [
    ("SUP-208", "Gulfstar Logistics", "Freight & relocation", "RUH", 2, "SUP-303", "NORMAL"),
    ("SUP-233", "Nile Secure Mobility", "Armoured vehicle leasing", "CAI", 1, "SUP-302", "NORMAL"),
    ("SUP-251", "Indus Facilities", "Facilities management", "ISB", 2, "SUP-304", "WATCH"),
    ("SUP-262", "Archipelago Movers", "Local transport", "JKT", 3, None, "WATCH"),
    ("SUP-305", "Northbridge Translations", "Interpretation services", None, 3, None, "NORMAL"),
]  # fmt: skip
# Every other mission's pouch courier (G-1), backed by SUP-301; Tier 1 at these ten.
SUPPLY_TIER1_COURIERS = {"ADD", "BGW", "ABV", "AMM", "PRY", "MOW", "ANK", "DAC", "MNL", "DEL"}
SUPPLY_FIRST_CODE = 201  # in mission order, skipping the design's codes
# Three more routine local suppliers, to the design's 52.
SUPPLY_EXTRA = [
    ("SUP-281", "Addis Facility Services", "Facilities management", "ADD"),
    ("SUP-282", "Tigris Catering", "Catering services", "BGW"),
    ("SUP-283", "Abuja Local Transport", "Local transport", "ABV"),
]
SUPPLY_VETTING_DAYS = (180, 540)  # vetting valid for 6-18 months after the seed date
# Routes (§3): Nairobi's four as the design; one pouch route at every other mission but the two
# multilateral ones (G-3). Points are (lat, lon).
JKIA = (-1.3192, 36.9278)
SUPPLY_NAIROBI_ROUTES = [
    ("R-NBO-1", "Pouch: Embassy → JKIA via CBD", "POUCH", "SUP-104", None,
     (EMBASSY, (-1.2864, 36.8172), (-1.3000, 36.8600), JKIA)),
    ("R-NBO-2", "Pouch: Embassy → JKIA via Southern Bypass", "POUCH", "SUP-104", "R-NBO-1",
     (EMBASSY, (-1.3180, 36.7950), (-1.3350, 36.8500), JKIA)),
    ("R-NBO-3", "Fuel: depot → Embassy", "FUEL", "SUP-121", None,
     ((-1.3100, 36.8500), (-1.3000, 36.8250), EMBASSY)),
    ("R-NBO-4", "Staff shuttle: Westlands → Embassy", "STAFF_TRANSPORT", "SUP-117", None,
     ((-1.2676, 36.8108), (-1.2800, 36.8100), EMBASSY)),
]  # fmt: skip
SUPPLY_NO_ROUTE = {"GVA", "NYC"}  # multilateral missions (G-3)
SUPPLY_ROUTE_OFFSET = 0.1  # degrees: an illustrative airport about 15 km out

# --- Predictive Risk (D-46, PRD-05; docs/plan-pilot-prd.md §7) --------------------------------
# An illustrative events calendar (simulated): (mission, kind, title, days after the scenario
# date, weight, days). Weights keep every calm forecast below the threshold of 70 (G-2): a LOW
# mission is 35 + at most 12, a MODERATE one 50 + at most 12.
PREDICTIVE_CALENDAR: list[tuple[str, str, str, int, int, int]] = [
    ("ADD", "HOLIDAY", "National holiday", 3, 8, 1),
    ("ISB", "RALLY", "Planned rallies", 2, 12, 1),
    ("ABV", "ELECTION", "Election campaign event", 6, 10, 1),
    ("JKT", "HOLIDAY", "Religious festival", 4, 10, 2),
    ("BGW", "RALLY", "Commemoration march", 8, 12, 1),
    ("NBO", "SPORTS", "City marathon", 9, 6, 1),
    ("PAR", "SUMMIT", "Trade fair", 7, 5, 3),
    ("LON", "OTHER", "State visit (host nation)", 10, 5, 2),
    ("CAI", "HOLIDAY", "National holiday", 12, 6, 1),
    ("DEL", "HOLIDAY", "Festival", 5, 8, 2),
    ("MNL", "RALLY", "Election rally", 11, 10, 1),
    ("DAC", "OTHER", "General strike (hartal)", 3, 12, 1),
]


# Exercise & Training (D-48, plan-pilot-exr §5): the seeded illustrative history. Offsets sum to 0
# and stay within +2, so the five scores' mean is the embassy's readiness (70..98).
EXERCISE_THEMES = ("Civil unrest", "Natural hazard", "Health", "Cyber-physical", "Evacuation")
EXERCISE_KINDS = ("TABLETOP", "FUNCTIONAL", "FULL_SCALE")
EXERCISE_OFFSETS = (2, -1, 1, -3, 1)

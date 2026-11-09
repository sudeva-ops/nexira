import type { DemoScenario } from "../api/scenario";

// Where each scene is best watched. NBO-CIVIL-UNREST: decisions.md §7 (plan G-24:
// scenes 0-6 only). FRA-NATIONAL-PROTESTS: everything happens on the map.
export const SCENE_SCREEN: Record<DemoScenario, Record<number, string>> = {
  "NBO-CIVIL-UNREST": {
    0: "/",
    1: "/operations",
    2: "/operations",
    3: "/",
    4: "/checkin",
    5: "/",
    6: "/incidents",
  },
  "FRA-NATIONAL-PROTESTS": {
    0: "/",
    1: "/operations",
    2: "/operations",
    3: "/operations",
  },
  // D-33: XW 451 holds near Nairobi, diverts to Mombasa and lands.
  "NBO-AIR-DIVERSION": {
    0: "/air",
    1: "/air",
    2: "/air",
    3: "/air",
  },
  // D-35 (WX-07): the weather panel and the storm on the map; PB-06 in the Decision Queue.
  "MNL-TROPICAL-STORM": {
    0: "/operations",
    1: "/operations",
    2: "/operations",
    3: "/operations",
  },
  // D-38 (HZ-11): the events and the countdown on the Natural Hazards screen; the arming
  // proposal in the Decision Queue; the armed PB-06 starting, and landfall, on the hazards screen.
  "DAC-CYCLONE": {
    0: "/hazards",
    1: "/hazards",
    2: "/",
    3: "/hazards",
    4: "/hazards",
    5: "/hazards",
  },
  // D-39 (HL-10, plan-pilot-hl §10): every scene on the health screen; scene 1's proposal is
  // then decided in the Decision Queue and its campaign approved on Mass Notification.
  "NBO-CHOLERA": {
    0: "/health",
    1: "/health",
    2: "/health",
  },
  // D-40 (EV-10): after NBO-CIVIL-UNREST scene 5, every scene on Evacuation Management.
  "NBO-EVACUATION": {
    0: "/evacuation",
    1: "/evacuation",
    2: "/evacuation",
    3: "/evacuation",
    4: "/evacuation",
  },
  // D-41 (FLT-08): during NBO-CIVIL-UNREST, every scene on Fleet & Assets (Prompt 75).
  "NBO-FLEET": {
    0: "/fleet",
    1: "/fleet",
    2: "/fleet",
    3: "/fleet",
  },
  // D-43 (TWN-07): during NBO-CIVIL-UNREST, every scene on Site Twin (Prompt 87).
  "NBO-SITE": {
    0: "/twin",
    1: "/twin",
    2: "/twin",
    3: "/twin",
  },
  // D-44 (SUP-07): during NBO-CIVIL-UNREST, every scene on Supply Chain Risk (Prompt 93).
  "NBO-SUPPLY": {
    0: "/supply",
    1: "/supply",
    2: "/supply",
    3: "/supply",
  },
  // D-46 (PRD-08): the rally plays on Predictive Risk (Prompt 104); the advice is then dismissed
  // in the Decision Queue.
  "ADD-FORECAST": {
    0: "/predictive",
    1: "/predictive",
  },
  // D-42 (VIP-08): the visit plays on VIP Protection (Prompt 81).
  "ADD-VISIT": {
    0: "/vip",
    1: "/vip",
    2: "/vip",
    3: "/vip",
  },
};

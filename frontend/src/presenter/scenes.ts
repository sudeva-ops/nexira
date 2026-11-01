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
  // D-40 (EV-10): after NBO-CIVIL-UNREST scene 5. Prompt 69 moves every scene to the
  // Evacuation Management screen; until then the Decision Queue.
  "NBO-EVACUATION": {
    0: "/",
    1: "/",
    2: "/",
    3: "/",
    4: "/",
  },
};

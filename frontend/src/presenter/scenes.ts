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
};

// The sign-in intro: the globe of monitored missions, then Global Operations. It plays once per
// sign-in, for every role, and never under reduced motion or Calm mode, nor in a browser driven by
// a test (the acceptance specs sign in and act at once).

const KEY = "nexira.intro.played";

export const INTRO_MS = { zoom: 4_800, fade: 6_200, done: 7_000 } as const;

export interface IntroContext {
  reduced: boolean;
  automated: boolean;
  played: boolean;
}

export function shouldPlayIntro({ reduced, automated, played }: IntroContext): boolean {
  return !reduced && !automated && !played;
}

export function introPlayed(): boolean {
  try {
    return window.sessionStorage.getItem(KEY) === "1";
  } catch {
    return true; // blocked storage: never risk replaying it on every page load
  }
}

export function markIntroPlayed(): void {
  try {
    window.sessionStorage.setItem(KEY, "1");
  } catch {
    // blocked storage: introPlayed() already says it played
  }
}

/** On sign-out, so the next sign-in in this tab plays it again. */
export function resetIntro(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // nothing stored
  }
}

export function automatedBrowser(): boolean {
  return typeof navigator !== "undefined" && navigator.webdriver === true;
}

/** Where the intro hands over: Global Operations from the home screen, else where the person
 * was going (a deep link keeps its page). */
export function introTarget(pathname: string): string | null {
  return pathname === "/" ? "/operations" : null;
}

const RAD = Math.PI / 180;

/** Great-circle distance in radians between two [lat, lon] points. */
function apart(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const h =
    Math.sin(((b.lat - a.lat) * RAD) / 2) ** 2 +
    Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(((b.lon - a.lon) * RAD) / 2) ** 2;
  return 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The arcs: each mission to its `near` nearest missions, each pair once, a regional network. */
export function arcPairs<T extends { lat: number; lon: number }>(missions: T[], near = 2): [T, T][] {
  const seen = new Set<string>();
  const out: [T, T][] = [];
  missions.forEach((m, i) => {
    missions
      .map((o, j) => ({ j, d: apart(m, o) }))
      .filter((x) => x.j !== i)
      .sort((x, y) => x.d - y.d)
      .slice(0, near)
      .forEach(({ j }) => {
        const key = i < j ? `${i}-${j}` : `${j}-${i}`;
        if (seen.has(key)) return;
        seen.add(key);
        out.push([m, missions[j] as T]);
      });
  });
  return out;
}

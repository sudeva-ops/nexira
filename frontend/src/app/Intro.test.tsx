import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { MISSIONS, SUMMARY } from "../test/fixtures";
import { DUTY_OFFICER, mockServer, renderApp } from "../test/render";
import { arcPairs, INTRO_MS, introTarget, resetIntro, shouldPlayIntro } from "./introRules";

// jsdom has no WebGL: the globe is a stand-in that says what it was given.
vi.mock("../map/IntroGlobe", () => ({
  IntroGlobe: ({ missions, descend }: { missions: unknown[]; descend: boolean }) => (
    <div data-testid="intro-globe">
      {missions.length} missions{descend ? " · descending" : ""}
    </div>
  ),
}));
vi.mock("../map/OperationsMap", () => ({ OperationsMap: () => <div data-testid="operations-map" /> }));

function motionAllowed() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

function setup() {
  return mockServer({
    "GET /api/me": { body: DUTY_OFFICER },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/operations/summary": { body: SUMMARY },
    "GET /api/incidents": { body: [] },
    "GET /api/agents": { body: { paused: false, agents: [{}, {}, {}, {}, {}, {}, {}] } },
    "GET /api/exercises/running": { body: [] },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  resetIntro();
});

describe("the sign-in intro", () => {
  it("plays once, counts what is monitored, and hands over to Global Operations on a key", async () => {
    motionAllowed();
    setup();
    renderApp("/");
    const intro = await screen.findByRole("dialog", { name: "NEXIRA" });
    expect(within(intro).getByText("Sovereign resilience for people and missions abroad")).toBeInTheDocument();
    expect(await within(intro).findByText(`${MISSIONS.length} missions`)).toBeInTheDocument();
    expect(within(intro).getByLabelText("Monitored now")).toHaveTextContent("Travellers in transit");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "NEXIRA" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Global Operations");
    expect(window.sessionStorage.getItem("nexira.intro.played")).toBe("1");
  });

  it("descends, fades and finishes on its own; a deep link keeps its page", async () => {
    motionAllowed();
    setup();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderApp("/incidents");
    expect(await screen.findByRole("dialog", { name: "NEXIRA" })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_MS.zoom + 10);
    });
    expect(screen.getByTestId("intro-globe")).toHaveTextContent("descending");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_MS.done);
    });
    expect(screen.queryByRole("dialog", { name: "NEXIRA" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Incidents");
  });

  it("does not play again in the same sign-in", async () => {
    motionAllowed();
    setup();
    window.sessionStorage.setItem("nexira.intro.played", "1");
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Decision Queue");
    expect(screen.queryByRole("dialog", { name: "NEXIRA" })).toBeNull();
  });

  it("follows the rules: never under reduced motion, in a test browser or twice", () => {
    expect(shouldPlayIntro({ reduced: false, automated: false, played: false })).toBe(true);
    expect(shouldPlayIntro({ reduced: true, automated: false, played: false })).toBe(false);
    expect(shouldPlayIntro({ reduced: false, automated: true, played: false })).toBe(false);
    expect(shouldPlayIntro({ reduced: false, automated: false, played: true })).toBe(false);
    expect([introTarget("/"), introTarget("/incidents")]).toEqual(["/operations", null]);
  });

  it("joins each mission to its nearest neighbours, each pair once", () => {
    const at = (code: string, lat: number, lon: number) => ({ code, lat, lon });
    const missions = [at("LON", 51.5, -0.1), at("PAR", 48.9, 2.4), at("BER", 52.5, 13.4), at("NBO", -1.3, 36.8)];
    const pairs = arcPairs(missions, 1).map(([a, b]) => `${a.code}-${b.code}`);
    expect(pairs).toEqual(["LON-PAR", "BER-PAR", "NBO-BER"]);
    expect(arcPairs([at("LON", 51.5, -0.1)])).toEqual([]);
  });
});

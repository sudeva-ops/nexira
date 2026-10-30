import { act, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { AgentRow } from "../../api/proposals";
import type { RealtimeEvent } from "../../api/realtimeClient";
import { type Listener, RealtimeContext } from "../../api/realtimeContext";
import { ASSESS_MS, useAssessing } from "./useAssessing";

const agent = (code: string, watches: string[], is_enabled = true) => ({ code, watches, is_enabled }) as AgentRow;
const AGENTS = [
  agent("EXPOSURE", ["EXPOSURE_COMPUTED"]),
  agent("TRAVEL", ["FLIGHT_UPDATED"]),
  agent("OFF", ["FLIGHT_UPDATED"], false),
];

function Busy() {
  return <div data-testid="busy">{[...useAssessing(AGENTS)].sort().join(",")}</div>;
}

afterEach(() => vi.useRealTimers());

it("marks the agents that watch an event as assessing for a few seconds", () => {
  vi.useFakeTimers();
  let send: Listener = () => undefined;
  const subscribe = (l: Listener) => {
    send = l;
    return () => undefined;
  };
  render(
    <RealtimeContext.Provider value={{ status: "live", subscribe }}>
      <Busy />
    </RealtimeContext.Provider>,
  );
  const event = (name: string) =>
    ({ type: "event", event: name, id: name, occurred_at: "", data: {} }) as RealtimeEvent;

  act(() => send(event("FLIGHT_UPDATED")));
  expect(screen.getByTestId("busy")).toHaveTextContent(/^TRAVEL$/); // not the disabled agent
  act(() => vi.advanceTimersByTime(ASSESS_MS / 2));
  act(() => send(event("EXPOSURE_COMPUTED")));
  expect(screen.getByTestId("busy")).toHaveTextContent("EXPOSURE,TRAVEL");
  act(() => vi.advanceTimersByTime(ASSESS_MS / 2));
  expect(screen.getByTestId("busy")).toHaveTextContent(/^EXPOSURE$/);
  act(() => vi.advanceTimersByTime(ASSESS_MS));
  expect(screen.getByTestId("busy")).toBeEmptyDOMElement();
});

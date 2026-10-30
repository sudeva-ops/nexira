import { act, render, screen } from "@testing-library/react";

import type { RealtimeEvent, RealtimeStatus } from "../api/realtimeClient";
import { type Listener, RealtimeContext } from "../api/realtimeContext";
import { eventLabel } from "./eventLabel";
import { LastEvent, LiveIndicator } from "./Heartbeat";

function withStatus(status: RealtimeStatus, subscribe: (l: Listener) => () => void = () => () => undefined) {
  return (
    <RealtimeContext.Provider value={{ status, subscribe }}>
      <LiveIndicator />
      <LastEvent />
    </RealtimeContext.Provider>
  );
}

function event(name: string, id: string): RealtimeEvent {
  return {
    type: "event",
    event: name,
    id,
    occurred_at: "2026-10-30T10:00:00Z",
    data: {},
  };
}

describe("live indicator", () => {
  it("says connecting before the socket has been live", () => {
    render(withStatus("connecting"));
    expect(screen.getByRole("status")).toHaveTextContent("CONNECTING");
  });

  it("says reconnecting, in amber, once a live socket drops", () => {
    const { rerender } = render(withStatus("live"));
    expect(screen.getByRole("status")).toHaveTextContent("LIVE");
    expect(screen.getByRole("status")).toHaveClass("live");
    rerender(withStatus("connecting"));
    expect(screen.getByRole("status")).toHaveTextContent("RECONNECTING");
    expect(screen.getByRole("status")).toHaveClass("reconnecting");
  });
});

describe("latest event", () => {
  it("is hidden until an event arrives, then names it and glows on each new one", () => {
    let listener: Listener = () => undefined;
    const subscribe = (l: Listener) => {
      listener = l;
      return () => undefined;
    };
    render(withStatus("live", subscribe));
    expect(screen.queryByLabelText("Latest event")).toBeNull();

    act(() => listener(event("FLIGHT_UPDATED", "1-0")));
    const latest = screen.getByLabelText("Latest event");
    expect(latest).toHaveTextContent(/^Flight updated · \d\d:\d\d/);
    expect(latest).toHaveClass("nx-flash-a");

    act(() => listener(event("PROPOSAL_CREATED", "2-0")));
    expect(latest).toHaveTextContent(/^New proposal/);
    expect(latest).toHaveClass("nx-flash-b");
  });

  it("names an event it has no label for in plain words", () => {
    expect(eventLabel("SITE_TWIN_CHANGED")).toBe("Site twin changed");
  });
});

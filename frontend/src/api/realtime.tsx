// Realtime provider: one WebSocket per tab (PLT-05). The protocol and cache
// invalidation live in realtimeClient.ts; the hooks in realtimeContext.ts.

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { getAccessToken } from "./client";
import { connectRealtime, type RealtimeEvent, type RealtimeStatus, staleKeys } from "./realtimeClient";
import { type Listener, RealtimeContext } from "./realtimeContext";

function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

function invalidate(client: QueryClient, event: RealtimeEvent) {
  for (const queryKey of staleKeys(event)) void client.invalidateQueries({ queryKey });
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const listeners = useRef(new Set<Listener>());
  const [value] = useState(() => ({
    subscribe: (listener: Listener) => {
      listeners.current.add(listener);
      return () => void listeners.current.delete(listener);
    },
  }));

  useEffect(
    () =>
      connectRealtime({
        url: socketUrl(),
        getToken: getAccessToken,
        onStatus: setStatus,
        // Events may have been missed while disconnected: refetch everything shown.
        onReady: () => void client.invalidateQueries(),
        onEvent: (event) => {
          invalidate(client, event);
          for (const listener of listeners.current) listener(event);
        },
      }),
    [client],
  );

  return (
    <RealtimeContext.Provider value={{ status, subscribe: value.subscribe }}>
      {children}
    </RealtimeContext.Provider>
  );
}

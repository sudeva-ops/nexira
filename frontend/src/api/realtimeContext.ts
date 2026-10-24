import { createContext, useContext, useEffect, useRef } from "react";

import type { RealtimeEvent, RealtimeStatus } from "./realtimeClient";

export type Listener = (event: RealtimeEvent) => void;

export interface RealtimeContextValue {
  status: RealtimeStatus;
  subscribe: (listener: Listener) => () => void;
}

export const RealtimeContext = createContext<RealtimeContextValue>({
  status: "offline",
  subscribe: () => () => undefined,
});

export function useRealtimeStatus(): RealtimeStatus {
  return useContext(RealtimeContext).status;
}

/** Calls listener for every realtime event while the component is mounted. */
export function useRealtimeEvents(listener: Listener): void {
  const { subscribe } = useContext(RealtimeContext);
  const latest = useRef(listener);
  useEffect(() => {
    latest.current = listener;
  });
  useEffect(() => subscribe((event) => latest.current(event)), [subscribe]);
}

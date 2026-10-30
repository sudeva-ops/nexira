import { useEffect, useRef, useState } from "react";

import type { AgentRow } from "../../api/proposals";
import { useRealtimeEvents } from "../../api/realtimeContext";

export const ASSESS_MS = 6000;

/**
 * The agents assessing right now: an event they watch arrived in the last few seconds.
 * Only events forwarded to the browser are seen (PLT-05), so this can miss some.
 */
export function useAssessing(agents: AgentRow[]): ReadonlySet<string> {
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useRealtimeEvents((event) => {
    for (const agent of agents) {
      if (!agent.is_enabled || !agent.watches.includes(event.event)) continue;
      clearTimeout(timers.current.get(agent.code));
      timers.current.set(
        agent.code,
        setTimeout(() => {
          timers.current.delete(agent.code);
          setBusy((codes) => new Set([...codes].filter((c) => c !== agent.code)));
        }, ASSESS_MS),
      );
      setBusy((codes) => new Set([...codes, agent.code]));
    }
  });
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
    };
  }, []);
  return busy;
}

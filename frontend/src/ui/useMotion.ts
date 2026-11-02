import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { calmNow, subscribeCalm } from "./calm";

// Motion shows that something changed, and nothing else: the screen is still when
// nothing happens. Everything here is off for people who ask for reduced motion.

const REDUCE = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void): () => void {
  const unsubscribeCalm = subscribeCalm(onChange);
  if (typeof window.matchMedia !== "function") return unsubscribeCalm;
  const query = window.matchMedia(REDUCE);
  query.addEventListener("change", onChange);
  return () => {
    query.removeEventListener("change", onChange);
    unsubscribeCalm();
  };
}

/** True when the person asked for reduced motion or chose Calm mode, or the browser cannot say
 * (no animation). */
function reducedNow(): boolean {
  return typeof window.matchMedia !== "function" || window.matchMedia(REDUCE).matches || calmNow();
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, reducedNow, () => true);
}

/**
 * A class that plays a short highlight each time `watch` changes, never on first show.
 * The two class names alternate so a second change restarts the animation.
 */
export function useFlash(watch: string): string {
  const [seen, setSeen] = useState(watch);
  const [changes, setChanges] = useState(0);
  if (seen !== watch) {
    setSeen(watch);
    setChanges(changes + 1);
  }
  if (changes === 0) return "";
  return changes % 2 ? "nx-flash-a" : "nx-flash-b";
}

export type FlashTone = "info" | "warning" | "danger" | "success";

const easeOut = (k: number) => 1 - (1 - k) ** 3;

/** The number shown while `target` is reached over `ms`; the first value shows at once. */
export function useCountUp(target: number, ms = 600): number {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    const from = current.current;
    if (reduced || from === target) {
      current.current = target;
      return;
    }
    let frame = 0;
    let start: number | null = null;
    const step = (now: number) => {
      start ??= now;
      const k = Math.min(1, (now - start) / ms);
      current.current = k === 1 ? target : from + (target - from) * easeOut(k);
      setShown(current.current);
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, ms, reduced]);
  return reduced ? target : shown;
}

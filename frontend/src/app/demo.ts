/** The presenter bar exists only in demo builds (VITE_DEMO_MODE=true). */
export function demoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

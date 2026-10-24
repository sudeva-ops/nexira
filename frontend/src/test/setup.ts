import "@testing-library/jest-dom/vitest";
/** A WebSocket that never connects; realtime tests drive connectRealtime directly.
 *  Assigned, not stubbed, so vi.unstubAllGlobals() in a test keeps it. */
class QuietWebSocket {
  static readonly OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  send(): void {}
  close(): void {}
}
globalThis.WebSocket = QuietWebSocket as unknown as typeof WebSocket;

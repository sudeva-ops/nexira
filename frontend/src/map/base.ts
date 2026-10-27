import { addProtocol, setWorkerUrl } from "maplibre-gl";
// MapLibre looks for its worker next to its own module; the bundle has it elsewhere.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Protocol } from "pmtiles";

import { TILES_PATH } from "./style";

// Shared by the operations and air maps (D-24: self-hosted PMTiles, no external URLs).

let protocolRegistered = false;
export function registerPmtiles() {
  if (protocolRegistered) return;
  setWorkerUrl(workerUrl);
  addProtocol("pmtiles", new Protocol().tile);
  protocolRegistered = true;
}

export async function tilesAvailable(): Promise<boolean> {
  try {
    const response = await fetch(`${TILES_PATH}/world.pmtiles`, { method: "HEAD" });
    return response.ok;
  } catch {
    return false;
  }
}

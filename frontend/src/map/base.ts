import { addProtocol, setWorkerUrl } from "maplibre-gl";
// MapLibre looks for its worker next to its own module; the bundle has it elsewhere.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Protocol } from "pmtiles";

import { type Tiles, TILES_PATH } from "./style";

// Shared by the operations and air maps (D-24: self-hosted PMTiles, no external URLs).

let protocolRegistered = false;
export function registerPmtiles() {
  if (protocolRegistered) return;
  setWorkerUrl(workerUrl);
  addProtocol("pmtiles", new Protocol().tile);
  protocolRegistered = true;
}

async function built(name: string): Promise<boolean> {
  try {
    const response = await fetch(`${TILES_PATH}/${name}`, { method: "HEAD" });
    return response.ok;
  } catch {
    return false;
  }
}

/** Which of the files `make tiles` builds are served (the NASA imagery is optional, GFX-02). */
export async function tilesAvailable(): Promise<Tiles> {
  const [base, imagery] = await Promise.all([built("world.pmtiles"), built("earth-day.pmtiles")]);
  return { base, imagery: base && imagery };
}

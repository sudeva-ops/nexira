// Map search (SRC-01..04; D-52; plan-pilot-map §4): coordinates, platform records and a bundled
// gazetteer, matched in the browser. Nothing is sent anywhere (D-24). Pure, apart from loadPlaces.

export type Place = [name: string, ascii: string, region: string, country: string, lon: number, lat: number, rank: number];

export type ResultKind = "COORDINATES" | "MISSION" | "SITE" | "INCIDENT" | "FLIGHT" | "PLACE";

export interface Result {
  kind: ResultKind;
  id: string; // the record's id, or the place's key
  label: string;
  detail: string;
  lon: number;
  lat: number;
  zoom: number; // how close the map goes
}

// The self-hosted world tiles carry detail to zoom 6 and the Nairobi extract to 15 (D-24), so a
// result goes where the map still reads: a place to 7, anything else to 8.
export const PLACE_ZOOM = 7;
export const RECORD_ZOOM = 8;

export const MAX_RESULTS = 8;

/** The gazetteer, loaded the first time the box is used, as its own chunk (plan G-11). */
export async function loadPlaces(): Promise<Place[]> {
  const module = await import("./places.json");
  return module.default as Place[];
}

/** Lower case, no accents: "São Paulo" → "sao paulo". */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

function onEarth(lat: number, lon: number): { lat: number; lon: number } | null {
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
    ? { lat, lon }
    : null;
}

const NUM = String.raw`[+-]?\d+(?:\.\d+)?`;

/** "-1.29, 36.82", "1.29 S 36.82 E", "1°17'31\"S 36°49'19\"E" and "geo:-1.29,36.82". */
export function parseCoordinates(input: string): { lat: number; lon: number } | null {
  const q = input.trim();
  // RFC 5870: geo:lat,lon[,alt][;crs=…;u=…]; only WGS84 (the default) is taken.
  const geo = q.match(new RegExp(`^geo:(${NUM}),(${NUM})(?:,${NUM})?(;.*)?$`, "i"));
  if (geo) {
    if (geo[3] && /;crs=(?!wgs84)/i.test(geo[3])) return null;
    return onEarth(Number(geo[1]), Number(geo[2]));
  }
  // Decimal degrees, latitude first, with a sign or a hemisphere letter.
  const decimal = q.match(new RegExp(`^(${NUM})\\s*°?\\s*([NS])?\\s*[,;\\s]\\s*(${NUM})\\s*°?\\s*([EW])?$`, "i"));
  if (decimal) {
    const lat = Number(decimal[1]) * (decimal[2]?.toUpperCase() === "S" ? -1 : 1);
    const lon = Number(decimal[3]) * (decimal[4]?.toUpperCase() === "W" ? -1 : 1);
    return onEarth(lat, lon);
  }
  // Degrees, minutes and seconds, each half with its hemisphere letter.
  const half = String.raw`(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(?:(\d{1,2}(?:\.\d+)?)\s*["″])?\s*`;
  const dms = q.match(new RegExp(`^${half}([NS])[,\\s]*${half}([EW])$`, "i"));
  if (dms) {
    const deg = (d?: string, m?: string, s?: string) => Number(d) + Number(m) / 60 + Number(s ?? 0) / 3600;
    const lat = deg(dms[1], dms[2], dms[3]) * (dms[4]?.toUpperCase() === "S" ? -1 : 1);
    const lon = deg(dms[5], dms[6], dms[7]) * (dms[8]?.toUpperCase() === "W" ? -1 : 1);
    return Math.abs(Number(dms[2])) < 60 && Math.abs(Number(dms[6])) < 60 ? onEarth(lat, lon) : null;
  }
  return null;
}

/** "-1.2921, 36.8219": how a found point is shown. */
export function coordinatesText(lat: number, lon: number): string {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

/** Platform records first (as given, best match first), then places (SRC-01). */
export function search(query: string, records: Result[], places: Place[] = []): Result[] {
  const q = fold(query);
  if (!q) return [];
  const at = parseCoordinates(query);
  if (at) {
    return [
      { kind: "COORDINATES", id: `${at.lat},${at.lon}`, label: coordinatesText(at.lat, at.lon), detail: "Coordinates", ...at, zoom: RECORD_ZOOM },
    ];
  }
  const score = (r: Result) => {
    const label = fold(r.label);
    const detail = fold(r.detail);
    if (label === q) return 0;
    if (label.startsWith(q)) return 1;
    if (label.split(/[\s·,-]+/).some((w) => w.startsWith(q))) return 2;
    if (detail.startsWith(q) || detail.includes(` ${q}`)) return 3;
    return label.includes(q) && q.length >= 3 ? 4 : -1;
  };
  const found = records
    .map((r) => ({ r, s: score(r) }))
    .filter(({ s }) => s >= 0)
    .sort((a, b) => a.s - b.s)
    .map(({ r }) => r);
  const placeResults: Result[] = [];
  if (q.length >= 2) {
    for (const p of places) {
      const [name, ascii, region, country, lon, lat] = p;
      if (fold(name).startsWith(q) || (ascii && fold(ascii).startsWith(q))) {
        placeResults.push({
          kind: "PLACE",
          id: `${name}|${region}|${country}`,
          label: name,
          detail: [region !== name ? region : "", country].filter(Boolean).join(", "),
          lon,
          lat,
          zoom: PLACE_ZOOM,
        });
        if (found.length + placeResults.length >= MAX_RESULTS) break;
      }
    }
  }
  return [...found, ...placeResults].slice(0, MAX_RESULTS);
}

import type { FeatureCollection, Point } from "geojson";

import type { IncidentDetail } from "../api/intel";
import type { Mission } from "../api/people";
import { exposureFeatures, missionFeatures, SEVERITY_COLOUR, zoneFeatures } from "./geo";

// GFX-08 (D-55; plan G-9): the incident mini-map's view and layers, kept apart from MapLibre so
// they can be tested without WebGL.

/** The area `make tiles` builds city detail for (west, south, east, north; build-tiles.sh). */
export const CITY_BOUNDS: [number, number, number, number] = [36.45, -1.65, 37.2, -0.95];
export const CITY_ZOOM = 12;
export const REGION_ZOOM = 5;

/** City zoom where city tiles exist, regional zoom elsewhere. */
export function miniZoom(lon: number, lat: number): number {
  const [west, south, east, north] = CITY_BOUNDS;
  return lon >= west && lon <= east && lat >= south && lat <= north ? CITY_ZOOM : REGION_ZOOM;
}

/** The incident's zone, its marker, its mission and the people and sites exposed, with Global
 *  Operations' colours. */
export function miniLayers(incident: IncidentDetail, missions: Mission[]) {
  const marker: FeatureCollection<Point> = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [incident.lon, incident.lat] },
        properties: { colour: SEVERITY_COLOUR[incident.severity] },
      },
    ],
  };
  return {
    zone: zoneFeatures([incident]),
    mission: missionFeatures(missions.filter((m) => m.id === incident.mission_id)),
    exposure: exposureFeatures(incident.exposure, incident.impact_radius_m),
    marker,
  };
}

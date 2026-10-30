import { Icon, Spinner } from "@blueprintjs/core";

import { ago } from "../../app/time";
import {
  CONDITION_ICON,
  CONDITION_LABEL,
  isStale,
  LEVEL_COLOUR,
  useWeather,
  weatherLevel,
  worstFirst,
} from "../../api/weather";
import { FlashRow } from "../../ui/motion";
import { Card } from "../../ui/primitives";

/** WX-02: current conditions at every mission, worst first; stale readings flagged (G-6). */
export function WeatherPanel() {
  const weather = useWeather();
  const rows = worstFirst(weather.data ?? []);
  // Staleness as of the last fetch (every 60 s), so a stopped feed shows (plan G-6).
  const now = weather.dataUpdatedAt;
  const severe = rows.filter((w) => weatherLevel(w) === "SEVERE").length;
  const stale = rows.filter((w) => isStale(w, now)).length;

  return (
    <Card
      icon="cloud"
      title="Weather at missions"
      sub="xWeather (simulated)"
      className="nx-weather"
      actions={
        <span className="nx-dim">
          {severe ? <b style={{ color: LEVEL_COLOUR.SEVERE }}>{severe} severe</b> : "No severe weather"}
          {stale > 0 && ` · ${stale} stale`}
        </span>
      }
    >
      {weather.isLoading ? (
        <Spinner size={20} />
      ) : rows.length === 0 ? (
        <div className="nx-feed-empty nx-dim">No conditions yet: the weather feed runs in the worker.</div>
      ) : (
        <div className="nx-weather-body">
          <table className="nx-table-plain nx-weather-table" aria-label="Weather at missions">
            <tbody>
              {rows.map((w) => {
                const old = isStale(w, now);
                const colour = LEVEL_COLOUR[weatherLevel(w)];
                return (
                  <FlashRow
                    key={w.mission_id}
                    watch={`${w.condition} ${weatherLevel(w)}`}
                    tone={weatherLevel(w) === "SEVERE" ? "danger" : weatherLevel(w) === "ROUGH" ? "warning" : "info"}
                    className={old ? "nx-stale" : undefined}
                  >
                    <td>
                      <b>{w.city}</b> <span className="nx-dim nx-mono">{w.mission_code}</span>
                    </td>
                    <td style={{ color: old ? undefined : colour }}>
                      <Icon icon={CONDITION_ICON[w.condition]} size={12} /> {CONDITION_LABEL[w.condition]}
                    </td>
                    <td className="nx-mono">{Math.round(w.temperature_c)}°C</td>
                    <td className="nx-mono" title="Wind / gusts (km/h)">
                      {w.wind_kph}/{w.gust_kph}
                    </td>
                    <td className="nx-mono" title="Rainfall">
                      {w.rain_mm > 0 ? `${w.rain_mm} mm` : "—"}
                    </td>
                    <td className="nx-dim" title={`Updated ${ago(w.observed_at)}`}>
                      {old && <span className="nx-stale-tag">Stale · {ago(w.observed_at).replace(" ago", "")}</span>}
                    </td>
                  </FlashRow>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

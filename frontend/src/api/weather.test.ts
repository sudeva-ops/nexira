import {
  isStale,
  STALE_AFTER_MS,
  type Weather,
  weatherLevel,
  weatherMarkers,
  weatherSummary,
  worstFirst,
} from "./weather";

const NOW = Date.parse("2026-10-30T06:00:00Z");
const minutesAgo = (n: number) => new Date(NOW - n * 60_000).toISOString();

function wx(code: string, city: string, change: Partial<Weather> = {}): Weather {
  return {
    mission_id: `id-${code}`,
    mission_code: code,
    city,
    country_code: "XX",
    lat: 1,
    lon: 2,
    observed_at: minutesAgo(5),
    temperature_c: 24,
    condition: "CLEAR",
    wind_kph: 10,
    gust_kph: 14,
    rain_mm: 0,
    source: "xWeather (simulated)",
    stale: false,
    ...change,
  };
}

describe("weather (WX-01, WX-02)", () => {
  it("rates conditions: storms, dust and extremes are severe", () => {
    expect(weatherLevel(wx("MNL", "Manila", { condition: "STORM", wind_kph: 110, gust_kph: 150 }))).toBe("SEVERE");
    expect(weatherLevel(wx("RUH", "Riyadh", { condition: "DUST" }))).toBe("SEVERE");
    expect(weatherLevel(wx("RUH", "Riyadh", { temperature_c: 46 }))).toBe("SEVERE");
    expect(weatherLevel(wx("LON", "London", { gust_kph: 90 }))).toBe("SEVERE");
    expect(weatherLevel(wx("MOW", "Moscow", { condition: "SNOW", temperature_c: -4 }))).toBe("ROUGH");
    expect(weatherLevel(wx("LON", "London", { condition: "RAIN", rain_mm: 12 }))).toBe("ROUGH");
    expect(weatherLevel(wx("LON", "London", { condition: "RAIN", rain_mm: 2 }))).toBe("FAIR");
  });

  it("lists the worst first, then the strongest gusts, then by city", () => {
    const rows = [
      wx("ROM", "Rome"),
      wx("MNL", "Manila", { condition: "STORM", gust_kph: 150 }),
      wx("BER", "Berlin"),
      wx("MOW", "Moscow", { condition: "SNOW" }),
      wx("RUH", "Riyadh", { condition: "DUST", gust_kph: 70 }),
      wx("AMM", "Amman", { gust_kph: 30, wind_kph: 20 }),
    ];
    expect(worstFirst(rows).map((w) => w.mission_code)).toEqual(["MNL", "RUH", "MOW", "AMM", "BER", "ROM"]);
    expect(rows.at(0)?.mission_code).toBe("ROM"); // the input is not reordered
  });

  it("flags a reading older than 30 minutes, or one the API already flagged (plan G-6)", () => {
    expect(STALE_AFTER_MS).toBe(30 * 60_000);
    expect(isStale(wx("A", "A", { observed_at: minutesAgo(30) }), NOW)).toBe(false);
    expect(isStale(wx("A", "A", { observed_at: minutesAgo(31) }), NOW)).toBe(true);
    expect(isStale(wx("A", "A", { stale: true }), NOW)).toBe(true);
  });

  it("summarises one mission's conditions for the popup", () => {
    expect(
      weatherSummary(wx("MNL", "Manila", { condition: "STORM", temperature_c: 26, wind_kph: 110, gust_kph: 150, rain_mm: 60 })),
    ).toBe("Storm · 26°C · wind 110 km/h, gusts 150 · rain 60 mm");
    expect(weatherSummary(wx("BER", "Berlin", { temperature_c: 9.6 }))).toBe("Clear · 10°C · wind 10 km/h, gusts 14");
  });

  it("gives the map layer one icon per mission, coloured by level and grey when stale", () => {
    const markers = weatherMarkers(
      [
        wx("MNL", "Manila", { condition: "STORM", lat: 14.6, lon: 120.98 }),
        wx("MOW", "Moscow", { condition: "SNOW" }),
        wx("BER", "Berlin", { observed_at: minutesAgo(45) }),
      ],
      NOW,
    );
    expect(markers.map(({ code, icon, colour }) => [code, icon, colour])).toEqual([
      ["MNL", "lightning", "#CD4246"],
      ["MOW", "snowflake", "#EC9A3C"],
      ["BER", "flash", "#738091"],
    ]);
    expect(markers.map(({ lon, lat }) => [lon, lat])).toEqual([
      [120.98, 14.6],
      [2, 1],
      [2, 1],
    ]);
    expect(markers.at(-1)?.title).toBe("Berlin · Clear · 24°C · wind 10 km/h, gusts 14 · stale");
  });
});

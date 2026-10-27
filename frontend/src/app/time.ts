// GST is UTC+4 (plan Q2). The zone is configurable for other customers.
export const HOME_TZ = import.meta.env.VITE_HOME_TZ ?? "Asia/Dubai";
export const HOME_TZ_LABEL = "GST";

export function formatTime(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

/** "now", "45 s ago", "12 min ago", "3 h ago", "2 d ago". */
export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 10) return "now";
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86_400)} d ago`;
}

/** Date and time in the home zone, e.g. "24 Oct 14:05:09 GST". */
export function formatStamp(iso: string, timeZone: string = HOME_TZ): string {
  const date = new Date(iso);
  const day = new Intl.DateTimeFormat("en-GB", { timeZone, day: "2-digit", month: "short" }).format(
    date,
  );
  return `${day} ${formatTime(date, timeZone)} ${timeZone === HOME_TZ ? HOME_TZ_LABEL : timeZone}`;
}

function zoneOffsetMs(utcMs: number, timeZone: string): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
      .formatToParts(new Date(utcMs))
      .map((p) => [p.type, Number(p.value)]),
  ) as Record<string, number>;
  const asUtc = Date.UTC(parts.year ?? 0, (parts.month ?? 1) - 1, parts.day, parts.hour, parts.minute, parts.second);
  return asUtc - Math.floor(utcMs / 1000) * 1000;
}

/** "2026-10-31T09:30" read as home-zone time (Journey plan G-8) -> ISO instant. */
export function homeInputToIso(local: string, timeZone: string = HOME_TZ): string {
  const [day = "", time = "00:00"] = local.split("T");
  const [y, m, d] = day.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const guess = Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0);
  return new Date(guess - zoneOffsetMs(guess, timeZone)).toISOString();
}

/** An ISO instant -> "2026-10-31T09:30" in the home zone, for datetime-local inputs. */
export function isoToHomeInput(iso: string, timeZone: string = HOME_TZ): string {
  const utc = new Date(iso).getTime();
  return new Date(utc + zoneOffsetMs(utc, timeZone)).toISOString().slice(0, 16);
}

/** "18–22 Oct", "31 Oct–2 Nov" or "21 Oct" for a date range (YYYY-MM-DD). */
export function formatDays(startsOn: string, endsOn: string): string {
  const fmt = (iso: string, month: boolean) =>
    new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", ...(month ? { month: "short" } : {}) }).format(
      new Date(`${iso}T00:00:00Z`),
    );
  if (startsOn === endsOn) return fmt(startsOn, true);
  const sameMonth = startsOn.slice(0, 7) === endsOn.slice(0, 7);
  return `${fmt(startsOn, !sameMonth)}–${fmt(endsOn, true)}`;
}

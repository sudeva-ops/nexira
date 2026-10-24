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

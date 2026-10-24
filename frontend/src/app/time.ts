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

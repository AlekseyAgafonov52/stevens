export const now = (): Date => new Date();
export const userTimezone = (): string =>
  Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Местное время устройства в ISO 8601 со смещением: "2026-10-21T10:00:00+03:00" */
export function clientTime(): string {
  const date = now();
  const offset = -date.getTimezoneOffset();
  const local = new Date(date.getTime() + offset * 60_000)
    .toISOString()
    .slice(0, 19);
  const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const minutes = String(Math.abs(offset) % 60).padStart(2, "0");
  return `${local}${offset >= 0 ? "+" : "-"}${hours}:${minutes}`;
}

import { apiMode } from "../config/features";

export const MOCK_TIME = "2026-10-21T10:00:00+03:00";
export const now = (): Date =>
  new Date(apiMode === "mock" ? MOCK_TIME : Date.now());
export const userTimezone = (): string =>
  apiMode === "mock"
    ? "Europe/Moscow"
    : Intl.DateTimeFormat().resolvedOptions().timeZone;

export function clientTime(): string {
  if (apiMode === "mock") return MOCK_TIME;
  const date = now();
  const offset = -date.getTimezoneOffset();
  const local = new Date(date.getTime() + offset * 60_000)
    .toISOString()
    .slice(0, 19);
  const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const minutes = String(Math.abs(offset) % 60).padStart(2, "0");
  return `${local}${offset >= 0 ? "+" : "-"}${hours}:${minutes}`;
}

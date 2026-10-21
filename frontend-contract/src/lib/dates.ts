import type { RecordItem } from "../api/types";
import { T } from "../content/texts";
import { now, userTimezone } from "./clock";

const months = [
  "янв",
  "фев",
  "мар",
  "апр",
  "мая",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];
const weekdays = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

export function today(reference = now()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: userTimezone(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(reference);
  const get = (type: string) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function dayDifference(value: string, reference: Date) {
  return (
    (Date.parse(`${value}T12:00:00Z`) -
      Date.parse(`${today(reference)}T12:00:00Z`)) /
    86_400_000
  );
}

export function shortDate(value: string, reference = now()): string {
  const date = new Date(`${value}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  const year = Number(today(reference).slice(0, 4));
  return `${weekdays[date.getUTCDay()]}, ${date.getUTCDate()} ${months[date.getUTCMonth()]}${date.getUTCFullYear() !== year ? ` ${date.getUTCFullYear()}` : ""}`;
}

export function displayDate(value: string | null, reference = now()): string {
  if (!value) return T.date_none;
  const difference = dayDifference(value, reference);
  if (difference === 0) return T.date_today;
  if (difference === 1) return T.date_tomorrow;
  if (difference === -1) return T.date_yesterday;
  return shortDate(value, reference);
}

export function groupDate(value: string | null): string {
  if (!value) return T.group_no_date;
  const relative = displayDate(value);
  const date = shortDate(value).replace(",", "");
  const label =
    Math.abs(dayDifference(value, now())) <= 1
      ? `${relative}, ${date}`
      : shortDate(value);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function isPast(record: RecordItem, reference = now()): boolean {
  if (
    !record.date ||
    record.date_kind === "none" ||
    record.marks.includes("draft")
  )
    return false;
  const currentDay = today(reference);
  if (record.date !== currentDay) return record.date < currentDay;
  if (record.date_kind !== "exact" || !record.time) return false;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: userTimezone(),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(reference);
  return record.time < parts;
}

import type { RecordItem } from "../../api/types";

export function addDays(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
export function mondayOf(value: string): string {
  const weekday = new Date(`${value}T12:00:00Z`).getUTCDay();
  return addDays(value, -((weekday + 6) % 7));
}
export const order = (record: RecordItem) =>
  `${record.date ?? "9999-99-99"} ${record.time ?? "99:99"}`;

/** Встречи с одинаковыми датой и временем начала — пометку «В то же время» ставит фронт (15.5) */
export function sameTimeIds(records: RecordItem[]): Set<number> {
  const slots = new Map<string, number[]>();
  for (const record of records) {
    if (
      record.type !== "meeting" ||
      record.id === null ||
      !record.date ||
      !record.time ||
      record.marks.includes("deleted")
    )
      continue;
    const key = `${record.date} ${record.time}`;
    slots.set(key, [...(slots.get(key) ?? []), record.id]);
  }
  return new Set([...slots.values()].filter((ids) => ids.length > 1).flat());
}

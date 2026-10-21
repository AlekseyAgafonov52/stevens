/** Даты в карточках и заголовках дней — 02-screens.md, 3.2 и 3.3. */
import type { RecordItem } from '../api/types';
import { T, fill } from '../content/texts';
import { now } from './clock';

export function isoDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function parseIso(value: string): Date {
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** Понедельник = 0 */
export function weekdayIndex(date: Date): number {
  return (date.getDay() + 6) % 7;
}

function relative(value: string, today: Date): 'today' | 'tomorrow' | 'yesterday' | null {
  if (value === isoDate(today)) return 'today';
  if (value === isoDate(addDays(today, 1))) return 'tomorrow';
  if (value === isoDate(addDays(today, -1))) return 'yesterday';
  return null;
}

/** «пн, 19 окт», с годом — если не текущий */
export function shortDate(value: string, today: Date = now()): string {
  const date = parseIso(value);
  const base = `${T.weekdays_short[weekdayIndex(date)]}, ${date.getDate()} ${T.months_short[date.getMonth()]}`;
  return date.getFullYear() === today.getFullYear() ? base : `${base} ${date.getFullYear()}`;
}

/** Дата в мете карточки: сегодня / завтра / вчера / «пн, 19 окт» */
export function metaDate(value: string, today: Date = now()): string {
  const rel = relative(value, today);
  if (rel === 'today') return T.date_today;
  if (rel === 'tomorrow') return T.date_tomorrow;
  if (rel === 'yesterday') return T.date_yesterday;
  return shortDate(value, today);
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Заголовок группы дня: «Сегодня, ср 21 окт» / «Пт, 23 окт» */
export function dayTitle(value: string, today: Date = now()): string {
  const date = parseIso(value);
  const year = date.getFullYear() === today.getFullYear() ? '' : ` ${date.getFullYear()}`;
  const wd = T.weekdays_short[weekdayIndex(date)];
  const dm = `${date.getDate()} ${T.months_short[date.getMonth()]}${year}`;
  const rel = relative(value, today);
  if (rel) return `${capitalize(T[`date_${rel}`])}, ${wd} ${dm}`;
  return `${capitalize(wd)}, ${dm}`;
}

export type MetaPart = { field: 'date' | 'time' | null; text: string };

/** Части меты после слова типа: [дата] · [время] — 02-screens.md, 3.1 */
export function metaParts(record: RecordItem, withDate: boolean, today: Date = now()): MetaPart[] {
  const parts: MetaPart[] = [];
  if (record.date_kind === 'none' || !record.date) {
    parts.push({ field: 'date', text: T.date_none });
  } else if (record.date_kind === 'deadline') {
    parts.push({ field: 'date', text: fill(T.date_deadline, { date: metaDate(record.date, today) }) });
  } else if (withDate) {
    parts.push({ field: 'date', text: metaDate(record.date, today) });
  }
  if (record.time && record.date_kind !== 'none') parts.push({ field: 'time', text: record.time });
  return parts;
}

/** Прошедшая — считает фронт (02-screens.md, 3.4) */
export function isPast(record: RecordItem, at: Date = now()): boolean {
  if (record.marks.includes('draft') || !record.date || record.date_kind === 'none') return false;
  const today = isoDate(at);
  if (record.date_kind === 'exact' && record.time) {
    const [h, m] = record.time.split(':').map(Number);
    const moment = parseIso(record.date);
    moment.setHours(h, m, 0, 0);
    return moment.getTime() < at.getTime();
  }
  return record.date < today;
}

export type DayGroup = { date: string | null; records: RecordItem[] };

/** Группы list по дням: подряд идущие с одной датой; без срока — одной группой в конце */
export function groupByDay(records: RecordItem[]): DayGroup[] {
  const groups: DayGroup[] = [];
  const noDate: RecordItem[] = [];
  for (const record of records) {
    if (record.date_kind === 'none' || !record.date) {
      noDate.push(record);
      continue;
    }
    const last = groups[groups.length - 1];
    if (last && last.date === record.date) last.records.push(record);
    else groups.push({ date: record.date, records: [record] });
  }
  if (noDate.length) groups.push({ date: null, records: noDate });
  return groups;
}

/** Склонение: one / few / many */
export function pluralKey(count: number): 'one' | 'few' | 'many' {
  const n10 = count % 10;
  const n100 = count % 100;
  if (n10 === 1 && n100 !== 11) return 'one';
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return 'few';
  return 'many';
}

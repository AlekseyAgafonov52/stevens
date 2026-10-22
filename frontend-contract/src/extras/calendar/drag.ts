/** Перенос перетаскиванием в календаре: шаг времени и проверка «в то же время». */
import type { RecordItem, RecordPatch } from '../../api/types';

/** Сколько пикселей вверх-вниз по списку дня — один шаг времени */
export const STEP_PX = 12;
export const STEP_MIN = 15;
/** Мышь: сдвиг до начала переноса; палец: долгое нажатие */
export const MOUSE_SLOP_PX = 6;
export const TOUCH_HOLD_MS = 350;
export const TOUCH_SLOP_PX = 10;
/** Задержка над стрелкой месяца, после которой месяц листается */
export const ARROW_HOLD_MS = 700;

const LAST = 23 * 60 + 45;

export function toMinutes(time: string): number {
  const [h, m] = time.split(':').map(Number);
  return h * 60 + m;
}

export function fromMinutes(value: number): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(value / 60))}:${pad(value % 60)}`;
}

/** Время после сдвига на dy пикселей: шаг 15 минут, в пределах дня, кратно 15 */
export function shiftedTime(time: string, dy: number): string {
  const steps = Math.round(dy / STEP_PX);
  if (steps === 0) return time;
  const moved = Math.round((toMinutes(time) + steps * STEP_MIN) / STEP_MIN) * STEP_MIN;
  return fromMinutes(Math.min(LAST, Math.max(0, moved)));
}

/** Только изменённые поля переноса */
export function movePatch(record: RecordItem, date: string, time: string | null): RecordPatch {
  const patch: RecordPatch = {};
  if (date !== record.date) patch.date = date;
  if (time !== record.time) patch.time = time;
  return patch;
}

/** Встречи на новом месте с тем же временем — как «В то же время» в календаре */
export function clashes(record: RecordItem, date: string, time: string | null, records: RecordItem[]): RecordItem[] {
  if (record.type !== 'meeting' || !time) return [];
  return records.filter((r) => r.id !== record.id && r.type === 'meeting' && r.date === date && r.time === time
    && !r.marks.includes('deleted'));
}

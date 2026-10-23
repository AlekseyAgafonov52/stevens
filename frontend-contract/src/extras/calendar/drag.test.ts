import { describe, expect, it } from 'vitest';
import type { RecordItem } from '../../api/types';
import { clashes, movePatch, shiftedTime, STEP_PX } from './drag';

const rec = (over: Partial<RecordItem>): RecordItem => ({
  id: 1, type: 'meeting', text: 'Планёрка', date: '2026-10-22', time: '10:00', date_kind: 'exact',
  status: null, created_at: null, repeat: null, demo: false, marks: [], highlight: null, ...over,
});

describe('shiftedTime', () => {
  it('шаг 15 минут на STEP_PX', () => {
    expect(shiftedTime('10:00', STEP_PX)).toBe('10:15');
    expect(shiftedTime('10:00', -STEP_PX * 4)).toBe('09:00');
    expect(shiftedTime('10:00', STEP_PX / 3)).toBe('10:00');
  });
  it('выравнивает до 15 и не выходит за день', () => {
    expect(shiftedTime('10:10', STEP_PX)).toBe('10:30');
    expect(shiftedTime('00:30', -STEP_PX * 10)).toBe('00:00');
    expect(shiftedTime('23:00', STEP_PX * 10)).toBe('23:45');
  });
});

describe('movePatch', () => {
  it('только изменённое', () => {
    expect(movePatch(rec({}), '2026-10-23', '10:00')).toEqual({ date: '2026-10-23' });
    expect(movePatch(rec({}), '2026-10-22', '11:00')).toEqual({ time: '11:00' });
  });
});

describe('clashes', () => {
  const other = rec({ id: 2, text: 'Звонок', date: '2026-10-23' });
  it('встреча на то же время в новом дне', () => {
    expect(clashes(rec({}), '2026-10-23', '10:00', [other])).toEqual([other]);
    expect(clashes(rec({}), '2026-10-23', '11:00', [other])).toEqual([]);
  });
  it('задачи и сама запись не мешают', () => {
    expect(clashes(rec({ type: 'task' }), '2026-10-23', '10:00', [other])).toEqual([]);
    expect(clashes(rec({ id: 2 }), '2026-10-23', '10:00', [other])).toEqual([]);
  });
});

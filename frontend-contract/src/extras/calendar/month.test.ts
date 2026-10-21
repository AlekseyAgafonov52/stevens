import { describe, expect, it } from 'vitest';
import { conflictIds, dayLabel, dotsFor, gridRange } from './month';
import type { RecordItem } from '../../api/types';

const meeting = (id: number, time: string): RecordItem => ({
  id, type: 'meeting', text: 'm', date: '2026-10-24', time, date_kind: 'exact', status: null,
  created_at: null, marks: [], highlight: null,
});

describe('calendar month', () => {
  it('grid starts on Monday and spans 6 weeks', () => {
    expect(gridRange(2026, 9)).toEqual({ from: '2026-09-28', to: '2026-11-08' });
  });
  it('dots', () => {
    expect([0, 1, 2, 3, 7].map(dotsFor)).toEqual([0, 1, 2, 3, 3]);
  });
  it('conflicts by same start time', () => {
    expect([...conflictIds([meeting(1, '10:00'), meeting(2, '10:00'), meeting(3, '11:00')])]).toEqual([1, 2]);
  });
  it('aria label', () => {
    expect(dayLabel('2026-10-21', 2)).toBe('среда, 21 октября, 2 записи');
    expect(dayLabel('2026-10-21', 0)).toBe('среда, 21 октября');
  });
});

import { describe, expect, it } from 'vitest';
import { busyDates, conflictIds, countByDate, dayLabel, dotsByDate, dotsFor, gridRange } from './month';
import type { RecordItem } from '../../api/types';

const meeting = (id: number, time: string): RecordItem => ({
  id, type: 'meeting', text: 'm', date: '2026-10-24', time, date_kind: 'exact', status: null,
  created_at: null, repeat: null, demo: false, marks: [], highlight: null,
});

describe('calendar month', () => {
  it('grid starts on Monday and spans 6 weeks', () => {
    expect(gridRange(2026, 9)).toEqual({ from: '2026-09-28', to: '2026-11-08' });
  });
  it('dots', () => {
    expect([0, 1, 2, 3, 7].map(dotsFor)).toEqual([0, 1, 2, 3, 3]);
  });
  it('keeps unfinished events visible when the day has more than three events', () => {
    const records: RecordItem[] = [1, 2, 3].map((id) => ({ ...meeting(id, '10:00'), status: 'done' }));
    records.push({ ...meeting(4, '17:00'), status: 'open' });
    records.push({ ...meeting(5, '18:00'), status: 'open', marks: ['deleted'] });
    records.push({ ...meeting(6, '19:00'), type: 'busy', status: null });
    expect(dotsByDate(records).get('2026-10-24')).toEqual(['open', 'done', 'done']);
    records[3] = { ...records[3], status: 'done' };
    expect(dotsByDate(records).get('2026-10-24')).toEqual(['done', 'done', 'done']);
  });
  it('conflicts by same start time', () => {
    expect([...conflictIds([meeting(1, '10:00'), meeting(2, '10:00'), meeting(3, '11:00')])]).toEqual([1, 2]);
  });
  it('busy is a gray bar, not a dot', () => {
    const work: RecordItem = { ...meeting(9, '09:00'), type: 'busy', end_time: '18:00', date: '2026-10-23' };
    expect(countByDate([work, meeting(1, '10:00')]).get('2026-10-23')).toBeUndefined();
    expect([...busyDates([work, meeting(1, '10:00')])]).toEqual(['2026-10-23']);
  });
  it('aria label', () => {
    expect(dayLabel('2026-10-21', 2)).toBe('среда, 21 октября, 2 записи');
    expect(dayLabel('2026-10-21', 0)).toBe('среда, 21 октября');
  });
});

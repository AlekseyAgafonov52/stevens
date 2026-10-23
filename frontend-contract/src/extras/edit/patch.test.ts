import { describe, expect, it } from 'vitest';
import type { RecordItem } from '../../api/types';
import { buildPatch, validate } from './patch';

const task: RecordItem = {
  id: 1, type: 'task', text: 'Отчёт', date: '2026-10-22', time: '10:00', date_kind: 'exact',
  status: 'open', created_at: null, repeat: null, demo: false, marks: [], highlight: null,
};

describe('edit form', () => {
  it('sends only changed fields', () => {
    expect(buildPatch(task, { text: 'Отчёт', date: '2026-10-22', time: '12:00' })).toEqual({ time: '12:00' });
    expect(buildPatch(task, { text: 'Отчёт', date: '', time: '' })).toEqual({ date: null, time: null });
  });
  it('validates', () => {
    expect(validate(task, { text: ' ', date: '', time: '' })).toEqual({ text: 'edit_err_text' });
    expect(validate(task, { text: 'a', date: '', time: '10:00' })).toEqual({ datetime: 'edit_err_datetime' });
    expect(validate({ ...task, type: 'meeting' }, { text: 'a', date: '2026-10-22', time: '' })).toEqual({ datetime: 'edit_err_datetime' });
  });
});

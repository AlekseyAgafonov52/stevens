import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { RecordItem } from '../../api/types';

vi.mock('../../api', () => ({ api: { records: vi.fn(async () => []) }, ApiFailure: class extends Error {} }));
vi.mock('../../state/session', () => ({ sessionExpired: vi.fn() }));

const { api } = await import('../../api');
const { store } = await import('../../state/store');
const { calendar, invalidate, load } = await import('./state');
const demo: RecordItem = {
  id: 1, type: 'task', text: 'Учебная задача', date: '2026-10-26', time: null, date_kind: 'exact',
  status: 'open', created_at: null, repeat: null, demo: true, marks: [], highlight: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  store.set({ screen: 'app', mode: 'sandbox', userId: null, calendarOpen: false });
  invalidate();
});

describe('очистка календаря обучения', () => {
  it('старый ответ с демо-данными не возвращает записи после очистки', async () => {
    let finish!: (records: RecordItem[]) => void;
    vi.mocked(api.records).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = load();
    calendar.set({ records: [demo] });
    invalidate();
    finish([demo]);
    await pending;
    expect(calendar.get().records).toEqual([]);
  });

  it('переход из песочницы в аккаунт очищает календарь даже при закрытой панели', () => {
    calendar.set({ records: [demo], loading: false });
    store.set({ mode: 'account', userId: 7 });
    expect(calendar.get().records).toEqual([]);
  });

  it('открытый календарь перечитывается для аккаунта после возврата из обучения', async () => {
    vi.mocked(api.records).mockResolvedValueOnce([]);
    calendar.set({ records: [demo] });
    store.set({ mode: 'account', userId: 7, calendarOpen: true });
    await Promise.resolve();
    expect(api.records).toHaveBeenCalledOnce();
    expect(calendar.get().records).toEqual([]);
  });
});

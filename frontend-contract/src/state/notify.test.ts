import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./chat', () => ({ setHint: vi.fn() }));
vi.mock('../api', () => ({ api: { records: vi.fn(async () => []), record: vi.fn() } }));

const { setHint } = await import('./chat');
const { enableNotify, notifyStore, handlePushMessage, closeNotifyCard } = await import('./notify');
const { api } = await import('../api');
const { store } = await import('./store');
const { T } = await import('../content/texts');
import type { RecordItem } from '../api/types';

afterEach(() => { closeNotifyCard(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

function iphone(standalone: boolean) {
  vi.stubGlobal('navigator', { userAgent: 'iPhone', standalone });
  vi.stubGlobal('window', { matchMedia: () => ({ matches: standalone }) });
}

describe('включение уведомлений на iPhone', () => {
  it('в Safari показывает существующую подсказку установки', async () => {
    iphone(false);
    await enableNotify();
    expect(setHint).toHaveBeenCalledWith('install_safari');
  });

  it('запрашивает разрешение сразу при нажатии и обрабатывает отказ API', async () => {
    iphone(true);
    const requestPermission = vi.fn(() => Promise.reject(new Error('unavailable')));
    const notification = { permission: 'default', requestPermission };
    vi.stubGlobal('Notification', notification);
    Object.assign(window, { Notification: notification });
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const pending = enableNotify();
    expect(requestPermission).toHaveBeenCalledOnce();
    await pending;
    expect(notifyStore.get().on).toBe(false);
    expect(setHint).toHaveBeenCalledWith('err_server');
    vi.restoreAllMocks();
  });
});

describe('вечерняя сводка о просроченном', () => {
  const record: RecordItem = { id: 42, type: 'meeting', text: 'Старая встреча', date: '2020-01-01', time: '13:00',
    date_kind: 'exact', status: null, created_at: null, repeat: null, demo: false, marks: [], highlight: null };
  const lastAnswer = () => {
    const last = store.get().messages.at(-1);
    return last?.kind === 'answer' ? last.response : null;
  };

  it('«Разобрать» присылает в чат дела из сводки по ID', async () => {
    store.set({ screen: 'app', messages: [] });
    vi.mocked(api.record).mockImplementation(async (id) => ({ ...record, id, text: `Дело ${id}` }));
    await handlePushMessage({ type: 'stevens-digest', recordIds: [42, 43] });
    expect(api.record).toHaveBeenCalledWith(42);
    expect(api.records).not.toHaveBeenCalled();
    expect(lastAnswer()?.kind).toBe('overdue');
    expect(lastAnswer()?.text).toBe(T.remind_digest);
    expect(lastAnswer()?.records.map((r) => r.id)).toEqual([42, 43]);
    // Повторное нажатие не дублирует сообщение
    await handlePushMessage({ type: 'stevens-digest', recordIds: [42, 43] });
    expect(store.get().messages).toHaveLength(1);
  });

  it('уже выполненное и удалённое в чат не попадает', async () => {
    store.set({ screen: 'app', messages: [] });
    vi.mocked(api.record).mockImplementation(async (id) => (id === 42 ? { ...record, status: 'done' } : { ...record, id }));
    await handlePushMessage({ type: 'stevens-digest', recordIds: [42, 44] });
    expect(lastAnswer()?.records.map((r) => r.id)).toEqual([44]);
    expect(lastAnswer()?.text).toBe(T.remind_digest_one);
    store.set({ messages: [] });
    vi.mocked(api.record).mockResolvedValue({ ...record, status: 'done' });
    await handlePushMessage({ type: 'stevens-digest', recordIds: [42] });
    expect(store.get().messages).toHaveLength(0);
  });
});

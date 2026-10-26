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

describe('повторный push о просроченном событии', () => {
  const record: RecordItem = { id: 42, type: 'meeting', text: 'Старая встреча', date: '2020-01-01', time: '13:00',
    date_kind: 'exact', status: null, created_at: null, repeat: null, demo: false, marks: [], highlight: null };

  it('получает старое событие по ID и показывает причину повтора', async () => {
    vi.mocked(api.record).mockResolvedValue(record);
    await handlePushMessage({ type: 'stevens-reminder', recordId: 42, overdue: true });
    expect(api.record).toHaveBeenCalledWith(42);
    expect(api.records).not.toHaveBeenCalled();
    expect(notifyStore.get().card?.title).toBe(T.remind_overdue);
  });

  it('не показывает уже выполненное событие из запоздавшего push', async () => {
    vi.mocked(api.record).mockResolvedValue({ ...record, status: 'done' });
    await handlePushMessage({ type: 'stevens-reminder', recordId: 42, overdue: true });
    expect(notifyStore.get().card).toBeNull();
  });

  it('после клика не говорит, что прошедшая встреча начнётся через 15 минут', async () => {
    store.set({ screen: 'app', messages: [] });
    vi.mocked(api.record).mockResolvedValue(record);
    await handlePushMessage({ type: 'stevens-open', recordId: 42, overdue: true });
    const last = store.get().messages.at(-1);
    expect(last?.kind === 'answer' && last.response.text).toBe(T.remind_overdue);
    await handlePushMessage({ type: 'stevens-reminder', recordId: 42, overdue: true });
    expect(notifyStore.get().card?.record.id).toBe(42);
  });
});

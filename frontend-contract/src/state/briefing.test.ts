import { describe, expect, it, vi } from 'vitest';

const today = new Date();
const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
const rec = (type: string, status = 'open') => ({ id: Math.random(), type, status, date: day, marks: [] });
const byOwner: Record<string, unknown[]> = {
  sandbox: [rec('task'), rec('meeting'), rec('reminder')],
  'a:7': [],
  'a:8': [rec('busy'), rec('task', 'done'), rec('task')],
};

vi.mock('../api', () => ({
  api: {
    records: vi.fn(async () => {
      const s = (await import('./store')).store.get();
      return byOwner[s.mode === 'account' ? `a:${s.userId}` : 'sandbox'];
    }),
  },
}));
vi.mock('./chat', () => ({ sendQuiet: () => true }));

const { store } = await import('./store');
const { briefingStore, initBriefing } = await import('./briefing');
const settle = () => new Promise((r) => setTimeout(r, 0));

describe('план на сегодня: число дел от того, кто вошёл', () => {
  it('из песочницы в новый аккаунт — плашка с делами песочницы уходит', async () => {
    initBriefing();
    store.set({ screen: 'app', mode: 'sandbox', server: 'ok' });
    await settle();
    expect(briefingStore.get().offer).toEqual({ count: 3 });
    store.set({ screen: 'auth', mode: null, userId: null });
    expect(briefingStore.get().offer).toBeNull();
    store.set({ screen: 'app', mode: 'account', userId: 7 });
    await settle();
    expect(briefingStore.get().offer).toBeNull();
  });
  it('считает как сервер: без занятости и выполненных', async () => {
    store.set({ screen: 'app', mode: 'account', userId: 8 });
    await settle();
    expect(briefingStore.get().offer).toEqual({ count: 1 });
  });
});

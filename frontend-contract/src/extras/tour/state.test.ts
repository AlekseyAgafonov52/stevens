import { beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../state/store';

vi.mock('../../api', () => ({
  api: { clearSandbox: vi.fn(async () => undefined) },
  errorKey: () => 'err_server',
}));
vi.mock('../../state/chat', () => ({ resetSandbox: vi.fn(async () => undefined), send: vi.fn(), pressButton: vi.fn() }));
vi.mock('../../state/briefing', () => ({ briefingStore: { subscribe: vi.fn() }, declineBriefing: vi.fn() }));
vi.mock('../../state/feed', () => ({ clearFeed: vi.fn() }));
vi.mock('../../state/notify', async () => {
  const { createStore: makeStore } = await import('../../state/store');
  return { notifyStore: makeStore({ card: null, offer: null }), showNotifyCard: vi.fn(), viewNotifyCard: vi.fn() };
});
vi.mock('../../state/session', async () => {
  const { store: app } = await import('../../state/store');
  return {
    enterTourSandbox: vi.fn(() => app.set({ mode: 'sandbox', userId: null })),
    returnToAccount: vi.fn((login: string | null, userId: number | null) => app.set({ mode: 'account', login, userId })),
  };
});
vi.mock('../../storage', () => ({ storage: {
  clientId: () => 'tour-device-123', setTourSeen: vi.fn(), setTourOffer: vi.fn(),
} }));

const { api } = await import('../../api');
const { returnToAccount } = await import('../../state/session');
const { onRecordsChanged } = await import('../../state/events');
const { startTour, closeTour, skipStep, tourSteps, tourStore } = await import('./state');

beforeEach(async () => {
  vi.clearAllMocks();
  vi.mocked(api.clearSandbox).mockResolvedValue(undefined);
  store.set({ mode: 'sandbox', screen: 'app', waiting: false, recording: false, messages: [], userId: null });
  tourStore.set({ status: 'off', cleaning: false });
  await startTour();
});

describe('очистка учебной песочницы', () => {
  it('при досрочном выходе удаляет данные, очищает ленту и обновляет календарь', async () => {
    const changed = vi.fn();
    const off = onRecordsChanged(changed);
    const conversation = store.get().conversationId;
    await closeTour();
    expect(api.clearSandbox).toHaveBeenCalledWith('tour-device-123');
    expect(store.get().messages).toEqual([]);
    expect(store.get().conversationId).not.toBe(conversation);
    expect(changed).toHaveBeenCalledOnce();
    expect(tourStore.get().status).toBe('off');
    off();
  });

  it('при последнем шаге очищает данные автоматически, закрытие не повторяет запрос', async () => {
    for (let i = 0; i < tourSteps().length; i += 1) skipStep();
    expect(tourStore.get().status).toBe('done');
    await closeTour();
    expect(api.clearSandbox).toHaveBeenCalledOnce();
    expect(tourStore.get().status).toBe('off');
  });

  it('при ошибке остаётся в обучении и позволяет повторить очистку', async () => {
    vi.mocked(api.clearSandbox).mockRejectedValueOnce(new Error('offline'));
    await closeTour();
    expect(tourStore.get().status).toBe('running');
    expect(store.get().resetError?.key).toBe('err_server');
    await closeTour();
    expect(api.clearSandbox).toHaveBeenCalledTimes(2);
    expect(tourStore.get().status).toBe('off');
  });

  it('не выходит посреди запроса, который ещё может создать учебную запись', async () => {
    store.set({ waiting: true });
    await closeTour();
    expect(api.clearSandbox).not.toHaveBeenCalled();
    expect(tourStore.get().status).toBe('running');
    store.set({ waiting: false });
    await closeTour();
  });

  it('возвращается в аккаунт только после успешной очистки песочницы', async () => {
    await closeTour();
    vi.clearAllMocks();
    store.set({ mode: 'account', login: 'owner', userId: 7 });
    await startTour();
    let finish!: () => void;
    vi.mocked(api.clearSandbox).mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const closing = closeTour();
    expect(store.get().mode).toBe('sandbox');
    expect(store.get().waiting).toBe(true);
    expect(returnToAccount).not.toHaveBeenCalled();
    finish();
    await closing;
    expect(returnToAccount).toHaveBeenCalledWith('owner', 7);
    expect(store.get().mode).toBe('account');
  });
});
